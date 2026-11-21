from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.auth.dependencies import AuthContext, record_audit_event
from app.auth.schemas import RoleEnum
from app.db.models import (
    MenuReviewRecordORM,
    OperationalPlanAssignmentORM,
    OperationalPlanServiceDateORM,
    OptimizationRunORM,
    RecoveryEventORM,
    RunMaterialUsageORM,
    ScenarioORM,
    UserORM,
)
from app.db.repository import SQLiteVaultRepository
from app.inventory.service import compute_usable_inventory
from app.operations.planning import (
    compute_cross_period_stock_context,
    derive_period_phase,
    extract_scenario_service_dates,
)
from app.operations.service import (
    _date_scope_key,
    check_run_stock_feasibility_across_dates,
    derive_production_scope,
    sync_assignment_service_dates,
)
from app.recovery.snapshot import compute_usable_inventory_sha256
from app.scenarios.service import ResourceNotFoundError
from app.reviews.schemas import (
    MenuReviewCreateRequest,
    MenuReviewDecisionEnum,
    MenuReviewDecisionRequest,
    MenuReviewResponse,
    MenuReviewStatusEnum,
    MenuReviewSubmitRequest,
)


def _user_display_name(session: Session, user_id: Optional[str]) -> Optional[str]:
    if not user_id:
        return None
    u = session.get(UserORM, user_id)
    return u.full_name if u else None


