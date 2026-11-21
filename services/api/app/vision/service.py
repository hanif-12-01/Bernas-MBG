from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session, selectinload

from app.auth.dependencies import AuthContext, record_audit_event
from app.auth.rate_limit import RateLimiter
from app.auth.schemas import RoleEnum
from app.db.models import (
    IngredientORM,
    MealBatchORM,
    MenuReviewRecordORM,
    OperationalPlanAssignmentORM,
    OptimizationRunORM,
    QCAIObservationORM,
    QCHumanReviewORM,
    QCImageORM,
    QCInspectionORM,
    RecipeVariantORM,
    RunAssignmentORM,
    ScenarioORM,
    UserORM,
)
from app.reviews.schemas import MenuReviewStatusEnum
from app.vision.comparator import compare_expected_menu_with_observations
from app.vision.image_security import (
    ImageSecurityError,
    get_qc_retention_days,
    image_expiry,
    qc_storage_path,
    read_stored_image_bytes,
    validate_strip_exif_and_store,
)
from app.vision.provider import (
    VisionOutputValidationError,
    VisionProvider,
    VisionProviderError,
    VisionProviderUnavailableError,
    resolve_vision_provider,
)
from app.vision.schemas import (
    ExpectedMenuSlot,
    ExpectedVsObservedFinding,
    HumanCorrectedComponent,
    QCAIObservationInfo,
    QCHumanReviewInfo,
    QCImageInfo,
    QCInspectionCreateRequest,
    QCInspectionResponse,
    QCInspectionStatusEnum,
    QCManagerReviewRequest,
    QCObservationsPatchRequest,
    QCReviewOutcomeEnum,
    QCSubmitRequest,
    VisionAnalysisOutput,
)

SLOT_ORDER = {"staple": 0, "protein": 1, "vegetable": 2, "fruit": 3}
MAX_IMAGES_PER_INSPECTION = 12
vision_rate_limiter = RateLimiter(max_attempts=12, window_seconds=60)


