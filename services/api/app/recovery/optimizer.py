from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional
from uuid import UUID

import pulp

from app.domain.models.schemas import (
    Ingredient,
    NutritionTargetProfile,
    RecipeFeatures,
    RecipeVariant,
    Scenario,
    SlotEnum,
    SolverStatusEnum,
)
from app.optimizer.model_builder import BuiltMILPModel, build_recipe_milp
from app.optimizer.solver import RawSolveResult, create_cbc_solver, solve_built_model


@dataclass
class MinDisruptionSolveOutcome:
    raw_result: RawSolveResult
    min_changed_slots: Optional[int]
    stage1_seconds: float
    stage2_seconds: float


def _build_disruption_expression(
    built: BuiltMILPModel,
    baseline_assignments: Dict[int, Dict[SlotEnum, UUID]],
) -> pulp.LpAffineExpression:
    """Construct exact slot-disruption count expression D(x) = sum_{d,s} (1 - x_{d, orig[d,s]})."""
    terms: List[pulp.LpAffineExpression | int] = []
    for d in built.days:
        day_orig = baseline_assignments.get(d, {})
        for slot in built.slots:
            orig_rid = day_orig.get(slot)
            if orig_rid is not None and (d, orig_rid) in built.x_vars:
                terms.append(1 - built.x_vars[(d, orig_rid)])
            else:
                terms.append(1)
    return pulp.lpSum(terms)


def count_slot_changes(
    baseline_assignments: Dict[int, Dict[SlotEnum, UUID]],
    candidate_assignments: Dict[int, Dict[SlotEnum, UUID]],
) -> int:
    """Count exact integer number of (day, slot) assignments differing from baseline."""
    changed = 0
    for d, orig_slots in baseline_assignments.items():
        cand_slots = candidate_assignments.get(d, {})
        for slot, orig_rid in orig_slots.items():
            if cand_slots.get(slot) != orig_rid:
                changed += 1
    return changed


def solve_minimum_disruption_milp(
    *,
    scenario: Scenario,
    recipes: List[RecipeVariant],
    features_by_id: Dict[UUID, RecipeFeatures],
    target: NutritionTargetProfile,
    stock_raw_g: Dict[str, float],
    baseline_assignments: Dict[int, Dict[SlotEnum, UUID]],
    ingredients_by_code: Optional[Dict[str, Ingredient]] = None,
    time_limit_seconds: float = 10.0,
) -> MinDisruptionSolveOutcome:
    """Solve exact two-stage lexicographic minimum-disruption MILP preserving all hard constraints.

    Stage 1: Minimize number of changed (day, slot) recipe assignments D subject to all
             nutrition, stock, budget, allergen, reviewed-only, repeat-cap, and slot-coverage rules.
    Stage 2: Minimize total procurement cost subject to all identical hard constraints AND
             D <= D_min proved in Stage 1.
    """
    half_budget_time = max(0.5, float(time_limit_seconds))

    # Stage 1: minimize slot swaps
    built_s1 = build_recipe_milp(
        scenario=scenario,
        recipes=recipes,
        features_by_id=features_by_id,
        target=target,
        stock_raw_g=stock_raw_g,
        ingredients_by_code=ingredients_by_code,
    )
    disruption_expr_s1 = _build_disruption_expression(built_s1, baseline_assignments)
    built_s1.problem.setObjective(disruption_expr_s1)

    solver_s1 = create_cbc_solver(time_limit_seconds=half_budget_time, gap_rel=0.0, gap_abs=0.0)
    raw_s1 = solve_built_model(built_s1, time_limit_seconds=half_budget_time, solver=solver_s1)

    if (
        raw_s1.solver_status in {SolverStatusEnum.INFEASIBLE, SolverStatusEnum.ERROR}
        or not raw_s1.has_incumbent
        or raw_s1.raw_x_values is None
    ):
        return MinDisruptionSolveOutcome(
            raw_result=raw_s1,
            min_changed_slots=None,
            stage1_seconds=raw_s1.solver_seconds,
            stage2_seconds=0.0,
        )

    d_min = count_slot_changes(baseline_assignments, raw_s1.assignments_by_day)

    # Stage 2: minimize procurement cost while holding D <= D_min
    built_s2 = build_recipe_milp(
        scenario=scenario,
        recipes=recipes,
        features_by_id=features_by_id,
        target=target,
        stock_raw_g=stock_raw_g,
        ingredients_by_code=ingredients_by_code,
    )
    disruption_expr_s2 = _build_disruption_expression(built_s2, baseline_assignments)
    built_s2.problem += (disruption_expr_s2 <= d_min, "lexicographic_min_disruption_cap")

    solver_s2 = create_cbc_solver(time_limit_seconds=half_budget_time, gap_rel=0.0, gap_abs=0.0)
    raw_s2 = solve_built_model(built_s2, time_limit_seconds=half_budget_time, solver=solver_s2)

    return MinDisruptionSolveOutcome(
        raw_result=raw_s2,
        min_changed_slots=d_min,
        stage1_seconds=raw_s1.solver_seconds,
        stage2_seconds=raw_s2.solver_seconds,
    )
