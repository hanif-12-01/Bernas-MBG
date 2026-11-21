from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.auth.dependencies import AuthContext, record_audit_event
from app.auth.schemas import RoleEnum
from app.db.models import (
    GoodsReceiptRecordORM,
    IngredientORM,
    InventoryLotORM,
    InventoryMovementORM,
    PurchaseDocumentLineORM,
    PurchaseDocumentORM,
    RecoveryEventORM,
    UserORM,
)
from app.db.repository import SQLiteVaultRepository
from app.inventory.timezone_utils import jakarta_now, jakarta_today, parse_expiry_date_jakarta
from app.inventory.unit_normalizer import UnitConversionError, normalize_quantity_to_grams
from app.procurement.file_security import (
    ProcurementFileSecurityError,
    evidence_storage_path,
    read_purchase_evidence_bytes,
    validate_and_store_purchase_evidence,
)
from app.procurement.schemas import (
    EvidenceStatusEnum,
    GoodsConditionEnum,
    GoodsReceiptCreateRequest,
    GoodsReceiptResponse,
    PurchaseDocumentCreateRequest,
    PurchaseDocumentLineResponse,
    PurchaseDocumentResponse,
    PurchaseDocumentReviewRequest,
)
from app.scenarios.service import ResourceNotFoundError


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _user_names_map(session: Session, user_ids: set[str]) -> Dict[str, str]:
    clean_ids = {u for u in user_ids if u}
    if not clean_ids:
        return {}
    rows = list(session.execute(select(UserORM).where(UserORM.id.in_(clean_ids))).scalars().all())
    return {u.id: u.full_name for u in rows}


def _to_document_response(
    session: Session,
    doc: PurchaseDocumentORM,
    names: Optional[Dict[str, str]] = None,
) -> PurchaseDocumentResponse:
    if names is None:
        ids = {x for x in (doc.recorded_by_user_id, doc.reviewed_by_user_id) if x}
        names = _user_names_map(session, ids)
    return PurchaseDocumentResponse(
        id=UUID(doc.id),
        kitchen_id=UUID(doc.kitchen_id),
        dataset_version_id=UUID(doc.dataset_version_id),
        linked_run_id=UUID(doc.linked_run_id) if doc.linked_run_id else None,
        linked_recovery_event_id=(
            UUID(doc.linked_recovery_event_id) if doc.linked_recovery_event_id else None
        ),
        supplier_name=doc.supplier_name,
        supplier_contact=doc.supplier_contact,
        invoice_number=doc.invoice_number,
        purchase_date=doc.purchase_date,
        total_amount_idr=doc.total_amount_idr,
        evidence_status=EvidenceStatusEnum(doc.evidence_status),
        has_evidence_file=bool(doc.document_storage_key),
        document_mime_type=doc.document_mime_type,
        document_sha256=doc.document_sha256,
        document_size_bytes=doc.document_size_bytes,
        document_original_filename=doc.document_original_filename,
        exif_stripped=doc.exif_stripped,
        evidence_url=(
            f"/api/v1/procurement/documents/{doc.id}/evidence" if doc.document_storage_key else None
        ),
        recorded_by_user_id=UUID(doc.recorded_by_user_id) if doc.recorded_by_user_id else None,
        recorded_by_name=(
            names.get(doc.recorded_by_user_id) if doc.recorded_by_user_id else None
        ),
        reviewed_by_user_id=UUID(doc.reviewed_by_user_id) if doc.reviewed_by_user_id else None,
        reviewed_by_name=(
            names.get(doc.reviewed_by_user_id) if doc.reviewed_by_user_id else None
        ),
        reviewed_at=doc.reviewed_at,
        notes=doc.notes,
        lines=[
            PurchaseDocumentLineResponse(
                id=UUID(ln.id),
                ingredient_id=UUID(ln.ingredient_id) if ln.ingredient_id else None,
                ingredient_code=ln.ingredient_code,
                item_name=ln.item_name,
                quantity_raw_g=float(ln.quantity_raw_g),
                unit_label=ln.unit_label,
                unit_price_idr=ln.unit_price_idr,
                line_total_idr=ln.line_total_idr,
                lot_code_hint=ln.lot_code_hint,
                expiry_date_hint=ln.expiry_date_hint,
            )
            for ln in sorted(doc.lines, key=lambda x: x.created_at)
        ],
        created_at=doc.created_at,
        updated_at=doc.updated_at,
    )


