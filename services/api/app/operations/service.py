from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.dependencies import AuthContext, record_audit_event
from app.auth.schemas import RoleEnum
from app.db.models import (
    IngredientIncidentORM,
    IncidentActionORM,
    MenuReviewRecordORM,
    NutritionTargetORM,
    OperationalPlanAssignmentORM,
    OptimizationRunORM,
    RecoveryEventORM,
    RunAssignmentORM,
    RunMaterialUsageORM,
    ScenarioORM,
    StockReservationORM,
    UserORM,
)
from app.inventory.service import compute_usable_inventory
from app.operations.schemas import (
    ActivateReplacementPlanRequest,
    EffectiveOperationalPlanResponse,
    OperationalPlanAssignmentResponse,
    OperationalPlanStateEnum,
    OperationalPlanStatusEnum,
    ProductionScopeInfo,
)
from app.recovery.snapshot import compute_usable_inventory_sha256


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _user_name(session: Session, user_id: Optional[str]) -> Optional[str]:
    if not user_id:
        return None
    u = session.get(UserORM, user_id)
    return u.full_name if u else None


def _root_scenario_id(session: Session, scenario: ScenarioORM) -> str:
    curr = scenario
    seen = {curr.id}
    for _ in range(10):
        if not curr.parent_scenario_id or curr.parent_scenario_id in seen:
            break
        parent = session.get(ScenarioORM, curr.parent_scenario_id)
        if parent is None:
            break
        seen.add(parent.id)
        curr = parent
    return curr.id


def derive_production_scope(
    session: Session,
    scenario: ScenarioORM,
    *,
    batch_label: Optional[str] = None,
) -> ProductionScopeInfo:
    """Compute a deterministic, collision-safe operational scope for uniqueness."""
    prod_dt = scenario.production_date or scenario.created_at
    prod_date = prod_dt.date() if isinstance(prod_dt, datetime) else prod_dt
    target = session.get(NutritionTargetORM, scenario.target_id)
    cohort = (target.cohort if target else "DEFAULT").strip() or "DEFAULT"
    meal_type = (scenario.meal_type or "lunch").strip().lower() or "lunch"

    if batch_label and batch_label.strip():
        batch = batch_label.strip()
    elif scenario.production_date is None:
        # Unscheduled legacy/test runs isolate by root scenario lineage so separate tests remain independent
        # while clones/recovery runs of the same baseline still share a single unique scope.
        root_id = _root_scenario_id(session, scenario)
        batch = f"SC-{root_id[:8]}"
    else:
        batch = "DEFAULT"

    scope_key = f"{scenario.kitchen_id or 'NONE'}|{prod_date.isoformat()}|{meal_type}|{cohort}|{batch}"
    scope_label = f"{prod_date.isoformat()} • {meal_type} • {cohort}" + (
        f" • {batch}" if batch != "DEFAULT" else ""
    )
    return ProductionScopeInfo(
        kitchen_id=UUID(scenario.kitchen_id),
        production_date=prod_date,
        horizon_days=int(scenario.days),
        meal_type=meal_type,
        target_cohort=cohort,
        batch_label=batch,
        scope_key=scope_key,
        scope_label=scope_label,
    )


