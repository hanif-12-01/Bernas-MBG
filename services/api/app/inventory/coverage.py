from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    MenuReviewRecordORM,
    OperationalPlanAssignmentORM,
    OptimizationRunORM,
    RecipeIngredientORM,
    RunAssignmentORM,
    ScenarioORM,
)
from app.inventory.timezone_utils import date_only_to_jakarta_production_dt, to_jakarta_date


class IngredientCoverageForecast(BaseModel):
    coverage_status: str  # SUFFICIENT | LOW_COVERAGE | EXPIRES_BEFORE_USE | NO_ACTIVE_PLAN | UNVERIFIED_OR_HELD
    planned_daily_usage_kg: Optional[float] = None
    planned_total_horizon_kg: Optional[float] = None
    estimated_coverage_days: Optional[int] = None
    horizon_days: Optional[int] = None
    covers_horizon_days: Optional[bool] = None
    first_shortage_day_index: Optional[int] = None
    first_shortage_date: Optional[date] = None
    expires_before_use_kg: float = 0.0
    plan_title: Optional[str] = None
    human_summary_id: str
    disclaimer: str = (
        "Estimasi kecukupan berdasarkan stok siap pakai, tanggal kedaluwarsa tercatat (FEFO), "
        "dan rencana menu aktif — bukan uji mutu atau jaminan keamanan pangan."
    )


