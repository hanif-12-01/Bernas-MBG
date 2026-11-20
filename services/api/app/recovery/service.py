from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import AuthContext, record_audit_event
from app.db.models import (
    DatasetVersionORM,
    IngredientIncidentORM,
    MenuReviewRecordORM,
    OperationalPlanAssignmentORM,
    OptimizationRunORM,
    RecoveryEventORM,
    ScenarioORM,
)
from app.db.repository import SQLiteVaultRepository
from app.domain.models.schemas import (
    OptimizationRunResponse,
    PriceOverrideEntry,
    PriceOverridesRequest,
    ScenarioCloneRequest,
    StockOverrideEntry,
    StockOverridesRequest,
)
from app.domain.recipe_calculator import precompute_all_recipes
from app.ingestion.unit_converter import DataValidationError, convert_price_to_idr_per_g
from app.inventory.service import _ensure_utc, compute_usable_inventory
from app.recovery.comparison import build_candidate_summary, build_fair_comparison_bundle
from app.recovery.impact import build_disruption_impact_report, compute_baseline_material_usage
from app.recovery.optimizer import solve_minimum_disruption_milp
from app.recovery.procurement import build_procurement_delta
from app.recovery.schemas import (
    CandidatePlanSummary,
    DisruptionConditionRequest,
    DisruptionImpactReport,
    FairComparisonBundle,
    ProcurementDeltaItem,
    RecoveryEventResponse,
    RecoveryModeEnum,
    RecoveryStatusEnum,
    RecoverySubmitRequest,
)
from app.recovery.snapshot import compute_usable_inventory_sha256
from app.reviews.schemas import MenuReviewCreateRequest, MenuReviewResponse
from app.reviews.service import create_menu_review, submit_menu_review
from app.scenarios.service import ResourceNotFoundError


def _resolve_baseline(
    session: Session,
    repo: SQLiteVaultRepository,
    auth: AuthContext,
    req: DisruptionConditionRequest,
) -> Tuple[OptimizationRunResponse, Optional[MenuReviewRecordORM], str, str]:
    """Locate baseline optimization run & optional review with strict kitchen isolation."""
    baseline_review: Optional[MenuReviewRecordORM] = None
    run_id = req.baseline_run_id

    if req.baseline_menu_review_id is not None:
        baseline_review = session.execute(
            select(MenuReviewRecordORM).where(
                MenuReviewRecordORM.id == str(req.baseline_menu_review_id),
                MenuReviewRecordORM.kitchen_id == str(auth.kitchen_id),
            )
        ).scalar_one_or_none()
        if baseline_review is None:
            raise HTTPException(
                status_code=404,
                detail="Catatan peninjauan menu baseline tidak ditemukan pada dapur ini.",
            )
        run_id = UUID(baseline_review.run_id)

    if run_id is None:
        active_assign = session.execute(
            select(OperationalPlanAssignmentORM)
            .where(
                OperationalPlanAssignmentORM.kitchen_id == str(auth.kitchen_id),
                OperationalPlanAssignmentORM.operational_status.in_(["ACTIVE", "ON_HOLD"]),
            )
            .order_by(
                OperationalPlanAssignmentORM.activated_at.desc(),
                OperationalPlanAssignmentORM.updated_at.desc(),
            )
        ).scalars().first()
        if active_assign is not None:
            baseline_review = session.execute(
                select(MenuReviewRecordORM).where(
                    MenuReviewRecordORM.id == active_assign.menu_review_id,
                    MenuReviewRecordORM.kitchen_id == str(auth.kitchen_id),
                )
            ).scalar_one_or_none()
            if baseline_review is not None:
                run_id = UUID(baseline_review.run_id)

    if run_id is None:
        baseline_review = session.execute(
            select(MenuReviewRecordORM)
            .where(
                MenuReviewRecordORM.kitchen_id == str(auth.kitchen_id),
                MenuReviewRecordORM.status == "APPROVED",
            )
            .order_by(MenuReviewRecordORM.reviewed_at.desc(), MenuReviewRecordORM.created_at.desc())
        ).scalars().first()
        if baseline_review is not None:
            run_id = UUID(baseline_review.run_id)
        else:
            latest_run_row = session.execute(
                select(OptimizationRunORM)
                .join(ScenarioORM, OptimizationRunORM.scenario_id == ScenarioORM.id)
                .where(
                    ScenarioORM.kitchen_id == str(auth.kitchen_id),
                    OptimizationRunORM.validation_passed.is_(True),
                    OptimizationRunORM.solver_status.in_(["OPTIMAL", "FEASIBLE"]),
                )
                .order_by(OptimizationRunORM.created_at.desc())
            ).scalars().first()
            if latest_run_row is None:
                raise HTTPException(
                    status_code=404,
                    detail="Belum ada rencana menu tervalidasi di dapur ini sebagai baseline pemulihan.",
                )
            run_id = UUID(latest_run_row.id)

    try:
        baseline_run = repo.get_run(run_id, kitchen_id=auth.kitchen_id)
    except ResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Baseline run tidak ditemukan pada dapur ini.") from exc

    if not baseline_run.validation_passed or not baseline_run.days:
        raise HTTPException(
            status_code=409,
            detail="Baseline run belum valid atau tidak layak sehingga tidak dapat dijadikan dasar pemulihan.",
        )

    if baseline_review is None:
        baseline_review = session.execute(
            select(MenuReviewRecordORM)
            .where(
                MenuReviewRecordORM.kitchen_id == str(auth.kitchen_id),
                MenuReviewRecordORM.run_id == str(run_id),
            )
            .order_by(MenuReviewRecordORM.version_number.desc())
        ).scalars().first()

    baseline_title = (
        baseline_review.title
        if baseline_review is not None
        else f"Skenario Baseline ({str(baseline_run.run_id)[:8]})"
    )
    baseline_status = baseline_review.status if baseline_review is not None else "VALIDATED_RUN"
    return baseline_run, baseline_review, baseline_title, baseline_status