def _update_inspection(session: Session, row: QCInspectionORM, **values: object) -> None:
    """Keep concurrent writes from advancing an inspection based on stale evidence."""
    result = session.execute(
        update(QCInspectionORM)
        .where(QCInspectionORM.id == row.id, QCInspectionORM.updated_at == row.updated_at)
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        raise HTTPException(status_code=409, detail="Pemeriksaan berubah. Muat ulang dan coba lagi.")


def _latest_image(row: QCInspectionORM) -> QCImageORM:
    return max(row.images, key=lambda image: (image.created_at, image.id))


def _read_active_image(image: QCImageORM) -> bytes:
    if datetime.now(timezone.utc) >= image_expiry(image.created_at, image.retention_days):
        raise HTTPException(status_code=410, detail="Masa simpan foto telah berakhir.")
    try:
        return read_stored_image_bytes(image.storage_key)
    except (FileNotFoundError, ImageSecurityError) as exc:
        raise HTTPException(status_code=404, detail="Berkas gambar privat tidak ditemukan.") from exc


def _user_name(session: Session, user_id: Optional[str]) -> Optional[str]:
    if not user_id:
        return None
    u = session.get(UserORM, user_id)
    return u.full_name if u else None


def _load_expected_menu(
    session: Session, run_id: str, day_index: int
) -> List[ExpectedMenuSlot]:
    stmt = (
        select(RunAssignmentORM)
        .where(
            RunAssignmentORM.run_id == run_id,
            RunAssignmentORM.day_index == day_index,
        )
    )
    assignments = list(session.execute(stmt).scalars().all())
    assignments.sort(key=lambda a: SLOT_ORDER.get(a.slot, 99))

    slots: List[ExpectedMenuSlot] = []
    for a in assignments:
        rec = session.execute(
            select(RecipeVariantORM)
            .options(selectinload(RecipeVariantORM.ingredients))
            .where(RecipeVariantORM.id == a.recipe_id)
        ).scalar_one_or_none()
        ing_names: List[str] = []
        if rec:
            ing_ids = [ri.ingredient_id for ri in rec.ingredients]
            if ing_ids:
                ing_rows = session.execute(
                    select(IngredientORM.name).where(IngredientORM.id.in_(ing_ids))
                ).scalars().all()
                ing_names = sorted(list(ing_rows))
        slots.append(
            ExpectedMenuSlot(
                slot=a.slot,
                recipe_id=a.recipe_id,
                recipe_name=a.recipe_name,
                ingredient_names=ing_names,
            )
        )
    return slots


def _load_inspection_orm(
    session: Session, inspection_id: UUID, *, fresh: bool = False
) -> Optional[QCInspectionORM]:
    if fresh:
        session.expire_all()
    stmt = (
        select(QCInspectionORM)
        .options(
            selectinload(QCInspectionORM.images),
            selectinload(QCInspectionORM.ai_observations),
            selectinload(QCInspectionORM.human_reviews),
        )
        .where(QCInspectionORM.id == str(inspection_id))
    )
    return session.execute(stmt).scalar_one_or_none()


def _to_response(session: Session, row: QCInspectionORM) -> QCInspectionResponse:
    run = session.get(OptimizationRunORM, row.run_id)
    sc = session.get(ScenarioORM, run.scenario_id) if run else None
    expected_menu = _load_expected_menu(session, row.run_id, row.day_index)

    images = [
        QCImageInfo(
            id=UUID(img.id),
            original_filename_sanitized=img.original_filename_sanitized,
            mime_type=img.mime_type,
            size_bytes=img.size_bytes,
            width_px=img.width_px,
            height_px=img.height_px,
            sha256=img.sha256,
            exif_stripped=img.exif_stripped,
            retention_days=img.retention_days,
            uploaded_by_user_id=UUID(img.uploaded_by_user_id),
            created_at=img.created_at,
            expires_at=image_expiry(img.created_at, img.retention_days),
            image_url=f"/api/v1/qc/inspections/{row.id}/images/{img.id}",
        )
        for img in sorted(row.images, key=lambda x: x.created_at)
    ]

    ai_observations = [
        QCAIObservationInfo(
            id=UUID(obs.id),
            image_id=UUID(obs.image_id),
            provider_name=obs.provider_name,
            provider_mode=obs.provider_mode,
            is_live_ai=obs.is_live_ai,
            model_identifier=obs.model_identifier,
            prompt_version=obs.prompt_version,
            validated_output=VisionAnalysisOutput.model_validate(obs.validated_output_json),
            comparison_findings=[
                ExpectedVsObservedFinding.model_validate(f)
                for f in (obs.comparison_findings_json or [])
            ],
            latency_ms=obs.latency_ms,
            created_at=obs.created_at,
        )
        for obs in sorted(row.ai_observations, key=lambda x: x.created_at)
    ]

    human_reviews = [
        QCHumanReviewInfo(
            id=UUID(hr.id),
            ai_observation_id=UUID(hr.ai_observation_id) if hr.ai_observation_id else None,
            reviewer_user_id=UUID(hr.reviewer_user_id),
            reviewer_name=_user_name(session, hr.reviewer_user_id) or "Petugas QC",
            corrected_components=[
                HumanCorrectedComponent.model_validate(c)
                for c in (hr.corrected_components_json or [])
            ],
            notes=hr.notes,
            request_retake=hr.request_retake,
            created_at=hr.created_at,
        )
        for hr in sorted(row.human_reviews, key=lambda x: x.created_at)
    ]

    op_row = (
        session.execute(
            select(OperationalPlanAssignmentORM)
            .where(OperationalPlanAssignmentORM.menu_review_id == row.menu_review_id)
            .order_by(OperationalPlanAssignmentORM.updated_at.desc())
        )
        .scalars()
        .first()
        if row.menu_review_id
        else None
    )

    return QCInspectionResponse(
        id=UUID(row.id),
        kitchen_id=UUID(row.kitchen_id),
        menu_review_id=UUID(row.menu_review_id) if row.menu_review_id else None,
        run_id=UUID(row.run_id),
        scenario_name=sc.name if sc else f"Rencana {row.run_id[:8]}",
        day_index=row.day_index,
        status=QCInspectionStatusEnum(row.status),
        review_outcome=QCReviewOutcomeEnum(row.review_outcome) if row.review_outcome else None,
        plan_operational_status=op_row.operational_status if op_row else None,
        plan_hold_reason=op_row.hold_reason if op_row else None,
        created_by_user_id=UUID(row.created_by_user_id),
        created_by_name=_user_name(session, row.created_by_user_id) or "Petugas QC",
        submitted_by_user_id=UUID(row.submitted_by_user_id) if row.submitted_by_user_id else None,
        submitted_by_name=_user_name(session, row.submitted_by_user_id),
        reviewed_by_user_id=UUID(row.reviewed_by_user_id) if row.reviewed_by_user_id else None,
        reviewed_by_name=_user_name(session, row.reviewed_by_user_id),
        qc_notes=row.qc_notes,
        manager_notes=row.manager_notes,
        submitted_at=row.submitted_at,
        reviewed_at=row.reviewed_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
        expected_menu=expected_menu,
        images=images,
        ai_observations=ai_observations,
        human_reviews=human_reviews,
    )


def create_inspection(
    session: Session,
    auth: AuthContext,
    req: QCInspectionCreateRequest,
) -> QCInspectionResponse:
    if auth.role != RoleEnum.QC_OFFICER:
        raise HTTPException(
            status_code=403,
            detail="Hanya Petugas QC (QC_OFFICER) yang dapat membuat pemeriksaan visual menu.",
        )

    run = session.get(OptimizationRunORM, str(req.run_id))
    if run is None:
        raise HTTPException(status_code=404, detail=f"Rencana optimasi '{req.run_id}' tidak ditemukan.")

    scenario = session.get(ScenarioORM, run.scenario_id)
    if scenario is None or scenario.kitchen_id != str(auth.kitchen_id):
        raise HTTPException(
            status_code=404, detail=f"Rencana optimasi '{req.run_id}' tidak ditemukan pada dapur Anda."
        )

    if not run.validation_passed:
        raise HTTPException(
            status_code=409,
            detail="Inspeksi QC hanya dapat dibuat untuk rencana menu yang lolos validator independen.",
        )

    if req.day_index > scenario.days:
        raise HTTPException(
            status_code=422,
            detail=f"Hari ke-{req.day_index} melebihi horizon rencana ({scenario.days} hari).",
        )

    ref: Optional[MenuReviewRecordORM]
    if req.menu_review_id is not None:
        ref = session.get(MenuReviewRecordORM, str(req.menu_review_id))
        if ref is None or ref.kitchen_id != str(auth.kitchen_id) or ref.run_id != run.id:
            raise HTTPException(
                status_code=404,
                detail="Catatan peninjauan menu tidak cocok dengan dapur atau run yang dipilih.",
            )
    else:
        ref = session.scalar(
            select(MenuReviewRecordORM)
            .where(
                MenuReviewRecordORM.kitchen_id == str(auth.kitchen_id),
                MenuReviewRecordORM.run_id == run.id,
                MenuReviewRecordORM.status == MenuReviewStatusEnum.APPROVED.value,
            )
            .order_by(MenuReviewRecordORM.version_number.desc())
            .limit(1)
        )
    if ref is None or ref.status != MenuReviewStatusEnum.APPROVED.value:
        raise HTTPException(status_code=409, detail="Pilih rencana menu yang telah disetujui Kepala Dapur.")

    # Sprint 3B.1/3C Operational plan status check: block routine QC on ON_HOLD, SUPERSEDED, or unactivated replacements
    from app.operations.service import derive_production_scope

    op_row = session.execute(
        select(OperationalPlanAssignmentORM)
        .where(OperationalPlanAssignmentORM.menu_review_id == ref.id)
        .order_by(OperationalPlanAssignmentORM.updated_at.desc())
    ).scalars().first()
    if op_row is not None:
        if op_row.operational_status == "ON_HOLD":
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Pemeriksaan QC rutin diblokir: rencana '{ref.title}' sedang berstatus ON HOLD "
                    f"({op_row.hold_reason or 'insiden bahan bermasalah'}). Tunggu aktivasi rencana pengganti oleh Kepala Dapur."
                ),
            )
        if op_row.operational_status == "SUPERSEDED":
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Pemeriksaan QC rutin diblokir: rencana '{ref.title}' berstatus SUPERSEDED karena telah digantikan rencana aktif terbaru."
                ),
            )
    elif ref.recovery_event_id is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Rencana pengganti '{ref.title}' sudah disetujui tetapi belum diaktifkan (APPROVED_NOT_ACTIVE). "
                "Minta Kepala Dapur mengaktifkan rencana pengganti terlebih dahulu."
            ),
        )
    else:
        scope = derive_production_scope(session, scenario)
        existing_scope_row = session.execute(
            select(OperationalPlanAssignmentORM).where(
                OperationalPlanAssignmentORM.active_scope_key == scope.scope_key
            )
        ).scalar_one_or_none()
        if existing_scope_row is not None and existing_scope_row.menu_review_id != ref.id:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Rencana '{ref.title}' bukan rencana operasional ACTIVE untuk lingkup {scope.scope_label}."
                ),
            )

    menu_review_id_str = ref.id

    if req.previous_inspection_id is not None:
        previous = session.get(QCInspectionORM, str(req.previous_inspection_id))
        if previous is None or previous.kitchen_id != str(auth.kitchen_id):
            raise HTTPException(status_code=404, detail="Pemeriksaan sebelumnya tidak ditemukan.")
        if (
            previous.status != QCInspectionStatusEnum.REVIEWED.value
            or previous.review_outcome not in {
                QCReviewOutcomeEnum.REVISION_REQUIRED.value,
                QCReviewOutcomeEnum.RETAKE_REQUIRED.value,
            }
            or previous.run_id != run.id
            or previous.day_index != req.day_index
        ):
            raise HTTPException(status_code=409, detail="Tindak lanjut harus sesuai rencana dan hari pemeriksaan yang diminta.")

    meal_batch_id_str: Optional[str] = None
    if req.meal_batch_code and req.meal_batch_code.strip():
        batch_code = req.meal_batch_code.strip()
        existing_batch = session.execute(
            select(MealBatchORM).where(
                MealBatchORM.kitchen_id == str(auth.kitchen_id),
                MealBatchORM.batch_code == batch_code,
            )
        ).scalar_one_or_none()
        if existing_batch is not None:
            if (
                existing_batch.run_id != run.id
                or existing_batch.day_index != req.day_index
                or existing_batch.meal_type != scenario.meal_type
            ):
                raise HTTPException(
                    status_code=409, detail="Kode batch sudah dipakai untuk rencana atau hari yang berbeda."
                )
            meal_batch_id_str = existing_batch.id
        else:
            batch = MealBatchORM(
                id=str(uuid4()),
                kitchen_id=str(auth.kitchen_id),
                menu_review_id=menu_review_id_str,
                run_id=run.id,
                day_index=req.day_index,
                meal_type=scenario.meal_type,
                batch_code=batch_code,
                planned_servings=scenario.servings_per_day,
                created_at=datetime.now(timezone.utc),
            )
            session.add(batch)
            session.flush()
            meal_batch_id_str = batch.id

    now = datetime.now(timezone.utc)
    insp = QCInspectionORM(
        id=str(uuid4()),
        kitchen_id=str(auth.kitchen_id),
        menu_review_id=menu_review_id_str,
        run_id=run.id,
        meal_batch_id=meal_batch_id_str,
        day_index=req.day_index,
        status=QCInspectionStatusEnum.CREATED.value,
        created_by_user_id=str(auth.user_id),
        qc_notes=req.qc_notes.strip() if req.qc_notes else None,
        created_at=now,
        updated_at=now,
    )
    session.add(insp)
    record_audit_event(
        session,
        action="qc_inspection.created",
        entity_type="qc_inspection",
        entity_id=insp.id,
        kitchen_id=auth.kitchen_id,
        actor_user_id=auth.user_id,
        actor_role=auth.role.value,
        metadata={
            "run_id": run.id,
            "day_index": req.day_index,
            "previous_inspection_id": str(req.previous_inspection_id) if req.previous_inspection_id else None,
        },
    )
    session.commit()
    reloaded = _load_inspection_orm(session, UUID(insp.id), fresh=True)
    assert reloaded is not None
    return _to_response(session, reloaded)


