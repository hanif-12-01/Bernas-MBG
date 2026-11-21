from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import AuthContext, record_audit_event
from app.db.models import (
    IngredientORM,
    InventoryLotORM,
    InventoryMovementORM,
    InventoryReconciliationORM,
)
from app.db.repository import SQLiteVaultRepository
from app.inventory.timezone_utils import jakarta_now, parse_expiry_date_jakarta
from app.inventory.unit_normalizer import UnitConversionError, normalize_quantity_to_grams
from app.scenarios.service import ResourceNotFoundError


class ManualStockAdjustmentTypeEnum(str, Enum):
    PURCHASE_RECEIPT = "PURCHASE_RECEIPT"
    USAGE_CONSUMPTION = "USAGE_CONSUMPTION"
    SPOILAGE_DAMAGE = "SPOILAGE_DAMAGE"
    STOCK_OPNAME_COUNT = "STOCK_OPNAME_COUNT"
    STOCK_CORRECTION = "STOCK_CORRECTION"


class ManualStockAdjustmentRequest(BaseModel):
    dataset_version_id: Optional[UUID] = None
    ingredient_code: str = Field(min_length=1, max_length=64)
    lot_code: Optional[str] = Field(default=None, max_length=128)
    adjustment_type: ManualStockAdjustmentTypeEnum
    quantity: float = Field(ge=0.0)
    unit: str = Field(default="kg", min_length=1, max_length=32)
    expires_at: Optional[str] = Field(default=None, max_length=64)
    supplier_name: Optional[str] = Field(default=None, max_length=255)
    source_document_ref: Optional[str] = Field(default=None, max_length=128)
    notes: Optional[str] = Field(default=None, max_length=1000)
    idempotency_key: Optional[str] = Field(default=None, max_length=128)


class ManualStockAdjustmentResponse(BaseModel):
    movement_id: UUID
    lot_id: UUID
    lot_code: str
    ingredient_code: str
    ingredient_name: str
    adjustment_type: ManualStockAdjustmentTypeEnum
    recorded_raw_g: float
    damaged_raw_g: float
    verified_physical_raw_g: Optional[float] = None
    verification_status: str
    safety_hold_status: str
    supplier_name: Optional[str] = None
    duplicate_skipped: bool = False
    message: str


_TYPE_TO_MOVEMENT = {
    ManualStockAdjustmentTypeEnum.PURCHASE_RECEIPT: "GOODS_RECEIPT",
    ManualStockAdjustmentTypeEnum.USAGE_CONSUMPTION: "PRODUCTION_CONSUMPTION",
    ManualStockAdjustmentTypeEnum.SPOILAGE_DAMAGE: "DAMAGE",
    ManualStockAdjustmentTypeEnum.STOCK_OPNAME_COUNT: "PHYSICAL_COUNT_RECONCILIATION",
    ManualStockAdjustmentTypeEnum.STOCK_CORRECTION: "ADJUSTMENT",
}


