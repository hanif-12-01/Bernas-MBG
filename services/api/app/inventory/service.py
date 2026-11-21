from __future__ import annotations

import csv
import io
import json
import math
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID, uuid4

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    DatasetSourceORM,
    DatasetStockSnapshotORM,
    DatasetVersionORM,
    IngredientORM,
    IngredientPriceORM,
    InventoryLotORM,
    InventoryMovementORM,
    InventoryReconciliationORM,
    MarketPriceReferenceORM,
    MenuReviewRecordORM,
    OperationalPlanAssignmentORM,
    OptimizationRunORM,
    RunMaterialUsageORM,
    StockReservationORM,
    SupplierDeliveryORM,
)
from app.ingestion.unit_converter import UnitConversionError, convert_price_to_idr_per_g
from app.inventory.coverage import IngredientCoverageForecast, compute_coverage_forecasts_for_kitchen
from app.inventory.timezone_utils import parse_production_date_jakarta, to_jakarta_date
from app.inventory.unit_normalizer import (
    PriceProvenanceEnum,
    classify_price_provenance,
    normalize_quantity_to_grams,
)

MANIFEST_PATH = Path(__file__).resolve().parents[1] / "data" / "source_manifest.json"
VALID_DATA_CLASSIFICATIONS = {"synthetic", "pilot_real"}
VALID_MARKET_PROVENANCE = {
    PriceProvenanceEnum.OFFICIAL_MARKET_REFERENCE.value,
    PriceProvenanceEnum.ACTUAL_SUPPLIER.value,
    PriceProvenanceEnum.SYNTHETIC_EXAMPLE.value,
    PriceProvenanceEnum.UNKNOWN.value,
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_iso_dt(raw: Optional[str], *, field: str) -> Optional[datetime]:
    if raw is None:
        return None
    text = raw.strip()
    if not text:
        return None
    if len(text) == 10:
        try:
            d = date.fromisoformat(text)
            return datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=timezone.utc)
        except ValueError as exc:
            raise ValueError(f"Format tanggal tidak valid untuk {field}: '{text}'") from exc
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"Format datetime ISO tidak valid untuk {field}: '{text}'") from exc
    return _ensure_utc(dt)


class InventoryLotSummary(BaseModel):
    id: UUID
    lot_code: str
    recorded_raw_g: float
    usable_raw_g: float = 0.0
    damaged_raw_g: float = 0.0
    expires_at: Optional[datetime] = None
    expiry_known: bool = False
    received_at: Optional[datetime] = None
    supplier_name: Optional[str] = None
    purchase_document_id: Optional[UUID] = None
    days_until_expiry: Optional[int] = None
    verification_status: str
    safety_hold_status: str = "NONE"
    notes: Optional[str] = None


class IngredientAvailability(BaseModel):
    ingredient_id: UUID
    ingredient_code: str
    ingredient_name: str
    unit: str = "g"
    recorded_raw_g: Optional[float] = None
    usable_raw_g: Optional[float] = None
    physical_raw_g: Optional[float] = None
    reserved_raw_g: float = 0.0
    unavailable_raw_g: float = 0.0
    expired_raw_g: float = 0.0
    damaged_raw_g: float = 0.0
    unverified_raw_g: float = 0.0
    safety_held_raw_g: float = 0.0
    rejected_disposed_raw_g: float = 0.0
    held_lot_codes: List[str] = Field(default_factory=list)
    lots: List[InventoryLotSummary] = Field(default_factory=list)
    incoming_raw_g: float = 0.0
    delivery_status: str = "NONE"
    quarantined_events_count: int = 0
    latest_supplier_name: Optional[str] = None
    latest_received_at: Optional[datetime] = None
    nearest_expiry_at: Optional[datetime] = None
    days_until_nearest_expiry: Optional[int] = None
    coverage: Optional[IngredientCoverageForecast] = None
    as_of_timestamp: datetime
    production_date: datetime
    dataset_version_id: UUID
    source_name: str
    data_classification: str  # synthetic | pilot_real
    data_quality_status: str  # VERIFIED | SYNTHETIC_BASELINE | PARTIAL_OR_ADJUSTED | DISCREPANCY | UNVERIFIED | UNKNOWN | QUARANTINED | SAFETY_HOLD | PARTIAL_SAFETY_HOLD
    last_verified_at: Optional[datetime] = None
    availability_explanation: str
    warnings: List[str] = Field(default_factory=list)


class InventoryAvailabilitySummary(BaseModel):
    kitchen_id: UUID
    dataset_version_id: UUID
    production_date: datetime
    as_of_timestamp: datetime
    uses_batch_ledger: bool
    verified_count: int
    warning_count: int
    unknown_count: int
    quarantined_events_count: int
    items: List[IngredientAvailability] = Field(default_factory=list)


class InventoryTransactionRowResult(BaseModel):
    row_number: int
    idempotency_key: str
    event_type: str
    ingredient_code: str
    status: str  # APPLIED | DUPLICATE_SKIPPED | QUARANTINED | VALIDATED_DRY_RUN | ERROR
    normalized_raw_g: Optional[float] = None
    message: str


class InventoryTransactionImportResponse(BaseModel):
    dataset_version_id: UUID
    kitchen_id: UUID
    dry_run: bool
    data_classification: str
    total_rows: int
    applied_count: int
    duplicate_skipped_count: int
    quarantined_count: int
    error_count: int
    results: List[InventoryTransactionRowResult] = Field(default_factory=list)


class MarketPriceReferenceItem(BaseModel):
    id: UUID
    commodity_code: str
    commodity_name: str
    canonical_ingredient_code: Optional[str] = None
    region: str
    observed_date: date
    price_value: float
    unit: str
    price_idr_per_g: Optional[float] = None
    price_provenance: PriceProvenanceEnum
    source_name: str
    published_at: Optional[date] = None
    retrieved_at: datetime
    imported_at: datetime
    quality_status: str
    notes: Optional[str] = None


class MarketReferenceImportResponse(BaseModel):
    imported_count: int
    skipped_count: int
    source_name: str
    price_provenance: PriceProvenanceEnum
    warnings: List[str] = Field(default_factory=list)
    items: List[MarketPriceReferenceItem] = Field(default_factory=list)


class ApprovedPlanInventoryAlert(BaseModel):
    menu_review_id: UUID
    run_id: UUID
    title: str
    status: str
    operational_status: Optional[str] = None
    hold_incident_id: Optional[UUID] = None
    hold_reason: Optional[str] = None
    requires_inventory_review: bool
    affected_ingredients: List[str] = Field(default_factory=list)
    summary_message: str


def load_source_manifest_entries() -> List[Dict[str, Any]]:
    if not MANIFEST_PATH.exists():
        return []
    raw = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return list(raw.get("sources", []))


def seed_dataset_sources_if_empty(session: Session) -> None:
    existing = list(session.execute(select(DatasetSourceORM.source_name)).scalars().all())
    existing_set = set(existing)
    for src in load_source_manifest_entries():
        name = src.get("source_name")
        if not name or name in existing_set:
            continue
        retrieved = _parse_iso_dt(src.get("retrieved_at"), field="retrieved_at") or _utcnow()
        session.add(
            DatasetSourceORM(
                id=str(uuid4()),
                kitchen_id=None,
                source_name=name,
                source_url=src.get("source_url"),
                license=src.get("license", "UNKNOWN"),
                license_verified=bool(src.get("license_verified", False)),
                dataset_type=src.get("dataset_type", "synthetic"),
                retrieved_at=retrieved,
                checksum=src.get("checksum"),
                allowed_use=src.get("allowed_use", "UNSPECIFIED"),
                transformation_notes=src.get("transformation_notes"),
                created_at=_utcnow(),
            )
        )