def _prepare_recovery_conditions(
    *,
    session: Session,
    repo: SQLiteVaultRepository,
    auth: AuthContext,
    req: DisruptionConditionRequest,
    baseline_run: OptimizationRunResponse,
):
    baseline_scenario = repo.get_scenario(baseline_run.scenario_id, kitchen_id=auth.kitchen_id)
    ingredients_by_code, _ing_id_by_code, base_prices, base_stock, recipes = (
        repo.load_dataset_bundle(baseline_scenario.dataset_version_id, kitchen_id=auth.kitchen_id)
    )
    ds_row = session.get(DatasetVersionORM, str(baseline_scenario.dataset_version_id))
    dataset_name = ds_row.name if ds_row else "Dataset"
    recipes_by_id = {r.id: r for r in recipes}
    target = repo.get_target(baseline_scenario.nutrition_target_id)

    prod_date = _ensure_utc(
        req.production_date
        or baseline_scenario.production_date
        or datetime.now(timezone.utc)
    )
    assert prod_date is not None

    # Historical prices & stock stored in the baseline run snapshot (preserved read-only!)
    snap = baseline_run.input_snapshot or {}
    snap_prices = snap.get("prices_idr_per_g", {})
    previous_prices = {
        code: float(snap_prices[code])
        if code in snap_prices
        else base_prices[code].price_idr_per_g
        for code in ingredients_by_code
    }
    snap_stock = snap.get("stock_raw_g", {})
    previous_stock: Dict[str, Optional[float]] = {
        code: float(snap_stock[code])
        if code in snap_stock
        else (base_stock[code].stock_raw_g if code in base_stock else None)
        for code in ingredients_by_code
    }

    # Live verified inventory state
    availability = compute_usable_inventory(
        session,
        kitchen_id=auth.kitchen_id,
        dataset_version_id=baseline_scenario.dataset_version_id,
        production_date=prod_date,
    )
    live_inv_sha256 = compute_usable_inventory_sha256(availability)

    # Apply explicit price overrides cleanly with Decimal conversion
    effective_prices_new = dict(previous_prices)
    price_overrides_map: Dict[str, float] = dict(baseline_scenario.price_overrides_idr_per_g)
    for po in req.price_changes:
        if po.ingredient_code not in ingredients_by_code:
            raise HTTPException(
                status_code=422,
                detail=f"Kode bahan tidak dikenal: '{po.ingredient_code}'.",
            )
        per_g = convert_price_to_idr_per_g(po.new_price_idr_per_kg, "IDR/kg")
        effective_prices_new[po.ingredient_code] = per_g
        price_overrides_map[po.ingredient_code] = per_g

    # Safety hold check: held or rejected/disposed lots must NEVER be re-enabled by recovery overrides
    avail_by_code = {item.ingredient_code: item for item in availability.items}
    held_items = [
        item
        for item in availability.items
        if item.safety_held_raw_g > 0 or item.rejected_disposed_raw_g > 0
    ]
    if held_items and not req.use_latest_verified_inventory:
        names = ", ".join(sorted(i.ingredient_name for i in held_items))
        raise HTTPException(
            status_code=409,
            detail=(
                f"Terdapat bahan dalam STATUS TAHAN KEAMANAN (SAFETY HOLD: {names}). "
                "Analisis pemulihan wajib menggunakan stok terverifikasi terbaru agar lot yang ditahan tidak ikut terhitung."
            ),
        )

    # Base usable stock before explicit stock overrides
    effective_stock_new: Dict[str, Optional[float]] = {}
    if req.use_latest_verified_inventory:
        for item in availability.items:
            effective_stock_new[item.ingredient_code] = item.usable_raw_g
    else:
        for code, val in previous_stock.items():
            effective_stock_new[code] = val

    stock_overrides_map: Dict[str, float] = dict(baseline_scenario.stock_overrides_raw_g)
    for so in req.stock_changes:
        if so.ingredient_code not in ingredients_by_code:
            raise HTTPException(
                status_code=422,
                detail=f"Kode bahan tidak dikenal: '{so.ingredient_code}'.",
            )
        curr_g = effective_stock_new.get(so.ingredient_code)
        base_g = curr_g if curr_g is not None else (previous_stock.get(so.ingredient_code) or 0.0)
        if so.unavailable:
            new_g = 0.0
        elif so.new_usable_kg is not None:
            new_g = round(float(so.new_usable_kg) * 1000.0, 3)
        elif so.received_delivery_kg is not None and so.expected_delivery_kg is not None:
            shortfall_g = max(0.0, (so.expected_delivery_kg - so.received_delivery_kg) * 1000.0)
            new_g = round(max(0.0, base_g - shortfall_g), 3)
        elif (so.delivery_status or "").upper() == "DELAYED" and so.expected_delivery_kg is not None:
            new_g = round(max(0.0, base_g - so.expected_delivery_kg * 1000.0), 3)
        else:
            new_g = base_g

        avail_item = avail_by_code.get(so.ingredient_code)
        if avail_item is not None and (
            avail_item.safety_held_raw_g > 0 or avail_item.rejected_disposed_raw_g > 0
        ):
            max_clean_g = avail_item.usable_raw_g if avail_item.usable_raw_g is not None else 0.0
            if new_g > max_clean_g + 1e-6:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"Lot bahan '{avail_item.ingredient_name}' ({so.ingredient_code}) sedang dalam STATUS TAHAN KEAMANAN (safety hold). "
                        f"Stok bersih maksimum yang diizinkan hanya {max_clean_g / 1000.0:.2f} kg (permintaan override: {new_g / 1000.0:.2f} kg)."
                    ),
                )

        effective_stock_new[so.ingredient_code] = new_g
        stock_overrides_map[so.ingredient_code] = new_g

    new_servings = (
        int(req.new_servings_per_day)
        if req.new_servings_per_day is not None
        else baseline_scenario.servings_per_day
    )
    new_budget = (
        float(req.new_budget_idr_per_serving)
        if req.new_budget_idr_per_serving is not None
        else baseline_scenario.budget_idr_per_serving
    )

    features_new = {
        f.recipe_id: f
        for f in precompute_all_recipes(recipes, ingredients_by_code, effective_prices_new, target.limits)
    }

    return {
        "baseline_scenario": baseline_scenario,
        "dataset_name": dataset_name,
        "ingredients_by_code": ingredients_by_code,
        "recipes": recipes,
        "recipes_by_id": recipes_by_id,
        "target": target,
        "prod_date": prod_date,
        "previous_prices": previous_prices,
        "effective_prices_new": effective_prices_new,
        "price_overrides_map": price_overrides_map,
        "previous_stock": previous_stock,
        "effective_stock_new": effective_stock_new,
        "stock_overrides_map": stock_overrides_map,
        "availability": availability,
        "live_inv_sha256": live_inv_sha256,
        "new_servings": new_servings,
        "new_budget": new_budget,
        "features_new": features_new,
    }


