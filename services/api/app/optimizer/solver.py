from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple
from uuid import UUID

import pulp
from pulp.constants import LpSolveStatus

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

INTEGRALITY_TOLERANCE = 1e-6
OPTIMALITY_GAP_ABS_TOL = 1e-6
OPTIMALITY_GAP_REL_TOL = 1e-9


@dataclass
class RawSolveResult:
    solver_status: SolverStatusEnum
    solver_seconds: float
    assignments_by_day: Dict[int, Dict[SlotEnum, UUID]]
    has_incumbent: bool
    raw_x_values: Optional[Dict[Tuple[int, UUID], Optional[float]]] = None
    reported_objective: Optional[float] = None
    best_bound: Optional[float] = None
    gap_abs: Optional[float] = None
    gap_rel: Optional[float] = None
    solver_name: Optional[str] = None
    solver_version: Optional[str] = None
    raw_solver_status: Optional[str] = None
    error_message: Optional[str] = None


def create_cbc_solver(
    time_limit_seconds: float = 10.0,
    gap_rel: float = 0.0,
    gap_abs: float = 0.0,
) -> pulp.LpSolver:
    """Resolve an available CBC solver configured for exact optimality (gapRel=0, gapAbs=0)."""
    if hasattr(pulp, "PULP_CBC_CMD"):
        solver = pulp.PULP_CBC_CMD(
            msg=False, timeLimit=time_limit_seconds, gapRel=gap_rel, gapAbs=gap_abs
        )
        if solver.available():
            return solver

    for name in ("COIN_CMD", "HiGHS", "HiGHS_CMD", "GLPK_CMD"):
        try:
            kwargs = {"msg": False, "timeLimit": time_limit_seconds}
            if name == "COIN_CMD":
                kwargs["gapRel"] = gap_rel
                kwargs["gapAbs"] = gap_abs
            solver = pulp.getSolver(name, **kwargs)
            if solver.available():
                return solver
        except Exception:
            continue

    available = pulp.listSolvers(onlyAvailable=True)
    for name in available:
        try:
            return pulp.getSolver(name, msg=False, timeLimit=time_limit_seconds)
        except Exception:
            continue

    raise RuntimeError(
        "No MILP solver available for PuLP. Install 'pulp[cbc]' or ensure CBC is on PATH."
    )


def extract_raw_x_values(
    built: BuiltMILPModel,
) -> Dict[Tuple[int, UUID], Optional[float]]:
    """Extract raw solver values for every binary decision variable without thresholding."""
    return {(d, rid): pulp.value(var) for (d, rid), var in built.x_vars.items()}


def extract_assignments_from_raw_x(
    raw_x_values: Dict[Tuple[int, UUID], Optional[float]],
    eligible_features: Dict[UUID, RecipeFeatures],
    days: list[int],
    int_tol: float = INTEGRALITY_TOLERANCE,
) -> Tuple[Dict[int, Dict[SlotEnum, UUID]], bool]:
    """Convert raw x values to day->slot->recipe map ONLY if binary and non-overlapping.

    Returns (assignments_by_day, is_clean_complete_integer_incumbent).
    Even when non-integer or overlapping, returns partial map so verifier can report exact violations.
    """
    assignments: Dict[int, Dict[SlotEnum, UUID]] = {d: {} for d in days}
    clean = True
    seen_slots: Dict[Tuple[int, SlotEnum], int] = {}

    for (d, rid), val in raw_x_values.items():
        if val is None or not math.isfinite(val):
            clean = False
            continue
        near_zero = abs(val) <= int_tol
        near_one = abs(val - 1.0) <= int_tol
        if not (near_zero or near_one):
            clean = False
        if val > 0.5:
            feat = eligible_features.get(rid)
            if feat is None or d not in assignments:
                clean = False
                continue
            key = (d, feat.slot)
            seen_slots[key] = seen_slots.get(key, 0) + 1
            if seen_slots[key] > 1:
                clean = False
            assignments[d][feat.slot] = rid

    expected_slots = set(SlotEnum)
    complete = all(set(assignments.get(d, {}).keys()) == expected_slots for d in days)
    return assignments, (clean and complete)