def compute_usable_inventory(
    session: Session,
    *,
    kitchen_id: UUID,
    dataset_version_id: UUID,
    production_date: Optional[datetime] = None,
) -> InventoryAvailabilitySummary:
    """Compute kitchen-isolated usable stock for a specific production date/time.

    Guarantees:
    - Strict kitchen isolation: only lots/movements/reservations/deliveries belonging to kitchen_id.
    - Backwards compatibility: if no batch ledger records exist for (kitchen_id, dataset_version_id),
      falls back transparently to dataset_stock_snapshots.
    - Never counts pending/delayed deliveries as on-hand stock.
    - Never counts expired or damaged stock as usable, and never double-subtracts unusable buckets.
    - Never treats missing expiration data (expiry_known=False) or UNKNOWN lots as confirmed fresh stock.
    - Never fabricates stock for missing ingredient records (exposes explicit UNKNOWN state).
    """
    prod_dt = _ensure_utc(production_date) or parse_production_date_jakarta(None)
    prod_jkt_date = to_jakarta_date(prod_dt)
    as_of = _utcnow()

    ds_row = session.get(DatasetVersionORM, str(dataset_version_id))
    if ds_row is None:
        raise ValueError(f"Dataset '{dataset_version_id}' not found")

    ingredients = list(
        session.execute(
            select(IngredientORM)
            .where(IngredientORM.dataset_version_id == str(dataset_version_id))
            .order_by(IngredientORM.code)
        )
        .scalars()
        .all()
    )

    snapshots_by_ing = {
        row.ingredient_id: row
        for row in session.execute(
            select(DatasetStockSnapshotORM).where(
                DatasetStockSnapshotORM.dataset_version_id == str(dataset_version_id)
            )
        )
        .scalars()
        .all()
    }

    lots = list(
        session.execute(
            select(InventoryLotORM).where(
                InventoryLotORM.kitchen_id == str(kitchen_id),
                InventoryLotORM.dataset_version_id == str(dataset_version_id),
            )
        )
        .scalars()
        .all()
    )
    reservations = list(
        session.execute(
            select(StockReservationORM).where(
                StockReservationORM.kitchen_id == str(kitchen_id),
                StockReservationORM.dataset_version_id == str(dataset_version_id),
                StockReservationORM.status == "ACTIVE",
            )
        )
        .scalars()
        .all()
    )
    deliveries = list(
        session.execute(
            select(SupplierDeliveryORM).where(
                SupplierDeliveryORM.kitchen_id == str(kitchen_id),
                SupplierDeliveryORM.dataset_version_id == str(dataset_version_id),
            )
        )
        .scalars()
        .all()
    )
    reconciliations = list(
        session.execute(
            select(InventoryReconciliationORM).where(
                InventoryReconciliationORM.kitchen_id == str(kitchen_id),
                InventoryReconciliationORM.dataset_version_id == str(dataset_version_id),
            )
        )
        .scalars()
        .all()
    )
    quarantined_movements = list(
        session.execute(
            select(InventoryMovementORM).where(
                InventoryMovementORM.kitchen_id == str(kitchen_id),
                InventoryMovementORM.dataset_version_id == str(dataset_version_id),
                InventoryMovementORM.quarantined.is_(True),
            )
        )
        .scalars()
        .all()
    )

    source_names_by_id = {
        s.id: s.source_name
        for s in session.execute(select(DatasetSourceORM)).scalars().all()
    }

    uses_batch_ledger = bool(
        lots or reservations or deliveries or reconciliations or quarantined_movements
    )

    lots_by_ing: Dict[str, List[InventoryLotORM]] = {}
    for lot in lots:
        lots_by_ing.setdefault(lot.ingredient_id, []).append(lot)

    res_by_ing: Dict[str, List[StockReservationORM]] = {}
    for res in reservations:
        res_by_ing.setdefault(res.ingredient_id, []).append(res)

    deliv_by_ing: Dict[str, List[SupplierDeliveryORM]] = {}
    for d in deliveries:
        deliv_by_ing.setdefault(d.ingredient_id, []).append(d)

    recon_by_ing: Dict[str, List[InventoryReconciliationORM]] = {}
    for rec in reconciliations:
        recon_by_ing.setdefault(rec.ingredient_id, []).append(rec)

    quar_by_ing: Dict[str, List[InventoryMovementORM]] = {}
    for qm in quarantined_movements:
        quar_by_ing.setdefault(qm.ingredient_id, []).append(qm)

    items: List[IngredientAvailability] = []
    verified_count = 0
    warning_count = 0
    unknown_count = 0
    total_quarantined = len(quarantined_movements)
    usable_lots_by_ing_id: Dict[str, List[Tuple[float, Optional[datetime]]]] = {}
    safety_held_by_ing_id: Dict[str, float] = {}
    unverified_by_ing_id: Dict[str, float] = {}

    for ing in ingredients:
        ing_lots = lots_by_ing.get(ing.id, [])
        ing_res = [
            r
            for r in res_by_ing.get(ing.id, [])
            if (_ensure_utc(r.production_date) or prod_dt) <= prod_dt
        ]
        ing_deliv = deliv_by_ing.get(ing.id, [])
        ing_recon = recon_by_ing.get(ing.id, [])
        ing_quar = quar_by_ing.get(ing.id, [])
        snap = snapshots_by_ing.get(ing.id)

        if not uses_batch_ledger:
            # Legacy flat snapshot compatibility mode
            if snap is None:
                unknown_count += 1
                items.append(
                    IngredientAvailability(
                        ingredient_id=UUID(ing.id),
                        ingredient_code=ing.code,
                        ingredient_name=ing.name,
                        recorded_raw_g=None,
                        usable_raw_g=None,
                        physical_raw_g=None,
                        as_of_timestamp=as_of,
                        production_date=prod_dt,
                        dataset_version_id=dataset_version_id,
                        source_name=ds_row.name,
                        data_classification="synthetic" if ds_row.is_synthetic else "pilot_real",
                        data_quality_status="UNKNOWN",
                        availability_explanation=(
                            f"Tidak ada catatan stok untuk {ing.name} dalam dataset ini (status UNKNOWN)."
                        ),
                        warnings=["Catatan stok belum tersedia."],
                    )
                )
            else:
                q_status = "SYNTHETIC_BASELINE" if ds_row.is_synthetic else "UNVERIFIED"
                if ds_row.is_synthetic:
                    verified_count += 1
                else:
                    warning_count += 1
                items.append(
                    IngredientAvailability(
                        ingredient_id=UUID(ing.id),
                        ingredient_code=ing.code,
                        ingredient_name=ing.name,
                        recorded_raw_g=round(snap.stock_raw_g, 3),
                        usable_raw_g=round(snap.stock_raw_g, 3),
                        physical_raw_g=None,
                        as_of_timestamp=as_of,
                        production_date=prod_dt,
                        dataset_version_id=dataset_version_id,
                        source_name=ds_row.name,
                        data_classification="synthetic" if ds_row.is_synthetic else "pilot_real",
                        data_quality_status=q_status,
                        last_verified_at=_ensure_utc(snap.recorded_at),
                        availability_explanation=(
                            f"Stok {ing.name} menggunakan snapshot baseline dataset sebesar "
                            f"{snap.stock_raw_g / 1000.0:.2f} kg ({'data simulasi DEMO_ONLY' if ds_row.is_synthetic else 'snapshot datar tanpa verifikasi batch'})."
                        ),
                        warnings=(
                            []
                            if ds_row.is_synthetic
                            else ["Menggunakan snapshot datar; belum ada catatan batch/kedaluwarsa."]
                        ),
                    )
                )
            continue

        # Batch & ledger-aware calculation
        incoming_raw_g = sum(
            max(0.0, d.expected_raw_g - d.received_raw_g)
            for d in ing_deliv
            if d.status in {"PROMISED", "DELAYED", "PARTIAL"}
        )
        deliv_statuses = {d.status for d in ing_deliv}
        if "DELAYED" in deliv_statuses:
            delivery_status = "DELAYED"
        elif "PARTIAL" in deliv_statuses:
            delivery_status = "PARTIAL"
        elif "PROMISED" in deliv_statuses:
            delivery_status = "PROMISED"
        elif "RECEIVED" in deliv_statuses:
            delivery_status = "RECEIVED"
        else:
            delivery_status = "NONE"

        # Missing inventory record (Scenario G)
        if not ing_lots and snap is None:
            warnings: List[str] = []
            if incoming_raw_g > 0:
                warnings.append(
                    f"Ada pengiriman {delivery_status.lower()} sebesar {incoming_raw_g / 1000.0:.2f} kg yang belum diterima — tidak dihitung sebagai stok siap pakai."
                )
                usable_val = 0.0
                rec_val = 0.0
                q_status = "UNVERIFIED"
                warning_count += 1
                expl = (
                    f"Stok di tangan untuk {ing.name} belum tercatat (0 kg), sedangkan pengiriman "
                    f"{incoming_raw_g / 1000.0:.2f} kg masih berstatus {delivery_status} dan belum tiba."
                )
            else:
                warnings.append("Tidak ada catatan lot stok maupun snapshot awal.")
                usable_val = None
                rec_val = None
                q_status = "UNKNOWN"
                unknown_count += 1
                expl = f"Ketersediaan {ing.name} tidak diketahui (UNKNOWN) karena tidak ada catatan stok terverifikasi."
            if ing_quar:
                warnings.append(f"{len(ing_quar)} transaksi bermasalah dikarantina.")
            items.append(
                IngredientAvailability(
                    ingredient_id=UUID(ing.id),
                    ingredient_code=ing.code,
                    ingredient_name=ing.name,
                    recorded_raw_g=rec_val,
                    usable_raw_g=usable_val,
                    physical_raw_g=None,
                    incoming_raw_g=round(incoming_raw_g, 3),
                    delivery_status=delivery_status,
                    quarantined_events_count=len(ing_quar),
                    as_of_timestamp=as_of,
                    production_date=prod_dt,
                    dataset_version_id=dataset_version_id,
                    source_name=ds_row.name,
                    data_classification="synthetic" if ds_row.is_synthetic else "pilot_real",
                    data_quality_status=q_status,
                    availability_explanation=expl,
                    warnings=warnings,
                )
            )
            continue

        # Compute across lots (never double-subtracting expired + damaged)
        recorded_raw_g = 0.0
        safety_held_raw_g = 0.0
        rejected_disposed_raw_g = 0.0
        expired_raw_g = 0.0
        damaged_raw_g = 0.0
        unverified_raw_g = 0.0
        discrepancy_delta_g = 0.0
        physical_values: List[float] = []
        verified_timestamps: List[datetime] = []
        classifications = set()
        lot_sources = set()
        lot_usable_map: Dict[str, float] = {}
        held_lot_codes: List[str] = []
        warnings = []

        for lot in ing_lots:
            recorded_raw_g += lot.recorded_raw_g
            classifications.add(lot.data_classification)
            if lot.source_id and lot.source_id in source_names_by_id:
                lot_sources.add(source_names_by_id[lot.source_id])
            if lot.verified_at:
                vdt = _ensure_utc(lot.verified_at)
                if vdt:
                    verified_timestamps.append(vdt)
            if lot.verified_physical_raw_g is not None:
                physical_values.append(lot.verified_physical_raw_g)

            exp_dt = _ensure_utc(lot.expires_at)
            hold_status = getattr(lot, "safety_hold_status", "NONE") or "NONE"

            # 0. Safety hold / rejected-disposed exclusion takes highest priority (no double subtraction)
            if hold_status == "ON_HOLD":
                safety_held_raw_g += lot.recorded_raw_g
                lot_usable_map[lot.id] = 0.0
                held_lot_codes.append(lot.lot_code)
                warnings.append(
                    f"Lot {lot.lot_code} ({lot.recorded_raw_g / 1000.0:.2f} kg) sedang dalam STATUS TAHAN KEAMANAN (ON_HOLD) dan dikecualikan dari stok siap pakai."
                )
                continue
            if hold_status == "REJECTED_DISPOSED":
                rejected_disposed_raw_g += lot.recorded_raw_g
                lot_usable_map[lot.id] = 0.0
                warnings.append(
                    f"Lot {lot.lot_code} ({lot.recorded_raw_g / 1000.0:.2f} kg) berstatus DITOLAK/DIMUSNAHKAN (REJECTED_DISPOSED)."
                )
                continue

            # 1. Quarantine or explicitly unknown lot cannot count as confirmed usable
            if lot.verification_status in {"QUARANTINED", "UNKNOWN"}:
                unverified_raw_g += lot.recorded_raw_g
                lot_usable_map[lot.id] = 0.0
                warnings.append(
                    f"Lot {lot.lot_code} ({lot.recorded_raw_g / 1000.0:.2f} kg) berstatus {lot.verification_status}."
                )
                continue

            # 2. Missing expiration date is NEVER treated as proof of freshness
            if not lot.expiry_known or exp_dt is None:
                unverified_raw_g += lot.recorded_raw_g
                lot_usable_map[lot.id] = 0.0
                warnings.append(
                    f"Lot {lot.lot_code} ({lot.recorded_raw_g / 1000.0:.2f} kg) belum memiliki tanggal kedaluwarsa yang terverifikasi."
                )
                continue

            # 3. Expired at or before production_date -> whole lot unavailable (no double subtraction)
            if exp_dt <= prod_dt:
                expired_raw_g += lot.recorded_raw_g
                lot_usable_map[lot.id] = 0.0
                warnings.append(
                    f"Lot {lot.lot_code} ({lot.recorded_raw_g / 1000.0:.2f} kg) kedaluwarsa per {exp_dt.date().isoformat()}."
                )
                continue

            # 4. Valid unexpired lot: apply damage once, bounded by recorded or verified physical lower count
            book_base = lot.recorded_raw_g
            if lot.verified_physical_raw_g is not None and lot.verified_physical_raw_g < book_base:
                discrepancy_delta_g += book_base - lot.verified_physical_raw_g
                book_base = lot.verified_physical_raw_g
                warnings.append(
                    f"Selisih stok fisik pada lot {lot.lot_code}: tercatat {lot.recorded_raw_g / 1000.0:.2f} kg, fisik {lot.verified_physical_raw_g / 1000.0:.2f} kg."
                )
            elif lot.verified_physical_raw_g is not None and lot.verified_physical_raw_g > book_base:
                warnings.append(
                    f"Stok fisik lot {lot.lot_code} ({lot.verified_physical_raw_g / 1000.0:.2f} kg) lebih tinggi dari buku ({lot.recorded_raw_g / 1000.0:.2f} kg); perlu rekonsiliasi."
                )

            valid_damaged = min(lot.damaged_raw_g, book_base)
            damaged_raw_g += valid_damaged
            lot_usable_map[lot.id] = max(0.0, book_base - valid_damaged)

        # Apply reservations (lot-scoped against that lot first, general against sum) without double counting
        reserved_applied = 0.0
        general_reserved = 0.0
        for res in ing_res:
            if res.lot_id and res.lot_id in lot_usable_map:
                before = lot_usable_map[res.lot_id]
                deduct = min(before, res.reserved_raw_g)
                lot_usable_map[res.lot_id] = before - deduct
                reserved_applied += res.reserved_raw_g
            else:
                general_reserved += res.reserved_raw_g
                reserved_applied += res.reserved_raw_g

        usable_before_general = sum(lot_usable_map.values())
        usable_raw_g = max(0.0, usable_before_general - general_reserved)

        lot_summaries: List[InventoryLotSummary] = []
        lot_dates: List[Tuple[datetime, InventoryLotORM]] = []
        for lot in ing_lots:
            lot_exp_dt = _ensure_utc(lot.expires_at)
            days_until = (
                (to_jakarta_date(lot_exp_dt) - prod_jkt_date).days
                if (lot.expiry_known and lot_exp_dt is not None)
                else None
            )
            lot_summaries.append(
                InventoryLotSummary(
                    id=UUID(lot.id),
                    lot_code=lot.lot_code,
                    recorded_raw_g=round(lot.recorded_raw_g, 3),
                    usable_raw_g=round(lot_usable_map.get(lot.id, 0.0), 3),
                    damaged_raw_g=round(lot.damaged_raw_g, 3),
                    expires_at=lot.expires_at,
                    expiry_known=lot.expiry_known,
                    received_at=lot.received_at,
                    supplier_name=getattr(lot, "supplier_name", None),
                    purchase_document_id=(
                        UUID(lot.purchase_document_id)
                        if getattr(lot, "purchase_document_id", None)
                        else None
                    ),
                    days_until_expiry=days_until,
                    verification_status=lot.verification_status,
                    safety_hold_status=getattr(lot, "safety_hold_status", "NONE") or "NONE",
                    notes=lot.notes,
                )
            )
            sort_ts = _ensure_utc(lot.received_at or lot.created_at) or as_of
            lot_dates.append((sort_ts, lot))

        lot_dates.sort(key=lambda pair: pair[0], reverse=True)
        latest_supplier_name = next(
            (
                getattr(l, "supplier_name", None)
                for _, l in lot_dates
                if getattr(l, "supplier_name", None)
            ),
            None,
        )
        received_timestamps = [_ensure_utc(l.received_at) for l in ing_lots if l.received_at is not None]
        latest_received_at = (
            max(dt for dt in received_timestamps if dt is not None) if received_timestamps else None
        )
        usable_expiries = [
            _ensure_utc(lot.expires_at)
            for lot in ing_lots
            if lot_usable_map.get(lot.id, 0.0) > 1e-6 and lot.expiry_known and lot.expires_at is not None
        ]
        fallback_expiries = [
            _ensure_utc(lot.expires_at)
            for lot in ing_lots
            if (getattr(lot, "safety_hold_status", "NONE") or "NONE") == "NONE"
            and lot.expiry_known
            and lot.expires_at is not None
        ]
        candidate_expiries = [d for d in (usable_expiries or fallback_expiries) if d is not None]
        nearest_expiry_at = min(candidate_expiries) if candidate_expiries else None
        days_until_nearest_expiry = (
            (to_jakarta_date(nearest_expiry_at) - prod_jkt_date).days
            if nearest_expiry_at is not None
            else None
        )

        # Record usable FEFO lots for batch coverage forecast after loop
        usable_lots_by_ing_id[ing.id] = [
            (
                float(lot_usable_map.get(lot.id, 0.0)),
                _ensure_utc(lot.expires_at),
            )
            for lot in ing_lots
            if lot_usable_map.get(lot.id, 0.0) > 1e-6 and lot.expiry_known and lot.expires_at is not None
        ]
        safety_held_by_ing_id[ing.id] = safety_held_raw_g + rejected_disposed_raw_g
        unverified_by_ing_id[ing.id] = unverified_raw_g

        # If every single lot was unverified/missing expiry/on hold and usable is 0 with zero clean verified lots
        has_verified_lot = any(
            (getattr(lot, "safety_hold_status", "NONE") or "NONE") == "NONE"
            and lot.verification_status in {"VERIFIED", "DISCREPANCY"}
            and lot.expiry_known
            and lot.expires_at is not None
            for lot in ing_lots
        )

        # Compute physical total if physical counts exist
        physical_raw_g: Optional[float] = round(sum(physical_values), 3) if physical_values else None
        if ing_recon:
            for r in ing_recon:
                if r.status == "DISCREPANCY_DETECTED" and not any("Selisih stok" in w for w in warnings):
                    warnings.append(
                        f"Rekonsiliasi terakhir mencatat selisih {r.discrepancy_raw_g / 1000.0:.2f} kg."
                    )

        if ing_quar:
            warnings.append(
                f"{len(ing_quar)} transaksi untuk bahan ini dikarantina karena konflik unit atau nilai tidak valid."
            )
        if incoming_raw_g > 0:
            warnings.append(
                f"Pengiriman {delivery_status} sebesar {incoming_raw_g / 1000.0:.2f} kg belum dikonfirmasi tiba dan tidak dimasukkan ke stok siap pakai."
            )

        unavailable_raw_g = (
            safety_held_raw_g
            + rejected_disposed_raw_g
            + expired_raw_g
            + damaged_raw_g
            + unverified_raw_g
            + discrepancy_delta_g
        )

        if (safety_held_raw_g > 0 or rejected_disposed_raw_g > 0) and usable_raw_g <= 1e-6:
            q_status = "SAFETY_HOLD"
            warning_count += 1
            usable_out: Optional[float] = round(usable_raw_g, 3)
        elif (safety_held_raw_g > 0 or rejected_disposed_raw_g > 0) and usable_raw_g > 1e-6:
            q_status = "PARTIAL_SAFETY_HOLD"
            warning_count += 1
            usable_out = round(usable_raw_g, 3)
        elif not has_verified_lot and unverified_raw_g > 0:
            q_status = "UNVERIFIED"
            warning_count += 1
            usable_out = None if all(l.verification_status == "UNKNOWN" for l in ing_lots) else round(usable_raw_g, 3)
        elif ing_quar and usable_raw_g == 0 and recorded_raw_g == 0:
            q_status = "QUARANTINED"
            warning_count += 1
            usable_out = None
        elif discrepancy_delta_g > 0 or any(r.status == "DISCREPANCY_DETECTED" for r in ing_recon):
            q_status = "DISCREPANCY"
            warning_count += 1
            usable_out = round(usable_raw_g, 3)
        elif unavailable_raw_g > 0 or reserved_applied > 0 or incoming_raw_g > 0 or ing_quar:
            q_status = "PARTIAL_OR_ADJUSTED"
            warning_count += 1
            usable_out = round(usable_raw_g, 3)
        else:
            q_status = "VERIFIED"
            verified_count += 1
            usable_out = round(usable_raw_g, 3)

        # Human-readable Indonesian explanation
        rec_kg = recorded_raw_g / 1000.0
        if usable_out is None:
            expl = (
                f"Stok {ing.name} tercatat {rec_kg:.2f} kg, namun berstatus {q_status} karena belum ada lot terverifikasi untuk tanggal produksi ini."
            )
        elif abs(recorded_raw_g - usable_out) > 1e-6 or safety_held_raw_g > 0 or rejected_disposed_raw_g > 0:
            reasons: List[str] = []
            if safety_held_raw_g > 0:
                reasons.append(f"{safety_held_raw_g / 1000.0:.2f} kg ditahan keamanan (ON_HOLD)")
            if rejected_disposed_raw_g > 0:
                reasons.append(f"{rejected_disposed_raw_g / 1000.0:.2f} kg ditolak/dimusnahkan")
            if reserved_applied > 0:
                reasons.append(f"{reserved_applied / 1000.0:.2f} kg dialokasikan")
            if expired_raw_g > 0:
                reasons.append(f"{expired_raw_g / 1000.0:.2f} kg kedaluwarsa")
            if damaged_raw_g > 0:
                reasons.append(f"{damaged_raw_g / 1000.0:.2f} kg rusak")
            if unverified_raw_g > 0:
                reasons.append(f"{unverified_raw_g / 1000.0:.2f} kg belum terverifikasi")
            if discrepancy_delta_g > 0:
                reasons.append(f"penyesuaian selisih fisik {discrepancy_delta_g / 1000.0:.2f} kg")
            expl = (
                f"Stok {ing.name} tercatat {rec_kg:.2f} kg, tetapi hanya {usable_out / 1000.0:.2f} kg yang dapat digunakan untuk produksi pada tanggal ini"
                + (f" ({', '.join(reasons)})." if reasons else ".")
            )
        else:
            expl = f"Stok {ing.name} sebesar {usable_out / 1000.0:.2f} kg terverifikasi dan siap digunakan untuk produksi."

        if "pilot_real" in classifications:
            data_cls = "pilot_real"
        elif classifications:
            data_cls = next(iter(classifications))
        else:
            data_cls = "synthetic" if ds_row.is_synthetic else "pilot_real"

        source_name = ", ".join(sorted(lot_sources)) if lot_sources else ds_row.name
        last_verified = max(verified_timestamps) if verified_timestamps else None

        items.append(
            IngredientAvailability(
                ingredient_id=UUID(ing.id),
                ingredient_code=ing.code,
                ingredient_name=ing.name,
                recorded_raw_g=round(recorded_raw_g, 3),
                usable_raw_g=usable_out,
                physical_raw_g=physical_raw_g,
                reserved_raw_g=round(reserved_applied, 3),
                unavailable_raw_g=round(unavailable_raw_g, 3),
                expired_raw_g=round(expired_raw_g, 3),
                damaged_raw_g=round(damaged_raw_g, 3),
                unverified_raw_g=round(unverified_raw_g, 3),
                safety_held_raw_g=round(safety_held_raw_g, 3),
                rejected_disposed_raw_g=round(rejected_disposed_raw_g, 3),
                held_lot_codes=sorted(held_lot_codes),
                lots=lot_summaries,
                incoming_raw_g=round(incoming_raw_g, 3),
                delivery_status=delivery_status,
                quarantined_events_count=len(ing_quar),
                latest_supplier_name=latest_supplier_name,
                latest_received_at=latest_received_at,
                nearest_expiry_at=nearest_expiry_at,
                days_until_nearest_expiry=days_until_nearest_expiry,
                as_of_timestamp=as_of,
                production_date=prod_dt,
                dataset_version_id=dataset_version_id,
                source_name=source_name,
                data_classification=data_cls,
                data_quality_status=q_status,
                last_verified_at=last_verified,
                availability_explanation=expl,
                warnings=warnings,
            )
        )

    coverage_map = compute_coverage_forecasts_for_kitchen(
        session,
        kitchen_id=kitchen_id,
        dataset_version_id=dataset_version_id,
        production_dt_utc=prod_dt,
        usable_lots_by_ing_id=usable_lots_by_ing_id,
        safety_held_by_ing_id=safety_held_by_ing_id,
        unverified_by_ing_id=unverified_by_ing_id,
    )
    for item in items:
        item.coverage = coverage_map.get(str(item.ingredient_id))

    return InventoryAvailabilitySummary(
        kitchen_id=kitchen_id,
        dataset_version_id=dataset_version_id,
        production_date=prod_dt,
        as_of_timestamp=as_of,
        uses_batch_ledger=uses_batch_ledger,
        verified_count=verified_count,
        warning_count=warning_count,
        unknown_count=unknown_count,
        quarantined_events_count=total_quarantined,
        items=items,
    )