def create_purchase_document(
    session: Session,
    auth: AuthContext,
    req: PurchaseDocumentCreateRequest,
) -> PurchaseDocumentResponse:
    """Create a manual supplier purchase record (never auto-filled from menu estimates)."""
    repo = SQLiteVaultRepository(session)
    ds_id = req.dataset_version_id or repo.get_active_dataset_id(auth.kitchen_id)
    try:
        repo.get_dataset_orm(ds_id, kitchen_id=auth.kitchen_id)
    except ResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if req.linked_run_id is not None:
        try:
            repo.get_run(req.linked_run_id, kitchen_id=auth.kitchen_id)
        except ResourceNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail="Rencana/run terkait tidak ditemukan pada dapur ini.",
            ) from exc

    if req.linked_recovery_event_id is not None:
        rec_row = session.get(RecoveryEventORM, str(req.linked_recovery_event_id))
        if rec_row is None or rec_row.kitchen_id != str(auth.kitchen_id):
            raise HTTPException(status_code=404, detail="Event pemulihan terkait tidak ditemukan pada dapur ini.")

    ing_rows = list(
        session.execute(select(IngredientORM).where(IngredientORM.dataset_version_id == str(ds_id)))
        .scalars()
        .all()
    )
    ing_by_code = {i.code: i for i in ing_rows}

    now = _utcnow()
    doc_id = str(uuid4())
    doc = PurchaseDocumentORM(
        id=doc_id,
        kitchen_id=str(auth.kitchen_id),
        dataset_version_id=str(ds_id),
        linked_run_id=str(req.linked_run_id) if req.linked_run_id else None,
        linked_recovery_event_id=(
            str(req.linked_recovery_event_id) if req.linked_recovery_event_id else None
        ),
        supplier_name=req.supplier_name.strip(),
        supplier_contact=req.supplier_contact.strip() if req.supplier_contact else None,
        invoice_number=req.invoice_number.strip() if req.invoice_number else None,
        purchase_date=req.purchase_date or jakarta_today(),
        total_amount_idr=req.total_amount_idr,
        evidence_status=EvidenceStatusEnum.NO_EVIDENCE.value,
        recorded_by_user_id=str(auth.user_id),
        notes=req.notes.strip() if req.notes and req.notes.strip() else None,
        created_at=now,
        updated_at=now,
    )
    session.add(doc)
    session.flush()

    for line_in in req.lines:
        ing_obj = None
        clean_code = line_in.ingredient_code.strip() if line_in.ingredient_code else None
        if clean_code:
            ing_obj = ing_by_code.get(clean_code)
            if ing_obj is None:
                raise HTTPException(
                    status_code=422, detail=f"Kode bahan baris pembelian tidak dikenal: '{clean_code}'."
                )
        try:
            norm = normalize_quantity_to_grams(line_in.quantity, line_in.unit)
        except UnitConversionError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        session.add(
            PurchaseDocumentLineORM(
                id=str(uuid4()),
                purchase_document_id=doc_id,
                kitchen_id=str(auth.kitchen_id),
                ingredient_id=ing_obj.id if ing_obj else None,
                ingredient_code=clean_code,
                item_name=line_in.item_name.strip(),
                quantity_raw_g=norm.normalized_raw_g,
                unit_label=norm.original_unit,
                unit_price_idr=line_in.unit_price_idr,
                line_total_idr=line_in.line_total_idr,
                lot_code_hint=line_in.lot_code_hint.strip() if line_in.lot_code_hint else None,
                expiry_date_hint=line_in.expiry_date_hint,
                created_at=now,
            )
        )

    record_audit_event(
        session,
        action="procurement.document_created",
        entity_type="purchase_document",
        entity_id=doc_id,
        kitchen_id=auth.kitchen_id,
        actor_user_id=auth.user_id,
        actor_role=auth.role.value,
        metadata={
            "supplier_name": doc.supplier_name,
            "invoice_number": doc.invoice_number,
            "lines_count": len(req.lines),
        },
    )
    session.commit()
    reloaded = session.execute(
        select(PurchaseDocumentORM)
        .options(selectinload(PurchaseDocumentORM.lines))
        .where(PurchaseDocumentORM.id == doc_id)
    ).scalar_one()
    return _to_document_response(session, reloaded)


