from __future__ import annotations

from typing import Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.domain.models.schemas import OptimizationRunResponse, SlotEnum, SolverStatusEnum


class RunSummary(BaseModel):
    run_id: UUID
    scenario_id: UUID
    dataset_version_id: UUID
    solver_status: SolverStatusEnum
    validation_passed: bool
    simulation_only: bool
    objective_total_idr: Optional[float]
    cost_per_serving_average_idr: Optional[float]
    input_sha256: str
    model_version: str
    solver_name: Optional[str]
    solver_version: Optional[str]


class PriceDiffItem(BaseModel):
    ingredient_code: str
    base_price_idr_per_g: Optional[float]
    candidate_price_idr_per_g: Optional[float]
    delta_pct: Optional[float]


class StockDiffItem(BaseModel):
    ingredient_code: str
    base_stock_raw_g: Optional[float]
    candidate_stock_raw_g: Optional[float]


class InputCompatibility(BaseModel):
    same_dataset_version: bool
    same_nutrition_target: bool
    same_horizon_and_servings: bool
    same_prices: bool
    same_stock: bool
    same_constraints: bool
    changed_prices: List[PriceDiffItem] = Field(default_factory=list)
    changed_stock: List[StockDiffItem] = Field(default_factory=list)
    constraint_differences: List[str] = Field(default_factory=list)
    apples_to_apples_comparable: bool
    comparison_basis: str


class CostComparison(BaseModel):
    base_total_idr: Optional[float]
    candidate_total_idr: Optional[float]
    delta_total_idr: Optional[float]
    base_cost_per_serving_idr: Optional[float]
    candidate_cost_per_serving_idr: Optional[float]
    delta_cost_per_serving_idr: Optional[float]
    delta_cost_pct: Optional[float]
    cost_savings_achieved_idr: Optional[float]
    cost_savings_pct: Optional[float]
    interpretation: str


class NutrientComparisonItem(BaseModel):
    nutrient_key: str
    unit: str
    min_per_serving: Optional[float]
    max_per_serving: Optional[float]
    base_avg_per_serving: Optional[float]
    candidate_avg_per_serving: Optional[float]
    delta_avg_per_serving: Optional[float]
    base_min_margin_above_floor: Optional[float]
    candidate_min_margin_above_floor: Optional[float]
    base_min_margin_below_ceiling: Optional[float]
    candidate_min_margin_below_ceiling: Optional[float]


class RecipeSwapItem(BaseModel):
    day_index: int
    slot: SlotEnum
    base_recipe_name: Optional[str]
    candidate_recipe_name: Optional[str]
    changed: bool


class IngredientUsageDiffItem(BaseModel):
    ingredient_code: str
    ingredient_name: str
    base_used_raw_g: float
    candidate_used_raw_g: float
    delta_raw_g: float
    base_available_raw_g: Optional[float]
    candidate_available_raw_g: Optional[float]
    base_utilization_pct: Optional[float]
    candidate_utilization_pct: Optional[float]


class ScenarioComparisonResponse(BaseModel):
    base: RunSummary
    candidate: RunSummary
    compatibility: InputCompatibility
    cost_comparison: CostComparison
    nutrient_comparison: List[NutrientComparisonItem] = Field(default_factory=list)
    recipe_changes: List[RecipeSwapItem] = Field(default_factory=list)
    total_slot_swaps: int = 0
    ingredient_usage_comparison: List[IngredientUsageDiffItem] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


def _summarize(run: OptimizationRunResponse) -> RunSummary:
    return RunSummary(
        run_id=run.run_id,
        scenario_id=run.scenario_id,
        dataset_version_id=run.dataset_version_id,
        solver_status=run.solver_status,
        validation_passed=run.validation_passed,
        simulation_only=run.simulation_only,
        objective_total_idr=run.objective_total_idr,
        cost_per_serving_average_idr=run.cost_per_serving_average_idr,
        input_sha256=run.input_sha256,
        model_version=run.model_version,
        solver_name=run.solver_name,
        solver_version=run.solver_version,
    )