def _to_response(session: Session, row: MenuReviewRecordORM) -> MenuReviewResponse:
    sc = session.get(ScenarioORM, row.scenario_id)
    run = session.get(OptimizationRunORM, row.run_id)
    rec_event = (
        session.get(RecoveryEventORM, row.recovery_event_id)
        if row.recovery_event_id
        else None
    )
    svc_dates = extract_scenario_service_dates(sc) if sc is not None else []
    period_start = svc_dates[0] if svc_dates else None
    period_end = svc_dates[-1] if svc_dates else None
    derived_phase = derive_period_phase(svc_dates)
    cw_meta = ((run.input_snapshot_json or {}).get("_cross_week_meta") or {}) if run else {}

    is_stale = False
    if (
        (row.recovery_event_id or (sc is not None and sc.continuation_of_run_id))
        and row.inventory_snapshot_sha256
        and row.status in {
            MenuReviewStatusEnum.DRAFT.value,
            MenuReviewStatusEnum.SUBMITTED.value,
            MenuReviewStatusEnum.APPROVED.value,
        }
    ):
        live_summary = compute_usable_inventory(
            session,
            kitchen_id=UUID(row.kitchen_id),
            dataset_version_id=UUID(row.dataset_version_id),
            production_date=sc.production_date if sc else None,
        )
        is_stale = compute_usable_inventory_sha256(live_summary) != row.inventory_snapshot_sha256

    changed_slots_count: Optional[int] = None
    if rec_event and rec_event.selected_mode and rec_event.comparison_json:
        key = "min_disruption" if rec_event.selected_mode == "MIN_DISRUPTION" else "min_cost"
        cand_info = rec_event.comparison_json.get(key)
        if isinstance(cand_info, dict) and "changed_slots_count" in cand_info:
            changed_slots_count = int(cand_info["changed_slots_count"])

    days_count = len(svc_dates) if svc_dates else (sc.days if sc else 5)
    servings_per_day = sc.servings_per_day if sc else None
    total_servings = (days_count * servings_per_day) if servings_per_day is not None else None
    cost_per_day_avg = (
        round(float(run.objective_total_idr) / max(1, days_count), 2)
        if run and run.objective_total_idr is not None and days_count > 0
        else None
    )

    op_row = session.execute(
        select(OperationalPlanAssignmentORM)
        .where(OperationalPlanAssignmentORM.menu_review_id == row.id)
        .order_by(OperationalPlanAssignmentORM.updated_at.desc())
    ).scalars().first()
    op_status: Optional[str] = None
    op_assign_id: Optional[UUID] = None
    scope_label: Optional[str] = None
    hold_incident_id: Optional[UUID] = None
    hold_reason: Optional[str] = None
    if op_row is not None:
        op_status = op_row.operational_status
        op_assign_id = UUID(op_row.id)
        hold_incident_id = UUID(op_row.hold_incident_id) if op_row.hold_incident_id else None
        hold_reason = op_row.hold_reason
        p_txt = (
            f"{period_start.isoformat()} s.d. {period_end.isoformat()}"
            if period_start and period_end and period_start != period_end
            else op_row.production_date.isoformat()
        )
        scope_label = f"{p_txt} • {op_row.meal_type} • {op_row.target_cohort}" + (
            f" • {op_row.batch_label}" if op_row.batch_label and op_row.batch_label != "DEFAULT" else ""
        )
    elif row.status == MenuReviewStatusEnum.APPROVED.value:
        op_status = "APPROVED_NOT_ACTIVE"
        if sc is not None and sc.kitchen_id:
            scope_label = derive_production_scope(session, sc).scope_label
    elif sc is not None and sc.kitchen_id:
        scope_label = derive_production_scope(session, sc).scope_label

    return MenuReviewResponse(
        id=UUID(row.id),
        kitchen_id=UUID(row.kitchen_id),
        scenario_id=UUID(row.scenario_id),
        scenario_name=sc.name if sc else f"Skenario {row.scenario_id[:8]}",
        run_id=UUID(row.run_id),
        dataset_version_id=UUID(row.dataset_version_id),
        version_number=row.version_number,
        status=MenuReviewStatusEnum(row.status),
        title=row.title,
        planner_notes=row.planner_notes,
        reviewer_notes=row.reviewer_notes,
        created_by_user_id=UUID(row.created_by_user_id),
        created_by_name=_user_display_name(session, row.created_by_user_id) or "Pengguna",
        submitted_by_user_id=UUID(row.submitted_by_user_id) if row.submitted_by_user_id else None,
        submitted_by_name=_user_display_name(session, row.submitted_by_user_id),
        reviewed_by_user_id=UUID(row.reviewed_by_user_id) if row.reviewed_by_user_id else None,
        reviewed_by_name=_user_display_name(session, row.reviewed_by_user_id),
        submitted_at=row.submitted_at,
        reviewed_at=row.reviewed_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
        cost_per_serving_average_idr=run.cost_per_serving_average_idr if run else None,
        objective_total_idr=run.objective_total_idr if run else None,
        days_count=days_count,
        servings_per_day=servings_per_day,
        total_servings=total_servings,
        cost_per_day_average_idr=cost_per_day_avg,
        simulation_only=run.simulation_only if run else True,
        recovery_event_id=UUID(row.recovery_event_id) if row.recovery_event_id else None,
        inventory_snapshot_sha256=row.inventory_snapshot_sha256,
        is_stale_inventory=is_stale,
        recovery_selected_mode=rec_event.selected_mode if rec_event else None,
        recovery_changed_slots_count=changed_slots_count,
        operational_status=op_status,
        operational_assignment_id=op_assign_id,
        production_scope_label=scope_label,
        service_dates=svc_dates,
        period_start_date=period_start,
        period_end_date=period_end,
        derived_period_phase=derived_phase,
        continuation_of_run_id=(
            UUID(sc.continuation_of_run_id)
            if sc is not None and sc.continuation_of_run_id
            else None
        ),
        stock_confirmation_required=bool(cw_meta.get("stock_confirmation_required", False)),
        stock_confirmation_reason=cw_meta.get("stock_confirmation_reason"),
        hold_incident_id=hold_incident_id,
        hold_reason=hold_reason,
    )