def upload_purchase_document_evidence(
    session: Session,
    auth: AuthContext,
    document_id: UUID,
    raw_bytes: bytes,
    original_filename: str,
) -> PurchaseDocumentResponse:
    doc = session.execute(
        select(PurchaseDocumentORM)
        .options(selectinload(PurchaseDocumentORM.lines))
        .where(PurchaseDocumentORM.id == str(document_id))
    ).scalar_one_or_none()
    if doc is None or doc.kitchen_id != str(auth.kitchen_id):
        raise HTTPException(status_code=404, detail="Catatan pembelian tidak ditemukan pada dapur ini.")

    try:
        stored = validate_and_store_purchase_evidence(raw_bytes, original_filename)
    except ProcurementFileSecurityError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    old_storage_key = doc.document_storage_key
    now = _utcnow()
    try:
        doc.document_storage_key = stored.storage_key
        doc.document_mime_type = stored.mime_type
        doc.document_sha256 = stored.sha256
        doc.document_size_bytes = stored.size_bytes
        doc.document_original_filename = stored.original_filename_sanitized
        doc.exif_stripped = stored.exif_stripped
        if doc.evidence_status in {
            EvidenceStatusEnum.NO_EVIDENCE.value,
            EvidenceStatusEnum.VERIFIED_MATCH.value,
            EvidenceStatusEnum.DISCREPANCY_FLAGGED.value,
        }:
            doc.evidence_status = EvidenceStatusEnum.RECEIPT_UPLOADED.value
        doc.updated_at = now
        record_audit_event(
            session,
            action="procurement.evidence_uploaded",
            entity_type="purchase_document",
            entity_id=doc.id,
            kitchen_id=auth.kitchen_id,
            actor_user_id=auth.user_id,
            actor_role=auth.role.value,
            metadata={
                "mime_type": stored.mime_type,
                "sha256": stored.sha256,
                "exif_stripped": stored.exif_stripped,
            },
        )
        session.commit()
    except Exception:
        session.rollback()
        try:
            evidence_storage_path(stored.storage_key).unlink(missing_ok=True)
        except OSError:
            pass
        raise

    if old_storage_key and old_storage_key != stored.storage_key:
        try:
            evidence_storage_path(old_storage_key).unlink(missing_ok=True)
        except OSError:
            pass

    session.refresh(doc)
    return _to_document_response(session, doc)


def list_purchase_documents(
    session: Session,
    auth: AuthContext,
    *,
    limit: int = 50,
) -> List[PurchaseDocumentResponse]:
    bounded = max(1, min(limit, 100))
    rows = list(
        session.execute(
            select(PurchaseDocumentORM)
            .options(selectinload(PurchaseDocumentORM.lines))
            .where(PurchaseDocumentORM.kitchen_id == str(auth.kitchen_id))
            .order_by(PurchaseDocumentORM.purchase_date.desc(), PurchaseDocumentORM.created_at.desc())
            .limit(bounded)
        )
        .scalars()
        .all()
    )
    user_ids: set[str] = set()
    for r in rows:
        if r.recorded_by_user_id:
            user_ids.add(r.recorded_by_user_id)
        if r.reviewed_by_user_id:
            user_ids.add(r.reviewed_by_user_id)
    names = _user_names_map(session, user_ids)
    return [_to_document_response(session, r, names) for r in rows]


