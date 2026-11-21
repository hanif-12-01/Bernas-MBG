from __future__ import annotations

from datetime import date, datetime, timezone
from typing import List, Optional, Tuple
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import AuthContext, record_audit_event
from app.auth.schemas import RoleEnum
from app.db.models import (
    MenuReviewRecordORM,
    NutritionTargetORM,
    OperationalPlanAssignmentORM,
    OptimizationRunORM,
    ScenarioORM,
)
from app.db.repository import SQLiteVaultRepository
from app.domain.models.schemas import ScenarioCreateRequest, SourceTypeEnum
from app.operations.planning import (
    NextWeekDefaultsResponse,
    PrepareNextWeekRequest,
    PrepareNextWeekResponse,
    collect_previous_menu_history,
    compute_cross_period_stock_context,
    extract_assignment_service_dates,
    extract_scenario_service_dates,
    suggest_next_week_service_dates,
)
from app.recovery.snapshot import compute_usable_inventory_sha256
from app.reviews.schemas import MenuReviewCreateRequest
from app.reviews.service import create_menu_review
from app.scenarios.service import ResourceNotFoundError


def _resolve_source_plan(
    session: Session,
    auth: AuthContext,
    *,
    source_run_id: Optional[UUID] = None,
    source_assignment_id: Optional[UUID] = None,
) -> Tuple[Optional[OperationalPlanAssignmentORM], Optional[OptimizationRunORM], Optional[ScenarioORM], Optional[str]]:
    """Locate the authoritative previous plan/run to continue from (never crossing kitchens)."""
    assign: Optional[OperationalPlanAssignmentORM] = None
    run: Optional[OptimizationRunORM] = None
    sc: Optional[ScenarioORM] = None
    title: Optional[str] = None

    if source_assignment_id is not None:
        assign = session.execute(
            select(OperationalPlanAssignmentORM).where(
                OperationalPlanAssignmentORM.id == str(source_assignment_id),
                OperationalPlanAssignmentORM.kitchen_id == str(auth.kitchen_id),
            )
        ).scalar_one_or_none()
        if assign is None:
            raise HTTPException(
                status_code=404, detail="Rencana operasional sumber tidak ditemukan pada dapur ini."
            )
        run = session.get(OptimizationRunORM, assign.run_id)
        sc = session.get(ScenarioORM, assign.scenario_id)
        rev = session.get(MenuReviewRecordORM, assign.menu_review_id)
        title = rev.title if rev else (sc.name if sc else None)
        return assign, run, sc, title

    if source_run_id is not None:
        run = session.get(OptimizationRunORM, str(source_run_id))
        if run is None:
            raise HTTPException(status_code=404, detail="Run rencana sumber tidak ditemukan.")
        sc = session.get(ScenarioORM, run.scenario_id)
        if sc is None or sc.kitchen_id != str(auth.kitchen_id):
            raise HTTPException(
                status_code=404, detail="Run rencana sumber tidak ditemukan pada dapur ini."
            )
        assign = session.execute(
            select(OperationalPlanAssignmentORM)
            .where(
                OperationalPlanAssignmentORM.kitchen_id == str(auth.kitchen_id),
                OperationalPlanAssignmentORM.run_id == run.id,
            )
            .order_by(OperationalPlanAssignmentORM.updated_at.desc())
        ).scalars().first()
        rev = session.execute(
            select(MenuReviewRecordORM)
            .where(
                MenuReviewRecordORM.kitchen_id == str(auth.kitchen_id),
                MenuReviewRecordORM.run_id == run.id,
            )
            .order_by(MenuReviewRecordORM.version_number.desc())
        ).scalars().first()
        title = rev.title if rev else sc.name
        return assign, run, sc, title

    # Auto-resolve latest ACTIVE (or ON_HOLD) operational plan for this kitchen
    assign = session.execute(
        select(OperationalPlanAssignmentORM)
        .where(
            OperationalPlanAssignmentORM.kitchen_id == str(auth.kitchen_id),
            OperationalPlanAssignmentORM.operational_status.in_(["ACTIVE", "ON_HOLD"]),
        )
        .order_by(
            OperationalPlanAssignmentORM.production_date.desc(),
            OperationalPlanAssignmentORM.activated_at.desc(),
        )
    ).scalars().first()

    if assign is not None:
        run = session.get(OptimizationRunORM, assign.run_id)
        sc = session.get(ScenarioORM, assign.scenario_id)
        rev = session.get(MenuReviewRecordORM, assign.menu_review_id)
        title = rev.title if rev else (sc.name if sc else None)
        return assign, run, sc, title

    # Fallback: latest validated run on this kitchen
    run = session.execute(
        select(OptimizationRunORM)
        .join(ScenarioORM, OptimizationRunORM.scenario_id == ScenarioORM.id)
        .where(
            ScenarioORM.kitchen_id == str(auth.kitchen_id),
            OptimizationRunORM.validation_passed.is_(True),
        )
        .order_by(OptimizationRunORM.created_at.desc())
    ).scalars().first()
    if run is not None:
        sc = session.get(ScenarioORM, run.scenario_id)
        title = sc.name if sc else None
    return None, run, sc, title