def create_menu_review(
    session: Session,
    auth: AuthContext,
    req: MenuReviewCreateRequest,
    *,
    recovery_event_id: Optional[UUID] = None,
    inventory_snapshot_sha256: Optional[str] = None,
) -> MenuReviewResponse:
    if auth.role != RoleEnum.MENU_PLANNER:
        raise HTTPException(
            status_code=403,
            detail="Hanya Perencana Menu (MENU_PLANNER) yang dapat membuat pengajuan peninjauan rencana menu.",
        )

    run = session.get(OptimizationRunORM, str(req.run_id))
    if run is None:
        raise HTTPException(status_code=404, detail=f"Optimization run '{req.run_id}' tidak ditemukan.")

    scenario = session.get(ScenarioORM, run.scenario_id)
    if scenario is None or scenario.kitchen_id != str(auth.kitchen_id):
        raise HTTPException(
            status_code=404,
            detail=f"Optimization run '{req.run_id}' tidak ditemukan pada dapur Anda.",
        )
    repo = SQLiteVaultRepository(session)
    try:
        repo.get_dataset_orm(UUID(run.dataset_version_id), kitchen_id=auth.kitchen_id)
    except ResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Hasil optimasi tidak tersedia pada dapur Anda.") from exc

    if not run.validation_passed or run.solver_status in {"INFEASIBLE", "ERROR"}:
        raise HTTPException(
            status_code=409,
            detail="Hanya hasil optimasi yang lolos validator independen (layak) yang dapat diajukan untuk peninjauan.",
        )

    # Serialize version allocation for the scenario before reading the current maximum.
    session.execute(
        update(ScenarioORM).where(ScenarioORM.id == scenario.id).values(locked=ScenarioORM.locked)
    )
    prev_max = session.execute(
        select(func.max(MenuReviewRecordORM.version_number)).where(
            MenuReviewRecordORM.kitchen_id == str(auth.kitchen_id),
            MenuReviewRecordORM.scenario_id == scenario.id,
        )
    ).scalar_one_or_none()
    next_version = (prev_max or 0) + 1

    now = datetime.now(timezone.utc)
    rec = MenuReviewRecordORM(
        id=str(uuid4()),
        kitchen_id=str(auth.kitchen_id),
        scenario_id=scenario.id,
        run_id=run.id,
        dataset_version_id=run.dataset_version_id,
        version_number=next_version,
        status=MenuReviewStatusEnum.DRAFT.value,
        title=(req.title.strip() if req.title and req.title.strip() else f"{scenario.name} (v{next_version})"),
        planner_notes=req.planner_notes.strip() if req.planner_notes else None,
        recovery_event_id=str(recovery_event_id) if recovery_event_id else None,
        inventory_snapshot_sha256=inventory_snapshot_sha256,
        created_by_user_id=str(auth.user_id),
        created_at=now,
        updated_at=now,
    )
    session.add(rec)
    record_audit_event(
        session,
        action="menu_review.created",
        entity_type="menu_review",
        entity_id=rec.id,
        kitchen_id=auth.kitchen_id,
        actor_user_id=auth.user_id,
        actor_role=auth.role.value,
        metadata={
            "run_id": run.id,
            "scenario_id": scenario.id,
            "version_number": next_version,
        },
    )
    session.commit()
    return _to_response(session, rec)


def list_menu_reviews(
    session: Session,
    auth: AuthContext,
    status_filter: Optional[MenuReviewStatusEnum] = None,
) -> List[MenuReviewResponse]:
    stmt = (
        select(MenuReviewRecordORM)
        .where(
            MenuReviewRecordORM.kitchen_id == str(auth.kitchen_id),
            MenuReviewRecordORM.dataset_version_id.in_(
                SQLiteVaultRepository(session).visible_dataset_ids(auth.kitchen_id)
            ),
        )
        .order_by(MenuReviewRecordORM.updated_at.desc())
    )
    if status_filter is not None:
        stmt = stmt.where(MenuReviewRecordORM.status == status_filter.value)
    if auth.role == RoleEnum.QC_OFFICER:
        stmt = stmt.where(MenuReviewRecordORM.status == MenuReviewStatusEnum.APPROVED.value)

    rows = list(session.execute(stmt).scalars().all())
    return [_to_response(session, r) for r in rows]