def get_purchase_document(
    session: Session,
    auth: AuthContext,
    document_id: UUID,
) -> PurchaseDocumentResponse:
    doc = session.execute(
        select(PurchaseDocumentORM)
        .options(selectinload(PurchaseDocumentORM.lines))
        .where(PurchaseDocumentORM.id == str(document_id))
    ).scalar_one_or_none()
    if doc is None or doc.kitchen_id != str(auth.kitchen_id):
        raise HTTPException(status_code=404, detail="Catatan pembelian tidak ditemukan pada dapur ini.")
    return _to_document_response(session, doc)


def get_purchase_document_evidence_bytes(
    session: Session,
    auth: AuthContext,
    document_id: UUID,
) -> Tuple[bytes, str, str]:
    doc = session.get(PurchaseDocumentORM, str(document_id))
    if doc is None or doc.kitchen_id != str(auth.kitchen_id) or not doc.document_storage_key:
        raise HTTPException(status_code=404, detail="Berkas bukti pembelian tidak ditemukan.")
    try:
        content = read_purchase_evidence_bytes(doc.document_storage_key)
    except (ProcurementFileSecurityError, OSError) as exc:
        raise HTTPException(status_code=404, detail="Berkas bukti pembelian tidak dapat dibaca.") from exc
    return content, (doc.document_mime_type or "application/octet-stream"), (
        doc.document_original_filename or "bukti_pembelian"
    )


def review_purchase_document(
    session: Session,
    auth: AuthContext,
    document_id: UUID,
    req: PurchaseDocumentReviewRequest,
) -> PurchaseDocumentResponse:
    if auth.role != RoleEnum.KITCHEN_MANAGER:
        raise HTTPException(
            status_code=403,
            detail="Hanya Kepala Dapur (KITCHEN_MANAGER) yang dapat memverifikasi bukti pembelian.",
        )
    doc = session.execute(
        select(PurchaseDocumentORM)
        .options(selectinload(PurchaseDocumentORM.lines))
        .where(PurchaseDocumentORM.id == str(document_id))
    ).scalar_one_or_none()
    if doc is None or doc.kitchen_id != str(auth.kitchen_id):
        raise HTTPException(status_code=404, detail="Catatan pembelian tidak ditemukan pada dapur ini.")

    if req.decision.value == EvidenceStatusEnum.VERIFIED_MATCH.value and not doc.document_storage_key:
        raise HTTPException(
            status_code=409,
            detail="Bukti pembelian (struk/faktur) harus diunggah terlebih dahulu sebelum ditandai Cocok.",
        )

    now = _utcnow()
    doc.evidence_status = req.decision.value
    doc.reviewed_by_user_id = str(auth.user_id)
    doc.reviewed_at = now
    if req.notes and req.notes.strip():
        doc.notes = req.notes.strip()
    doc.updated_at = now

    record_audit_event(
        session,
        action="procurement.document_reviewed",
        entity_type="purchase_document",
        entity_id=doc.id,
        kitchen_id=auth.kitchen_id,
        actor_user_id=auth.user_id,
        actor_role=auth.role.value,
        metadata={
            "decision": req.decision.value,
            "has_evidence": bool(doc.document_storage_key),
        },
    )
    session.commit()
    session.refresh(doc)
    return _to_document_response(session, doc)