def classify_solve_stats(
    status: object,
    has_solution: bool,
    objective: Optional[float],
    best_bound: Optional[float],
    gap_abs: Optional[float],
    gap_rel: Optional[float],
    solver_log_status: Optional[str],
) -> Tuple[SolverStatusEnum, Optional[str]]:
    """Strictly classify PuLP 4.x LpSolveStats into SolverStatusEnum.

    Rules:
    - OPTIMAL requires either:
        (a) LpSolveStatus.Optimal with has_solution=True and finite objective, OR
        (b) LpSolveStatus.GapLimit ONLY when has_solution=True, both objective and
            best_bound are finite, gap_abs <= 1e-6, gap_rel <= 1e-9, AND the raw solver
            log explicitly states "Optimal solution found".
    - GapLimit with has_solution=True that lacks full optimality proof stays FEASIBLE.
    - Never returns OPTIMAL or FEASIBLE when has_solution=False.
    """
    finite_obj = objective is not None and math.isfinite(objective)
    finite_bound = best_bound is not None and math.isfinite(best_bound)

    if status == LpSolveStatus.Infeasible:
        return SolverStatusEnum.INFEASIBLE, None

    if status == LpSolveStatus.Optimal:
        if has_solution and finite_obj:
            return SolverStatusEnum.OPTIMAL, None
        return (
            SolverStatusEnum.ERROR,
            "Solver reported Optimal without a valid finite incumbent solution",
        )

    if status == LpSolveStatus.GapLimit:
        if not (has_solution and finite_obj):
            return (
                SolverStatusEnum.ERROR,
                "Solver reported GapLimit without a feasible incumbent solution",
            )
        proven_zero_gap = (
            finite_bound
            and gap_abs is not None
            and math.isfinite(gap_abs)
            and gap_abs <= OPTIMALITY_GAP_ABS_TOL
            and gap_rel is not None
            and math.isfinite(gap_rel)
            and gap_rel <= OPTIMALITY_GAP_REL_TOL
            and solver_log_status == "Optimal solution found"
        )
        if proven_zero_gap:
            return SolverStatusEnum.OPTIMAL, None
        return SolverStatusEnum.FEASIBLE, None

    if status == LpSolveStatus.SolutionLimit:
        if has_solution and finite_obj:
            return SolverStatusEnum.FEASIBLE, None
        return (
            SolverStatusEnum.ERROR,
            "Solver stopped on SolutionLimit without a feasible solution",
        )

    if status in {
        LpSolveStatus.TimeLimit,
        LpSolveStatus.NodeLimit,
        LpSolveStatus.IterationLimit,
        LpSolveStatus.NotSolved,
        LpSolveStatus.Stopped,
    }:
        return SolverStatusEnum.TIME_LIMIT, None

    return SolverStatusEnum.ERROR, f"Solver returned status {status!r}"


