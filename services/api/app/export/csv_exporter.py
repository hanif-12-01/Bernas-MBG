from __future__ import annotations

import csv
import io
from typing import Any, List

from app.domain.models.schemas import OptimizationRunResponse, SlotEnum, SolverStatusEnum

FORMULA_TRIGGER_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


class ExportConflictError(RuntimeError):
    """Raised when attempting to export an infeasible or unvalidated optimization run (409)."""


def escape_csv_formula(value: Any) -> Any:
    """Prevent spreadsheet CSV formula injection on string values.

    Numeric types are returned unchanged; strings starting with '=', '+', '-', '@', '\\t',
    or '\\r' (including after leading spaces) are prefixed with a single quote.
    """
    if value is None or isinstance(value, (int, float, bool)):
        return value
    text = str(value)
    if not text:
        return text
    stripped_leading = text.lstrip(" ")
    if text[0] in FORMULA_TRIGGER_PREFIXES or (
        stripped_leading and stripped_leading[0] in FORMULA_TRIGGER_PREFIXES
    ):
        return f"'{text}"
    return text


def export_run_to_csv(run: OptimizationRunResponse) -> str:
    """Render a validated feasible OptimizationRunResponse to a formula-safe UTF-8 CSV."""
    if (
        not run.validation_passed
        or run.solver_status in {SolverStatusEnum.INFEASIBLE, SolverStatusEnum.ERROR}
        or not run.days
    ):
        raise ExportConflictError(
            f"Run '{run.run_id}' cannot be exported because solver_status={run.solver_status.value} "
            f"or validation_passed={run.validation_passed} (AC-14)."
        )

    snap = run.input_snapshot or {}
    params = snap.get("scenario_params", {})

    # Collect only actually persisted nutrient keys — never fabricate missing nutrients
    nutrient_keys: List[str] = sorted(
        {k for day in run.days for k in day.nutrients_per_serving.keys()}
    )

    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\r\n")

    servings_val = run.servings_per_day if run.servings_per_day is not None else params.get("servings_per_day", "")
    days_val = run.days_count if run.days_count is not None else params.get("days", len(run.days))
    total_servings_val = (
        run.total_servings
        if run.total_servings is not None
        else (int(servings_val) * int(days_val) if str(servings_val).isdigit() and str(days_val).isdigit() else "")
    )
    total_slots_val = (
        run.total_menu_slots
        if run.total_menu_slots is not None
        else sum(len(d.recipes_by_slot) for d in run.days)
    )
    cost_per_day_val = (
        run.cost_per_day_average_idr
        if run.cost_per_day_average_idr is not None
        else (
            round(float(run.objective_total_idr) / max(1, int(days_val)), 2)
            if run.objective_total_idr is not None and str(days_val).isdigit()
            else ""
        )
    )

    # Metadata & governance banner
    metadata_rows = [
        ("meta_key", "meta_value"),
        ("simulation_only", str(run.simulation_only).lower()),
        (
            "compliance_notice",
            "SIMULATION_ONLY (DEMO_ONLY): Hasil simulasi teknis, bukan standar resmi BGN dan belum divalidasi ahli gizi.",
        ),
        ("run_id", str(run.run_id)),
        ("scenario_id", str(run.scenario_id)),
        ("dataset_version_id", str(run.dataset_version_id)),
        ("price_snapshot_id", run.price_snapshot_id),
        ("input_sha256", run.input_sha256),
        ("model_version", run.model_version),
        ("solver_status", run.solver_status.value),
        ("solver_name", run.solver_name or ""),
        ("solver_version", run.solver_version or ""),
        ("validation_passed", str(run.validation_passed).lower()),
        ("servings_per_day", servings_val),
        ("days", days_val),
        ("total_servings", total_servings_val),
        ("total_menu_slots", total_slots_val),
        ("budget_idr_per_serving", params.get("budget_idr_per_serving", "")),
        ("max_repeat_per_family", params.get("max_repeat_per_family", "")),
        ("excluded_allergens", ";".join(params.get("excluded_allergens", []))),
        ("objective_total_idr", run.objective_total_idr),
        ("total_ingredient_cost_idr", run.objective_total_idr),
        ("cost_per_day_average_idr", cost_per_day_val),
        ("cost_per_serving_average_idr", run.cost_per_serving_average_idr),
    ]
    for k, v in metadata_rows:
        writer.writerow([escape_csv_formula(k), escape_csv_formula(v)])

    writer.writerow([])

    # Menu schedule table matching persisted OptimizationRun
    header = [
        "day_index",
        "slot",
        "recipe_id",
        "recipe_name",
        "daily_cost_idr_per_serving",
    ] + [f"day_{k}" for k in nutrient_keys]
    writer.writerow([escape_csv_formula(col) for col in header])

    for day in sorted(run.days, key=lambda d: d.day_index):
        for slot in SlotEnum:
            if slot not in day.recipes_by_slot:
                continue
            row = [
                day.day_index,
                slot.value,
                str(day.recipes_by_slot[slot]),
                escape_csv_formula(day.recipe_names_by_slot.get(slot, "")),
                day.daily_cost_idr_per_serving,
            ] + [day.nutrients_per_serving.get(k, "") for k in nutrient_keys]
            writer.writerow(row)

    return buf.getvalue()