def create_goods_receipt(
    session: Session,
    auth: AuthContext,
    req: GoodsReceiptCreateRequest,
) -> GoodsReceiptResponse:
    """Authoritative QC Custodian physical goods receipt -> creates/updates InventoryLot + InventoryMovement."""
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
        raise HTTPException(status_code=422, detail=f"Kode bahan '{ing_code}' tidak terdaftar.")

    linked_doc: Optional[PurchaseDocumentORM] = None
    if req.purchase_document_id is not None:
        linked_doc = session.get(PurchaseDocumentORM, str(req.purchase_document_id))
        if linked_doc is None or linked_doc.kitchen_id != str(auth.kitchen_id):
            raise HTTPException(status_code=404, detail="Dokumen pembelian terkait tidak ditemukan pada dapur ini.")

    try:
        norm = normalize_quantity_to_grams(req.received_quantity, req.unit)
    except UnitConversionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    idemp_key = (
        req.idempotency_key.strip()
        if req.idempotency_key and req.idempotency_key.strip()
        else f"GR-{uuid4()}"
    )
    existing_mov = session.execute(
        select(InventoryMovementORM).where(
            InventoryMovementORM.kitchen_id == str(auth.kitchen_id),
            InventoryMovementORM.dataset_version_id == str(ds_id),
            InventoryMovementORM.idempotency_key == idemp_key,
        )
    ).scalar_one_or_none()
    if existing_mov is not None and existing_mov.lot_id:
        existing_receipt = session.execute(
            select(GoodsReceiptRecordORM)
            .where(
                GoodsReceiptRecordORM.kitchen_id == str(auth.kitchen_id),
                GoodsReceiptRecordORM.lot_id == existing_mov.lot_id,
            )
            .order_by(GoodsReceiptRecordORM.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        existing_lot = session.get(InventoryLotORM, existing_mov.lot_id)
        if existing_receipt is not None and existing_lot is not None:
            names = _user_names_map(
                session, {existing_receipt.received_by_user_id} if existing_receipt.received_by_user_id else set()
            )
            return GoodsReceiptResponse(
                id=UUID(existing_receipt.id),
                kitchen_id=UUID(existing_receipt.kitchen_id),
                purchase_document_id=(
                    UUID(existing_receipt.purchase_document_id)
                    if existing_receipt.purchase_document_id
                    else None
                ),
                dataset_version_id=UUID(existing_receipt.dataset_version_id),
                ingredient_id=UUID(ing.id),
                ingredient_code=ing.code,
                ingredient_name=ing.name,
                lot_id=UUID(existing_lot.id),
                lot_code=existing_lot.lot_code,
                received_raw_g=float(existing_receipt.received_raw_g),
                expiry_date=existing_receipt.expiry_date,
                supplier_name=existing_receipt.supplier_name,
                condition_status=GoodsConditionEnum(existing_receipt.condition_status),
                lot_verification_status=existing_lot.verification_status,
                lot_safety_hold_status=existing_lot.safety_hold_status,
                usable_added_raw_g=(
                    float(existing_receipt.received_raw_g)
                    if existing_receipt.condition_status == GoodsConditionEnum.GOOD.value
                    and existing_receipt.expiry_date is not None
                    else 0.0
                ),
                received_by_user_id=(
                    UUID(existing_receipt.received_by_user_id)
                    if existing_receipt.received_by_user_id
                    else None
                ),
                received_by_name=(
                    names.get(existing_receipt.received_by_user_id)
                    if existing_receipt.received_by_user_id
                    else None
                ),
                received_at=existing_receipt.received_at,
                notes=existing_receipt.notes,
                created_at=existing_receipt.created_at,
            )

    now_utc = _utcnow()
    now_jkt = jakarta_now()
    lot_code = (
        req.lot_code.strip()
        if req.lot_code and req.lot_code.strip()
        else f"LOT-{ing.code}-{now_jkt.strftime('%Y%m%d')}-{str(uuid4())[:4].upper()}"
    )
    resolved_supplier = (
        req.supplier_name.strip()
        if req.supplier_name and req.supplier_name.strip()
        else (linked_doc.supplier_name if linked_doc else None)
    )
    exp_dt = parse_expiry_date_jakarta(req.expiry_date) if req.expiry_date else None
    notes_clean = req.notes.strip() if req.notes and req.notes.strip() else None

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
                f"Lot '{lot.lot_code}' berstatus {lot.safety_hold_status} dan tidak boleh "
                "ditambah lewat penerimaan baru. Gunakan kode lot baru."
            ),
        )

    if lot is None:
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
            expiry_known=exp_dt is not None,
            received_at=now_utc,
            supplier_name=resolved_supplier,
            purchase_document_id=linked_doc.id if linked_doc else None,
            verification_status="UNVERIFIED",
            safety_hold_status="NONE",
            unit_original=norm.original_unit,
            quantity_original=norm.original_value,
            notes=notes_clean,
            created_at=now_utc,
        )
        session.add(lot)
        session.flush()
    else:
        if resolved_supplier:
            lot.supplier_name = resolved_supplier
        if linked_doc is not None and not lot.purchase_document_id:
            lot.purchase_document_id = linked_doc.id
        lot.received_at = lot.received_at or now_utc

    usable_added = 0.0
    lot.recorded_raw_g += norm.normalized_raw_g

    if req.condition_status == GoodsConditionEnum.GOOD:
        if exp_dt is not None:
            lot.expires_at = exp_dt
            lot.expiry_known = True
            lot.verification_status = "VERIFIED"
            usable_added = norm.normalized_raw_g
        else:
            lot.expiry_known = False
            lot.verification_status = "UNVERIFIED"
    elif req.condition_status == GoodsConditionEnum.DAMAGED:
        lot.damaged_raw_g += norm.normalized_raw_g
        if exp_dt is not None:
            lot.expires_at = exp_dt
            lot.expiry_known = True
    elif req.condition_status == GoodsConditionEnum.QUARANTINED:
        lot.verification_status = "QUARANTINED"
        if exp_dt is not None:
            lot.expires_at = exp_dt
            lot.expiry_known = True
    elif req.condition_status == GoodsConditionEnum.REJECTED:
        lot.safety_hold_status = "REJECTED_DISPOSED"
        if exp_dt is not None:
            lot.expires_at = exp_dt
            lot.expiry_known = True

    receipt_id = str(uuid4())
    receipt = GoodsReceiptRecordORM(
        id=receipt_id,
        kitchen_id=str(auth.kitchen_id),
        purchase_document_id=linked_doc.id if linked_doc else None,
        dataset_version_id=str(ds_id),
        ingredient_id=ing.id,
        ingredient_code=ing.code,
        lot_id=lot.id,
        lot_code=lot.lot_code,
        received_raw_g=norm.normalized_raw_g,
        expiry_date=req.expiry_date,
        supplier_name=resolved_supplier,
        condition_status=req.condition_status.value,
        received_by_user_id=str(auth.user_id),
        received_at=now_utc,
        notes=notes_clean,
        created_at=now_utc,
    )
    session.add(receipt)

    session.add(
        InventoryMovementORM(
            id=str(uuid4()),
            kitchen_id=str(auth.kitchen_id),
            dataset_version_id=str(ds_id),
            ingredient_id=ing.id,
            lot_id=lot.id,
            movement_type="GOODS_RECEIPT",
            quantity_delta_raw_g=norm.normalized_raw_g,
            original_value=norm.original_value,
            original_unit=norm.original_unit,
            idempotency_key=idemp_key,
            source_document_ref=linked_doc.invoice_number if linked_doc else None,
            source_id=None,
            event_at=now_utc,
            quarantined=(req.condition_status == GoodsConditionEnum.QUARANTINED),
            quarantine_reason=(
                "Penerimaan barang ditandai QUARANTINED saat inspeksi."
                if req.condition_status == GoodsConditionEnum.QUARANTINED
                else None
            ),
            actor_user_id=str(auth.user_id),
            created_at=now_utc,
        )
    )

    if linked_doc is not None and linked_doc.evidence_status in {
        EvidenceStatusEnum.NO_EVIDENCE.value,
        EvidenceStatusEnum.RECEIPT_UPLOADED.value,
    }:
        linked_doc.evidence_status = EvidenceStatusEnum.GOODS_RECEIVED.value
        linked_doc.updated_at = now_utc

    record_audit_event(
        session,
        action="procurement.goods_received",
        entity_type="goods_receipt",
        entity_id=receipt_id,
        kitchen_id=auth.kitchen_id,
        actor_user_id=auth.user_id,
        actor_role=auth.role.value,
        metadata={
            "ingredient_code": ing.code,
            "lot_code": lot.lot_code,
            "received_raw_g": norm.normalized_raw_g,
            "condition_status": req.condition_status.value,
            "usable_added_raw_g": usable_added,
        },
    )
    session.commit()

    return GoodsReceiptResponse(
        id=UUID(receipt.id),
        kitchen_id=UUID(receipt.kitchen_id),
        purchase_document_id=UUID(linked_doc.id) if linked_doc else None,
        dataset_version_id=ds_id if isinstance(ds_id, UUID) else UUID(str(ds_id)),
        ingredient_id=UUID(ing.id),
        ingredient_code=ing.code,
        ingredient_name=ing.name,
        lot_id=UUID(lot.id),
        lot_code=lot.lot_code,
        received_raw_g=float(receipt.received_raw_g),
        expiry_date=receipt.expiry_date,
        supplier_name=receipt.supplier_name,
        condition_status=GoodsConditionEnum(receipt.condition_status),
        lot_verification_status=lot.verification_status,
        lot_safety_hold_status=lot.safety_hold_status,
        usable_added_raw_g=usable_added,
        received_by_user_id=auth.user_id,
        received_by_name=auth.full_name,
        received_at=receipt.received_at,
        notes=receipt.notes,
        created_at=receipt.created_at,
    )