def _to_assignment_response(
    session: Session,
    row: OperationalPlanAssignmentORM,
    *,
    live_sha_cache: Optional[Dict[Tuple[str, str, date], Tuple[str, bool]]] = None,
) -> OperationalPlanAssignmentResponse:
    rev = session.get(MenuReviewRecordORM, row.menu_review_id)
    run = session.get(OptimizationRunORM, row.run_id)
    sc = session.get(ScenarioORM, row.scenario_id)

    horizon = int(row.horizon_days or (sc.days if sc else 5))
    servings_per_day = int(sc.servings_per_day if sc else 100)
    total_servings = max(1, horizon * servings_per_day)

    slot_count = len(
        session.execute(
            select(RunAssignmentORM.day_index, RunAssignmentORM.slot).where(
                RunAssignmentORM.run_id == row.run_id
            )
        ).all()
    )

    total_cost = float(run.objective_total_idr) if run and run.objective_total_idr is not None else None
    cost_per_serv = (
        round(total_cost / total_servings, 2)
        if total_cost is not None
        else (
            float(run.cost_per_serving_average_idr)
            if run and run.cost_per_serving_average_idr is not None
            else None
        )
    )
    cost_per_day = (
        round(total_cost / max(1, horizon), 2) if total_cost is not None else None
    )

    scope_key = (
        f"{row.kitchen_id}|{row.production_date.isoformat()}|{row.meal_type}|{row.target_cohort}|{row.batch_label}"
    )
    scope_label = f"{row.production_date.isoformat()} • {row.meal_type} • {row.target_cohort}" + (
        f" • {row.batch_label}" if row.batch_label and row.batch_label != "DEFAULT" else ""
    )

    is_stale = False
    has_live_shortage = False
    cache_key = (row.kitchen_id, row.dataset_version_id, row.production_date)
    if row.operational_status in {"ACTIVE", "ON_HOLD"}:
        if live_sha_cache is not None and cache_key in live_sha_cache:
            live_sha, has_live_shortage = live_sha_cache[cache_key]
        else:
            prod_dt = datetime(
                row.production_date.year,
                row.production_date.month,
                row.production_date.day,
                8,
                0,
                tzinfo=timezone.utc,
            )
            avail = compute_usable_inventory(
                session,
                kitchen_id=UUID(row.kitchen_id),
                dataset_version_id=UUID(row.dataset_version_id),
                production_date=prod_dt,
            )
            live_sha = compute_usable_inventory_sha256(avail)
            avail_by_code = {i.ingredient_code: i for i in avail.items}
            usages = list(
                session.execute(
                    select(RunMaterialUsageORM).where(RunMaterialUsageORM.run_id == row.run_id)
                )
                .scalars()
                .all()
            )
            for u in usages:
                item = avail_by_code.get(u.ingredient_code)
                if (
                    item is None
                    or item.usable_raw_g is None
                    or item.usable_raw_g + 1e-6 < u.used_raw_g
                ):
                    has_live_shortage = True
                    break
            if live_sha_cache is not None:
                live_sha_cache[cache_key] = (live_sha, has_live_shortage)
        if row.inventory_snapshot_sha256 and live_sha != row.inventory_snapshot_sha256:
            is_stale = True

    op_status = OperationalPlanStatusEnum(row.operational_status)
    ready = op_status == OperationalPlanStatusEnum.ACTIVE

    return OperationalPlanAssignmentResponse(
        id=UUID(row.id),
        kitchen_id=UUID(row.kitchen_id),
        dataset_version_id=UUID(row.dataset_version_id),
        menu_review_id=UUID(row.menu_review_id),
        run_id=UUID(row.run_id),
        scenario_id=UUID(row.scenario_id),
        plan_title=rev.title if rev else (sc.name if sc else f"Rencana {row.run_id[:8]}"),
        scenario_name=sc.name if sc else f"Skenario {row.scenario_id[:8]}",
        review_version_number=rev.version_number if rev else 1,
        historical_review_status=rev.status if rev else "APPROVED",
        operational_status=op_status,
        production_date=row.production_date,
        horizon_days=horizon,
        meal_type=row.meal_type,
        target_cohort=row.target_cohort,
        batch_label=row.batch_label,
        scope_key=scope_key,
        scope_label=scope_label,
        supersedes_assignment_id=(
            UUID(row.supersedes_assignment_id) if row.supersedes_assignment_id else None
        ),
        hold_incident_id=UUID(row.hold_incident_id) if row.hold_incident_id else None,
        hold_reason=row.hold_reason,
        held_at=row.held_at,
        activated_by_user_id=(
            UUID(row.activated_by_user_id) if row.activated_by_user_id else None
        ),
        activated_by_name=_user_name(session, row.activated_by_user_id),
        activated_at=row.activated_at,
        superseded_at=row.superseded_at,
        inventory_snapshot_sha256=row.inventory_snapshot_sha256,
        is_stale_inventory=is_stale or has_live_shortage,
        is_ready_for_execution=ready,
        servings_per_day=servings_per_day,
        total_servings=total_servings,
        total_menu_slots=slot_count,
        total_cost_idr=round(total_cost, 2) if total_cost is not None else None,
        cost_per_serving_idr=cost_per_serv,
        cost_per_day_average_idr=cost_per_day,
        simulation_only=run.simulation_only if run else True,
    )