def list_inspections(
    session: Session,
    auth: AuthContext,
    status_filter: Optional[QCInspectionStatusEnum] = None,
) -> List[QCInspectionResponse]:
    stmt = (
        select(QCInspectionORM)
        .options(
            selectinload(QCInspectionORM.images),
            selectinload(QCInspectionORM.ai_observations),
            selectinload(QCInspectionORM.human_reviews),
        )
        .where(QCInspectionORM.kitchen_id == str(auth.kitchen_id))
        .order_by(QCInspectionORM.updated_at.desc())
    )
    if status_filter is not None:
        stmt = stmt.where(QCInspectionORM.status == status_filter.value)
    rows = list(session.execute(stmt).scalars().all())
    return [_to_response(session, r) for r in rows]


def get_inspection(
    session: Session,
    auth: AuthContext,
    inspection_id: UUID,
) -> QCInspectionResponse:
    row = _load_inspection_orm(session, inspection_id)
    if row is None or row.kitchen_id != str(auth.kitchen_id):
        raise HTTPException(
            status_code=404, detail=f"Pemeriksaan QC '{inspection_id}' tidak ditemukan."
        )
    return _to_response(session, row)


def upload_inspection_image(
    session: Session,
    auth: AuthContext,
    inspection_id: UUID,
    raw_bytes: bytes,
    original_filename: str,
) -> QCImageInfo:
    if auth.role != RoleEnum.QC_OFFICER:
        raise HTTPException(
            status_code=403,
            detail="Hanya Petugas QC (QC_OFFICER) yang dapat mengunggah foto sampel makanan.",
        )

    row = _load_inspection_orm(session, inspection_id)
    if row is None or row.kitchen_id != str(auth.kitchen_id):
        raise HTTPException(
            status_code=404, detail=f"Pemeriksaan QC '{inspection_id}' tidak ditemukan."
        )
    if row.status in {QCInspectionStatusEnum.SUBMITTED.value, QCInspectionStatusEnum.REVIEWED.value}:
        raise HTTPException(
            status_code=409,
            detail="Pemeriksaan yang sudah dikirim atau ditinjau tidak dapat diubah. Buat pemeriksaan baru jika perlu foto ulang.",
        )
    if len(row.images) >= MAX_IMAGES_PER_INSPECTION:
        raise HTTPException(
            status_code=409, detail="Batas 12 foto per pemeriksaan tercapai. Buat pemeriksaan baru."
        )

    try:
        stored = validate_strip_exif_and_store(raw_bytes, original_filename)
    except ImageSecurityError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    now = datetime.now(timezone.utc)
    img_orm = QCImageORM(
        id=str(uuid4()),
        inspection_id=row.id,
        kitchen_id=row.kitchen_id,
        storage_key=stored.storage_key,
        original_filename_sanitized=stored.original_filename_sanitized,
        mime_type=stored.mime_type,
        size_bytes=stored.size_bytes,
        width_px=stored.width_px,
        height_px=stored.height_px,
        sha256=stored.sha256,
        exif_stripped=stored.exif_stripped,
        retention_days=get_qc_retention_days(),
        uploaded_by_user_id=str(auth.user_id),
        created_at=now,
    )
    try:
        _update_inspection(session, row, status=QCInspectionStatusEnum.CREATED.value, updated_at=now)
        session.add(img_orm)
        record_audit_event(
            session,
            action="qc_inspection.image_uploaded",
            entity_type="qc_inspection",
            entity_id=row.id,
            kitchen_id=auth.kitchen_id,
            actor_user_id=auth.user_id,
            actor_role=auth.role.value,
            metadata={
                "image_id": img_orm.id,
                "mime_type": stored.mime_type,
                "size_bytes": stored.size_bytes,
                "sha256": stored.sha256,
                "exif_stripped": stored.exif_stripped,
            },
        )
        session.commit()
    except Exception:
        session.rollback()
        qc_storage_path(stored.storage_key).unlink(missing_ok=True)
        raise

    return QCImageInfo(
        id=UUID(img_orm.id),
        original_filename_sanitized=img_orm.original_filename_sanitized,
        mime_type=img_orm.mime_type,
        size_bytes=img_orm.size_bytes,
        width_px=img_orm.width_px,
        height_px=img_orm.height_px,
        sha256=img_orm.sha256,
        exif_stripped=img_orm.exif_stripped,
        retention_days=img_orm.retention_days,
        uploaded_by_user_id=UUID(img_orm.uploaded_by_user_id),
        created_at=img_orm.created_at,
        expires_at=image_expiry(img_orm.created_at, img_orm.retention_days),
        image_url=f"/api/v1/qc/inspections/{row.id}/images/{img_orm.id}",
    )