def _load_active_plan_daily_demand(
    session: Session,
    *,
    kitchen_id: UUID,
    dataset_version_id: UUID,
) -> Tuple[Optional[str], int, Dict[str, Dict[int, float]]]:
    """Return (plan_title, horizon_days, {ingredient_id: {day_index: required_raw_g}})."""
    op_row = (
        session.execute(
            select(OperationalPlanAssignmentORM)
            .where(
                OperationalPlanAssignmentORM.kitchen_id == str(kitchen_id),
                OperationalPlanAssignmentORM.dataset_version_id == str(dataset_version_id),
                OperationalPlanAssignmentORM.operational_status.in_(["ACTIVE", "ON_HOLD"]),
            )
            .order_by(OperationalPlanAssignmentORM.updated_at.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )
    run_id: Optional[str] = None
    plan_title: Optional[str] = None
    if op_row is not None:
        run_id = op_row.run_id
        rev = session.get(MenuReviewRecordORM, op_row.menu_review_id)
        plan_title = rev.title if rev else "Rencana Operasional Aktif"
    else:
        latest_rev = (
            session.execute(
                select(MenuReviewRecordORM)
                .join(OptimizationRunORM, OptimizationRunORM.id == MenuReviewRecordORM.run_id)
                .where(
                    MenuReviewRecordORM.kitchen_id == str(kitchen_id),
                    MenuReviewRecordORM.status == "APPROVED",
                    OptimizationRunORM.dataset_version_id == str(dataset_version_id),
                )
                .order_by(MenuReviewRecordORM.reviewed_at.desc(), MenuReviewRecordORM.updated_at.desc())
                .limit(1)
            )
            .scalars()
            .first()
        )
        if latest_rev is not None:
            run_id = latest_rev.run_id
            plan_title = latest_rev.title

    if not run_id:
        return None, 0, {}

    run_orm = session.get(OptimizationRunORM, run_id)
    if run_orm is None:
        return None, 0, {}
    scenario = session.get(ScenarioORM, run_orm.scenario_id)
    servings_per_day = scenario.servings_per_day if scenario else 100
    horizon_days = scenario.days if scenario else 5

    assignments = list(
        session.execute(select(RunAssignmentORM).where(RunAssignmentORM.run_id == run_id))
        .scalars()
        .all()
    )
    if not assignments:
        return plan_title, horizon_days, {}

    recipe_ids = list({a.recipe_id for a in assignments})
    ri_rows = list(
        session.execute(
            select(RecipeIngredientORM).where(RecipeIngredientORM.recipe_id.in_(recipe_ids))
        )
        .scalars()
        .all()
    )
    ri_by_recipe: Dict[str, List[RecipeIngredientORM]] = {}
    for ri in ri_rows:
        ri_by_recipe.setdefault(ri.recipe_id, []).append(ri)

    demand_by_ing_day: Dict[str, Dict[int, float]] = {}
    for a in assignments:
        for ri in ri_by_recipe.get(a.recipe_id, []):
            by_day = demand_by_ing_day.setdefault(ri.ingredient_id, {})
            by_day[a.day_index] = by_day.get(a.day_index, 0.0) + (
                float(ri.raw_g_per_serving) * float(servings_per_day)
            )
    return plan_title, horizon_days, demand_by_ing_day


def compute_coverage_forecasts_for_kitchen(
    session: Session,
    *,
    kitchen_id: UUID,
    dataset_version_id: UUID,
    production_dt_utc: datetime,
    usable_lots_by_ing_id: Dict[str, List[Tuple[float, Optional[datetime]]]],
    safety_held_by_ing_id: Dict[str, float],
    unverified_by_ing_id: Dict[str, float],
) -> Dict[str, IngredientCoverageForecast]:
    """Deterministic FEFO stock duration & shortage forecast from verified unexpired lots vs active menu demand."""
    plan_title, horizon_days, demand_by_ing_day = _load_active_plan_daily_demand(
        session,
        kitchen_id=kitchen_id,
        dataset_version_id=dataset_version_id,
    )
    prod_jakarta_date = to_jakarta_date(production_dt_utc)

    forecasts: Dict[str, IngredientCoverageForecast] = {}
    all_ing_ids = set(usable_lots_by_ing_id.keys()) | set(demand_by_ing_day.keys())

    for ing_id in all_ing_ids:
        held_g = safety_held_by_ing_id.get(ing_id, 0.0)
        unver_g = unverified_by_ing_id.get(ing_id, 0.0)
        raw_lots = usable_lots_by_ing_id.get(ing_id, [])
        total_usable_g = sum(qty for qty, _ in raw_lots)

        if not plan_title or horizon_days <= 0:
            forecasts[ing_id] = IngredientCoverageForecast(
                coverage_status="NO_ACTIVE_PLAN",
                human_summary_id="Belum dapat diperkirakan — belum ada rencana menu aktif.",
            )
            continue

        day_demands = demand_by_ing_day.get(ing_id, {})
        total_horizon_demand_g = sum(day_demands.values())
        if total_horizon_demand_g <= 1e-6:
            forecasts[ing_id] = IngredientCoverageForecast(
                coverage_status="SUFFICIENT",
                planned_daily_usage_kg=0.0,
                planned_total_horizon_kg=0.0,
                estimated_coverage_days=horizon_days,
                horizon_days=horizon_days,
                covers_horizon_days=True,
                plan_title=plan_title,
                human_summary_id="Tidak dipakai dalam rencana menu aktif saat ini.",
            )
            continue

        avg_daily_g = total_horizon_demand_g / float(horizon_days)
        if total_usable_g <= 1e-6 and (held_g > 0 or unver_g > 0):
            reason = (
                "sedang ditahan keamanan"
                if held_g > 0
                else "belum terverifikasi atau tanpa tanggal kedaluwarsa"
            )
            forecasts[ing_id] = IngredientCoverageForecast(
                coverage_status="UNVERIFIED_OR_HELD",
                planned_daily_usage_kg=round(avg_daily_g / 1000.0, 2),
                planned_total_horizon_kg=round(total_horizon_demand_g / 1000.0, 2),
                estimated_coverage_days=0,
                horizon_days=horizon_days,
                covers_horizon_days=False,
                first_shortage_day_index=1,
                first_shortage_date=prod_jakarta_date,
                plan_title=plan_title,
                human_summary_id=f"Belum dapat diperkirakan — stok siap pakai 0 kg ({reason}).",
            )
            continue

        # Sort lots FEFO: earliest expiry first
        fefo_lots = [
            [float(qty), exp_dt]
            for qty, exp_dt in sorted(
                raw_lots,
                key=lambda item: (item[1] is None, item[1] or datetime.max),
            )
            if qty > 1e-6
        ]

        shortage_day: Optional[int] = None
        shortage_date: Optional[date] = None
        expired_unused_g = 0.0
        covered_days = 0

        # Simulate up to horizon + extra 30 days using avg daily rate after horizon
        max_sim_days = max(horizon_days, 1) + 30
        for day_idx in range(1, max_sim_days + 1):
            day_date = prod_jakarta_date + timedelta(days=day_idx - 1)
            day_start_utc = date_only_to_jakarta_production_dt(day_date)
            req_g = day_demands.get(day_idx, avg_daily_g if day_idx > horizon_days else 0.0)

            # Retire lots that have expired on or before day's 08:00 WIB production window
            for lot_entry in fefo_lots:
                if lot_entry[0] > 1e-6 and lot_entry[1] is not None and lot_entry[1] <= day_start_utc:
                    expired_unused_g += lot_entry[0]
                    lot_entry[0] = 0.0

            remaining_req = req_g
            for lot_entry in fefo_lots:
                if remaining_req <= 1e-6:
                    break
                if lot_entry[0] <= 1e-6:
                    continue
                take = min(lot_entry[0], remaining_req)
                lot_entry[0] -= take
                remaining_req -= take

            if remaining_req > 1e-4:
                if shortage_day is None:
                    shortage_day = day_idx
                    shortage_date = day_date
                break
            covered_days += 1

        covers_horizon = shortage_day is None or shortage_day > horizon_days
        if not covers_horizon and expired_unused_g > 1e-4:
            status = "EXPIRES_BEFORE_USE"
            summary_id = (
                f"Cukup {covered_days} hari; {expired_unused_g / 1000.0:.2f} kg kedaluwarsa sebelum hari ke-{shortage_day}."
            )
        elif not covers_horizon:
            status = "LOW_COVERAGE"
            summary_id = (
                f"Hanya cukup {covered_days} hari (kurang mulai hari ke-{shortage_day})."
            )
        else:
            status = "SUFFICIENT"
            days_txt = f"{covered_days}+" if covered_days >= max_sim_days else str(covered_days)
            summary_id = f"Cukup {days_txt} hari ke depan (sesuai rencana {horizon_days} hari)."

        forecasts[ing_id] = IngredientCoverageForecast(
            coverage_status=status,
            planned_daily_usage_kg=round(avg_daily_g / 1000.0, 2),
            planned_total_horizon_kg=round(total_horizon_demand_g / 1000.0, 2),
            estimated_coverage_days=covered_days,
            horizon_days=horizon_days,
            covers_horizon_days=covers_horizon,
            first_shortage_day_index=shortage_day,
            first_shortage_date=shortage_date,
            expires_before_use_kg=round(expired_unused_g / 1000.0, 2),
            plan_title=plan_title,
            human_summary_id=summary_id,
        )

    return forecasts