def list_operational_plan_assignments(
    session: Session,
    kitchen_id: UUID,
    *,
    dataset_version_id: Optional[UUID] = None,
    include_superseded: bool = True,
) -> List[OperationalPlanAssignmentResponse]:
    stmt = (
        select(OperationalPlanAssignmentORM)
        .where(OperationalPlanAssignmentORM.kitchen_id == str(kitchen_id))
        .order_by(
            OperationalPlanAssignmentORM.production_date.desc(),
            OperationalPlanAssignmentORM.updated_at.desc(),
            OperationalPlanAssignmentORM.activated_at.desc(),
        )
    )
    if dataset_version_id is not None:
        stmt = stmt.where(
            OperationalPlanAssignmentORM.dataset_version_id == str(dataset_version_id)
        )
    if not include_superseded:
        stmt = stmt.where(
            OperationalPlanAssignmentORM.operational_status.in_(["ACTIVE", "ON_HOLD"])
        )
    rows = list(session.execute(stmt).scalars().all())
    cache: Dict[Tuple[str, str, date], Tuple[str, bool]] = {}
    return [_to_assignment_response(session, r, live_sha_cache=cache) for r in rows]


def get_review_operational_state_map(
    session: Session,
    kitchen_id: UUID,
) -> Dict[str, Tuple[OperationalPlanAssignmentORM, str]]:
    """Map menu_review_id -> (latest OperationalPlanAssignmentORM, scope_label)."""
    rows = list(
        session.execute(
            select(OperationalPlanAssignmentORM)
            .where(OperationalPlanAssignmentORM.kitchen_id == str(kitchen_id))
            .order_by(
                OperationalPlanAssignmentORM.activated_at.asc(),
                OperationalPlanAssignmentORM.updated_at.asc(),
            )
        )
        .scalars()
        .all()
    )
    out: Dict[str, Tuple[OperationalPlanAssignmentORM, str]] = {}
    for row in rows:
        label = f"{row.production_date.isoformat()} • {row.meal_type} • {row.target_cohort}" + (
            f" • {row.batch_label}" if row.batch_label and row.batch_label != "DEFAULT" else ""
        )
        out[row.menu_review_id] = (row, label)
    return out