def evaluate_approved_plans_against_inventory(
    session: Session,
    *,
    kitchen_id: UUID,
    production_date: Optional[datetime] = None,
) -> List[ApprovedPlanInventoryAlert]:
    """Non-destructively verify whether operationally APPROVED plans remain feasible under latest usable stock.

    Does NOT alter or unapprove historical menu reviews or snapshots.
    """
    approved_reviews = list(
        session.execute(
            select(MenuReviewRecordORM)
            .where(
                MenuReviewRecordORM.kitchen_id == str(kitchen_id),
                MenuReviewRecordORM.status == "APPROVED",
            )
            .order_by(MenuReviewRecordORM.reviewed_at.desc())
        )
        .scalars()
        .all()
    )

    op_rows = list(
        session.execute(
            select(OperationalPlanAssignmentORM).where(
                OperationalPlanAssignmentORM.kitchen_id == str(kitchen_id)
            )
        )
        .scalars()
        .all()
    )
    op_by_review = {r.menu_review_id: r for r in op_rows}

    availability_cache: Dict[str, Dict[str, IngredientAvailability]] = {}
    alerts: List[ApprovedPlanInventoryAlert] = []

    for rev in approved_reviews:
        op_row = op_by_review.get(rev.id)
        if op_row is not None and op_row.operational_status == "SUPERSEDED":
            continue
        if rev.dataset_version_id not in availability_cache:
            summary = compute_usable_inventory(
                session,
                kitchen_id=kitchen_id,
                dataset_version_id=UUID(rev.dataset_version_id),
                production_date=production_date,
            )
            availability_cache[rev.dataset_version_id] = {
                item.ingredient_code: item for item in summary.items
            }
        avail_by_code = availability_cache[rev.dataset_version_id]
        usages = list(
            session.execute(
                select(RunMaterialUsageORM).where(RunMaterialUsageORM.run_id == rev.run_id)
            )
            .scalars()
            .all()
        )

        shortages: List[str] = []
        for u in usages:
            avail = avail_by_code.get(u.ingredient_code)
            if avail is None or avail.usable_raw_g is None:
                shortages.append(f"{u.ingredient_name} (stok tidak diketahui)")
            elif avail.usable_raw_g + 1e-6 < u.used_raw_g:
                shortages.append(
                    f"{u.ingredient_name}: butuh {u.used_raw_g / 1000.0:.2f} kg, siap pakai {avail.usable_raw_g / 1000.0:.2f} kg"
                )

        is_held = op_row is not None and op_row.operational_status == "ON_HOLD"
        if shortages or is_held:
            op_status = op_row.operational_status if op_row is not None else "APPROVED"
            if is_held:
                msg = (
                    f"Rencana '{rev.title}' berstatus ON HOLD karena insiden keamanan bahan: "
                    f"{op_row.hold_reason or 'menunggu pemulihan'}."
                    + (f" Kekurangan stok layak: {'; '.join(shortages)}." if shortages else "")
                )
            else:
                msg = (
                    f"Rencana '{rev.title}' tetap tersimpan dengan snapshot aslinya, namun memerlukan peninjauan ulang karena stok terbaru tidak mencukupi: {'; '.join(shortages)}."
                )
            alerts.append(
                ApprovedPlanInventoryAlert(
                    menu_review_id=UUID(rev.id),
                    run_id=UUID(rev.run_id),
                    title=rev.title,
                    status=rev.status,
                    operational_status=op_status,
                    hold_incident_id=(
                        UUID(op_row.hold_incident_id)
                        if op_row is not None and op_row.hold_incident_id
                        else None
                    ),
                    hold_reason=op_row.hold_reason if op_row is not None else None,
                    requires_inventory_review=True,
                    affected_ingredients=shortages,
                    summary_message=msg,
                )
            )

    return alerts