def get_menu_review(
    session: Session,
    auth: AuthContext,
    review_id: UUID,
) -> MenuReviewResponse:
    row = _find_menu_review(session, auth, review_id)
    if auth.role == RoleEnum.QC_OFFICER and row.status != MenuReviewStatusEnum.APPROVED.value:
        raise HTTPException(
            status_code=404, detail=f"Rencana menu '{review_id}' belum tersedia untuk pemeriksaan."
        )
    return _to_response(session, row)


def _find_menu_review(session: Session, auth: AuthContext, review_id: UUID) -> MenuReviewRecordORM:
    row = session.execute(
        select(MenuReviewRecordORM).where(
            MenuReviewRecordORM.id == str(review_id),
            MenuReviewRecordORM.kitchen_id == str(auth.kitchen_id),
            MenuReviewRecordORM.dataset_version_id.in_(
                SQLiteVaultRepository(session).visible_dataset_ids(auth.kitchen_id)
            ),
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=404, detail=f"Catatan peninjauan menu '{review_id}' tidak ditemukan."
        )
    return row


def _transition_review(
    session: Session, row: MenuReviewRecordORM, expected: MenuReviewStatusEnum, **values
) -> None:
    result = session.execute(
        update(MenuReviewRecordORM)
        .where(MenuReviewRecordORM.id == row.id, MenuReviewRecordORM.status == expected.value)
        .values(**values)
    )
    if result.rowcount != 1:
        raise HTTPException(
            status_code=409, detail="Status pengajuan sudah berubah. Muat ulang sebelum mencoba lagi."
        )


def submit_menu_review(
    session: Session,
    auth: AuthContext,
    review_id: UUID,
    req: Optional[MenuReviewSubmitRequest] = None,
) -> MenuReviewResponse:
    if auth.role != RoleEnum.MENU_PLANNER:
        raise HTTPException(
            status_code=403,
            detail="Hanya Perencana Menu (MENU_PLANNER) yang dapat mengajukan peninjauan rencana menu.",
        )

    row = _find_menu_review(session, auth, review_id)

    if row.status != MenuReviewStatusEnum.DRAFT.value:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Peninjauan berstatus '{row.status}' tidak dapat diajukan ulang secara langsung. "
                "Buat catatan peninjauan baru untuk menjaga riwayat versi."
            ),
        )

    run = session.get(OptimizationRunORM, row.run_id)
    if run is None or not run.validation_passed:
        raise HTTPException(
            status_code=409,
            detail="Rencana menu tidak valid atau tidak lolos validator independen.",
        )

    now = datetime.now(timezone.utc)
    notes = req.planner_notes.strip() or None if req and req.planner_notes is not None else row.planner_notes
    _transition_review(
        session, row, MenuReviewStatusEnum.DRAFT,
        status=MenuReviewStatusEnum.SUBMITTED.value, planner_notes=notes,
        submitted_by_user_id=str(auth.user_id), submitted_at=now, updated_at=now,
    )
    if row.recovery_event_id:
        rec_event = session.get(RecoveryEventORM, row.recovery_event_id)
        if rec_event is not None:
            rec_event.status = "SUBMITTED"
            rec_event.updated_at = now

    record_audit_event(
        session,
        action="menu_review.submitted",
        entity_type="menu_review",
        entity_id=row.id,
        kitchen_id=auth.kitchen_id,
        actor_user_id=auth.user_id,
        actor_role=auth.role.value,
        metadata={"run_id": row.run_id, "version_number": row.version_number},
    )
    session.commit()
    return _to_response(session, row)