def get_effective_operational_plan(
    session: Session,
    kitchen_id: UUID,
    *,
    production_date: Optional[date] = None,
    meal_type: Optional[str] = None,
    target_cohort: Optional[str] = None,
    batch_label: Optional[str] = None,
    dataset_version_id: Optional[UUID] = None,
) -> EffectiveOperationalPlanResponse:
    """Authoritative single source of truth resolving the effective operational plan for a scope."""
    stmt = (
        select(OperationalPlanAssignmentORM)
        .where(OperationalPlanAssignmentORM.kitchen_id == str(kitchen_id))
        .order_by(
            OperationalPlanAssignmentORM.production_date.desc(),
            OperationalPlanAssignmentORM.updated_at.desc(),
            OperationalPlanAssignmentORM.activated_at.desc(),
        )
    )
    if production_date is not None:
        stmt = stmt.where(OperationalPlanAssignmentORM.production_date == production_date)
    if meal_type is not None:
        stmt = stmt.where(OperationalPlanAssignmentORM.meal_type == meal_type.strip().lower())
    if target_cohort is not None:
        stmt = stmt.where(OperationalPlanAssignmentORM.target_cohort == target_cohort.strip())
    if batch_label is not None:
        stmt = stmt.where(OperationalPlanAssignmentORM.batch_label == batch_label.strip())
    if dataset_version_id is not None:
        stmt = stmt.where(
            OperationalPlanAssignmentORM.dataset_version_id == str(dataset_version_id)
        )

    assignments = list(session.execute(stmt).scalars().all())

    rev_stmt = select(MenuReviewRecordORM).where(
        MenuReviewRecordORM.kitchen_id == str(kitchen_id)
    )
    if dataset_version_id is not None:
        rev_stmt = rev_stmt.where(
            MenuReviewRecordORM.dataset_version_id == str(dataset_version_id)
        )
    reviews = list(session.execute(rev_stmt).scalars().all())
    assigned_review_ids = {a.menu_review_id for a in assignments}

    approved_unassigned = [
        UUID(r.id)
        for r in reviews
        if r.status == "APPROVED" and r.id not in assigned_review_ids
    ]
    draft_count = sum(1 for r in reviews if r.status in {"DRAFT", "SUBMITTED"})
    historical_approved_count = sum(1 for r in reviews if r.status == "APPROVED")
    superseded_rows = [a for a in assignments if a.operational_status == "SUPERSEDED"]

    effective_rows = [
        a for a in assignments if a.operational_status in {"ACTIVE", "ON_HOLD"}
    ]
    held_row = next((a for a in effective_rows if a.operational_status == "ON_HOLD"), None)
    active_row = next((a for a in effective_rows if a.operational_status == "ACTIVE"), None)

    # Prefer the most recently updated effective record if both an ON_HOLD and an unrelated scope ACTIVE exist
    primary_row = effective_rows[0] if effective_rows else None
    cache: Dict[Tuple[str, str, date], Tuple[str, bool]] = {}

    if primary_row is not None and primary_row.operational_status == "ON_HOLD":
        held_resp = _to_assignment_response(session, primary_row, live_sha_cache=cache)
        return EffectiveOperationalPlanResponse(
            kitchen_id=kitchen_id,
            state=OperationalPlanStateEnum.ACTIVE_ON_HOLD,
            is_ready_for_execution=False,
            status_message=(
                f"Rencana '{held_resp.plan_title}' sedang DITAHAN (ON_HOLD) terkait insiden bahan pangan "
                f"dan tidak boleh dijalankan hingga rencana pengganti diaktifkan."
            ),
            active_plan=_to_assignment_response(session, active_row, live_sha_cache=cache)
            if active_row and active_row.id != primary_row.id
            else None,
            held_plan=held_resp,
            approved_pending_activation=approved_unassigned,
            superseded_plans_count=len(superseded_rows),
            draft_plans_count=draft_count,
            historical_approved_count=historical_approved_count,
        )

    if active_row is not None:
        active_resp = _to_assignment_response(session, active_row, live_sha_cache=cache)
        return EffectiveOperationalPlanResponse(
            kitchen_id=kitchen_id,
            state=OperationalPlanStateEnum.ACTIVE,
            is_ready_for_execution=not active_resp.is_stale_inventory,
            status_message=(
                f"Rencana operasional aktif untuk {active_resp.scope_label}: '{active_resp.plan_title}'."
                if not active_resp.is_stale_inventory
                else f"Rencana aktif '{active_resp.plan_title}' membutuhkan peninjauan stok/insiden."
            ),
            active_plan=active_resp,
            held_plan=_to_assignment_response(session, held_row, live_sha_cache=cache)
            if held_row
            else None,
            approved_pending_activation=approved_unassigned,
            superseded_plans_count=len(superseded_rows),
            draft_plans_count=draft_count,
            historical_approved_count=historical_approved_count,
        )

    if approved_unassigned:
        return EffectiveOperationalPlanResponse(
            kitchen_id=kitchen_id,
            state=OperationalPlanStateEnum.APPROVED_NOT_ACTIVE,
            is_ready_for_execution=False,
            status_message=(
                "Terdapat rencana yang telah disetujui secara historis tetapi belum diaktifkan pada cakupan operasional ini."
            ),
            approved_pending_activation=approved_unassigned,
            superseded_plans_count=len(superseded_rows),
            draft_plans_count=draft_count,
            historical_approved_count=historical_approved_count,
        )

    if superseded_rows:
        return EffectiveOperationalPlanResponse(
            kitchen_id=kitchen_id,
            state=OperationalPlanStateEnum.SUPERSEDED,
            is_ready_for_execution=False,
            status_message="Seluruh rencana pada cakupan ini berstatus digantikan (SUPERSEDED).",
            superseded_plans_count=len(superseded_rows),
            draft_plans_count=draft_count,
            historical_approved_count=historical_approved_count,
        )

    if draft_count > 0:
        return EffectiveOperationalPlanResponse(
            kitchen_id=kitchen_id,
            state=OperationalPlanStateEnum.DRAFT,
            is_ready_for_execution=False,
            status_message="Baru tersedia draft / pengajuan menunggu persetujuan Kepala Dapur.",
            draft_plans_count=draft_count,
            historical_approved_count=historical_approved_count,
        )

    return EffectiveOperationalPlanResponse(
        kitchen_id=kitchen_id,
        state=OperationalPlanStateEnum.NO_PLAN,
        is_ready_for_execution=False,
        status_message="Belum ada rencana operasional pada cakupan dapur yang dipilih.",
        historical_approved_count=historical_approved_count,
    )