def solve_built_model(
    built: BuiltMILPModel,
    time_limit_seconds: float = 10.0,
    solver: Optional[pulp.LpSolver] = None,
) -> RawSolveResult:
    """Solve MILP via PuLP/CBC and map LpSolveStats explicitly into RawSolveResult."""
    t0 = time.perf_counter()
    try:
        chosen_solver = (
            solver if solver is not None else create_cbc_solver(time_limit_seconds=time_limit_seconds)
        )
        solve_stats = built.problem.solve(chosen_solver)
    except Exception as exc:
        elapsed = time.perf_counter() - t0
        return RawSolveResult(
            solver_status=SolverStatusEnum.ERROR,
            solver_seconds=round(elapsed, 4),
            assignments_by_day={},
            has_incumbent=False,
            error_message=str(exc),
        )

    elapsed = round(time.perf_counter() - t0, 4)
    status = getattr(solve_stats, "status", solve_stats)
    has_solution = bool(getattr(solve_stats, "has_solution", False))
    objective = getattr(solve_stats, "objective", None)
    best_bound = getattr(solve_stats, "best_bound", None)
    gap_abs = getattr(solve_stats, "gap_abs", None)
    gap_rel = getattr(solve_stats, "gap_rel", None)
    solver_name = getattr(solve_stats, "solver", None)
    solver_version = getattr(solve_stats, "solver_version", None)
    solver_log_status = getattr(solve_stats, "solver_status", None)
    raw_status_label = getattr(solve_stats, "status_str", str(status))

    mapped_status, error_msg = classify_solve_stats(
        status=status,
        has_solution=has_solution,
        objective=objective,
        best_bound=best_bound,
        gap_abs=gap_abs,
        gap_rel=gap_rel,
        solver_log_status=solver_log_status,
    )

    if mapped_status in {SolverStatusEnum.INFEASIBLE, SolverStatusEnum.ERROR}:
        return RawSolveResult(
            solver_status=mapped_status,
            solver_seconds=elapsed,
            assignments_by_day={},
            has_incumbent=False,
            raw_x_values=None,
            reported_objective=None,
            best_bound=best_bound,
            gap_abs=gap_abs,
            gap_rel=gap_rel,
            solver_name=solver_name,
            solver_version=solver_version,
            raw_solver_status=raw_status_label,
            error_message=error_msg,
        )

    if not has_solution:
        return RawSolveResult(
            solver_status=mapped_status,
            solver_seconds=elapsed,
            assignments_by_day={},
            has_incumbent=False,
            raw_x_values=None,
            reported_objective=None,
            best_bound=best_bound,
            gap_abs=gap_abs,
            gap_rel=gap_rel,
            solver_name=solver_name,
            solver_version=solver_version,
            raw_solver_status=raw_status_label,
        )

    raw_x = extract_raw_x_values(built)
    assignments, is_clean_incumbent = extract_assignments_from_raw_x(
        raw_x, built.eligible_features, built.days
    )

    return RawSolveResult(
        solver_status=mapped_status,
        solver_seconds=elapsed,
        assignments_by_day=assignments,
        has_incumbent=is_clean_incumbent,
        raw_x_values=raw_x,
        reported_objective=objective,
        best_bound=best_bound,
        gap_abs=gap_abs,
        gap_rel=gap_rel,
        solver_name=solver_name,
        solver_version=solver_version,
        raw_solver_status=raw_status_label,
    )


def _attach_cross_week_boundary_penalty(
    built: BuiltMILPModel,
    scenario: Scenario,
    history_days: Sequence[Any],
    window_days: int = 5,
) -> pulp.LpAffineExpression:
    """Attach soft slack constraints for 5-day cross-week sliding-window family repeat
    and boundary recipe repeat, returning the weighted penalty expression on NEW decisions only.

    History is treated as immutable fact: because every boundary constraint includes a
    non-negative slack variable, history can NEVER make a feasible new week INFEASIBLE.
    """
    hist = list(history_days)[-window_days:]
    if not hist:
        return pulp.lpSum([])

    prob = built.problem
    x = built.x_vars
    eligible = built.eligible_features
    days = built.days
    hist_len = len(hist)

    families: Dict[str, List[UUID]] = {}
    for rid, feat in eligible.items():
        families.setdefault(feat.family, []).append(rid)

    penalty_terms: List[Any] = []

    # 1. Sliding 5-day family repeat window spanning history suffix + new week prefix
    max_k = min(window_days - 1, len(days))
    for k in range(1, max_k + 1):
        hist_take = window_days - k
        hist_suffix = hist[max(0, hist_len - hist_take) :]
        if not hist_suffix:
            continue
        hist_fam_counts: Dict[str, int] = {}
        for hd in hist_suffix:
            for fam in hd.families_by_slot.values():
                hist_fam_counts[fam] = hist_fam_counts.get(fam, 0) + 1

        for family, rids in sorted(families.items()):
            h_cnt = hist_fam_counts.get(family, 0)
            if h_cnt <= 0:
                continue
            allowed_new = max(0, scenario.max_repeat_per_family - h_cnt)
            slack = prob.add_variable(
                f"slack_cw_k{k}_{family[:20]}_{len(penalty_terms)}",
                lowBound=0.0,
                cat="Continuous",
            )
            prob += (
                pulp.lpSum(x[(d, rid)] for d in days[:k] for rid in rids) - slack
                <= allowed_new,
                f"cw_fam_win_k{k}_{family[:20]}_{len(penalty_terms)}",
            )
            penalty_terms.append(5.0 * slack)

    # 2. Boundary exact recipe repetition penalty (Day 5 -> Day 1 strongest, plus recent 5-day context)
    last_day_codes = set(hist[-1].recipe_codes_by_slot.values())
    recent_2_codes = {
        code for hd in hist[-2:] for code in hd.recipe_codes_by_slot.values()
    }
    recent_all_codes = {
        code for hd in hist for code in hd.recipe_codes_by_slot.values()
    }

    if 1 in days:
        for rid, feat in eligible.items():
            if feat.recipe_code in last_day_codes:
                penalty_terms.append(10.0 * x[(1, rid)])
            elif feat.recipe_code in recent_2_codes:
                penalty_terms.append(6.0 * x[(1, rid)])
            elif feat.recipe_code in recent_all_codes:
                penalty_terms.append(2.0 * x[(1, rid)])

    if 2 in days:
        for rid, feat in eligible.items():
            if feat.recipe_code in last_day_codes:
                penalty_terms.append(4.0 * x[(2, rid)])
            elif feat.recipe_code in recent_all_codes:
                penalty_terms.append(1.0 * x[(2, rid)])

    return pulp.lpSum(penalty_terms)