def import_inventory_transactions_csv(
    session: Session,
    *,
    kitchen_id: UUID,
    dataset_version_id: UUID,
    csv_text: str,
    data_classification: str = "synthetic",
    authorization_confirmed: bool = False,
    dry_run: bool = False,
    actor_user_id: Optional[UUID] = None,
    source_name: str = "Manual Kitchen CSV Import",
) -> InventoryTransactionImportResponse:
    """Idempotent CSV importer for inventory lots, receipts, damages, reservations, counts & deliveries.

    Enforces:
    - Explicit authorization required when importing pilot_real records.
    - Idempotent deduplication by idempotency_key (duplicate deliveries never double stock).
    - Quarantine on claimed_unit conflict (e.g. 500 g vs 500 kg) or unsupported/negative quantities.
    - Optional dry_run preview before committing changes.
    """
    if data_classification not in VALID_DATA_CLASSIFICATIONS:
        raise ValueError(f"data_classification harus salah satu dari {sorted(VALID_DATA_CLASSIFICATIONS)}")
    if data_classification == "pilot_real" and not authorization_confirmed:
        raise PermissionError(
            "Impor data dapur nyata (pilot_real) memerlukan konfirmasi otorisasi eksplisit."
        )

    ing_rows = list(
        session.execute(
            select(IngredientORM).where(IngredientORM.dataset_version_id == str(dataset_version_id))
        )
        .scalars()
        .all()
    )
    ing_by_code = {r.code: r for r in ing_rows}

    existing_mov_keys = set(
        session.execute(
            select(InventoryMovementORM.idempotency_key).where(
                InventoryMovementORM.kitchen_id == str(kitchen_id),
                InventoryMovementORM.dataset_version_id == str(dataset_version_id),
            )
        )
        .scalars()
        .all()
    )
    existing_deliv_keys = set(
        session.execute(
            select(SupplierDeliveryORM.idempotency_key).where(
                SupplierDeliveryORM.kitchen_id == str(kitchen_id),
                SupplierDeliveryORM.dataset_version_id == str(dataset_version_id),
            )
        )
        .scalars()
        .all()
    )
    existing_res_keys = set(
        session.execute(
            select(StockReservationORM.idempotency_key).where(
                StockReservationORM.kitchen_id == str(kitchen_id),
                StockReservationORM.dataset_version_id == str(dataset_version_id),
            )
        )
        .scalars()
        .all()
    )

    reader = csv.DictReader(io.StringIO(csv_text.lstrip("\ufeff")))
    required_cols = {"event_type", "ingredient_code", "quantity", "unit", "idempotency_key", "event_at"}
    if reader.fieldnames is None or not required_cols.issubset({c.strip() for c in reader.fieldnames}):
        raise ValueError(
            f"Header CSV transaksi wajib memuat: {', '.join(sorted(required_cols))}"
        )

    source_row: Optional[DatasetSourceORM] = None
    if not dry_run:
        source_row = DatasetSourceORM(
            id=str(uuid4()),
            kitchen_id=str(kitchen_id),
            source_name=source_name,
            source_url="upload://inventory-transactions-csv",
            license="AUTHORIZED_KITCHEN_PILOT" if data_classification == "pilot_real" else "SYNTHETIC_DEMO",
            license_verified=True,
            dataset_type=data_classification,
            retrieved_at=_utcnow(),
            checksum=None,
            allowed_use="KITCHEN_INVENTORY_IMPORT",
            transformation_notes=f"Imported by user {actor_user_id} ({data_classification})",
            created_at=_utcnow(),
        )
        session.add(source_row)
        session.flush()

    results: List[InventoryTransactionRowResult] = []
    applied = 0
    dup_skipped = 0
    quarantined = 0
    errors = 0

    for idx, row in enumerate(reader, start=2):
        ev_type = (row.get("event_type") or "").strip().upper()
        ing_code = (row.get("ingredient_code") or "").strip()
        idemp_key = (row.get("idempotency_key") or "").strip()
        lot_code = (row.get("lot_code") or f"LOT-{ing_code}-DEFAULT").strip()
        unit = (row.get("unit") or "").strip()
        claimed_unit = (row.get("claimed_unit") or "").strip() or None
        qty_raw = (row.get("quantity") or "").strip()
        ev_at_raw = (row.get("event_at") or "").strip()
        exp_at_raw = (row.get("expires_at") or "").strip()
        exp_known_raw = (row.get("expiry_known") or "true").strip().lower()
        doc_ref = (row.get("source_document_ref") or "").strip() or None
        explicit_supplier_name = (row.get("supplier_name") or "").strip() or None
        supplier_name = explicit_supplier_name or "Pemasok Tidak Dicatat"
        deliv_status = (row.get("delivery_status") or "RECEIVED").strip().upper()
        density_raw = (row.get("density_g_per_ml") or "").strip()
        item_wt_raw = (row.get("unit_weight_g") or "").strip()
        notes = (row.get("notes") or "").strip() or None

        if not idemp_key or not ing_code or not ev_type:
            errors += 1
            results.append(
                InventoryTransactionRowResult(
                    row_number=idx,
                    idempotency_key=idemp_key or f"row-{idx}",
                    event_type=ev_type or "UNKNOWN",
                    ingredient_code=ing_code or "UNKNOWN",
                    status="ERROR",
                    message="Kolom wajib event_type, ingredient_code, atau idempotency_key kosong.",
                )
            )
            continue

        ing = ing_by_code.get(ing_code)
        if ing is None:
            errors += 1
            results.append(
                InventoryTransactionRowResult(
                    row_number=idx,
                    idempotency_key=idemp_key,
                    event_type=ev_type,
                    ingredient_code=ing_code,
                    status="ERROR",
                    message=f"Kode bahan '{ing_code}' tidak terdaftar di dataset target.",
                )
            )
            continue

        # Duplicate detection
        is_dup = (
            (ev_type == "SUPPLIER_DELIVERY" and idemp_key in existing_deliv_keys)
            or (ev_type == "RESERVATION" and idemp_key in existing_res_keys)
            or (ev_type not in {"SUPPLIER_DELIVERY", "RESERVATION"} and idemp_key in existing_mov_keys)
        )
        if is_dup:
            dup_skipped += 1
            results.append(
                InventoryTransactionRowResult(
                    row_number=idx,
                    idempotency_key=idemp_key,
                    event_type=ev_type,
                    ingredient_code=ing_code,
                    status="DUPLICATE_SKIPPED",
                    message=f"Dokumen/kunci idempotensi '{idemp_key}' sudah pernah diimpor — stok tidak digandakan.",
                )
            )
            continue

        try:
            qty_val = float(qty_raw)
            density_val = float(density_raw) if density_raw else None
            item_wt_val = float(item_wt_raw) if item_wt_raw else None
            ev_dt = _parse_iso_dt(ev_at_raw, field="event_at")
            if ev_dt is None:
                raise ValueError("event_at wajib diisi.")
            exp_dt = _parse_iso_dt(exp_at_raw, field="expires_at")
        except ValueError as exc:
            errors += 1
            results.append(
                InventoryTransactionRowResult(
                    row_number=idx,
                    idempotency_key=idemp_key,
                    event_type=ev_type,
                    ingredient_code=ing_code,
                    status="ERROR",
                    message=str(exc),
                )
            )
            continue

        # Normalize units & catch unit mismatch / bad units -> QUARANTINE
        try:
            norm = normalize_quantity_to_grams(
                qty_val,
                unit,
                density_g_per_ml=density_val,
                unit_weight_g=item_wt_val,
                claimed_unit=claimed_unit,
                allow_zero=(ev_type in {"PHYSICAL_COUNT", "SUPPLIER_DELIVERY"}),
            )
        except UnitConversionError as exc:
            quarantined += 1
            if not dry_run:
                existing_mov_keys.add(idemp_key)
                session.add(
                    InventoryMovementORM(
                        id=str(uuid4()),
                        kitchen_id=str(kitchen_id),
                        dataset_version_id=str(dataset_version_id),
                        ingredient_id=ing.id,
                        lot_id=None,
                        movement_type="ADJUSTMENT",
                        quantity_delta_raw_g=0.0,
                        original_value=qty_val if math.isfinite(qty_val) else 0.0,
                        original_unit=unit or "UNKNOWN",
                        idempotency_key=idemp_key,
                        source_document_ref=doc_ref,
                        source_id=source_row.id if source_row else None,
                        event_at=ev_dt,
                        quarantined=True,
                        quarantine_reason=str(exc),
                        actor_user_id=str(actor_user_id) if actor_user_id else None,
                        created_at=_utcnow(),
                    )
                )
            results.append(
                InventoryTransactionRowResult(
                    row_number=idx,
                    idempotency_key=idemp_key,
                    event_type=ev_type,
                    ingredient_code=ing_code,
                    status="QUARANTINED",
                    message=str(exc),
                )
            )
            continue

        if dry_run:
            applied += 1
            if ev_type == "SUPPLIER_DELIVERY":
                existing_deliv_keys.add(idemp_key)
            elif ev_type == "RESERVATION":
                existing_res_keys.add(idemp_key)
            else:
                existing_mov_keys.add(idemp_key)
            results.append(
                InventoryTransactionRowResult(
                    row_number=idx,
                    idempotency_key=idemp_key,
                    event_type=ev_type,
                    ingredient_code=ing_code,
                    status="VALIDATED_DRY_RUN",
                    normalized_raw_g=norm.normalized_raw_g,
                    message=f"Valid ({norm.normalized_raw_g / 1000.0:.3f} kg) — siap diimpor.",
                )
            )
            continue

        # Mutate database inside caller's transaction
        expiry_known = exp_known_raw not in {"false", "0", "no", "unknown"} and exp_dt is not None
        lot = session.execute(
            select(InventoryLotORM).where(
                InventoryLotORM.kitchen_id == str(kitchen_id),
                InventoryLotORM.dataset_version_id == str(dataset_version_id),
                InventoryLotORM.lot_code == lot_code,
            )
        ).scalar_one_or_none()

        def _get_or_create_lot(initial_g: float = 0.0) -> InventoryLotORM:
            nonlocal lot
            if lot is not None:
                return lot
            lot = InventoryLotORM(
                id=str(uuid4()),
                kitchen_id=str(kitchen_id),
                dataset_version_id=str(dataset_version_id),
                ingredient_id=ing.id,
                lot_code=lot_code,
                source_id=source_row.id if source_row else None,
                data_classification=data_classification,
                recorded_raw_g=initial_g,
                damaged_raw_g=0.0,
                expires_at=exp_dt,
                expiry_known=expiry_known,
                received_at=ev_dt,
                supplier_name=explicit_supplier_name,
                verification_status="VERIFIED" if expiry_known else "UNVERIFIED",
                unit_original=norm.original_unit,
                quantity_original=norm.original_value,
                notes=notes,
                created_at=_utcnow(),
            )
            session.add(lot)
            session.flush()
            return lot

        if ev_type in {"OPENING_BALANCE", "GOODS_RECEIPT"}:
            target_lot = _get_or_create_lot(0.0)
            target_lot.recorded_raw_g += norm.normalized_raw_g
            if explicit_supplier_name:
                target_lot.supplier_name = explicit_supplier_name
            if exp_dt is not None:
                target_lot.expires_at = exp_dt
                target_lot.expiry_known = True
                if target_lot.verification_status == "UNVERIFIED":
                    target_lot.verification_status = "VERIFIED"
            elif exp_known_raw in {"false", "0", "no", "unknown"}:
                target_lot.expiry_known = False
                target_lot.verification_status = "UNVERIFIED"

            existing_mov_keys.add(idemp_key)
            session.add(
                InventoryMovementORM(
                    id=str(uuid4()),
                    kitchen_id=str(kitchen_id),
                    dataset_version_id=str(dataset_version_id),
                    ingredient_id=ing.id,
                    lot_id=target_lot.id,
                    movement_type=ev_type,
                    quantity_delta_raw_g=norm.normalized_raw_g,
                    original_value=norm.original_value,
                    original_unit=norm.original_unit,
                    idempotency_key=idemp_key,
                    source_document_ref=doc_ref,
                    source_id=source_row.id if source_row else None,
                    event_at=ev_dt,
                    quarantined=False,
                    actor_user_id=str(actor_user_id) if actor_user_id else None,
                    created_at=_utcnow(),
                )
            )
        elif ev_type == "DAMAGE":
            target_lot = _get_or_create_lot(0.0)
            target_lot.damaged_raw_g += norm.normalized_raw_g
            existing_mov_keys.add(idemp_key)
            session.add(
                InventoryMovementORM(
                    id=str(uuid4()),
                    kitchen_id=str(kitchen_id),
                    dataset_version_id=str(dataset_version_id),
                    ingredient_id=ing.id,
                    lot_id=target_lot.id,
                    movement_type="DAMAGE",
                    quantity_delta_raw_g=0.0,
                    original_value=norm.original_value,
                    original_unit=norm.original_unit,
                    idempotency_key=idemp_key,
                    source_document_ref=doc_ref,
                    source_id=source_row.id if source_row else None,
                    event_at=ev_dt,
                    quarantined=False,
                    actor_user_id=str(actor_user_id) if actor_user_id else None,
                    created_at=_utcnow(),
                )
            )
        elif ev_type in {"PRODUCTION_CONSUMPTION", "DISPOSAL"}:
            target_lot = _get_or_create_lot(0.0)
            if target_lot.recorded_raw_g + 1e-6 < norm.normalized_raw_g:
                quarantined += 1
                existing_mov_keys.add(idemp_key)
                session.add(
                    InventoryMovementORM(
                        id=str(uuid4()),
                        kitchen_id=str(kitchen_id),
                        dataset_version_id=str(dataset_version_id),
                        ingredient_id=ing.id,
                        lot_id=target_lot.id,
                        movement_type=ev_type,
                        quantity_delta_raw_g=-norm.normalized_raw_g,
                        original_value=norm.original_value,
                        original_unit=norm.original_unit,
                        idempotency_key=idemp_key,
                        source_document_ref=doc_ref,
                        source_id=source_row.id if source_row else None,
                        event_at=ev_dt,
                        quarantined=True,
                        quarantine_reason="Konsumsi/pembuangan melebihi stok tercatat lot (mencegah stok negatif).",
                        actor_user_id=str(actor_user_id) if actor_user_id else None,
                        created_at=_utcnow(),
                    )
                )
                results.append(
                    InventoryTransactionRowResult(
                        row_number=idx,
                        idempotency_key=idemp_key,
                        event_type=ev_type,
                        ingredient_code=ing_code,
                        status="QUARANTINED",
                        normalized_raw_g=norm.normalized_raw_g,
                        message="Dikarantina: pengurangan akan menyebabkan stok lot menjadi negatif.",
                    )
                )
                continue
            target_lot.recorded_raw_g = max(0.0, target_lot.recorded_raw_g - norm.normalized_raw_g)
            if ev_type == "DISPOSAL":
                target_lot.damaged_raw_g = max(0.0, target_lot.damaged_raw_g - norm.normalized_raw_g)
            existing_mov_keys.add(idemp_key)
            session.add(
                InventoryMovementORM(
                    id=str(uuid4()),
                    kitchen_id=str(kitchen_id),
                    dataset_version_id=str(dataset_version_id),
                    ingredient_id=ing.id,
                    lot_id=target_lot.id,
                    movement_type=ev_type,
                    quantity_delta_raw_g=-norm.normalized_raw_g,
                    original_value=norm.original_value,
                    original_unit=norm.original_unit,
                    idempotency_key=idemp_key,
                    source_document_ref=doc_ref,
                    source_id=source_row.id if source_row else None,
                    event_at=ev_dt,
                    quarantined=False,
                    actor_user_id=str(actor_user_id) if actor_user_id else None,
                    created_at=_utcnow(),
                )
            )
        elif ev_type == "RESERVATION":
            existing_res_keys.add(idemp_key)
            session.add(
                StockReservationORM(
                    id=str(uuid4()),
                    kitchen_id=str(kitchen_id),
                    dataset_version_id=str(dataset_version_id),
                    ingredient_id=ing.id,
                    lot_id=lot.id if lot else None,
                    reserved_raw_g=norm.normalized_raw_g,
                    production_date=ev_dt,
                    status="ACTIVE",
                    idempotency_key=idemp_key,
                    notes=notes,
                    created_at=_utcnow(),
                )
            )
        elif ev_type == "PHYSICAL_COUNT":
            target_lot = _get_or_create_lot(0.0)
            target_lot.verified_physical_raw_g = norm.normalized_raw_g
            target_lot.verified_at = ev_dt
            discrepancy = norm.normalized_raw_g - target_lot.recorded_raw_g
            recon_status = "MATCHED" if abs(discrepancy) <= 1e-6 else "DISCREPANCY_DETECTED"
            if abs(discrepancy) > 1e-6:
                target_lot.verification_status = "DISCREPANCY"
            else:
                target_lot.verification_status = "VERIFIED" if target_lot.expiry_known else "UNVERIFIED"
            existing_mov_keys.add(idemp_key)
            session.add(
                InventoryReconciliationORM(
                    id=str(uuid4()),
                    kitchen_id=str(kitchen_id),
                    dataset_version_id=str(dataset_version_id),
                    ingredient_id=ing.id,
                    lot_id=target_lot.id,
                    recorded_raw_g=target_lot.recorded_raw_g,
                    physical_raw_g=norm.normalized_raw_g,
                    discrepancy_raw_g=discrepancy,
                    status=recon_status,
                    counted_by=row.get("counted_by") or "Operator Dapur",
                    counted_at=ev_dt,
                    notes=notes,
                    created_at=_utcnow(),
                )
            )
            session.add(
                InventoryMovementORM(
                    id=str(uuid4()),
                    kitchen_id=str(kitchen_id),
                    dataset_version_id=str(dataset_version_id),
                    ingredient_id=ing.id,
                    lot_id=target_lot.id,
                    movement_type="PHYSICAL_COUNT_RECONCILIATION",
                    quantity_delta_raw_g=0.0,
                    original_value=norm.original_value,
                    original_unit=norm.original_unit,
                    idempotency_key=idemp_key,
                    source_document_ref=doc_ref,
                    source_id=source_row.id if source_row else None,
                    event_at=ev_dt,
                    quarantined=False,
                    actor_user_id=str(actor_user_id) if actor_user_id else None,
                    created_at=_utcnow(),
                )
            )
        elif ev_type == "SUPPLIER_DELIVERY":
            expected_raw_g_str = (row.get("expected_quantity") or "").strip()
            exp_g = norm.normalized_raw_g
            rec_g = norm.normalized_raw_g if deliv_status == "RECEIVED" else 0.0
            if expected_raw_g_str:
                exp_norm = normalize_quantity_to_grams(
                    float(expected_raw_g_str),
                    unit,
                    density_g_per_ml=density_val,
                    unit_weight_g=item_wt_val,
                    allow_zero=False,
                )
                exp_g = exp_norm.normalized_raw_g
                rec_g = norm.normalized_raw_g if deliv_status in {"PARTIAL", "RECEIVED"} else 0.0
            existing_deliv_keys.add(idemp_key)
            session.add(
                SupplierDeliveryORM(
                    id=str(uuid4()),
                    kitchen_id=str(kitchen_id),
                    dataset_version_id=str(dataset_version_id),
                    ingredient_id=ing.id,
                    source_id=source_row.id if source_row else None,
                    supplier_name=supplier_name,
                    delivery_ref=doc_ref or idemp_key,
                    expected_raw_g=exp_g,
                    received_raw_g=rec_g,
                    original_value=norm.original_value,
                    original_unit=norm.original_unit,
                    expected_at=ev_dt,
                    confirmed_at=ev_dt if rec_g > 0 else None,
                    status=deliv_status,
                    idempotency_key=idemp_key,
                    notes=notes,
                    created_at=_utcnow(),
                )
            )
            # Only actually confirmed received quantity enters a stock lot!
            if rec_g > 0:
                target_lot = _get_or_create_lot(0.0)
                target_lot.recorded_raw_g += rec_g
                if exp_dt is not None:
                    target_lot.expires_at = exp_dt
                    target_lot.expiry_known = True
                    target_lot.verification_status = "VERIFIED"
        else:
            errors += 1
            results.append(
                InventoryTransactionRowResult(
                    row_number=idx,
                    idempotency_key=idemp_key,
                    event_type=ev_type,
                    ingredient_code=ing_code,
                    status="ERROR",
                    message=f"event_type '{ev_type}' tidak dikenal.",
                )
            )
            continue

        applied += 1
        results.append(
            InventoryTransactionRowResult(
                row_number=idx,
                idempotency_key=idemp_key,
                event_type=ev_type,
                ingredient_code=ing_code,
                status="APPLIED",
                normalized_raw_g=norm.normalized_raw_g,
                message=f"{ev_type} diterapkan ({norm.normalized_raw_g / 1000.0:.3f} kg).",
            )
        )

    return InventoryTransactionImportResponse(
        dataset_version_id=dataset_version_id,
        kitchen_id=kitchen_id,
        dry_run=dry_run,
        data_classification=data_classification,
        total_rows=len(results),
        applied_count=applied,
        duplicate_skipped_count=dup_skipped,
        quarantined_count=quarantined,
        error_count=errors,
        results=results,
    )