def get_next_week_defaults(
    session: Session,
    auth: AuthContext,
    *,
    source_run_id: Optional[UUID] = None,
    source_assignment_id: Optional[UUID] = None,
) -> NextWeekDefaultsResponse:
    """Suggest clean next-week defaults from the previous period (never carrying simulation overrides)."""
    repo = SQLiteVaultRepository(session)
    assign, run, sc, title = _resolve_source_plan(
        session,
        auth,
        source_run_id=source_run_id,
        source_assignment_id=source_assignment_id,
    )

    prev_dates: List[date] = []
    if assign is not None:
        prev_dates = extract_assignment_service_dates(assign)
    elif sc is not None:
        prev_dates = extract_scenario_service_dates(sc)

    days = int(sc.days) if sc is not None else 5
    suggested_dates = suggest_next_week_service_dates(prev_dates, days=days)

    ds_id = (
        UUID(sc.dataset_version_id)
        if sc is not None
        else repo.get_active_dataset_id(auth.kitchen_id)
    )
    target_id = (
        UUID(sc.target_id) if sc is not None else repo.get_default_target_id()
    )
    target = session.get(NutritionTargetORM, str(target_id))
    cohort = (target.cohort if target else "DEFAULT").strip() or "DEFAULT"
    meal_type = (sc.meal_type if sc else "lunch").strip().lower() or "lunch"
    batch_label = assign.batch_label if assign is not None else "DEFAULT"

    history_ctx = collect_previous_menu_history(
        session,
        kitchen_id=auth.kitchen_id,
        before_date=suggested_dates[0],
        meal_type=meal_type,
        target_cohort=cohort,
        batch_label=batch_label,
        window_days=5,
        fallback_source_run_id=UUID(run.id) if run is not None else None,
    )
    stock_ctx = compute_cross_period_stock_context(
        session,
        kitchen_id=auth.kitchen_id,
        dataset_version_id=ds_id,
        service_dates=suggested_dates,
    )

    period_label = (
        f"{suggested_dates[0].isoformat()} s.d. {suggested_dates[-1].isoformat()}"
        if suggested_dates
        else "Minggu Berikutnya"
    )
    suggested_name = f"Rencana Mingguan ({period_label})"

    return NextWeekDefaultsResponse(
        source_run_id=UUID(run.id) if run is not None else None,
        source_assignment_id=UUID(assign.id) if assign is not None else None,
        source_plan_title=title,
        source_service_dates=prev_dates,
        suggested_name=suggested_name,
        suggested_service_dates=suggested_dates,
        dataset_version_id=ds_id,
        nutrition_target_id=target_id,
        meal_type=meal_type,
        servings_per_day=int(sc.servings_per_day) if sc is not None else 100,
        days=len(suggested_dates),
        budget_idr_per_serving=float(sc.budget_idr_per_serving) if sc is not None else 12000.0,
        max_repeat_per_family=int(sc.max_repeat_per_family) if sc is not None else 2,
        excluded_allergens=list(sc.excluded_allergens_json or []) if sc is not None else [],
        history_source_type=history_ctx.primary_source_type,
        history_source_notice=history_ctx.source_notice,
        stock_confirmation_required=stock_ctx.stock_confirmation_required,
        stock_confirmation_reason=stock_ctx.stock_confirmation_reason,
    )


