from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.auth.dependencies import AuthContext, record_audit_event
from app.auth.schemas import RoleEnum
from app.db.models import (
    IngredientIncidentORM,
    IngredientORM,
    IncidentActionORM,
    IncidentAffectedLotORM,
    IncidentImageORM,
    InventoryLotORM,
    InventoryMovementORM,
    MealBatchORM,
    MenuReviewRecordORM,
    OperationalPlanAssignmentORM,
    RecipeIngredientORM,
    RunAssignmentORM,
    RunMaterialUsageORM,
    StockReservationORM,
    UserORM,
)
from app.db.repository import SQLiteVaultRepository
from app.incidents.schemas import (
    AffectedPlanSlotReference,
    IncidentActionResponse,
    IncidentAffectedLotResponse,
    IncidentCategoryEnum,
    IncidentCreateRequest,
    IncidentImageInfo,
    IncidentImpactSummaryResponse,
    IncidentReleaseHoldRequest,
    IncidentSeverityEnum,
    IncidentStartRecoveryRequest,
    IncidentStatusEnum,
    IncidentStatusUpdateRequest,
    IngredientIncidentResponse,
    ProductionExposureItem,
)
from app.inventory.service import compute_usable_inventory
from app.operations.service import place_affected_plans_on_hold
from app.recovery.schemas import DisruptionConditionRequest, DisruptionTypeEnum
from app.recovery.service import analyze_and_create_recovery_event
from app.scenarios.service import ResourceNotFoundError
from app.vision.image_security import (
    ImageSecurityError,
    get_qc_retention_days,
    image_expiry,
    qc_storage_path,
    read_stored_image_bytes,
    validate_strip_exif_and_store,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _user_name(session: Session, user_id: Optional[str]) -> Optional[str]:
    if not user_id:
        return None
    u = session.get(UserORM, user_id)
    return u.full_name if u else None


def _compute_production_exposure(
    session: Session,
    *,
    kitchen_id: str,
    affected_lot_ids: Set[str],
    affected_ing_ids: Set[str],
    affected_plan_run_ids: Set[str],
    lot_by_id: Dict[str, InventoryLotORM],
    ing_by_id: Dict[str, IngredientORM],
) -> Tuple[str, List[ProductionExposureItem]]:
    """Inspect real consumption movements, reservations, and meal batches for exposure."""
    exposures: List[ProductionExposureItem] = []

    if affected_lot_ids or affected_ing_ids:
        cons_rows = list(
            session.execute(
                select(InventoryMovementORM)
                .where(
                    InventoryMovementORM.kitchen_id == kitchen_id,
                    InventoryMovementORM.quarantined.is_(False),
                    InventoryMovementORM.movement_type == "PRODUCTION_CONSUMPTION",
                )
                .order_by(InventoryMovementORM.event_at.desc())
            )
            .scalars()
            .all()
        )
        for mv in cons_rows:
            hit_lot = mv.lot_id in affected_lot_ids if mv.lot_id else False
            hit_ing = mv.ingredient_id in affected_ing_ids
            if not (hit_lot or hit_ing):
                continue
            lot = lot_by_id.get(mv.lot_id) if mv.lot_id else None
            ing = ing_by_id.get(mv.ingredient_id)
            qty_kg = round(abs(float(mv.quantity_delta_raw_g)) / 1000.0, 3)
            exposures.append(
                ProductionExposureItem(
                    exposure_status="POTENTIAL_PRODUCTION_EXPOSURE",
                    summary=(
                        f"Peringatan paparan produksi: {qty_kg:.2f} kg {ing.name if ing else mv.ingredient_id}"
                        + (f" dari lot {lot.lot_code}" if lot else " (catatan konsumsi bahan)")
                        + " sudah tercatat sebagai PRODUCTION_CONSUMPTION sebelum insiden dilaporkan."
                    ),
                    lot_id=UUID(lot.id) if lot else None,
                    lot_code=lot.lot_code if lot else None,
                    ingredient_code=ing.code if ing else None,
                    ingredient_name=ing.name if ing else None,
                    quantity_kg=qty_kg,
                    recorded_at=mv.event_at,
                )
            )

        res_rows = list(
            session.execute(
                select(StockReservationORM).where(
                    StockReservationORM.kitchen_id == kitchen_id,
                    StockReservationORM.status == "ACTIVE",
                )
            )
            .scalars()
            .all()
        )
        for res in res_rows:
            hit_lot = res.lot_id in affected_lot_ids if res.lot_id else False
            hit_ing = res.ingredient_id in affected_ing_ids
            if not (hit_lot or hit_ing):
                continue
            lot = lot_by_id.get(res.lot_id) if res.lot_id else None
            ing = ing_by_id.get(res.ingredient_id)
            qty_kg = round(float(res.reserved_raw_g) / 1000.0, 3)
            exposures.append(
                ProductionExposureItem(
                    exposure_status="POTENTIAL_PRODUCTION_EXPOSURE",
                    summary=(
                        f"Reservasi aktif {qty_kg:.2f} kg {ing.name if ing else res.ingredient_id}"
                        + (f" pada lot {lot.lot_code}" if lot else "")
                        + f" ({res.notes or 'alokasi produksi'})."
                    ),
                    lot_id=UUID(lot.id) if lot else None,
                    lot_code=lot.lot_code if lot else None,
                    ingredient_code=ing.code if ing else None,
                    ingredient_name=ing.name if ing else None,
                    quantity_kg=qty_kg,
                    recorded_at=res.created_at,
                )
            )

    batch_run_ids = set(affected_plan_run_ids)
    if affected_ing_ids:
        usage_run_rows = session.execute(
            select(RunMaterialUsageORM.run_id).where(
                RunMaterialUsageORM.ingredient_id.in_(affected_ing_ids)
            )
        ).all()
        for ur in usage_run_rows:
            batch_run_ids.add(ur[0])

    if batch_run_ids:
        batches = list(
            session.execute(
                select(MealBatchORM).where(
                    MealBatchORM.kitchen_id == kitchen_id,
                    MealBatchORM.run_id.in_(batch_run_ids),
                )
            )
            .scalars()
            .all()
        )
        for batch in batches:
            exposures.append(
                ProductionExposureItem(
                    exposure_status="POTENTIAL_PRODUCTION_EXPOSURE",
                    summary=(
                        f"Batch hidangan {batch.batch_code} (Hari {batch.day_index}, {batch.planned_servings} porsi terencana) "
                        "terkait dengan rencana menu yang memakai bahan terdampak — segera periksa apakah sudah diporsikan/didistribusikan."
                    ),
                    meal_batch_code=batch.batch_code,
                    run_id=UUID(batch.run_id),
                    day_index=batch.day_index,
                    recorded_at=batch.created_at,
                )
            )

    if exposures:
        overall = "POTENTIAL_PRODUCTION_EXPOSURE"
    else:
        overall = "EXPOSURE_UNKNOWN"
        exposures.append(
            ProductionExposureItem(
                exposure_status="EXPOSURE_UNKNOWN",
                summary=(
                    "Tidak ditemukan log PRODUCTION_CONSUMPTION atau batch distribusi terkait; namun distribusi hilir per penerima "
                    "tidak terlacak otomatis di sistem ini (EXPOSURE_UNKNOWN). Lakukan verifikasi fisik langsung di dapur dan area saji."
                ),
            )
        )

    return overall, exposures


def _compute_affected_plan_slots(
    session: Session,
    *,
    kitchen_id: str,
    dataset_version_id: str,
    affected_codes: Set[str],
    linked_incident_id: Optional[str] = None,
) -> Tuple[List[UUID], List[AffectedPlanSlotReference], Set[str]]:
    """Find ACTIVE (or held-by-this-incident) operational plans & recipe slots touching affected ingredients."""
    op_rows = list(
        session.execute(
            select(OperationalPlanAssignmentORM).where(
                OperationalPlanAssignmentORM.kitchen_id == kitchen_id,
                OperationalPlanAssignmentORM.dataset_version_id == dataset_version_id,
                OperationalPlanAssignmentORM.operational_status.in_(["ACTIVE", "ON_HOLD"]),
            )
        )
        .scalars()
        .all()
    )
    if not op_rows or not affected_codes:
        return [], [], set()

    slot_refs: List[AffectedPlanSlotReference] = []
    affected_plan_ids: List[UUID] = []
    run_ids_touched: Set[str] = set()

    for op in op_rows:
        if (
            op.operational_status == "ON_HOLD"
            and linked_incident_id is not None
            and op.hold_incident_id not in {None, linked_incident_id}
        ):
            continue
        usages = list(
            session.execute(
                select(RunMaterialUsageORM).where(RunMaterialUsageORM.run_id == op.run_id)
            )
            .scalars()
            .all()
        )
        used_codes = {u.ingredient_code for u in usages}
        if not (used_codes & affected_codes):
            continue

        rev = session.get(MenuReviewRecordORM, op.menu_review_id)
        plan_title = rev.title if rev else f"Rencana {op.run_id[:8]}"
        affected_plan_ids.append(UUID(op.menu_review_id))
        run_ids_touched.add(op.run_id)

        assignments = list(
            session.execute(
                select(RunAssignmentORM)
                .where(RunAssignmentORM.run_id == op.run_id)
                .order_by(RunAssignmentORM.day_index, RunAssignmentORM.slot)
            )
            .scalars()
            .all()
        )
        for assign in assignments:
            rec_ings = list(
                session.execute(
                    select(RecipeIngredientORM).where(
                        RecipeIngredientORM.recipe_id == assign.recipe_id
                    )
                )
                .scalars()
                .all()
            )
            ing_hits: List[str] = []
            for ri in rec_ings:
                ing = session.get(IngredientORM, ri.ingredient_id)
                if ing and ing.code in affected_codes:
                    ing_hits.append(ing.code)
            if ing_hits:
                slot_refs.append(
                    AffectedPlanSlotReference(
                        menu_review_id=UUID(op.menu_review_id),
                        run_id=UUID(op.run_id),
                        plan_title=plan_title,
                        operational_status=op.operational_status,
                        day_index=assign.day_index,
                        slot=assign.slot,
                        recipe_id=UUID(assign.recipe_id),
                        recipe_name=assign.recipe_name,
                        affected_ingredients=sorted(set(ing_hits)),
                    )
                )

    return affected_plan_ids, slot_refs, run_ids_touched


def _load_incident_orm(
    session: Session, incident_id: UUID, *, fresh: bool = False
) -> Optional[IngredientIncidentORM]:
    if fresh:
        session.expire_all()
    stmt = (
        select(IngredientIncidentORM)
        .options(
            selectinload(IngredientIncidentORM.affected_lots),
            selectinload(IngredientIncidentORM.actions),
            selectinload(IngredientIncidentORM.images),
        )
        .where(IngredientIncidentORM.id == str(incident_id))
    )
    return session.execute(stmt).scalar_one_or_none()


def _to_incident_response(session: Session, row: IngredientIncidentORM) -> IngredientIncidentResponse:
    affected_lot_ids = {l.lot_id for l in row.affected_lots}
    affected_ing_ids = {l.ingredient_id for l in row.affected_lots}

    lot_by_id: Dict[str, InventoryLotORM] = {}
    if affected_lot_ids:
        for l in (
            session.execute(
                select(InventoryLotORM).where(InventoryLotORM.id.in_(affected_lot_ids))
            )
            .scalars()
            .all()
        ):
            lot_by_id[l.id] = l

    ing_by_id: Dict[str, IngredientORM] = {}
    if affected_ing_ids:
        for ing in (
            session.execute(
                select(IngredientORM).where(IngredientORM.id.in_(affected_ing_ids))
            )
            .scalars()
            .all()
        ):
            ing_by_id[ing.id] = ing

    clean_by_ing_id: Dict[str, float] = {}
    if affected_ing_ids:
        all_lots_for_ings = list(
            session.execute(
                select(InventoryLotORM).where(
                    InventoryLotORM.kitchen_id == row.kitchen_id,
                    InventoryLotORM.dataset_version_id == row.dataset_version_id,
                    InventoryLotORM.ingredient_id.in_(affected_ing_ids),
                )
            )
            .scalars()
            .all()
        )
        for l in all_lots_for_ings:
            if (
                (l.safety_hold_status or "NONE") == "NONE"
                and l.verification_status not in {"QUARANTINED", "UNKNOWN"}
                and l.expiry_known
            ):
                avail_lot = max(0.0, float(l.recorded_raw_g) - float(l.damaged_raw_g))
                clean_by_ing_id[l.ingredient_id] = clean_by_ing_id.get(l.ingredient_id, 0.0) + avail_lot

    lot_resps: List[IncidentAffectedLotResponse] = []
    affected_codes_set: Set[str] = set()
    affected_names_set: Set[str] = set()
    total_held_g = 0.0
    for al in row.affected_lots:
        lot_orm = lot_by_id.get(al.lot_id)
        ing_orm = ing_by_id.get(al.ingredient_id)
        code = ing_orm.code if ing_orm else al.ingredient_code
        name = ing_orm.name if ing_orm else al.ingredient_name
        affected_codes_set.add(code)
        affected_names_set.add(name)
        live_safety = lot_orm.safety_hold_status if lot_orm else al.lot_safety_status
        total_held_g += float(al.usable_before_hold_raw_g)
        lot_resps.append(
            IncidentAffectedLotResponse(
                id=UUID(al.id),
                incident_id=UUID(row.id),
                lot_id=UUID(al.lot_id),
                lot_code=lot_orm.lot_code if lot_orm else al.lot_code,
                ingredient_id=UUID(al.ingredient_id),
                ingredient_code=code,
                ingredient_name=name,
                lot_safety_status=live_safety,
                prior_lot_verification_status=al.prior_lot_verification_status,
                recorded_raw_g_snapshot=round(al.recorded_raw_g_snapshot, 3),
                usable_before_hold_raw_g=round(al.usable_before_hold_raw_g, 3),
                usable_after_hold_raw_g=round(al.usable_after_hold_raw_g, 3),
                clean_remaining_raw_g=round(clean_by_ing_id.get(al.ingredient_id, 0.0), 3),
                reason_detail=al.reason_detail,
                updated_at=al.updated_at,
            )
        )

    total_clean_remaining_kg = round(sum(clean_by_ing_id.values()) / 1000.0, 3)

    _, slot_refs, run_ids_touched = _compute_affected_plan_slots(
        session,
        kitchen_id=row.kitchen_id,
        dataset_version_id=row.dataset_version_id,
        affected_codes=affected_codes_set,
        linked_incident_id=row.id,
    )
    exposure_status, exposures = _compute_production_exposure(
        session,
        kitchen_id=row.kitchen_id,
        affected_lot_ids=affected_lot_ids,
        affected_ing_ids=affected_ing_ids,
        affected_plan_run_ids=run_ids_touched,
        lot_by_id=lot_by_id,
        ing_by_id=ing_by_id,
    )

    images = [
        IncidentImageInfo(
            id=UUID(img.id),
            incident_id=UUID(row.id),
            original_filename_sanitized=img.original_filename_sanitized,
            mime_type=img.mime_type,
            size_bytes=img.size_bytes,
            width_px=img.width_px,
            height_px=img.height_px,
            sha256=img.sha256,
            exif_stripped=img.exif_stripped,
            uploaded_by_user_id=UUID(img.uploaded_by_user_id),
            created_at=img.created_at,
            expires_at=image_expiry(img.created_at, img.retention_days),
            image_url=f"/api/v1/incidents/{row.id}/images/{img.id}",
        )
        for img in sorted(row.images, key=lambda x: x.created_at)
    ]

    actions = [
        IncidentActionResponse(
            id=UUID(act.id),
            incident_id=UUID(row.id),
            action_type=act.action_type,
            actor_user_id=UUID(act.actor_user_id) if act.actor_user_id else None,
            actor_name=_user_name(session, act.actor_user_id),
            actor_role=act.actor_role,
            notes=act.notes,
            metadata=dict(act.metadata_json or {}),
            created_at=act.created_at,
        )
        for act in sorted(row.actions, key=lambda a: a.created_at)
    ]

    return IngredientIncidentResponse(
        id=UUID(row.id),
        kitchen_id=UUID(row.kitchen_id),
        dataset_version_id=UUID(row.dataset_version_id),
        title=row.title,
        category=IncidentCategoryEnum(row.category),
        severity=IncidentSeverityEnum(row.severity),
        status=IncidentStatusEnum(row.status),
        notes=row.notes,
        supplier_name=row.supplier_name,
        delivery_ref=row.delivery_ref,
        related_batch_code=row.related_batch_code,
        observed_at=row.observed_at,
        reported_by_user_id=UUID(row.reported_by_user_id),
        reported_by_name=_user_name(session, row.reported_by_user_id) or "Petugas Dapur",
        reporter_role=row.reporter_role,
        created_at=row.created_at,
        updated_at=row.updated_at,
        affected_lots=lot_resps,
        affected_ingredient_codes=sorted(affected_codes_set),
        affected_ingredient_names=sorted(affected_names_set),
        total_held_kg=round(total_held_g / 1000.0, 3),
        total_clean_remaining_kg=total_clean_remaining_kg,
        affected_plans=slot_refs,
        exposure_status=exposure_status,
        production_exposures=exposures,
        recovery_event_id=UUID(row.recovery_event_id) if row.recovery_event_id else None,
        images=images,
        actions=actions,
    )


def report_ingredient_incident(
    session: Session,
    auth: AuthContext,
    req: IncidentCreateRequest,
) -> IngredientIncidentResponse:
    """Atomically report one or multiple compromised ingredients/lots, place ON_HOLD, inspect exposure, and hold affected active plans."""
    if req.idempotency_key and req.idempotency_key.strip():
        key = req.idempotency_key.strip()
        existing = session.execute(
            select(IngredientIncidentORM).where(
                IngredientIncidentORM.kitchen_id == str(auth.kitchen_id),
                IngredientIncidentORM.idempotency_key == key,
            )
        ).scalar_one_or_none()
        if existing is not None:
            reloaded = _load_incident_orm(session, UUID(existing.id), fresh=True)
            assert reloaded is not None
            return _to_incident_response(session, reloaded)
    else:
        key = None

    repo = SQLiteVaultRepository(session)
    ds_id = req.dataset_version_id or repo.get_active_dataset_id(auth.kitchen_id)
    try:
        repo.get_dataset_orm(ds_id, kitchen_id=auth.kitchen_id)
    except ResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    ing_rows = list(
        session.execute(
            select(IngredientORM).where(IngredientORM.dataset_version_id == str(ds_id))
        )
        .scalars()
        .all()
    )
    ing_by_code = {i.code: i for i in ing_rows}
    ing_by_id = {i.id: i for i in ing_rows}

    all_kitchen_lots = list(
        session.execute(
            select(InventoryLotORM).where(
                InventoryLotORM.kitchen_id == str(auth.kitchen_id),
                InventoryLotORM.dataset_version_id == str(ds_id),
            )
        )
        .scalars()
        .all()
    )
    lot_by_id = {l.id: l for l in all_kitchen_lots}
    lot_by_code = {l.lot_code: l for l in all_kitchen_lots}

    # Compute usable qty BEFORE hold so snapshots accurately capture usable_before_hold_raw_g
    pre_hold_avail = compute_usable_inventory(
        session,
        kitchen_id=auth.kitchen_id,
        dataset_version_id=ds_id,
    )
    pre_lot_usable: Dict[str, float] = {}
    for av in pre_hold_avail.items:
        for lsum in av.lots:
            pre_lot_usable[str(lsum.id)] = float(lsum.usable_raw_g)

    target_lots: Dict[str, Tuple[InventoryLotORM, Optional[str]]] = {}
    affected_ing_codes: Set[str] = set()

    for lot_in in req.affected_lots:
        matched_lot: Optional[InventoryLotORM] = None
        if lot_in.lot_id is not None:
            matched_lot = lot_by_id.get(str(lot_in.lot_id))
            if matched_lot is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"Lot '{lot_in.lot_id}' tidak ditemukan pada dapur/dataset ini.",
                )
        elif lot_in.lot_code and lot_in.lot_code.strip():
            matched_lot = lot_by_code.get(lot_in.lot_code.strip())
            if matched_lot is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"Kode lot '{lot_in.lot_code}' tidak ditemukan pada dapur/dataset ini.",
                )
        elif lot_in.ingredient_code and lot_in.ingredient_code.strip():
            code = lot_in.ingredient_code.strip()
            ing = ing_by_code.get(code)
            if ing is None:
                raise HTTPException(status_code=422, detail=f"Kode bahan tidak dikenal: '{code}'.")
            matching = [l for l in all_kitchen_lots if l.ingredient_id == ing.id]
            for ml in matching:
                target_lots[ml.id] = (ml, lot_in.reason_detail)
            affected_ing_codes.add(code)
            continue
        else:
            raise HTTPException(
                status_code=422,
                detail="Setiap entri lot wajib menyertakan lot_id, lot_code, atau ingredient_code.",
            )

        ing_for_lot = ing_by_id.get(matched_lot.ingredient_id)
        if ing_for_lot:
            affected_ing_codes.add(ing_for_lot.code)
        target_lots[matched_lot.id] = (matched_lot, lot_in.reason_detail)

    for raw_code in req.ingredient_codes:
        code = raw_code.strip()
        if not code:
            continue
        ing = ing_by_code.get(code)
        if ing is None:
            raise HTTPException(status_code=422, detail=f"Kode bahan tidak dikenal: '{code}'.")
        affected_ing_codes.add(code)
        if req.auto_hold_matching_lots:
            for ml in all_kitchen_lots:
                if ml.ingredient_id == ing.id and ml.id not in target_lots:
                    target_lots[ml.id] = (ml, "Penahanan otomatis sesuai laporan insiden bahan.")

    if not target_lots:
        raise HTTPException(
            status_code=422,
            detail="Pilih minimal satu lot atau bahan yang memiliki lot aktif di dapur ini untuk ditahan.",
        )

    now = _utcnow()
    observed_dt = req.observed_at or now
    incident_id = str(uuid4())
    affected_ing_ids = {lot.ingredient_id for lot, _ in target_lots.values()}
    affected_lot_ids_set = set(target_lots.keys())

    # Calculate pre-hold plan/exposure snapshot before committing holds
    _, slot_refs, run_ids_touched = _compute_affected_plan_slots(
        session,
        kitchen_id=str(auth.kitchen_id),
        dataset_version_id=str(ds_id),
        affected_codes=affected_ing_codes,
    )
    exposure_status, exposures = _compute_production_exposure(
        session,
        kitchen_id=str(auth.kitchen_id),
        affected_lot_ids=affected_lot_ids_set,
        affected_ing_ids=affected_ing_ids,
        affected_plan_run_ids=run_ids_touched,
        lot_by_id=lot_by_id,
        ing_by_id=ing_by_id,
    )

    incident_row = IngredientIncidentORM(
        id=incident_id,
        kitchen_id=str(auth.kitchen_id),
        dataset_version_id=str(ds_id),
        title=req.title.strip(),
        category=req.category.value,
        severity=req.severity.value,
        status=IncidentStatusEnum.ON_HOLD.value,
        observed_at=observed_dt,
        reported_by_user_id=str(auth.user_id),
        reporter_role=auth.role.value,
        notes=req.notes.strip(),
        supplier_name=req.supplier_name.strip() if req.supplier_name else None,
        delivery_ref=req.delivery_ref.strip() if req.delivery_ref else None,
        related_batch_code=req.related_batch_code.strip() if req.related_batch_code else None,
        exposure_status=exposure_status,
        exposure_summary_json={"items": [e.model_dump(mode="json") for e in exposures]},
        affected_plans_json=[],
        idempotency_key=key,
        created_at=now,
        updated_at=now,
    )
    session.add(incident_row)
    session.flush()

    held_codes_for_audit: List[str] = []
    for lot_id, (lot_orm, note) in target_lots.items():
        if lot_orm.safety_hold_status == "REJECTED_DISPOSED":
            raise HTTPException(
                status_code=409,
                detail=f"Lot {lot_orm.lot_code} sudah berstatus REJECTED_DISPOSED.",
            )
        ing_orm = ing_by_id.get(lot_orm.ingredient_id)
        prior_status = lot_orm.verification_status
        lot_orm.safety_hold_status = "ON_HOLD"
        held_codes_for_audit.append(lot_orm.lot_code)
        before_g = pre_lot_usable.get(lot_orm.id, float(lot_orm.recorded_raw_g))
        session.add(
            IncidentAffectedLotORM(
                id=str(uuid4()),
                incident_id=incident_id,
                kitchen_id=str(auth.kitchen_id),
                dataset_version_id=str(ds_id),
                ingredient_id=lot_orm.ingredient_id,
                lot_id=lot_orm.id,
                lot_code=lot_orm.lot_code,
                ingredient_code=ing_orm.code if ing_orm else "",
                ingredient_name=ing_orm.name if ing_orm else lot_orm.ingredient_id,
                lot_safety_status="ON_HOLD",
                prior_lot_verification_status=prior_status,
                recorded_raw_g_snapshot=float(lot_orm.recorded_raw_g),
                usable_before_hold_raw_g=before_g,
                usable_after_hold_raw_g=0.0,
                reason_detail=note,
                created_at=now,
                updated_at=now,
            )
        )
    session.flush()

    hold_reason = f"Insiden {req.category.value} ({req.severity.value}): {', '.join(sorted(affected_ing_codes))}"
    held_plans = place_affected_plans_on_hold(
        session,
        kitchen_id=auth.kitchen_id,
        dataset_version_id=ds_id,
        incident_id=UUID(incident_id),
        reason=hold_reason,
        held_ingredient_codes=sorted(affected_ing_codes),
        held_lot_ids=sorted(affected_lot_ids_set),
        actor_user_id=auth.user_id,
        actor_role=auth.role.value,
    )
    incident_row.affected_plans_json = held_plans

    session.add(
        IncidentActionORM(
            id=str(uuid4()),
            incident_id=incident_id,
            kitchen_id=str(auth.kitchen_id),
            action_type="REPORTED_AND_HELD",
            actor_user_id=str(auth.user_id),
            actor_role=auth.role.value,
            notes=req.notes.strip(),
            metadata_json={
                "held_lot_codes": sorted(held_codes_for_audit),
                "affected_ingredient_codes": sorted(affected_ing_codes),
                "held_plans": held_plans,
                "severity": req.severity.value,
                "category": req.category.value,
                "exposure_status": exposure_status,
            },
            created_at=now,
        )
    )
    record_audit_event(
        session,
        action="incident.reported_hold",
        entity_type="ingredient_incident",
        entity_id=incident_id,
        kitchen_id=auth.kitchen_id,
        actor_user_id=auth.user_id,
        actor_role=auth.role.value,
        metadata={
            "title": req.title.strip(),
            "held_lot_codes": sorted(held_codes_for_audit),
            "affected_ingredient_codes": sorted(affected_ing_codes),
            "held_plans_count": len(held_plans),
            "exposure_status": exposure_status,
        },
    )
    session.commit()

    reloaded = _load_incident_orm(session, UUID(incident_id), fresh=True)
    assert reloaded is not None
    return _to_incident_response(session, reloaded)