def import_market_price_references_csv(
    session: Session,
    *,
    csv_text: str,
    source_name: str,
    price_provenance: PriceProvenanceEnum = PriceProvenanceEnum.OFFICIAL_MARKET_REFERENCE,
    source_url: Optional[str] = None,
) -> MarketReferenceImportResponse:
    """Import authorized external food-market price references strictly separate from kitchen stock & contract prices."""
    reader = csv.DictReader(io.StringIO(csv_text.lstrip("\ufeff")))
    required_cols = {"commodity_code", "commodity_name", "region", "observed_date", "price_value", "unit"}
    if reader.fieldnames is None or not required_cols.issubset({c.strip() for c in reader.fieldnames}):
        raise ValueError(
            f"Header CSV referensi pasar wajib memuat: {', '.join(sorted(required_cols))}"
        )

    source_row = DatasetSourceORM(
        id=str(uuid4()),
        kitchen_id=None,
        source_name=source_name,
        source_url=source_url or "manual://authorized-market-reference-csv",
        license="MANUAL_AUTHORIZED_IMPORT",
        license_verified=True,
        dataset_type="official_reference",
        retrieved_at=_utcnow(),
        checksum=None,
        allowed_use="REFERENCE_PRICE_COMPARISON_ONLY",
        transformation_notes="Imported manually; strictly separated from kitchen inventory and contract prices.",
        created_at=_utcnow(),
    )
    session.add(source_row)
    session.flush()

    now = _utcnow()
    imported: List[MarketPriceReferenceItem] = []
    skipped = 0
    warnings = [
        "Harga referensi pasar TIDAK otomatis menggantikan harga kontrak pemasok dapur dan BUKAN stok dapur."
    ]

    for row in reader:
        c_code = (row.get("commodity_code") or "").strip()
        c_name = (row.get("commodity_name") or "").strip()
        canon_code = (row.get("canonical_ingredient_code") or "").strip() or None
        region = (row.get("region") or "").strip()
        obs_raw = (row.get("observed_date") or "").strip()
        pub_raw = (row.get("published_at") or "").strip()
        val_raw = (row.get("price_value") or "").strip()
        unit = (row.get("unit") or "IDR/kg").strip()
        density_raw = (row.get("density_g_per_ml") or "").strip()
        notes = (row.get("notes") or "").strip() or None
        q_status = (row.get("quality_status") or "REFERENCE_ONLY").strip() or "REFERENCE_ONLY"

        if not c_code or not c_name or not region or not obs_raw or not val_raw:
            skipped += 1
            continue

        try:
            obs_date = date.fromisoformat(obs_raw)
            pub_date = date.fromisoformat(pub_raw) if pub_raw else None
            price_val = float(val_raw)
            density_val = float(density_raw) if density_raw else None
            per_g = convert_price_to_idr_per_g(price_val, unit, density_g_per_ml=density_val)
        except Exception:
            skipped += 1
            continue

        ref_id = str(uuid4())
        orm_row = MarketPriceReferenceORM(
            id=ref_id,
            source_id=source_row.id,
            commodity_code=c_code,
            commodity_name=c_name,
            canonical_ingredient_code=canon_code,
            region=region,
            observed_date=obs_date,
            price_value=price_val,
            unit=unit,
            price_idr_per_g=per_g,
            price_provenance=price_provenance.value,
            source_name=source_name,
            published_at=pub_date,
            retrieved_at=now,
            imported_at=now,
            quality_status=q_status,
            notes=notes,
        )
        session.add(orm_row)
        imported.append(
            MarketPriceReferenceItem(
                id=UUID(ref_id),
                commodity_code=c_code,
                commodity_name=c_name,
                canonical_ingredient_code=canon_code,
                region=region,
                observed_date=obs_date,
                price_value=price_val,
                unit=unit,
                price_idr_per_g=per_g,
                price_provenance=price_provenance,
                source_name=source_name,
                published_at=pub_date,
                retrieved_at=now,
                imported_at=now,
                quality_status=q_status,
                notes=notes,
            )
        )

    return MarketReferenceImportResponse(
        imported_count=len(imported),
        skipped_count=skipped,
        source_name=source_name,
        price_provenance=price_provenance,
        warnings=warnings,
        items=imported,
    )