def get_authorized_image_bytes(
    session: Session,
    auth: AuthContext,
    inspection_id: UUID,
    image_id: UUID,
) -> tuple[bytes, str]:
    img = session.get(QCImageORM, str(image_id))
    if (
        img is None
        or img.inspection_id != str(inspection_id)
        or img.kitchen_id != str(auth.kitchen_id)
    ):
        raise HTTPException(status_code=404, detail="Gambar QC tidak ditemukan.")
    return _read_active_image(img), img.mime_type


def analyze_inspection_with_ai(
    session: Session,
    auth: AuthContext,
    inspection_id: UUID,
    image_id: Optional[UUID] = None,
    provider_override: Optional[VisionProvider] = None,
) -> QCInspectionResponse:
    if auth.role != RoleEnum.QC_OFFICER:
        raise HTTPException(
            status_code=403,
            detail="Hanya Petugas QC (QC_OFFICER) yang dapat menjalankan analisis Vision AI.",
        )

    row = _load_inspection_orm(session, inspection_id)
    if row is None or row.kitchen_id != str(auth.kitchen_id):
        raise HTTPException(
            status_code=404, detail=f"Pemeriksaan QC '{inspection_id}' tidak ditemukan."
        )
    if row.status in {QCInspectionStatusEnum.SUBMITTED.value, QCInspectionStatusEnum.REVIEWED.value}:
        raise HTTPException(
            status_code=409,
            detail="Pemeriksaan yang sudah dikirim atau ditinjau tidak dapat dianalisis ulang.",
        )

    if not row.images:
        raise HTTPException(
            status_code=422,
            detail="Unggah foto sampel makanan terlebih dahulu sebelum menjalankan pemeriksaan AI.",
        )

    target_img = _latest_image(row)
    if image_id is not None and target_img.id != str(image_id):
        if not any(image.id == str(image_id) for image in row.images):
            raise HTTPException(status_code=404, detail="Foto yang dipilih tidak ditemukan pada pemeriksaan ini.")
        raise HTTPException(status_code=409, detail="Foto sampel sudah diganti. Analisis foto terbaru.")

    try:
        provider = provider_override or resolve_vision_provider()
    except VisionProviderUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    vision_rate_limiter.check(
        auth.user_id, detail="Terlalu banyak permintaan analisis. Tunggu sebentar, lalu coba lagi."
    )
    img_bytes = _read_active_image(target_img)
    expected_menu = _load_expected_menu(session, row.run_id, row.day_index)
    try:
        exec_res = provider.analyze_food_tray(
            image_bytes=img_bytes,
            mime_type=target_img.mime_type,
            expected_menu=expected_menu,
        )
    except VisionOutputValidationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except VisionProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    findings = compare_expected_menu_with_observations(expected_menu, exec_res.validated_output)

    now = datetime.now(timezone.utc)
    obs = QCAIObservationORM(
        id=str(uuid4()),
        inspection_id=row.id,
        image_id=target_img.id,
        provider_name=exec_res.provider_name,
        provider_mode=exec_res.provider_mode,
        is_live_ai=exec_res.is_live_ai,
        model_identifier=exec_res.model_identifier,
        prompt_version=exec_res.prompt_version,
        raw_response_json=exec_res.raw_response,
        validated_output_json=exec_res.validated_output.model_dump(mode="json"),
        comparison_findings_json=[f.model_dump(mode="json") for f in findings],
        latency_ms=exec_res.latency_ms,
        created_at=now,
    )
    _update_inspection(session, row, status=QCInspectionStatusEnum.AI_ANALYZED.value, updated_at=now)
    session.add(obs)

    record_audit_event(
        session,
        action="qc_inspection.ai_analyzed",
        entity_type="qc_inspection",
        entity_id=row.id,
        kitchen_id=auth.kitchen_id,
        actor_user_id=auth.user_id,
        actor_role=auth.role.value,
        metadata={
            "observation_id": obs.id,
            "image_id": target_img.id,
            "provider_name": exec_res.provider_name,
            "provider_mode": exec_res.provider_mode,
            "is_live_ai": exec_res.is_live_ai,
            "model_identifier": exec_res.model_identifier,
            "latency_ms": exec_res.latency_ms,
        },
    )
    session.commit()

    reloaded = _load_inspection_orm(session, inspection_id, fresh=True)
    assert reloaded is not None
    return _to_response(session, reloaded)