def list_incidents(session: Session, auth: AuthContext) -> List[IngredientIncidentResponse]:
    rows = list(
        session.execute(
            select(IngredientIncidentORM)
            .options(
                selectinload(IngredientIncidentORM.affected_lots),
                selectinload(IngredientIncidentORM.actions),
                selectinload(IngredientIncidentORM.images),
            )
            .where(IngredientIncidentORM.kitchen_id == str(auth.kitchen_id))
            .order_by(IngredientIncidentORM.created_at.desc())
        )
        .scalars()
        .all()
    )
    return [_to_incident_response(session, r) for r in rows]


def get_incident(session: Session, auth: AuthContext, incident_id: UUID) -> IngredientIncidentResponse:
    row = _load_incident_orm(session, incident_id)
    if row is None or row.kitchen_id != str(auth.kitchen_id):
        raise HTTPException(
            status_code=404,
            detail=f"Insiden bahan '{incident_id}' tidak ditemukan pada dapur ini.",
        )
    return _to_incident_response(session, row)


def get_incident_impact(
    session: Session, auth: AuthContext, incident_id: UUID
) -> IncidentImpactSummaryResponse:
    inc = get_incident(session, auth, incident_id)
    plan_ids = list(dict.fromkeys(p.menu_review_id for p in inc.affected_plans if p.menu_review_id))
    summary = (
        f"Insiden '{inc.title}' menahan {len(inc.affected_lots)} lot ({inc.total_held_kg:.2f} kg) "
        f"pada {len(inc.affected_ingredient_codes)} bahan ({', '.join(inc.affected_ingredient_names)}). "
        f"{len(inc.affected_plans)} slot menu pada rencana aktif/terdampak terkena imbas. "
        f"Status paparan produksi: {inc.exposure_status}."
    )
    return IncidentImpactSummaryResponse(
        incident_id=inc.id,
        affected_ingredient_codes=inc.affected_ingredient_codes,
        affected_ingredient_names=inc.affected_ingredient_names,
        held_lots_count=len(inc.affected_lots),
        total_held_kg=inc.total_held_kg,
        total_clean_remaining_kg=inc.total_clean_remaining_kg,
        affected_plan_ids=plan_ids,
        affected_slots=inc.affected_plans,
        exposure_status=inc.exposure_status,
        production_exposures=inc.production_exposures,
        summary_message=summary,
    )