def list_market_price_references(
    session: Session,
    *,
    canonical_ingredient_code: Optional[str] = None,
    region: Optional[str] = None,
) -> List[MarketPriceReferenceItem]:
    stmt = select(MarketPriceReferenceORM).order_by(
        MarketPriceReferenceORM.observed_date.desc(),
        MarketPriceReferenceORM.commodity_code,
    )
    if canonical_ingredient_code:
        stmt = stmt.where(
            MarketPriceReferenceORM.canonical_ingredient_code == canonical_ingredient_code
        )
    if region:
        stmt = stmt.where(MarketPriceReferenceORM.region == region)
    rows = list(session.execute(stmt).scalars().all())
    return [
        MarketPriceReferenceItem(
            id=UUID(r.id),
            commodity_code=r.commodity_code,
            commodity_name=r.commodity_name,
            canonical_ingredient_code=r.canonical_ingredient_code,
            region=r.region,
            observed_date=r.observed_date,
            price_value=r.price_value,
            unit=r.unit,
            price_idr_per_g=r.price_idr_per_g,
            price_provenance=PriceProvenanceEnum(r.price_provenance),
            source_name=r.source_name,
            published_at=r.published_at,
            retrieved_at=r.retrieved_at,
            imported_at=r.imported_at,
            quality_status=r.quality_status,
            notes=r.notes,
        )
        for r in rows
    ]