def review_menu_plan(
    session: Session,
    auth: AuthContext,
    review_id: UUID,
    req: MenuReviewDecisionRequest,
) -> MenuReviewResponse:
    if auth.role != RoleEnum.KITCHEN_MANAGER:
        raise HTTPException(
            status_code=403,
            detail="Hanya Kepala Dapur (KITCHEN_MANAGER) yang berwenang meninjau rencana menu.",
        )

    row = _find_menu_review(session, auth, review_id)

    if row.status != MenuReviewStatusEnum.SUBMITTED.value:
        raise HTTPException(
            status_code=409,
            detail=f"Hanya pengajuan berstatus SUBMITTED yang dapat ditinjau (status saat ini: {row.status}).",
        )

    # Separation of duties: prevent self-approval
    if row.submitted_by_user_id == str(auth.user_id) or row.created_by_user_id == str(auth.user_id):
        raise HTTPException(
            status_code=403,
            detail="Pembuat/pengaju rencana tidak diperbolehkan menyetujui pengajuannya sendiri.",
        )

    notes = req.reviewer_notes.strip() if req.reviewer_notes else None
    if req.decision == MenuReviewDecisionEnum.REVISION_REQUIRED and not notes:
        raise HTTPException(
            status_code=422,
            detail="Catatan revisi wajib diisi saat meminta revisi rencana menu.",
        )

    live_sha: Optional[str] = None
    sc = session.get(ScenarioORM, row.scenario_id)
    svc_dates = extract_scenario_service_dates(sc) if sc is not None else []
    if req.decision == MenuReviewDecisionEnum.APPROVED:
        if svc_dates and sc is not None:
            stock_ctx = compute_cross_period_stock_context(
                session,
                kitchen_id=UUID(row.kitchen_id),
                dataset_version_id=UUID(row.dataset_version_id),
                service_dates=svc_dates,
            )
            live_summary = stock_ctx.base_availability
            live_sha = compute_usable_inventory_sha256(live_summary)
            if (
                row.recovery_event_id
                and row.inventory_snapshot_sha256
                and live_sha != row.inventory_snapshot_sha256
            ):
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Snapshot inventaris telah berubah sejak usulan rencana pengganti diajukan. "
                        "Persetujuan diblokir (409 Stale Snapshot); minta Perencana Menu menghitung ulang rencana pengganti."
                    ),
                )
            shortages = check_run_stock_feasibility_across_dates(
                session,
                run_id=row.run_id,
                servings_per_day=int(sc.servings_per_day),
                service_dates=svc_dates,
                stock_ctx=stock_ctx,
            )
        else:
            live_summary = compute_usable_inventory(
                session,
                kitchen_id=UUID(row.kitchen_id),
                dataset_version_id=UUID(row.dataset_version_id),
                production_date=sc.production_date if sc else None,
            )
            live_sha = compute_usable_inventory_sha256(live_summary)
            if (
                row.recovery_event_id
                and row.inventory_snapshot_sha256
                and live_sha != row.inventory_snapshot_sha256
            ):
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Snapshot inventaris telah berubah sejak usulan rencana pengganti diajukan. "
                        "Persetujuan diblokir (409 Stale Snapshot); minta Perencana Menu menghitung ulang rencana pengganti."
                    ),
                )
            avail_by_code = {item.ingredient_code: item for item in live_summary.items}
            usages = list(
                session.execute(
                    select(RunMaterialUsageORM).where(RunMaterialUsageORM.run_id == row.run_id)
                )
                .scalars()
                .all()
            )
            shortages = []
            for u in usages:
                av = avail_by_code.get(u.ingredient_code)
                if av is None or av.usable_raw_g is None or av.usable_raw_g + 1e-6 < u.used_raw_g:
                    avail_kg = (
                        0.0
                        if (av is None or av.usable_raw_g is None)
                        else av.usable_raw_g / 1000.0
                    )
                    if av is not None and (
                        av.safety_held_raw_g > 0 or av.rejected_disposed_raw_g > 0
                    ):
                        shortages.append(
                            f"{u.ingredient_name} (SAFETY HOLD; sisa bersih {avail_kg:.2f} kg, butuh {u.used_raw_g / 1000.0:.2f} kg)"
                        )
                    else:
                        shortages.append(
                            f"{u.ingredient_name} (siap pakai {avail_kg:.2f} kg, butuh {u.used_raw_g / 1000.0:.2f} kg)"
                        )
        if shortages:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Persetujuan diblokir karena stok layak pakai terbaru tidak mencukupi atau sedang ditahan keamanan: "
                    + "; ".join(shortages)
                    + ". Hitung ulang atau pilih rencana pengganti yang layak."
                ),
            )

    now = datetime.now(timezone.utc)
    transition_values = dict(
        status=req.decision.value,
        reviewer_notes=notes,
        reviewed_by_user_id=str(auth.user_id),
        reviewed_at=now,
        updated_at=now,
    )
    if (
        req.decision == MenuReviewDecisionEnum.APPROVED
        and not row.inventory_snapshot_sha256
        and live_sha is not None
    ):
        transition_values["inventory_snapshot_sha256"] = live_sha

    _transition_review(
        session, row, MenuReviewStatusEnum.SUBMITTED,
        **transition_values,
    )
    if row.recovery_event_id:
        rec_event = session.get(RecoveryEventORM, row.recovery_event_id)
        if rec_event is not None:
            rec_event.status = req.decision.value
            rec_event.updated_at = now

    if req.decision == MenuReviewDecisionEnum.APPROVED and sc is not None and sc.kitchen_id:
        scope = derive_production_scope(session, sc)
        eff_dates = scope.service_dates or svc_dates
        existing_active = session.execute(
            select(OperationalPlanAssignmentORM).where(
                OperationalPlanAssignmentORM.active_scope_key == scope.scope_key
            )
        ).scalar_one_or_none()
        date_keys = [
            _date_scope_key(
                row.kitchen_id, d, scope.meal_type, scope.target_cohort, scope.batch_label
            )
            for d in eff_dates
        ]
        overlapping_date = (
            session.execute(
                select(OperationalPlanServiceDateORM.id).where(
                    OperationalPlanServiceDateORM.active_date_scope_key.in_(date_keys)
                )
            )
            .scalars()
            .first()
            if date_keys
            else None
        )
        # Never auto-activate recovery replacements, next-week continuation plans, or overlapping dates
        if (
            existing_active is None
            and row.recovery_event_id is None
            and sc.continuation_of_run_id is None
            and overlapping_date is None
        ):
            new_assign = OperationalPlanAssignmentORM(
                id=str(uuid4()),
                kitchen_id=row.kitchen_id,
                dataset_version_id=row.dataset_version_id,
                menu_review_id=row.id,
                run_id=row.run_id,
                scenario_id=row.scenario_id,
                operational_status="ACTIVE",
                production_date=scope.production_date,
                horizon_days=len(eff_dates) if eff_dates else scope.horizon_days,
                service_dates_json=[d.isoformat() for d in eff_dates] if eff_dates else None,
                meal_type=scope.meal_type,
                target_cohort=scope.target_cohort,
                batch_label=scope.batch_label,
                active_scope_key=scope.scope_key,
                supersedes_assignment_id=None,
                hold_incident_id=None,
                hold_reason=None,
                held_at=None,
                activated_by_user_id=str(auth.user_id),
                activated_at=now,
                superseded_at=None,
                inventory_snapshot_sha256=live_sha,
                created_at=now,
                updated_at=now,
            )
            session.add(new_assign)
            session.flush()
            if eff_dates:
                sync_assignment_service_dates(session, new_assign, eff_dates, is_effective=True)

    record_audit_event(
        session,
        action=f"menu_review.{req.decision.value.lower()}",
        entity_type="menu_review",
        entity_id=row.id,
        kitchen_id=auth.kitchen_id,
        actor_user_id=auth.user_id,
        actor_role=auth.role.value,
        metadata={
            "run_id": row.run_id,
            "decision": req.decision.value,
            "has_notes": bool(notes),
        },
    )
    session.commit()
    return _to_response(session, row)