def update_incident_status(
    session: Session,
    auth: AuthContext,
    incident_id: UUID,
    req: IncidentStatusUpdateRequest,
) -> IngredientIncidentResponse:
    row = _load_incident_orm(session, incident_id)
    if row is None or row.kitchen_id != str(auth.kitchen_id):
        raise HTTPException(status_code=404, detail="Insiden tidak ditemukan pada dapur ini.")

    if req.status in {
        IncidentStatusEnum.REJECTED,
        IncidentStatusEnum.RESOLVED,
        IncidentStatusEnum.CLOSED,
    } and auth.role != RoleEnum.KITCHEN_MANAGER:
        raise HTTPException(
            status_code=403,
            detail="Hanya Kepala Dapur (KITCHEN_MANAGER) yang dapat memusnahkan lot atau menutup insiden.",
        )

    now = _utcnow()
    row.status = req.status.value
    row.updated_at = now

    disposed_lots: List[str] = []
    if req.dispose_held_lots or req.status == IncidentStatusEnum.REJECTED:
        for al in row.affected_lots:
            lot = session.get(InventoryLotORM, al.lot_id)
            if lot is not None:
                lot.safety_hold_status = "REJECTED_DISPOSED"
                disposed_lots.append(lot.lot_code)
            al.lot_safety_status = "REJECTED_DISPOSED"
            al.updated_at = now
            if req.disposal_notes:
                al.reason_detail = req.disposal_notes.strip()

    session.add(
        IncidentActionORM(
            id=str(uuid4()),
            incident_id=row.id,
            kitchen_id=row.kitchen_id,
            action_type=f"STATUS_{req.status.value}",
            actor_user_id=str(auth.user_id),
            actor_role=auth.role.value,
            notes=req.notes.strip(),
            metadata_json={
                "new_status": req.status.value,
                "disposed_lots": disposed_lots,
            },
            created_at=now,
        )
    )
    record_audit_event(
        session,
        action="incident.status_updated",
        entity_type="ingredient_incident",
        entity_id=row.id,
        kitchen_id=auth.kitchen_id,
        actor_user_id=auth.user_id,
        actor_role=auth.role.value,
        metadata={"new_status": req.status.value, "disposed_lots": disposed_lots},
    )
    session.commit()
    reloaded = _load_incident_orm(session, incident_id, fresh=True)
    assert reloaded is not None
    return _to_incident_response(session, reloaded)