def prepare_next_week_plan(
    session: Session,
    auth: AuthContext,
    req: PrepareNextWeekRequest,
) -> PrepareNextWeekResponse:
    """Create a fresh next-week DRAFT scenario & optimization run using clean authorized config,
    live stock (with per-date expiry & cross-plan commitments), and 5-day prior menu history.

    - Never copies last week's recipes directly as final result.
    - Never inherits simulation price/stock overrides from prior scenario.
    - Never modifies/deactivates the currently running week or auto-approves/activates the new draft.
    """
    if auth.role != RoleEnum.MENU_PLANNER:
        raise HTTPException(
            status_code=403,
            detail="Hanya Perencana Menu (MENU_PLANNER) yang dapat menyiapkan draf rencana minggu berikutnya.",
        )

    repo = SQLiteVaultRepository(session)
    assign, source_run, source_sc, _source_title = _resolve_source_plan(
        session,
        auth,
        source_run_id=req.source_run_id,
        source_assignment_id=req.source_assignment_id,
    )

    prev_dates: List[date] = []
    if assign is not None:
        prev_dates = extract_assignment_service_dates(assign)
    elif source_sc is not None:
        prev_dates = extract_scenario_service_dates(source_sc)

    default_days = int(source_sc.days) if source_sc is not None else 5
    chosen_dates = (
        sorted(req.service_dates)
        if req.service_dates
        else suggest_next_week_service_dates(prev_dates, days=default_days)
    )

    dataset_id = req.dataset_version_id or (
        UUID(source_sc.dataset_version_id)
        if source_sc is not None
        else repo.get_active_dataset_id(auth.kitchen_id)
    )
    try:
        ds_orm = repo.get_dataset_orm(dataset_id, kitchen_id=auth.kitchen_id)
    except ResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    target_id = (
        UUID(source_sc.target_id)
        if source_sc is not None
        else repo.get_default_target_id()
    )
    meal_type = (source_sc.meal_type if source_sc else "lunch").strip().lower() or "lunch"
    servings_per_day = (
        int(req.servings_per_day)
        if req.servings_per_day is not None
        else (int(source_sc.servings_per_day) if source_sc is not None else 100)
    )
    budget_idr = (
        float(req.budget_idr_per_serving)
        if req.budget_idr_per_serving is not None
        else (float(source_sc.budget_idr_per_serving) if source_sc is not None else 12000.0)
    )
    max_repeat = (
        int(req.max_repeat_per_family)
        if req.max_repeat_per_family is not None
        else (int(source_sc.max_repeat_per_family) if source_sc is not None else 2)
    )
    excluded_allergens = (
        list(req.excluded_allergens)
        if req.excluded_allergens is not None
        else (list(source_sc.excluded_allergens_json or []) if source_sc is not None else [])
    )

    period_label = f"{chosen_dates[0].isoformat()} s.d. {chosen_dates[-1].isoformat()}"
    plan_name = (
        req.name.strip()
        if req.name and req.name.strip()
        else f"Rencana Mingguan ({period_label})"
    )
    first_dt = datetime(
        chosen_dates[0].year,
        chosen_dates[0].month,
        chosen_dates[0].day,
        8,
        0,
        tzinfo=timezone.utc,
    )

    # Create brand-new scenario (NO parent overrides inherited!)
    sc_req = ScenarioCreateRequest(
        name=plan_name,
        dataset_version_id=dataset_id,
        nutrition_target_id=target_id,
        meal_type=meal_type,
        servings_per_day=servings_per_day,
        days=len(chosen_dates),
        budget_idr_per_serving=budget_idr,
        max_repeat_per_family=max_repeat,
        excluded_allergens=excluded_allergens,
        source_label=SourceTypeEnum(ds_orm.source_type)
        if ds_orm.source_type in {e.value for e in SourceTypeEnum}
        else SourceTypeEnum.SYNTHETIC,
        production_date=first_dt,
        service_dates=chosen_dates,
        continuation_of_run_id=UUID(source_run.id) if source_run is not None else None,
    )
    created_sc = repo.create_scenario(sc_req, kitchen_id=auth.kitchen_id)

    # Run MILP with cross-week history + per-date expiry + cross-plan stock commitments
    run_resp = repo.run_optimization(created_sc.id, kitchen_id=auth.kitchen_id)

    # Compute snapshot SHA256 over current usable stock so stale-snapshot guard protects activation
    stock_ctx = compute_cross_period_stock_context(
        session,
        kitchen_id=auth.kitchen_id,
        dataset_version_id=dataset_id,
        service_dates=chosen_dates,
    )
    snap_sha = compute_usable_inventory_sha256(stock_ctx.base_availability)

    review_id: Optional[UUID] = None
    review_status: Optional[str] = None
    if run_resp.validation_passed:
        draft_notes = req.planner_notes.strip() if req.planner_notes and req.planner_notes.strip() else None
        if run_resp.stock_confirmation_required and run_resp.stock_confirmation_reason:
            note_prefix = f"[PERLU KONFIRMASI STOK] {run_resp.stock_confirmation_reason}"
            draft_notes = f"{draft_notes}\n{note_prefix}" if draft_notes else note_prefix
        review = create_menu_review(
            session,
            auth,
            MenuReviewCreateRequest(
                run_id=run_resp.run_id,
                title=plan_name,
                planner_notes=draft_notes,
            ),
            inventory_snapshot_sha256=snap_sha,
        )
        review_id = review.id
        review_status = review.status.value

    record_audit_event(
        session,
        action="scenario.next_week_prepared",
        entity_type="scenario",
        entity_id=str(created_sc.id),
        kitchen_id=auth.kitchen_id,
        actor_user_id=auth.user_id,
        actor_role=auth.role.value,
        metadata={
            "run_id": str(run_resp.run_id),
            "menu_review_id": str(review_id) if review_id else None,
            "service_dates": [d.isoformat() for d in chosen_dates],
            "continuation_of_run_id": str(source_run.id) if source_run is not None else None,
            "stock_confirmation_required": run_resp.stock_confirmation_required,
        },
    )
    session.commit()

    return PrepareNextWeekResponse(
        scenario_id=created_sc.id,
        run_id=run_resp.run_id,
        menu_review_id=review_id,
        menu_review_status=review_status,
        service_dates=chosen_dates,
        solver_status=run_resp.solver_status.value,
        validation_passed=run_resp.validation_passed,
        stock_confirmation_required=run_resp.stock_confirmation_required,
        stock_confirmation_reason=run_resp.stock_confirmation_reason,
        history_context=run_resp.history_context or {},
        warnings=run_resp.warnings,
    )