def save_human_observations_review(
    session: Session,
    auth: AuthContext,
    inspection_id: UUID,
    req: QCObservationsPatchRequest,
) -> QCInspectionResponse:
    if auth.role != RoleEnum.QC_OFFICER:
        raise HTTPException(
            status_code=403,
            detail="Hanya Petugas QC (QC_OFFICER) yang dapat mengonfirmasi atau mengoreksi observasi AI.",
        )

    row = _load_inspection_orm(session, inspection_id)
    if row is None or row.kitchen_id != str(auth.kitchen_id):
        raise HTTPException(
            status_code=404, detail=f"Pemeriksaan QC '{inspection_id}' tidak ditemukan."
        )
    if row.status in {QCInspectionStatusEnum.SUBMITTED.value, QCInspectionStatusEnum.REVIEWED.value}:
        raise HTTPException(
            status_code=409,
            detail="Observasi tidak dapat diubah setelah pemeriksaan dikirim atau ditinjau.",
        )
    latest_img = _latest_image(row)
    if not row.images or latest_img is None:
        raise HTTPException(
            status_code=409,
            detail="Unggah foto sajian terlebih dahulu sebelum menyimpan pemeriksaan manual.",
        )

    latest_ai = max(
        row.ai_observations,
        key=lambda observation: (observation.created_at, observation.id),
        default=None,
    )
    matched_ai = (
        latest_ai if (latest_ai is not None and latest_ai.image_id == latest_img.id) else None
    )
    if req.ai_observation_id is not None and (
        matched_ai is None or str(req.ai_observation_id) != matched_ai.id
    ):
        raise HTTPException(
            status_code=409,
            detail="Analisis foto sudah berubah. Periksa hasil foto terbaru.",
        )
    allowed_slots = {slot.slot for slot in _load_expected_menu(session, row.run_id, row.day_index)}
    corrected_slots = {component.slot for component in req.corrected_components}
    if not corrected_slots <= allowed_slots or len(corrected_slots) != len(req.corrected_components):
        raise HTTPException(status_code=422, detail="Setiap komponen tinjauan harus unik dan termasuk dalam rencana.")
    now = datetime.now(timezone.utc)

    # Preserve optional original AI observation; store human review in separate append-only table
    human_review = QCHumanReviewORM(
        id=str(uuid4()),
        inspection_id=row.id,
        ai_observation_id=matched_ai.id if matched_ai is not None else None,
        reviewer_user_id=str(auth.user_id),
        corrected_components_json=[c.model_dump(mode="json") for c in req.corrected_components],
        notes=req.notes.strip() if req.notes else None,
        request_retake=req.request_retake,
        created_at=now,
    )
    _update_inspection(
        session,
        row,
        qc_notes=(req.notes.strip() or None) if req.notes is not None else row.qc_notes,
        status=QCInspectionStatusEnum.HUMAN_REVIEWED.value,
        updated_at=now,
    )
    session.add(human_review)

    record_audit_event(
        session,
        action="qc_inspection.human_reviewed",
        entity_type="qc_inspection",
        entity_id=row.id,
        kitchen_id=auth.kitchen_id,
        actor_user_id=auth.user_id,
        actor_role=auth.role.value,
        metadata={
            "human_review_id": human_review.id,
            "ai_observation_id": matched_ai.id if matched_ai is not None else None,
            "manual_without_ai": matched_ai is None,
            "corrected_count": len(req.corrected_components),
            "request_retake": req.request_retake,
        },
    )
    session.commit()

    reloaded = _load_inspection_orm(session, inspection_id, fresh=True)
    assert reloaded is not None
    return _to_response(session, reloaded)