def release_safety_hold_blocked(
    session: Session,
    auth: AuthContext,
    incident_id: UUID,
    req: IncidentReleaseHoldRequest,
) -> None:
    """Strictly forbid releasing SAFETY HOLD lots inside GiziOptima while recording full forensic audit trail."""
    row = _load_incident_orm(session, incident_id)
    if row is None or row.kitchen_id != str(auth.kitchen_id):
        raise HTTPException(status_code=404, detail="Insiden tidak ditemukan pada dapur ini.")

    now = _utcnow()
    session.add(
        IncidentActionORM(
            id=str(uuid4()),
            incident_id=row.id,
            kitchen_id=row.kitchen_id,
            action_type="RELEASE_ATTEMPT_BLOCKED",
            actor_user_id=str(auth.user_id),
            actor_role=auth.role.value,
            notes=req.notes or "Percobaan pelepasan tahan keamanan di dalam aplikasi diblokir.",
            metadata_json={
                "authority_reference": req.authority_reference,
                "blocked_policy": "EXTERNAL_AUTHORITY_ONLY",
            },
            created_at=now,
        )
    )
    record_audit_event(
        session,
        action="incident.release_hold_blocked",
        entity_type="ingredient_incident",
        entity_id=row.id,
        kitchen_id=auth.kitchen_id,
        actor_user_id=auth.user_id,
        actor_role=auth.role.value,
        metadata={"authority_reference": req.authority_reference},
    )
    session.commit()
    raise HTTPException(
        status_code=403,
        detail=(
            "Pelepasan tahan keamanan (SAFETY HOLD) DILARANG dilakukan sepihak di dalam aplikasi. "
            "Lot tetap dikecualikan sampai keputusan/uji laboratorium otoritas resmi berwenang di luar sistem (BPOM/Dinkes/ahli gizi tersertifikasi)."
        ),
    )