def compare_runs(
    base: OptimizationRunResponse,
    candidate: OptimizationRunResponse,
) -> ScenarioComparisonResponse:
    """Compare two persisted optimization runs without fabricating savings across infeasible or changed-input runs."""
    base_snap = base.input_snapshot or {}
    cand_snap = candidate.input_snapshot or {}

    base_params = base_snap.get("scenario_params", {})
    cand_params = cand_snap.get("scenario_params", {})
    base_target = base_snap.get("nutrition_target", {})
    cand_target = cand_snap.get("nutrition_target", {})

    same_dataset = base.dataset_version_id == candidate.dataset_version_id
    same_target = base_target == cand_target
    same_horizon = (
        base_params.get("days") == cand_params.get("days")
        and base_params.get("servings_per_day") == cand_params.get("servings_per_day")
    )

    base_prices: Dict[str, float] = base_snap.get("prices_idr_per_g", {})
    cand_prices: Dict[str, float] = cand_snap.get("prices_idr_per_g", {})
    changed_prices: List[PriceDiffItem] = []
    for code in sorted(set(base_prices.keys()) | set(cand_prices.keys())):
        bp = base_prices.get(code)
        cp = cand_prices.get(code)
        if bp != cp:
            dpct = round(((cp - bp) / bp) * 100.0, 2) if (bp is not None and cp is not None and bp > 0) else None
            changed_prices.append(
                PriceDiffItem(
                    ingredient_code=code,
                    base_price_idr_per_g=bp,
                    candidate_price_idr_per_g=cp,
                    delta_pct=dpct,
                )
            )
    same_prices = len(changed_prices) == 0

    base_stock: Dict[str, float] = base_snap.get("stock_raw_g", {})
    cand_stock: Dict[str, float] = cand_snap.get("stock_raw_g", {})
    changed_stock: List[StockDiffItem] = []
    for code in sorted(set(base_stock.keys()) | set(cand_stock.keys())):
        bs = base_stock.get(code)
        cs = cand_stock.get(code)
        if bs != cs:
            changed_stock.append(
                StockDiffItem(
                    ingredient_code=code,
                    base_stock_raw_g=bs,
                    candidate_stock_raw_g=cs,
                )
            )
    same_stock = len(changed_stock) == 0

    constraint_diffs: List[str] = []
    for key in ("budget_idr_per_serving", "max_repeat_per_family", "excluded_allergens"):
        if base_params.get(key) != cand_params.get(key):
            constraint_diffs.append(
                f"{key}: base={base_params.get(key)!r} vs candidate={cand_params.get(key)!r}"
            )
    same_constraints = len(constraint_diffs) == 0 and same_target and same_stock

    both_valid = (
        base.validation_passed
        and candidate.validation_passed
        and base.objective_total_idr is not None
        and candidate.objective_total_idr is not None
    )

    apples_to_apples = (
        both_valid
        and same_dataset
        and same_horizon
        and same_prices
        and same_constraints
    )

    if not both_valid:
        basis = "not_comparable_infeasible"
    elif apples_to_apples:
        basis = "apples_to_apples_optimization"
    else:
        basis = "input_price_or_constraint_change"

    compatibility = InputCompatibility(
        same_dataset_version=same_dataset,
        same_nutrition_target=same_target,
        same_horizon_and_servings=same_horizon,
        same_prices=same_prices,
        same_stock=same_stock,
        same_constraints=same_constraints,
        changed_prices=changed_prices,
        changed_stock=changed_stock,
        constraint_differences=constraint_diffs,
        apples_to_apples_comparable=apples_to_apples,
        comparison_basis=basis,
    )

    warnings: List[str] = []
    if base.simulation_only or candidate.simulation_only:
        warnings.append("SIMULATION_ONLY: Perbandingan berbasis data sintetis DEMO_ONLY.")

    if not both_valid:
        warnings.append(
            "Salah satu atau kedua run tidak feasible / tidak lolos independent validator; tidak ada klaim penghematan biaya."
        )
        cost_comp = CostComparison(
            base_total_idr=base.objective_total_idr,
            candidate_total_idr=candidate.objective_total_idr,
            delta_total_idr=None,
            base_cost_per_serving_idr=base.cost_per_serving_average_idr,
            candidate_cost_per_serving_idr=candidate.cost_per_serving_average_idr,
            delta_cost_per_serving_idr=None,
            delta_cost_pct=None,
            cost_savings_achieved_idr=None,
            cost_savings_pct=None,
            interpretation="Not comparable: at least one run is infeasible or unvalidated. No cost savings reported.",
        )
    else:
        assert base.objective_total_idr is not None and candidate.objective_total_idr is not None
        assert (
            base.cost_per_serving_average_idr is not None
            and candidate.cost_per_serving_average_idr is not None
        )
        delta_total = round(candidate.objective_total_idr - base.objective_total_idr, 2)
        delta_serving = round(
            candidate.cost_per_serving_average_idr - base.cost_per_serving_average_idr, 2
        )
        delta_pct = (
            round((delta_total / base.objective_total_idr) * 100.0, 4)
            if base.objective_total_idr > 0
            else None
        )

        if apples_to_apples:
            savings_idr = round(base.objective_total_idr - candidate.objective_total_idr, 2)
            savings_pct = (
                round((savings_idr / base.objective_total_idr) * 100.0, 4)
                if base.objective_total_idr > 0
                else None
            )
            interp = (
                "Apples-to-apples comparison on identical dataset, prices, stock, and constraints."
            )
        else:
            savings_idr = None
            savings_pct = None
            reasons = []
            if not same_prices:
                reasons.append("input prices")
            if not same_stock:
                reasons.append("stock limits")
            if constraint_diffs or not same_target:
                reasons.append("constraints/targets")
            if not same_dataset:
                reasons.append("dataset version")
            if not same_horizon:
                reasons.append("horizon/servings")
            interp = (
                f"Scenario delta under different {', '.join(reasons)}; "
                "not reported as pure optimization savings."
            )
            warnings.append(interp)

        cost_comp = CostComparison(
            base_total_idr=base.objective_total_idr,
            candidate_total_idr=candidate.objective_total_idr,
            delta_total_idr=delta_total,
            base_cost_per_serving_idr=base.cost_per_serving_average_idr,
            candidate_cost_per_serving_idr=candidate.cost_per_serving_average_idr,
            delta_cost_per_serving_idr=delta_serving,
            delta_cost_pct=delta_pct,
            cost_savings_achieved_idr=savings_idr,
            cost_savings_pct=savings_pct,
            interpretation=interp,
        )

    # Nutrient averages & constraint margins
    limits_map: Dict[str, dict] = {
        lim["nutrient_key"]: lim for lim in (base_target.get("limits") or cand_target.get("limits") or [])
    }
    nutrient_keys = sorted(
        set(limits_map.keys())
        | {k for d in base.days for k in d.nutrients_per_serving.keys()}
        | {k for d in candidate.days for k in d.nutrients_per_serving.keys()}
    )

    def _avg_and_margins(
        run: OptimizationRunResponse, key: str, min_v: Optional[float], max_v: Optional[float]
    ):
        vals = [d.nutrients_per_serving[key] for d in run.days if key in d.nutrients_per_serving]
        if not vals:
            return None, None, None
        avg = round(sum(vals) / len(vals), 3)
        margin_floor = round(min(v - min_v for v in vals), 3) if min_v is not None else None
        margin_ceil = round(min(max_v - v for v in vals), 3) if max_v is not None else None
        return avg, margin_floor, margin_ceil

    nutrient_comp: List[NutrientComparisonItem] = []
    for k in nutrient_keys:
        lim = limits_map.get(k, {})
        min_v = lim.get("min_per_serving")
        max_v = lim.get("max_per_serving")
        b_avg, b_mf, b_mc = _avg_and_margins(base, k, min_v, max_v)
        c_avg, c_mf, c_mc = _avg_and_margins(candidate, k, min_v, max_v)
        delta_avg = round(c_avg - b_avg, 3) if (b_avg is not None and c_avg is not None) else None
        nutrient_comp.append(
            NutrientComparisonItem(
                nutrient_key=k,
                unit=lim.get("unit", ""),
                min_per_serving=min_v,
                max_per_serving=max_v,
                base_avg_per_serving=b_avg,
                candidate_avg_per_serving=c_avg,
                delta_avg_per_serving=delta_avg,
                base_min_margin_above_floor=b_mf,
                candidate_min_margin_above_floor=c_mf,
                base_min_margin_below_ceiling=b_mc,
                candidate_min_margin_below_ceiling=c_mc,
            )
        )

    # Recipe swaps per (day_index, slot)
    base_days_map = {d.day_index: d for d in base.days}
    cand_days_map = {d.day_index: d for d in candidate.days}
    all_days = sorted(set(base_days_map.keys()) | set(cand_days_map.keys()))
    recipe_changes: List[RecipeSwapItem] = []
    swaps = 0
    for d_idx in all_days:
        bd = base_days_map.get(d_idx)
        cd = cand_days_map.get(d_idx)
        for slot in SlotEnum:
            b_name = bd.recipe_names_by_slot.get(slot) if bd else None
            c_name = cd.recipe_names_by_slot.get(slot) if cd else None
            changed = b_name != c_name
            if changed:
                swaps += 1
            recipe_changes.append(
                RecipeSwapItem(
                    day_index=d_idx,
                    slot=slot,
                    base_recipe_name=b_name,
                    candidate_recipe_name=c_name,
                    changed=changed,
                )
            )

    # Ingredient usage & stock utilization diff
    base_mu = {m.ingredient_code: m for m in base.material_usage}
    cand_mu = {m.ingredient_code: m for m in candidate.material_usage}
    ing_diff: List[IngredientUsageDiffItem] = []
    for code in sorted(set(base_mu.keys()) | set(cand_mu.keys())):
        bm = base_mu.get(code)
        cm = cand_mu.get(code)
        name = (bm.ingredient_name if bm else cm.ingredient_name) if (bm or cm) else code
        b_used = bm.used_raw_g if bm else 0.0
        c_used = cm.used_raw_g if cm else 0.0
        b_avail = bm.available_raw_g if bm else base_stock.get(code)
        c_avail = cm.available_raw_g if cm else cand_stock.get(code)
        b_util = round((b_used / b_avail) * 100.0, 2) if (b_avail and b_avail > 0) else None
        c_util = round((c_used / c_avail) * 100.0, 2) if (c_avail and c_avail > 0) else None
        ing_diff.append(
            IngredientUsageDiffItem(
                ingredient_code=code,
                ingredient_name=name,
                base_used_raw_g=round(b_used, 2),
                candidate_used_raw_g=round(c_used, 2),
                delta_raw_g=round(c_used - b_used, 2),
                base_available_raw_g=b_avail,
                candidate_available_raw_g=c_avail,
                base_utilization_pct=b_util,
                candidate_utilization_pct=c_util,
            )
        )

    return ScenarioComparisonResponse(
        base=_summarize(base),
        candidate=_summarize(candidate),
        compatibility=compatibility,
        cost_comparison=cost_comp,
        nutrient_comparison=nutrient_comp,
        recipe_changes=recipe_changes,
        total_slot_swaps=swaps,
        ingredient_usage_comparison=ing_diff,
        warnings=warnings,
    )