def build_pilot_transactions_template_csv() -> str:
    return (
        "event_type,ingredient_code,lot_code,quantity,unit,claimed_unit,expected_quantity,expires_at,expiry_known,event_at,idempotency_key,source_document_ref,supplier_name,delivery_status,density_g_per_ml,unit_weight_g,counted_by,notes\n"
        "OPENING_BALANCE,ING001,LOT-ING001-01,45,kg,,,2027-06-30T23:59:59Z,true,2026-11-20T06:00:00Z,OP-ING001-20261120,DOC-OP-001,,,,,Kepala Gudang,Contoh saldo awal beras (ganti dengan catatan dapur nyata yang terotorisasi)\n"
        "GOODS_RECEIPT,ING007,LOT-ING007-01,20,kg,,,2026-11-25T23:59:59Z,true,2026-11-20T06:30:00Z,GR-ING007-20261120,SJ-AYAM-001,Pemasok Contoh,RECEIVED,,,,Penerimaan batch ayam terverifikasi\n"
        "DAMAGE,ING007,LOT-ING007-01,3,kg,,,,,2026-11-20T07:00:00Z,DMG-ING007-20261120,QC-DMG-001,,,,,,Bagian rusak atau mencair tidak dapat dipakai\n"
        "RESERVATION,ING007,LOT-ING007-01,5,kg,,,,,2026-11-20T07:15:00Z,RES-ING007-20261120,MENU-APPROVED-001,,,,,,Dialokasikan untuk jadwal produksi lain\n"
    )


def build_market_reference_template_csv() -> str:
    return (
        "commodity_code,commodity_name,canonical_ingredient_code,region,observed_date,price_value,unit,published_at,quality_status,notes\n"
        "BAP-BERAS-MED,Beras Medium (Referensi Pasar Resmi),ING001,DKI Jakarta,2026-11-18,14500,IDR/kg,2026-11-18,REFERENCE_ONLY,Templat manual data resmi Bapanas SAPA/Panel Harga — bukan harga kontrak dapur\n"
        "BAP-AYAM-RAS,Daging Ayam Ras Murni (Referensi Pasar),ING007,Jawa Barat,2026-11-18,39500,IDR/kg,2026-11-18,REFERENCE_ONLY,Templat manual data resmi Bapanas — bukan stok dapur\n"
    )