def submit_inspection(
    session: Session,
    auth: AuthContext,
    inspection_id: UUID,
    req: Optional[QCSubmitRequest] = None,
) -> QCInspectionResponse:
    if auth.role != RoleEnum.QC_OFFICER:
        raise HTTPException(
            status_code=403,
            detail="Hanya Petugas QC (QC_OFFICER) yang dapat mengirim laporan pemeriksaan QC.",
        )

    row = _load_inspection_orm(session, inspection_id)
    if row is None or row.kitchen_id != str(auth.kitchen_id):
        raise HTTPException(
            status_code=404, detail=f"Pemeriksaan QC '{inspection_id}' tidak ditemukan."
        )

    if row.status != QCInspectionStatusEnum.HUMAN_REVIEWED.value:
        raise HTTPException(
            status_code=409,
            detail=(
                "Pemeriksaan QC wajib melalui konfirmasi/koreksi manusia (HUMAN_REVIEWED) "
                f"sebelum dikirim (status saat ini: {row.status})."
            ),
        )

    latest_img = _latest_image(row)
    latest_ai = max(
        row.ai_observations,
        key=lambda observation: (observation.created_at, observation.id),
        default=None,
    )
    latest_review = max(
        row.human_reviews,
        key=lambda review: (review.created_at, review.id),
        default=None,
    )
    if (
        not row.images
        or latest_img is None
        or latest_review is None
        or latest_review.created_at < latest_img.created_at
    ):
        raise HTTPException(
            status_code=409,
            detail="Tinjau hasil foto sajian terbaru sebelum mengirim laporan.",
        )
    if (
        latest_ai is not None
        and latest_ai.image_id == latest_img.id
        and latest_review.ai_observation_id is not None
        and latest_review.ai_observation_id != latest_ai.id
    ):
        raise HTTPException(
            status_code=409,
            detail="Tinjau hasil analisis foto terbaru sebelum mengirim laporan.",
        )
    now = datetime.now(timezone.utc)
    _update_inspection(
        session,
        row,
        qc_notes=(req.qc_notes.strip() or None) if req and req.qc_notes is not None else row.qc_notes,
        status=QCInspectionStatusEnum.SUBMITTED.value,
        submitted_by_user_id=str(auth.user_id),
        submitted_at=now,
        updated_at=now,
    )

    record_audit_event(
        session,
        action="qc_inspection.submitted",
        entity_type="qc_inspection",
        entity_id=row.id,
        kitchen_id=auth.kitchen_id,
        actor_user_id=auth.user_id,
        actor_role=auth.role.value,
        metadata={"run_id": row.run_id, "day_index": row.day_index},
    )
    session.commit()

    reloaded = _load_inspection_orm(session, inspection_id, fresh=True)
    assert reloaded is not None
    return _to_response(session, reloaded)