def solve_with_cross_week_history(
    scenario: Scenario,
    recipes: List[RecipeVariant],
    features_by_id: Dict[UUID, RecipeFeatures],
    target: NutritionTargetProfile,
    stock_raw_g: Dict[str, float],
    history_days: Sequence[Any],
    *,
    ingredients_by_code: Optional[Dict[str, Ingredient]] = None,
    usable_stock_by_day: Optional[Dict[int, Dict[str, float]]] = None,
    time_limit_seconds: float = 10.0,
    window_days: int = 5,
) -> Tuple[RawSolveResult, Optional[float]]:
    """Lexicographic 2-stage MILP solver for cross-week menu planning:
    Stage 1: Minimize cross-week boundary repetition penalty (soft slack >= 0) subject to ALL hard constraints.
    Stage 2: Minimize total procurement cost subject to boundary penalty <= S_min + 1e-6.
    """
    built1 = build_recipe_milp(
        scenario=scenario,
        recipes=recipes,
        features_by_id=features_by_id,
        target=target,
        stock_raw_g=stock_raw_g,
        ingredients_by_code=ingredients_by_code,
        usable_stock_by_day=usable_stock_by_day,
    )
    if not history_days:
        return solve_built_model(built1, time_limit_seconds=time_limit_seconds), 0.0

    half_limit = max(2.0, time_limit_seconds * 0.5)
    penalty1 = _attach_cross_week_boundary_penalty(built1, scenario, history_days, window_days=window_days)
    built1.problem.setObjective(penalty1)
    stage1 = solve_built_model(built1, time_limit_seconds=half_limit)
    if (
        stage1.solver_status in {SolverStatusEnum.INFEASIBLE, SolverStatusEnum.ERROR}
        or not stage1.has_incumbent
    ):
        return stage1, None

    s_min = float(stage1.reported_objective or 0.0)

    built2 = build_recipe_milp(
        scenario=scenario,
        recipes=recipes,
        features_by_id=features_by_id,
        target=target,
        stock_raw_g=stock_raw_g,
        ingredients_by_code=ingredients_by_code,
        usable_stock_by_day=usable_stock_by_day,
    )
    penalty2 = _attach_cross_week_boundary_penalty(built2, scenario, history_days, window_days=window_days)
    built2.problem += penalty2 <= s_min + 1e-6, "cw_lexicographic_penalty_bound"
    stage2 = solve_built_model(built2, time_limit_seconds=half_limit)
    stage2.solver_seconds = round(stage1.solver_seconds + stage2.solver_seconds, 4)
    return stage2, round(s_min, 4)
