from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple
from uuid import UUID

import pulp
from pulp.constants import LpSolveStatus

from app.domain.models.schemas import (
    RecipeFeatures,
    SlotEnum,
    SolverStatusEnum,
)
from app.optimizer.model_builder import BuiltMILPModel

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