def manager_review_inspection(
    session: Session,
    auth: AuthContext,
    inspection_id: UUID,
    req: QCManagerReviewRequest,
) -> QCInspectionResponse:
    if auth.role != RoleEnum.KITCHEN_MANAGER:
        raise HTTPException(
            status_code=403,
            detail="Hanya Kepala Dapur (KITCHEN_MANAGER) yang dapat meninjau laporan QC.",
        )

    row = _load_inspection_orm(session, inspection_id)
    if row is None or row.kitchen_id != str(auth.kitchen_id):
        raise HTTPException(
            status_code=404, detail=f"Pemeriksaan QC '{inspection_id}' tidak ditemukan."
        )

    if row.status != QCInspectionStatusEnum.SUBMITTED.value:
        raise HTTPException(
            status_code=409,
            detail=f"Hanya pemeriksaan berstatus SUBMITTED yang dapat ditinjau Kepala Dapur (status saat ini: {row.status}).",
        )

    # Separation of duties
    if row.submitted_by_user_id == str(auth.user_id) or row.created_by_user_id == str(auth.user_id):
        raise HTTPException(
            status_code=403,
            detail="Petugas yang mengirim pemeriksaan tidak dapat meninjau pemeriksaannya sendiri.",
        )

    notes = req.manager_notes.strip() if req.manager_notes else None
    if req.outcome in {
        QCReviewOutcomeEnum.REVISION_REQUIRED,
        QCReviewOutcomeEnum.RETAKE_REQUIRED,
    } and not notes:
        raise HTTPException(
            status_code=422,
            detail="Catatan Kepala Dapur wajib diisi saat meminta revisi atau foto ulang.",
        )

    now = datetime.now(timezone.utc)
    _update_inspection(
        session,
        row,
        status=QCInspectionStatusEnum.REVIEWED.value,
        review_outcome=req.outcome.value,
        manager_notes=notes,
        reviewed_by_user_id=str(auth.user_id),
        reviewed_at=now,
        updated_at=now,
    )

    record_audit_event(
        session,
        action=f"qc_inspection.reviewed_{req.outcome.value.lower()}",
        entity_type="qc_inspection",
        entity_id=row.id,
        kitchen_id=auth.kitchen_id,
        actor_user_id=auth.user_id,
        actor_role=auth.role.value,
        metadata={"outcome": req.outcome.value, "has_notes": bool(notes)},
    )
    session.commit()

    reloaded = _load_inspection_orm(session, inspection_id, fresh=True)
    assert reloaded is not None
    return _to_response(session, reloaded)