def activate_replacement_plan(
    session: Session,
    auth: AuthContext,
    req: ActivateReplacementPlanRequest,
) -> OperationalPlanAssignmentResponse:
    """Transactionally activate an APPROVED plan for its production scope, superseding prior plan safely."""
    if auth.role != RoleEnum.KITCHEN_MANAGER:
        raise HTTPException(
            status_code=403,
            detail="Hanya Kepala Dapur (KITCHEN_MANAGER) yang berwenang mengaktifkan rencana operasional efektif.",
        )

    if req.idempotency_key:
        existing_idem = session.execute(
            select(OperationalPlanAssignmentORM).where(
                OperationalPlanAssignmentORM.kitchen_id == str(auth.kitchen_id),
                OperationalPlanAssignmentORM.idempotency_key == req.idempotency_key.strip(),
            )
        ).scalar_one_or_none()
        if existing_idem is not None:
            return _to_assignment_response(session, existing_idem)

    review = session.execute(
        select(MenuReviewRecordORM).where(
            MenuReviewRecordORM.id == str(req.menu_review_id),
            MenuReviewRecordORM.kitchen_id == str(auth.kitchen_id),
        )
    ).scalar_one_or_none()
    if review is None:
        raise HTTPException(
            status_code=404,
            detail="Catatan peninjauan menu tidak ditemukan pada dapur Anda.",
        )

    if review.status != "APPROVED":
        raise HTTPException(
            status_code=409,
            detail=(
                f"Rencana berstatus '{review.status}' tidak dapat diaktifkan. "
                "Rencana pengganti wajib disetujui (APPROVED) terlebih dahulu."
            ),
        )

    run = session.get(OptimizationRunORM, review.run_id)
    scenario = session.get(ScenarioORM, review.scenario_id)
    if (
        run is None
        or scenario is None
        or scenario.kitchen_id != str(auth.kitchen_id)
        or not run.validation_passed
        or run.solver_status in {"INFEASIBLE", "ERROR"}
    ):
        raise HTTPException(
            status_code=409,
            detail="Hasil optimasi tidak layak atau gagal verifikasi sehingga tidak dapat diaktifkan.",
        )

    # Validate snapshot freshness & verify no ingredient relies on safety-held or insufficient stock
    prod_dt = scenario.production_date or scenario.created_at
    avail = compute_usable_inventory(
        session,
        kitchen_id=auth.kitchen_id,
        dataset_version_id=UUID(review.dataset_version_id),
        production_date=prod_dt,
    )
    live_sha = compute_usable_inventory_sha256(avail)
    if review.inventory_snapshot_sha256 and live_sha != review.inventory_snapshot_sha256:
        raise HTTPException(
            status_code=409,
            detail=(
                "Snapshot inventaris berubah sejak rencana ini diajukan/disetujui. "
                "Minta Perencana Menu menghitung ulang alternatif pada kondisi stok terbaru sebelum mengaktifkan."
            ),
        )

    avail_by_code = {item.ingredient_code: item for item in avail.items}
    usages = list(
        session.execute(
            select(RunMaterialUsageORM).where(RunMaterialUsageORM.run_id == run.id)
        )
        .scalars()
        .all()
    )
    insufficient: List[str] = []
    for u in usages:
        item = avail_by_code.get(u.ingredient_code)
        if item is None or item.usable_raw_g is None:
            insufficient.append(f"{u.ingredient_name} (UNKNOWN/tidak tersedia)")
        elif item.usable_raw_g + 1e-6 < u.used_raw_g:
            insufficient.append(
                f"{u.ingredient_name} (butuh {u.used_raw_g / 1000.0:.2f} kg, siap pakai {item.usable_raw_g / 1000.0:.2f} kg)"
            )
    if insufficient:
        raise HTTPException(
            status_code=409,
            detail=(
                "Rencana tidak dapat diaktifkan karena bahan masih kurang atau ditahan oleh insiden keselamatan: "
                + "; ".join(insufficient)
            ),
        )

    scope = derive_production_scope(session, scenario, batch_label=req.batch_label)
    now = _utcnow()

    try:
        current_effective = session.execute(
            select(OperationalPlanAssignmentORM).where(
                OperationalPlanAssignmentORM.active_scope_key == scope.scope_key
            )
        ).scalar_one_or_none()

        if (
            req.expected_active_assignment_id is not None
            and current_effective is not None
            and current_effective.id != str(req.expected_active_assignment_id)
        ):
            raise HTTPException(
                status_code=409,
                detail="Rencana operasional aktif telah berubah karena aktivasi paralel lain. Muat ulang dan periksa ulang.",
            )

        if current_effective is not None and current_effective.menu_review_id == review.id:
            if current_effective.operational_status == "ACTIVE":
                return _to_assignment_response(session, current_effective)

        supersedes_id: Optional[str] = None
        if current_effective is not None:
            supersedes_id = current_effective.id
            upd = session.execute(
                update(OperationalPlanAssignmentORM)
                .where(
                    OperationalPlanAssignmentORM.id == current_effective.id,
                    OperationalPlanAssignmentORM.active_scope_key == scope.scope_key,
                )
                .values(
                    operational_status="SUPERSEDED",
                    active_scope_key=None,
                    superseded_at=now,
                    updated_at=now,
                )
            )
            if upd.rowcount != 1:
                raise HTTPException(
                    status_code=409,
                    detail="Konflik perubahan status rencana aktif secara bersamaan. Silakan ulangi.",
                )
            session.flush()
            record_audit_event(
                session,
                action="operational_plan.superseded",
                entity_type="operational_plan",
                entity_id=current_effective.id,
                kitchen_id=auth.kitchen_id,
                actor_user_id=auth.user_id,
                actor_role=auth.role.value,
                metadata={
                    "old_menu_review_id": current_effective.menu_review_id,
                    "replaced_by_review_id": review.id,
                    "scope_key": scope.scope_key,
                },
            )

        new_assign = OperationalPlanAssignmentORM(
            id=str(uuid4()),
            kitchen_id=str(auth.kitchen_id),
            dataset_version_id=review.dataset_version_id,
            menu_review_id=review.id,
            run_id=run.id,
            scenario_id=scenario.id,
            production_date=scope.production_date,
            horizon_days=scope.horizon_days,
            meal_type=scope.meal_type,
            target_cohort=scope.target_cohort,
            batch_label=scope.batch_label,
            operational_status="ACTIVE",
            active_scope_key=scope.scope_key,
            supersedes_assignment_id=supersedes_id,
            hold_incident_id=None,
            hold_reason=None,
            held_at=None,
            activated_by_user_id=str(auth.user_id),
            activated_at=now,
            superseded_at=None,
            inventory_snapshot_sha256=live_sha,
            idempotency_key=req.idempotency_key.strip() if req.idempotency_key else None,
            created_at=now,
            updated_at=now,
        )
        session.add(new_assign)
        session.flush()

        record_audit_event(
            session,
            action="operational_plan.activated",
            entity_type="operational_plan",
            entity_id=new_assign.id,
            kitchen_id=auth.kitchen_id,
            actor_user_id=auth.user_id,
            actor_role=auth.role.value,
            metadata={
                "menu_review_id": review.id,
                "run_id": run.id,
                "scope_key": scope.scope_key,
                "supersedes_assignment_id": supersedes_id,
                "notes": req.notes,
            },
        )

        # Link back to recovery event & incident timeline if applicable
        if review.recovery_event_id:
            rec_ev = session.get(RecoveryEventORM, review.recovery_event_id)
            if rec_ev and rec_ev.incident_id:
                session.add(
                    IncidentActionORM(
                        id=str(uuid4()),
                        incident_id=rec_ev.incident_id,
                        kitchen_id=str(auth.kitchen_id),
                        action_type="PLAN_ACTIVATED",
                        actor_user_id=str(auth.user_id),
                        actor_role=auth.role.value,
                        notes=req.notes
                        or f"Rencana pengganti '{review.title}' diaktifkan untuk {scope.scope_label}.",
                        metadata_json={
                            "assignment_id": new_assign.id,
                            "menu_review_id": review.id,
                            "run_id": run.id,
                            "supersedes_assignment_id": supersedes_id,
                        },
                        created_at=now,
                    )
                )

        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="Konflik aktivasi paralel untuk cakupan produksi yang sama; rencana aktif tidak digandakan.",
        ) from exc

    return _to_assignment_response(session, new_assign)