def preview_disruption_impact(
    session: Session,
    auth: AuthContext,
    req: DisruptionConditionRequest,
) -> DisruptionImpactReport:
    """Compute affected ingredients and broken slots without generating/persisting candidate runs."""
    repo = SQLiteVaultRepository(session)
    baseline_run, baseline_review, baseline_title, baseline_status = _resolve_baseline(
        session, repo, auth, req
    )
    ctx = _prepare_recovery_conditions(
        session=session, repo=repo, auth=auth, req=req, baseline_run=baseline_run
    )
    impact, _ = build_disruption_impact_report(
        req=req,
        baseline_run=baseline_run,
        baseline_scenario=ctx["baseline_scenario"],
        baseline_review_id=UUID(baseline_review.id) if baseline_review else None,
        baseline_title=baseline_title,
        baseline_status=baseline_status,
        dataset_name=ctx["dataset_name"],
        production_date=ctx["prod_date"],
        recipes_by_id=ctx["recipes_by_id"],
        features_by_id_new=ctx["features_new"],
        ingredients_by_code=ctx["ingredients_by_code"],
        target=ctx["target"],
        previous_prices_idr_per_g=ctx["previous_prices"],
        effective_prices_new=ctx["effective_prices_new"],
        previous_stock_raw_g=ctx["previous_stock"],
        effective_stock_new=ctx["effective_stock_new"],
        availability=ctx["availability"],
        inventory_snapshot_sha256=ctx["live_inv_sha256"],
        new_servings_per_day=ctx["new_servings"],
        new_budget_idr_per_serving=ctx["new_budget"],
    )
    return impact