def start_recovery_for_incident(
    session: Session,
    auth: AuthContext,
    incident_id: UUID,
    req: IncidentStartRecoveryRequest,
):
    """Trigger minimum-disruption & min-cost recovery strictly using clean verified stock (held lots excluded)."""
    if auth.role != RoleEnum.MENU_PLANNER:
        raise HTTPException(
            status_code=403,
            detail="Hanya Perencana Menu (MENU_PLANNER) yang dapat menjalankan optimasi pemulihan menu.",
        )
    inc = get_incident(session, auth, incident_id)
    if inc.status == IncidentStatusEnum.CLOSED:
        raise HTTPException(status_code=409, detail="Insiden sudah ditutup (CLOSED).")

    baseline_review_id = req.baseline_menu_review_id
    baseline_run_id = req.baseline_run_id
    if baseline_review_id is None and baseline_run_id is None:
        held_assign = session.execute(
            select(OperationalPlanAssignmentORM)
            .where(
                OperationalPlanAssignmentORM.kitchen_id == str(auth.kitchen_id),
                OperationalPlanAssignmentORM.hold_incident_id == str(incident_id),
            )
            .order_by(OperationalPlanAssignmentORM.updated_at.desc())
        ).scalars().first()
        if held_assign is not None:
            baseline_review_id = UUID(held_assign.menu_review_id)
        elif inc.affected_plans and inc.affected_plans[0].menu_review_id:
            baseline_review_id = inc.affected_plans[0].menu_review_id
        else:
            rev = session.execute(
                select(MenuReviewRecordORM)
                .where(
                    MenuReviewRecordORM.kitchen_id == str(auth.kitchen_id),
                    MenuReviewRecordORM.dataset_version_id == str(inc.dataset_version_id),
                    MenuReviewRecordORM.status == "APPROVED",
                )
                .order_by(MenuReviewRecordORM.reviewed_at.desc())
            ).scalars().first()
            if rev is not None:
                baseline_review_id = UUID(rev.id)

    rec_req = DisruptionConditionRequest(
        baseline_menu_review_id=baseline_review_id,
        baseline_run_id=baseline_run_id,
        incident_id=incident_id,
        title=req.title or f"Pemulihan Insiden: {inc.title}",
        disruption_summary=inc.notes or inc.title,
        disruption_types=[DisruptionTypeEnum.SAFETY_HOLD, DisruptionTypeEnum.STOCK_SHORTAGE],
        production_date=req.production_date,
        use_latest_verified_inventory=True,
        new_servings_per_day=req.new_servings_per_day,
        new_budget_idr_per_serving=req.new_budget_idr_per_serving,
        price_changes=[],
        stock_changes=[],
        time_limit_seconds=req.time_limit_seconds,
    )
    event_resp = analyze_and_create_recovery_event(session, auth, rec_req)

    inc_row = session.get(IngredientIncidentORM, str(incident_id))
    assert inc_row is not None
    now = _utcnow()
    inc_row.status = IncidentStatusEnum.UNDER_REVIEW.value
    inc_row.recovery_event_id = str(event_resp.id)
    inc_row.updated_at = now
    session.add(
        IncidentActionORM(
            id=str(uuid4()),
            incident_id=inc_row.id,
            kitchen_id=inc_row.kitchen_id,
            action_type="RECOVERY_STARTED",
            actor_user_id=str(auth.user_id),
            actor_role=auth.role.value,
            notes=f"Pemulihan menu dijalankan -> event {event_resp.id} ({event_resp.status.value}).",
            metadata_json={
                "recovery_event_id": str(event_resp.id),
                "recovery_status": event_resp.status.value,
                "min_disruption_feasible": event_resp.min_disruption.validation_passed,
                "min_cost_feasible": event_resp.min_cost.validation_passed,
            },
            created_at=now,
        )
    )
    session.commit()
    return event_resp