def place_affected_plans_on_hold(
    session: Session,
    *,
    kitchen_id: UUID,
    dataset_version_id: UUID,
    incident_id: UUID,
    reason: str,
    held_ingredient_codes: List[str],
    held_lot_ids: List[str],
    actor_user_id: Optional[UUID],
    actor_role: Optional[str],
    production_date: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """Immediately hold all ACTIVE operational plans that rely on compromised or short ingredients."""
    avail = compute_usable_inventory(
        session,
        kitchen_id=kitchen_id,
        dataset_version_id=dataset_version_id,
        production_date=production_date,
    )
    avail_by_code = {item.ingredient_code: item for item in avail.items}
    held_code_set = set(held_ingredient_codes)
    held_lot_set = set(held_lot_ids)

    active_plans = list(
        session.execute(
            select(OperationalPlanAssignmentORM).where(
                OperationalPlanAssignmentORM.kitchen_id == str(kitchen_id),
                OperationalPlanAssignmentORM.dataset_version_id == str(dataset_version_id),
                OperationalPlanAssignmentORM.operational_status == "ACTIVE",
            )
        )
        .scalars()
        .all()
    )

    reserved_review_ids = {
        r.menu_review_id
        for r in session.execute(
            select(StockReservationORM).where(
                StockReservationORM.kitchen_id == str(kitchen_id),
                StockReservationORM.dataset_version_id == str(dataset_version_id),
                StockReservationORM.lot_id.in_(held_lot_set) if held_lot_set else False,
                StockReservationORM.status == "ACTIVE",
            )
        )
        .scalars()
        .all()
        if r.menu_review_id
    }

    now = _utcnow()
    affected: List[Dict[str, Any]] = []

    for plan in active_plans:
        usages = list(
            session.execute(
                select(RunMaterialUsageORM).where(RunMaterialUsageORM.run_id == plan.run_id)
            )
            .scalars()
            .all()
        )
        reasons: List[str] = []
        depends_on_held_code = False
        for u in usages:
            if u.ingredient_code not in held_code_set:
                continue
            depends_on_held_code = True
            av = avail_by_code.get(u.ingredient_code)
            if av is None or av.usable_raw_g is None or av.usable_raw_g + 1e-6 < u.used_raw_g:
                avail_kg = 0.0 if (av is None or av.usable_raw_g is None) else av.usable_raw_g / 1000.0
                reasons.append(
                    f"{u.ingredient_name}: butuh {u.used_raw_g / 1000.0:.2f} kg, siap pakai tersisa {avail_kg:.2f} kg"
                )
            else:
                # Lot was held on this ingredient — flag for review even if unaffected verified lots happen to cover kg
                reasons.append(
                    f"{u.ingredient_name}: lot terdampak ditahan (sisa lot bersih terverifikasi {av.usable_raw_g / 1000.0:.2f} kg)"
                )

        if not depends_on_held_code and plan.menu_review_id not in reserved_review_ids:
            continue

        rev = session.get(MenuReviewRecordORM, plan.menu_review_id)
        plan_title = rev.title if rev else f"Rencana {plan.run_id[:8]}"
        hold_msg = f"{reason} ({'; '.join(reasons)})" if reasons else reason

        plan.operational_status = "ON_HOLD"
        plan.hold_incident_id = str(incident_id)
        plan.hold_reason = hold_msg
        plan.held_at = now
        plan.updated_at = now

        record_audit_event(
            session,
            action="operational_plan.placed_on_hold",
            entity_type="operational_plan",
            entity_id=plan.id,
            kitchen_id=kitchen_id,
            actor_user_id=actor_user_id,
            actor_role=actor_role,
            metadata={
                "incident_id": str(incident_id),
                "menu_review_id": plan.menu_review_id,
                "run_id": plan.run_id,
                "reasons": reasons,
            },
        )
        affected.append(
            {
                "assignment_id": plan.id,
                "menu_review_id": plan.menu_review_id,
                "run_id": plan.run_id,
                "title": plan_title,
                "production_date": plan.production_date.isoformat(),
                "operational_status": "ON_HOLD",
                "reasons": reasons,
            }
        )

    return affected