def _create_recovery_scenario_with_overrides(
    *,
    session: Session,
    repo: SQLiteVaultRepository,
    auth: AuthContext,
    base_scenario_id: UUID,
    name: str,
    new_servings: int,
    new_budget: float,
    prod_date: datetime,
    price_overrides_map: Dict[str, float],
    stock_overrides_map: Dict[str, float],
) -> UUID:
    cloned = repo.clone_scenario(
        base_scenario_id,
        req=ScenarioCloneRequest(name=name),
        kitchen_id=auth.kitchen_id,
    )
    sc_row = session.get(ScenarioORM, str(cloned.id))
    assert sc_row is not None
    sc_row.servings_per_day = new_servings
    sc_row.budget_idr_per_serving = new_budget
    sc_row.production_date = prod_date
    session.flush()

    if price_overrides_map:
        repo.apply_price_overrides(
            cloned.id,
            PriceOverridesRequest(
                overrides=[
                    PriceOverrideEntry(
                        ingredient_code=code,
                        price_value=round(per_g * 1000.0, 6),
                        unit="IDR/kg",
                    )
                    for code, per_g in sorted(price_overrides_map.items())
                ]
            ),
            kitchen_id=auth.kitchen_id,
        )
    if stock_overrides_map:
        repo.apply_stock_overrides(
            cloned.id,
            StockOverridesRequest(
                overrides=[
                    StockOverrideEntry(ingredient_code=code, stock_raw_g=val)
                    for code, val in sorted(stock_overrides_map.items())
                ]
            ),
            kitchen_id=auth.kitchen_id,
        )
    return cloned.id