def upload_incident_image(
    session: Session,
    auth: AuthContext,
    incident_id: UUID,
    raw_bytes: bytes,
    original_filename: str,
) -> IncidentImageInfo:
    row = session.get(IngredientIncidentORM, str(incident_id))
    if row is None or row.kitchen_id != str(auth.kitchen_id):
        raise HTTPException(status_code=404, detail="Insiden tidak ditemukan pada dapur ini.")

    existing_count = len(
        session.execute(
            select(IncidentImageORM.id).where(IncidentImageORM.incident_id == row.id)
        ).all()
    )
    if existing_count >= 12:
        raise HTTPException(status_code=422, detail="Maksimal 12 foto bukti per insiden.")

    try:
        stored = validate_strip_exif_and_store(raw_bytes, original_filename)
    except ImageSecurityError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    now = _utcnow()
    retention_days = get_qc_retention_days()
    img_id = str(uuid4())
    try:
        img_row = IncidentImageORM(
            id=img_id,
            incident_id=row.id,
            kitchen_id=row.kitchen_id,
            uploaded_by_user_id=str(auth.user_id),
            original_filename_sanitized=stored.original_filename_sanitized,
            mime_type=stored.mime_type,
            size_bytes=stored.size_bytes,
            width_px=stored.width_px,
            height_px=stored.height_px,
            sha256=stored.sha256,
            storage_key=stored.storage_key,
            exif_stripped=stored.exif_stripped,
            retention_days=retention_days,
            created_at=now,
        )
        session.add(img_row)
        session.add(
            IncidentActionORM(
                id=str(uuid4()),
                incident_id=row.id,
                kitchen_id=row.kitchen_id,
                action_type="EVIDENCE_PHOTO_UPLOADED",
                actor_user_id=str(auth.user_id),
                actor_role=auth.role.value,
                notes=f"Foto bukti '{stored.original_filename_sanitized}' diunggah (EXIF dibersihkan).",
                metadata_json={"image_id": img_id, "sha256": stored.sha256},
                created_at=now,
            )
        )
        record_audit_event(
            session,
            action="incident.image_uploaded",
            entity_type="ingredient_incident",
            entity_id=row.id,
            kitchen_id=auth.kitchen_id,
            actor_user_id=auth.user_id,
            actor_role=auth.role.value,
            metadata={"image_id": img_id, "sha256": stored.sha256},
        )
        session.commit()
    except Exception:
        session.rollback()
        try:
            qc_storage_path(stored.storage_key).unlink(missing_ok=True)
        except OSError:
            pass
        raise

    return IncidentImageInfo(
        id=UUID(img_id),
        incident_id=incident_id,
        original_filename_sanitized=stored.original_filename_sanitized,
        mime_type=stored.mime_type,
        size_bytes=stored.size_bytes,
        width_px=stored.width_px,
        height_px=stored.height_px,
        sha256=stored.sha256,
        exif_stripped=stored.exif_stripped,
        uploaded_by_user_id=auth.user_id,
        created_at=now,
        expires_at=image_expiry(now, retention_days),
        image_url=f"/api/v1/incidents/{row.id}/images/{img_id}",
    )


def get_incident_image_bytes(
    session: Session,
    auth: AuthContext,
    incident_id: UUID,
    image_id: UUID,
) -> Tuple[bytes, str]:
    img = session.get(IncidentImageORM, str(image_id))
    if (
        img is None
        or img.incident_id != str(incident_id)
        or img.kitchen_id != str(auth.kitchen_id)
    ):
        raise HTTPException(status_code=404, detail="Foto bukti insiden tidak ditemukan.")
    try:
        return read_stored_image_bytes(img.storage_key), img.mime_type
    except (ImageSecurityError, OSError) as exc:
        raise HTTPException(status_code=404, detail="File foto tidak ditemukan.") from exc


def get_incident_actions(
    session: Session, auth: AuthContext, incident_id: UUID
) -> List[IncidentActionResponse]:
    inc = get_incident(session, auth, incident_id)
    return inc.actions