def record_manual_inventory_adjustment(
    session: Session,
    auth: AuthContext,
    req: ManualStockAdjustmentRequest,
) -> ManualStockAdjustmentResponse:
    """Single-item manual ledger mutation executed strictly by the active QC stock custodian."""
    repo = SQLiteVaultRepository(session)
    ds_id = req.dataset_version_id or repo.get_active_dataset_id(auth.kitchen_id)
    try:
        repo.get_dataset_orm(ds_id, kitchen_id=auth.kitchen_id)
    except ResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    ing_code = req.ingredient_code.strip()
    ing = session.execute(
        select(IngredientORM).where(
            IngredientORM.dataset_version_id == str(ds_id),
            IngredientORM.code == ing_code,
        )
    ).scalar_one_or_none()
    if ing is None:
        raise HTTPException(status_code=422, detail=f"Kode bahan '{ing_code}' tidak ditemukan pada dataset ini.")

    idemp_key = (
        req.idempotency_key.strip()
        if req.idempotency_key and req.idempotency_key.strip()
        else f"MANUAL-{uuid4()}"
    )
    existing_mov = session.execute(
        select(InventoryMovementORM).where(
            InventoryMovementORM.kitchen_id == str(auth.kitchen_id),
            InventoryMovementORM.dataset_version_id == str(ds_id),
            InventoryMovementORM.idempotency_key == idemp_key,
        )
    ).scalar_one_or_none()
    if existing_mov is not None and existing_mov.lot_id:
        existing_lot = session.get(InventoryLotORM, existing_mov.lot_id)
        if existing_lot is not None:
            return ManualStockAdjustmentResponse(
                movement_id=UUID(existing_mov.id),
                lot_id=UUID(existing_lot.id),
                lot_code=existing_lot.lot_code,
                ingredient_code=ing.code,
                ingredient_name=ing.name,
                adjustment_type=req.adjustment_type,
                recorded_raw_g=float(existing_lot.recorded_raw_g),
                damaged_raw_g=float(existing_lot.damaged_raw_g),
                verified_physical_raw_g=existing_lot.verified_physical_raw_g,
                verification_status=existing_lot.verification_status,
                safety_hold_status=existing_lot.safety_hold_status,
                supplier_name=existing_lot.supplier_name,
                duplicate_skipped=True,
                message="Penyesuaian dengan kunci idempotensi yang sama sudah tercatat (tidak digandakan).",
            )

    try:
        norm = normalize_quantity_to_grams(
            req.quantity,
            req.unit,
            allow_zero=(
                req.adjustment_type
                in {
                    ManualStockAdjustmentTypeEnum.STOCK_OPNAME_COUNT,
                    ManualStockAdjustmentTypeEnum.STOCK_CORRECTION,
                }
            ),
        )
    except UnitConversionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    exp_dt: Optional[datetime] = None
    if req.expires_at and req.expires_at.strip():
        try:
            exp_dt = parse_expiry_date_jakarta(req.expires_at.strip())
        except ValueError as exc:
            raise HTTPException(
                status_code=422, detail=f"Format tanggal kedaluwarsa tidak valid: '{req.expires_at}'."
            ) from exc

    now_utc = datetime.now(timezone.utc)
    now_jkt = jakarta_now()
    default_lot_code = f"LOT-{ing.code}-{now_jkt.strftime('%Y%m%d')}"
    lot_code = req.lot_code.strip() if req.lot_code and req.lot_code.strip() else default_lot_code

    lot = session.execute(
        select(InventoryLotORM).where(
            InventoryLotORM.kitchen_id == str(auth.kitchen_id),
            InventoryLotORM.dataset_version_id == str(ds_id),
            InventoryLotORM.lot_code == lot_code,
        )
    ).scalar_one_or_none()

    if lot is not None and lot.safety_hold_status in {"ON_HOLD", "REJECTED_DISPOSED"}:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Lot '{lot.lot_code}' berstatus {lot.safety_hold_status} dan tidak dapat "
                "dimodifikasi atau dibuka kembali lewat penyesuaian stok biasa."
            ),
        )

    supplier_clean = req.supplier_name.strip() if req.supplier_name and req.supplier_name.strip() else None
    notes_clean = req.notes.strip() if req.notes and req.notes.strip() else None

    if lot is None:
        if req.adjustment_type in {
            ManualStockAdjustmentTypeEnum.USAGE_CONSUMPTION,
            ManualStockAdjustmentTypeEnum.SPOILAGE_DAMAGE,
        }:
            raise HTTPException(
                status_code=404,
                detail=f"Lot '{lot_code}' belum ditemukan untuk pengurangan/kerusakan stok.",
            )
        expiry_known = exp_dt is not None
        lot = InventoryLotORM(
            id=str(uuid4()),
            kitchen_id=str(auth.kitchen_id),
            dataset_version_id=str(ds_id),
            ingredient_id=ing.id,
            lot_code=lot_code,
            source_id=None,
            data_classification="pilot_real",
            recorded_raw_g=0.0,
            damaged_raw_g=0.0,
            expires_at=exp_dt,
            expiry_known=expiry_known,
            received_at=now_utc,
            supplier_name=supplier_clean,
            verification_status="VERIFIED" if expiry_known else "UNVERIFIED",
            unit_original=norm.original_unit,
            quantity_original=norm.original_value,
            notes=notes_clean,
            created_at=now_utc,
        )
        session.add(lot)
        session.flush()
    elif supplier_clean:
        lot.supplier_name = supplier_clean

    delta_g = 0.0
    if req.adjustment_type == ManualStockAdjustmentTypeEnum.PURCHASE_RECEIPT:
        lot.recorded_raw_g += norm.normalized_raw_g
        lot.received_at = lot.received_at or now_utc
        if exp_dt is not None:
            lot.expires_at = exp_dt
            lot.expiry_known = True
            if lot.verification_status == "UNVERIFIED":
                lot.verification_status = "VERIFIED"
        delta_g = norm.normalized_raw_g
        msg = f"Penerimaan {norm.normalized_raw_g / 1000.0:.2f} kg dicatat pada lot {lot.lot_code}."
    elif req.adjustment_type == ManualStockAdjustmentTypeEnum.USAGE_CONSUMPTION:
        available_for_use = max(0.0, float(lot.recorded_raw_g) - float(lot.damaged_raw_g))
        if available_for_use + 1e-6 < norm.normalized_raw_g:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Pemakaian ({norm.normalized_raw_g / 1000.0:.2f} kg) melebihi sisa stok siap pakai lot "
                    f"{lot.lot_code} ({available_for_use / 1000.0:.2f} kg)."
                ),
            )
        lot.recorded_raw_g = max(0.0, float(lot.recorded_raw_g) - norm.normalized_raw_g)
        delta_g = -norm.normalized_raw_g
        msg = f"Pemakaian dapur {norm.normalized_raw_g / 1000.0:.2f} kg dicatat dari lot {lot.lot_code}."
    elif req.adjustment_type == ManualStockAdjustmentTypeEnum.SPOILAGE_DAMAGE:
        lot.damaged_raw_g += norm.normalized_raw_g
        delta_g = 0.0
        msg = f"Kerusakan {norm.normalized_raw_g / 1000.0:.2f} kg dicatat pada lot {lot.lot_code}."
    elif req.adjustment_type == ManualStockAdjustmentTypeEnum.STOCK_OPNAME_COUNT:
        discrepancy = norm.normalized_raw_g - float(lot.recorded_raw_g)
        recon_status = "MATCH" if abs(discrepancy) <= 1.0 else "DISCREPANCY"
        lot.verified_physical_raw_g = norm.normalized_raw_g
        lot.verified_at = now_utc
        if recon_status == "DISCREPANCY":
            lot.verification_status = "DISCREPANCY"
        elif lot.expiry_known and lot.verification_status in {"UNVERIFIED", "DISCREPANCY"}:
            lot.verification_status = "VERIFIED"
        session.add(
            InventoryReconciliationORM(
                id=str(uuid4()),
                kitchen_id=str(auth.kitchen_id),
                dataset_version_id=str(ds_id),
                ingredient_id=ing.id,
                lot_id=lot.id,
                recorded_raw_g=float(lot.recorded_raw_g),
                physical_raw_g=norm.normalized_raw_g,
                discrepancy_raw_g=discrepancy,
                status=recon_status,
                counted_by=auth.full_name,
                counted_at=now_utc,
                notes=notes_clean,
                created_at=now_utc,
            )
        )
        msg = (
            f"Hasil opname fisik lot {lot.lot_code}: {norm.normalized_raw_g / 1000.0:.2f} kg "
            f"(selisih {discrepancy / 1000.0:+.2f} kg)."
        )
    else:  # STOCK_CORRECTION -> set exact recorded total safely
        old_g = float(lot.recorded_raw_g)
        lot.recorded_raw_g = norm.normalized_raw_g
        if exp_dt is not None:
            lot.expires_at = exp_dt
            lot.expiry_known = True
            if lot.verification_status == "UNVERIFIED":
                lot.verification_status = "VERIFIED"
        delta_g = norm.normalized_raw_g - old_g
        msg = f"Koreksi stok tercatat lot {lot.lot_code} menjadi {norm.normalized_raw_g / 1000.0:.2f} kg."

    mov_id = str(uuid4())
    session.add(
        InventoryMovementORM(
            id=mov_id,
            kitchen_id=str(auth.kitchen_id),
            dataset_version_id=str(ds_id),
            ingredient_id=ing.id,
            lot_id=lot.id,
            movement_type=_TYPE_TO_MOVEMENT[req.adjustment_type],
            quantity_delta_raw_g=delta_g,
            original_value=norm.original_value,
            original_unit=norm.original_unit,
            idempotency_key=idemp_key,
            source_document_ref=req.source_document_ref.strip() if req.source_document_ref else None,
            source_id=None,
            event_at=now_utc,
            quarantined=False,
            actor_user_id=str(auth.user_id),
            created_at=now_utc,
        )
    )
    record_audit_event(
        session,
        action="inventory.manual_adjustment",
        entity_type="inventory_lot",
        entity_id=lot.id,
        kitchen_id=auth.kitchen_id,
        actor_user_id=auth.user_id,
        actor_role=auth.role.value,
        metadata={
            "adjustment_type": req.adjustment_type.value,
            "ingredient_code": ing.code,
            "lot_code": lot.lot_code,
            "delta_raw_g": delta_g,
            "recorded_raw_g": lot.recorded_raw_g,
        },
    )
    session.commit()

    return ManualStockAdjustmentResponse(
        movement_id=UUID(mov_id),
        lot_id=UUID(lot.id),
        lot_code=lot.lot_code,
        ingredient_code=ing.code,
        ingredient_name=ing.name,
        adjustment_type=req.adjustment_type,
        recorded_raw_g=float(lot.recorded_raw_g),
        damaged_raw_g=float(lot.damaged_raw_g),
        verified_physical_raw_g=lot.verified_physical_raw_g,
        verification_status=lot.verification_status,
        safety_hold_status=lot.safety_hold_status,
        supplier_name=lot.supplier_name,
        duplicate_skipped=False,
        message=msg,
    )