def analyze_and_create_recovery_event(
    session: Session,
    auth: AuthContext,
    req: DisruptionConditionRequest,
) -> RecoveryEventResponse:
    """Detect disruption impact, solve Min-Disruption & Min-Cost recovery MILPs, verify, and persist."""
    repo = SQLiteVaultRepository(session)
    baseline_run, baseline_review, baseline_title, baseline_status = _resolve_baseline(
        session, repo, auth, req
    )
    ctx = _prepare_recovery_conditions(
        session=session, repo=repo, auth=auth, req=req, baseline_run=baseline_run
    )
    baseline_scenario = ctx["baseline_scenario"]
    ingredients_by_code = ctx["ingredients_by_code"]
    effective_stock_new: Dict[str, Optional[float]] = ctx["effective_stock_new"]

    # Solver requires numeric non-null stock for all ingredients used by eligible recipes.
    # For UNKNOWN ingredients (usable_raw_g is None), conservatively treat unverified stock as 0.0 g
    # only inside solver stock map OR let missing-stock raise 422 cleanly.
    solver_stock_map: Dict[str, float] = {}
    stock_overrides_for_clone = dict(ctx["stock_overrides_map"])
    for code, val in effective_stock_new.items():
        if val is None:
            solver_stock_map[code] = 0.0
            stock_overrides_for_clone[code] = 0.0
        else:
            solver_stock_map[code] = float(val)

    impact, counterfactual = build_disruption_impact_report(
        req=req,
        baseline_run=baseline_run,
        baseline_scenario=baseline_scenario,
        baseline_review_id=UUID(baseline_review.id) if baseline_review else None,
        baseline_title=baseline_title,
        baseline_status=baseline_status,
        dataset_name=ctx["dataset_name"],
        production_date=ctx["prod_date"],
        recipes_by_id=ctx["recipes_by_id"],
        features_by_id_new=ctx["features_new"],
        ingredients_by_code=ingredients_by_code,
        target=ctx["target"],
        previous_prices_idr_per_g=ctx["previous_prices"],
        effective_prices_new=ctx["effective_prices_new"],
        previous_stock_raw_g=ctx["previous_stock"],
        effective_stock_new=effective_stock_new,
        availability=ctx["availability"],
        inventory_snapshot_sha256=ctx["live_inv_sha256"],
        new_servings_per_day=ctx["new_servings"],
        new_budget_idr_per_serving=ctx["new_budget"],
    )

    slot_reasons = {
        (slot_item.day_index, slot_item.slot): slot_item.reasons
        for slot_item in impact.affected_slots
    }

    min_dis_sc_id = _create_recovery_scenario_with_overrides(
        session=session,
        repo=repo,
        auth=auth,
        base_scenario_id=baseline_scenario.id,
        name=f"{baseline_scenario.name} [Pemulihan Minim Perubahan]",
        new_servings=ctx["new_servings"],
        new_budget=ctx["new_budget"],
        prod_date=ctx["prod_date"],
        price_overrides_map=ctx["price_overrides_map"],
        stock_overrides_map=stock_overrides_for_clone,
    )
    min_dis_scenario = repo.get_scenario(min_dis_sc_id, kitchen_id=auth.kitchen_id)

    baseline_assignments = {
        d.day_index: dict(d.recipes_by_slot) for d in baseline_run.days
    }
    try:
        min_dis_outcome = solve_minimum_disruption_milp(
            scenario=min_dis_scenario,
            recipes=ctx["recipes"],
            features_by_id=ctx["features_new"],
            target=ctx["target"],
            stock_raw_g=solver_stock_map,
            baseline_assignments=baseline_assignments,
            ingredients_by_code=ingredients_by_code,
            time_limit_seconds=req.time_limit_seconds,
        )
        min_dis_run = repo.run_optimization(
            min_dis_sc_id,
            time_limit_seconds=req.time_limit_seconds,
            forced_raw_result=min_dis_outcome.raw_result,
            kitchen_id=auth.kitchen_id,
        )
    except (ValueError, DataValidationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    min_cost_sc_id = _create_recovery_scenario_with_overrides(
        session=session,
        repo=repo,
        auth=auth,
        base_scenario_id=baseline_scenario.id,
        name=f"{baseline_scenario.name} [Pemulihan Biaya Minimum]",
        new_servings=ctx["new_servings"],
        new_budget=ctx["new_budget"],
        prod_date=ctx["prod_date"],
        price_overrides_map=ctx["price_overrides_map"],
        stock_overrides_map=stock_overrides_for_clone,
    )
    try:
        min_cost_run = repo.run_optimization(
            min_cost_sc_id,
            time_limit_seconds=req.time_limit_seconds,
            kitchen_id=auth.kitchen_id,
        )
    except (ValueError, DataValidationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    min_dis_summary = build_candidate_summary(
        mode=RecoveryModeEnum.MIN_DISRUPTION,
        baseline_run=baseline_run,
        candidate_run=min_dis_run,
        counterfactual=counterfactual,
        slot_reasons=slot_reasons,
    )
    min_cost_summary = build_candidate_summary(
        mode=RecoveryModeEnum.MIN_COST,
        baseline_run=baseline_run,
        candidate_run=min_cost_run,
        counterfactual=counterfactual,
        slot_reasons=slot_reasons,
        min_disruption_total_cost_idr=min_dis_summary.total_cost_idr,
    )

    prices_changed = any(
        abs(ctx["effective_prices_new"][c] - ctx["previous_prices"].get(c, 0.0)) > 1e-9
        for c in ctx["effective_prices_new"]
    )
    comparison = build_fair_comparison_bundle(
        baseline_run=baseline_run,
        impact=impact,
        counterfactual=counterfactual,
        min_disruption=min_dis_summary,
        min_cost=min_cost_summary,
        prices_or_servings_changed=(
            prices_changed or ctx["new_servings"] != baseline_scenario.servings_per_day
        ),
    )

    baseline_usage_old_g, _ = compute_baseline_material_usage(
        baseline_run, ctx["recipes_by_id"], baseline_scenario.servings_per_day
    )
    proc_by_mode = {
        RecoveryModeEnum.MIN_DISRUPTION.value: build_procurement_delta(
            baseline_usage_old_g=baseline_usage_old_g,
            candidate_run=min_dis_run if min_dis_summary.validation_passed else None,
            ingredients_by_code=ingredients_by_code,
            effective_prices_new=ctx["effective_prices_new"],
            effective_stock_new_g=effective_stock_new,
            availability=ctx["availability"],
        ),
        RecoveryModeEnum.MIN_COST.value: build_procurement_delta(
            baseline_usage_old_g=baseline_usage_old_g,
            candidate_run=min_cost_run if min_cost_summary.validation_passed else None,
            ingredients_by_code=ingredients_by_code,
            effective_prices_new=ctx["effective_prices_new"],
            effective_stock_new_g=effective_stock_new,
            availability=ctx["availability"],
        ),
    }

    either_feasible = min_dis_summary.validation_passed or min_cost_summary.validation_passed
    status = (
        RecoveryStatusEnum.ANALYZED if either_feasible else RecoveryStatusEnum.INFEASIBLE
    )

    event_id = uuid4()
    now = datetime.now(timezone.utc)
    title = (
        req.title.strip()
        if req.title and req.title.strip()
        else f"Pemulihan: {baseline_title}"
    )
    summary_text = (
        req.disruption_summary.strip()
        if req.disruption_summary and req.disruption_summary.strip()
        else impact.summary_message
    )

    if req.incident_id is not None:
        inc_row = session.execute(
            select(IngredientIncidentORM).where(
                IngredientIncidentORM.id == str(req.incident_id),
                IngredientIncidentORM.kitchen_id == str(auth.kitchen_id),
            )
        ).scalar_one_or_none()
        if inc_row is None:
            raise HTTPException(
                status_code=404,
                detail="Insiden bahan bermasalah tidak ditemukan pada dapur ini.",
            )

    event_row = RecoveryEventORM(
        id=str(event_id),
        kitchen_id=str(auth.kitchen_id),
        dataset_version_id=str(baseline_scenario.dataset_version_id),
        baseline_menu_review_id=str(baseline_review.id) if baseline_review else None,
        baseline_run_id=str(baseline_run.run_id),
        baseline_scenario_id=str(baseline_scenario.id),
        incident_id=str(req.incident_id) if req.incident_id else None,
        title=title,
        disruption_types_json=[d.value for d in impact.disruption_types],
        disruption_summary=summary_text,
        disruption_input_json=req.model_dump(mode="json"),
        affected_slots_json=[s.model_dump(mode="json") for s in impact.affected_slots],
        impact_analysis_json=impact.model_dump(mode="json"),
        min_disruption_scenario_id=str(min_dis_sc_id),
        min_disruption_run_id=str(min_dis_run.run_id),
        min_cost_scenario_id=str(min_cost_sc_id),
        min_cost_run_id=str(min_cost_run.run_id),
        selected_mode=None,
        selected_run_id=None,
        submitted_review_id=None,
        inventory_snapshot_sha256=ctx["live_inv_sha256"],
        comparison_json={
            "comparison": comparison.model_dump(mode="json"),
            "min_disruption": min_dis_summary.model_dump(mode="json", exclude={"run_detail"}),
            "min_cost": min_cost_summary.model_dump(mode="json", exclude={"run_detail"}),
            "procurement_delta_by_mode": {
                k: [item.model_dump(mode="json") for item in v]
                for k, v in proc_by_mode.items()
            },
        },
        status=status.value,
        created_by_user_id=str(auth.user_id),
        created_at=now,
        updated_at=now,
    )
    session.add(event_row)
    record_audit_event(
        session,
        action="recovery.event_analyzed",
        entity_type="recovery_event",
        entity_id=str(event_id),
        kitchen_id=auth.kitchen_id,
        actor_user_id=auth.user_id,
        actor_role=auth.role.value,
        metadata={
            "baseline_run_id": str(baseline_run.run_id),
            "disruption_types": [d.value for d in impact.disruption_types],
            "status": status.value,
            "min_disruption_changed_slots": min_dis_summary.changed_slots_count,
            "min_disruption_feasible": min_dis_summary.validation_passed,
            "min_cost_feasible": min_cost_summary.validation_passed,
        },
    )
    session.commit()
    return get_recovery_event(session, auth, event_id)


def _hydrate_event(
    session: Session,
    repo: SQLiteVaultRepository,
    auth: AuthContext,
    row: RecoveryEventORM,
) -> RecoveryEventResponse:
    impact = DisruptionImpactReport.model_validate(row.impact_analysis_json)
    comp_payload = row.comparison_json or {}
    comparison = FairComparisonBundle.model_validate(comp_payload["comparison"])
    min_dis = CandidatePlanSummary.model_validate(comp_payload["min_disruption"])
    min_cost = CandidatePlanSummary.model_validate(comp_payload["min_cost"])

    if row.min_disruption_run_id:
        try:
            min_dis.run_detail = repo.get_run(UUID(row.min_disruption_run_id), kitchen_id=auth.kitchen_id)
        except ResourceNotFoundError:
            min_dis.run_detail = None
    if row.min_cost_run_id:
        try:
            min_cost.run_detail = repo.get_run(UUID(row.min_cost_run_id), kitchen_id=auth.kitchen_id)
        except ResourceNotFoundError:
            min_cost.run_detail = None

    raw_proc = comp_payload.get("procurement_delta_by_mode", {})
    proc_by_mode = {
        mode_key: [ProcurementDeltaItem.model_validate(item) for item in items]
        for mode_key, items in raw_proc.items()
    }

    # Live check whether underlying inventory changed since snapshot was created
    live_summary = compute_usable_inventory(
        session,
        kitchen_id=UUID(row.kitchen_id),
        dataset_version_id=UUID(row.dataset_version_id),
        production_date=impact.production_date,
    )
    live_sha = compute_usable_inventory_sha256(live_summary)
    is_stale = live_sha != row.inventory_snapshot_sha256

    return RecoveryEventResponse(
        id=UUID(row.id),
        kitchen_id=UUID(row.kitchen_id),
        dataset_version_id=UUID(row.dataset_version_id),
        baseline_menu_review_id=(
            UUID(row.baseline_menu_review_id) if row.baseline_menu_review_id else None
        ),
        baseline_run_id=UUID(row.baseline_run_id),
        baseline_scenario_id=UUID(row.baseline_scenario_id),
        incident_id=UUID(row.incident_id) if row.incident_id else None,
        title=row.title,
        status=RecoveryStatusEnum(row.status),
        disruption_types=impact.disruption_types,
        disruption_summary=row.disruption_summary,
        impact=impact,
        min_disruption=min_dis,
        min_cost=min_cost,
        comparison=comparison,
        procurement_delta_by_mode=proc_by_mode,
        selected_mode=RecoveryModeEnum(row.selected_mode) if row.selected_mode else None,
        selected_run_id=UUID(row.selected_run_id) if row.selected_run_id else None,
        submitted_review_id=UUID(row.submitted_review_id) if row.submitted_review_id else None,
        inventory_snapshot_sha256=row.inventory_snapshot_sha256,
        is_stale_inventory=is_stale,
        simulation_only=True,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def list_recovery_events(
    session: Session,
    auth: AuthContext,
) -> List[RecoveryEventResponse]:
    repo = SQLiteVaultRepository(session)
    rows = list(
        session.execute(
            select(RecoveryEventORM)
            .where(RecoveryEventORM.kitchen_id == str(auth.kitchen_id))
            .order_by(RecoveryEventORM.created_at.desc())
            .limit(20)
        )
        .scalars()
        .all()
    )
    return [_hydrate_event(session, repo, auth, r) for r in rows]


def get_recovery_event(
    session: Session,
    auth: AuthContext,
    event_id: UUID,
) -> RecoveryEventResponse:
    repo = SQLiteVaultRepository(session)
    row = session.execute(
        select(RecoveryEventORM).where(
            RecoveryEventORM.id == str(event_id),
            RecoveryEventORM.kitchen_id == str(auth.kitchen_id),
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Riwayat pemulihan tidak ditemukan.")
    return _hydrate_event(session, repo, auth, row)


def submit_recovery_candidate(
    session: Session,
    auth: AuthContext,
    event_id: UUID,
    req: RecoverySubmitRequest,
) -> Tuple[RecoveryEventResponse, MenuReviewResponse]:
    """Attach selected recovery candidate to a MenuReviewRecord with stale-snapshot protection."""
    row = session.execute(
        select(RecoveryEventORM).where(
            RecoveryEventORM.id == str(event_id),
            RecoveryEventORM.kitchen_id == str(auth.kitchen_id),
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Riwayat pemulihan tidak ditemukan.")

    if row.status in {"SUBMITTED", "APPROVED"}:
        raise HTTPException(
            status_code=409,
            detail="Usulan pemulihan sudah diajukan/disetujui sebelumnya. Buat analisis pemulihan baru jika perlu revisi.",
        )

    impact = DisruptionImpactReport.model_validate(row.impact_analysis_json)
    live_summary = compute_usable_inventory(
        session,
        kitchen_id=UUID(row.kitchen_id),
        dataset_version_id=UUID(row.dataset_version_id),
        production_date=impact.production_date,
    )
    live_sha = compute_usable_inventory_sha256(live_summary)
    if live_sha != row.inventory_snapshot_sha256:
        raise HTTPException(
            status_code=409,
            detail=(
                "Stok terverifikasi dapur telah berubah sejak analisis pemulihan dihitung. "
                "Silakan hitung ulang rencana pengganti terlebih dahulu sebelum mengajukan persetujuan."
            ),
        )

    candidate_run_id_str = (
        row.min_disruption_run_id
        if req.mode == RecoveryModeEnum.MIN_DISRUPTION
        else row.min_cost_run_id
    )
    if not candidate_run_id_str:
        raise HTTPException(status_code=409, detail="Kandidat pemulihan untuk mode ini tidak tersedia.")

    run_orm = session.get(OptimizationRunORM, candidate_run_id_str)
    if run_orm is None or not run_orm.validation_passed or run_orm.solver_status in {"INFEASIBLE", "ERROR"}:
        raise HTTPException(
            status_code=409,
            detail="Rencana pengganti yang dipilih tidak layak/gagal verifikasi dan tidak dapat diajukan.",
        )

    review_title = (
        req.title.strip()
        if req.title and req.title.strip()
        else f"Pengganti ({'Minim Perubahan' if req.mode == RecoveryModeEnum.MIN_DISRUPTION else 'Biaya Minimum'}): {row.title}"
    )

    review = create_menu_review(
        session,
        auth,
        MenuReviewCreateRequest(
            run_id=UUID(candidate_run_id_str),
            title=review_title[:255],
            planner_notes=req.planner_notes or row.disruption_summary,
        ),
        recovery_event_id=UUID(row.id),
        inventory_snapshot_sha256=live_sha,
    )
    if req.submit_for_review:
        review = submit_menu_review(session, auth, review.id)

    row.selected_mode = req.mode.value
    row.selected_run_id = candidate_run_id_str
    row.submitted_review_id = str(review.id)
    row.status = "SUBMITTED" if req.submit_for_review else "ANALYZED"
    row.updated_at = datetime.now(timezone.utc)

    record_audit_event(
        session,
        action="recovery.candidate_submitted",
        entity_type="recovery_event",
        entity_id=str(row.id),
        kitchen_id=auth.kitchen_id,
        actor_user_id=auth.user_id,
        actor_role=auth.role.value,
        metadata={
            "mode": req.mode.value,
            "selected_run_id": candidate_run_id_str,
            "submitted_review_id": str(review.id),
            "inventory_snapshot_sha256": live_sha,
        },
    )
    session.commit()
    return get_recovery_event(session, auth, event_id), review