def list_goods_receipts(
    session: Session,
    auth: AuthContext,
    *,
    limit: int = 50,
) -> List[GoodsReceiptResponse]:
    bounded = max(1, min(limit, 100))
    rows = list(
        session.execute(
            select(GoodsReceiptRecordORM)
            .where(GoodsReceiptRecordORM.kitchen_id == str(auth.kitchen_id))
            .order_by(GoodsReceiptRecordORM.received_at.desc())
            .limit(bounded)
        )
        .scalars()
        .all()
    )
    ing_ids = {r.ingredient_id for r in rows if r.ingredient_id}
    lot_ids = {r.lot_id for r in rows if r.lot_id}
    user_ids = {r.received_by_user_id for r in rows if r.received_by_user_id}

    ings = (
        {
            i.id: i
            for i in session.execute(select(IngredientORM).where(IngredientORM.id.in_(ing_ids)))
            .scalars()
            .all()
        }
        if ing_ids
        else {}
    )
    lots = (
        {
            l.id: l
            for l in session.execute(select(InventoryLotORM).where(InventoryLotORM.id.in_(lot_ids)))
            .scalars()
            .all()
        }
        if lot_ids
        else {}
    )
    names = _user_names_map(session, user_ids)

    out: List[GoodsReceiptResponse] = []
    for r in rows:
        ing = ings.get(r.ingredient_id) if r.ingredient_id else None
        lot = lots.get(r.lot_id) if r.lot_id else None
        out.append(
            GoodsReceiptResponse(
                id=UUID(r.id),
                kitchen_id=UUID(r.kitchen_id),
                purchase_document_id=(
                    UUID(r.purchase_document_id) if r.purchase_document_id else None
                ),
                dataset_version_id=UUID(r.dataset_version_id),
                ingredient_id=UUID(r.ingredient_id) if r.ingredient_id else None,
                ingredient_code=r.ingredient_code,
                ingredient_name=ing.name if ing else r.ingredient_code,
                lot_id=UUID(r.lot_id) if r.lot_id else None,
                lot_code=r.lot_code,
                received_raw_g=float(r.received_raw_g),
                expiry_date=r.expiry_date,
                supplier_name=r.supplier_name,
                condition_status=GoodsConditionEnum(r.condition_status),
                lot_verification_status=lot.verification_status if lot else "UNKNOWN",
                lot_safety_hold_status=lot.safety_hold_status if lot else "NONE",
                usable_added_raw_g=(
                    float(r.received_raw_g)
                    if r.condition_status == GoodsConditionEnum.GOOD.value
                    and r.expiry_date is not None
                    else 0.0
                ),
                received_by_user_id=(
                    UUID(r.received_by_user_id) if r.received_by_user_id else None
                ),
                received_by_name=(
                    names.get(r.received_by_user_id) if r.received_by_user_id else None
                ),
                received_at=r.received_at,
                notes=r.notes,
                created_at=r.created_at,
            )
        )
    return out
