from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional
from uuid import UUID

from app.domain.models.schemas import (
    ConstraintAudit,
    DayPlan,
    DiagnosticHint,
    MaterialUsage,
    NutritionTargetProfile,
    OptimizationRunResponse,
    PriceOverridesRequest,
    RecipeFeatures,
    RecipeVariant,
    Scenario,
    ScenarioCloneRequest,
    ScenarioCreateRequest,
    SlotEnum,
    SolverStatusEnum,
    StockOverridesRequest,
)
from app.domain.recipe_calculator import precompute_all_recipes
from app.ingestion.unit_converter import (
    DataValidationError,
    UnitConversionError,
    convert_price_to_idr_per_g,
)
from app.optimizer.diagnostics import diagnose_infeasibility
from app.optimizer.model_builder import build_recipe_milp
from app.optimizer.solver import RawSolveResult, create_cbc_solver, solve_built_model
from app.optimizer.verifier import verify_assignments
from app.scenarios.store import InMemoryVaultStore

MODEL_VERSION = "recipe-milp-v0.1"


class ResourceNotFoundError(LookupError):
    """Raised when dataset, target, scenario, or run does not exist (404)."""


class ScenarioConflictError(RuntimeError):
    """Raised when attempting to mutate a locked scenario (409)."""


def create_scenario(store: InMemoryVaultStore, req: ScenarioCreateRequest) -> Scenario:
    dataset_id = req.dataset_version_id or store.default_dataset_id
    target_id = req.nutrition_target_id or store.default_target_id

    if dataset_id not in store.datasets:
        raise ResourceNotFoundError(f"Dataset version '{dataset_id}' not found")
    if target_id not in store.targets:
        raise ResourceNotFoundError(f"Nutrition target '{target_id}' not found")

    scenario = Scenario(
        name=req.name,
        dataset_version_id=dataset_id,
        nutrition_target_id=target_id,
        meal_type=req.meal_type,
        servings_per_day=req.servings_per_day,
        days=req.days,
        budget_idr_per_serving=req.budget_idr_per_serving,
        max_repeat_per_family=req.max_repeat_per_family,
        excluded_allergens=list(req.excluded_allergens),
        source_label=req.source_label,
    )
    store.scenarios[scenario.id] = scenario
    return scenario


def clone_scenario(
    store: InMemoryVaultStore,
    scenario_id: UUID,
    req: Optional[ScenarioCloneRequest] = None,
) -> Scenario:
    base = store.scenarios.get(scenario_id)
    if base is None:
        raise ResourceNotFoundError(f"Scenario '{scenario_id}' not found")

    new_name = req.name if req and req.name else f"{base.name} (Clone)"
    cloned = Scenario(
        name=new_name,
        parent_scenario_id=base.id,
        dataset_version_id=base.dataset_version_id,
        nutrition_target_id=base.nutrition_target_id,
        meal_type=base.meal_type,
        servings_per_day=base.servings_per_day,
        days=base.days,
        budget_idr_per_serving=base.budget_idr_per_serving,
        max_repeat_per_family=base.max_repeat_per_family,
        excluded_allergens=list(base.excluded_allergens),
        price_overrides_idr_per_g=dict(base.price_overrides_idr_per_g),
        stock_overrides_raw_g=dict(base.stock_overrides_raw_g),
        source_label=base.source_label,
        locked=False,
    )
    store.scenarios[cloned.id] = cloned
    return cloned


def apply_price_overrides(
    store: InMemoryVaultStore,
    scenario_id: UUID,
    req: PriceOverridesRequest,
) -> Scenario:
    scenario = store.scenarios.get(scenario_id)
    if scenario is None:
        raise ResourceNotFoundError(f"Scenario '{scenario_id}' not found")
    if scenario.locked:
        raise ScenarioConflictError(
            f"Scenario '{scenario_id}' is locked after optimization; clone it to create a what-if scenario"
        )

    new_overrides = dict(scenario.price_overrides_idr_per_g)
    for entry in req.overrides:
        if entry.ingredient_code not in store.ingredients_by_code:
            raise DataValidationError(f"Unknown ingredient_code '{entry.ingredient_code}'")
        idr_per_g = convert_price_to_idr_per_g(
            entry.price_value, entry.unit, entry.density_g_per_ml
        )
        new_overrides[entry.ingredient_code] = idr_per_g

    updated = scenario.model_copy(update={"price_overrides_idr_per_g": new_overrides})
    store.scenarios[scenario_id] = updated
    return updated


def apply_stock_overrides(
    store: InMemoryVaultStore,
    scenario_id: UUID,
    req: StockOverridesRequest,
) -> Scenario:
    scenario = store.scenarios.get(scenario_id)
    if scenario is None:
        raise ResourceNotFoundError(f"Scenario '{scenario_id}' not found")
    if scenario.locked:
        raise ScenarioConflictError(
            f"Scenario '{scenario_id}' is locked after optimization; clone it to create a what-if scenario"
        )

    new_overrides = dict(scenario.stock_overrides_raw_g)
    for entry in req.overrides:
        if entry.ingredient_code not in store.ingredients_by_code:
            raise DataValidationError(f"Unknown ingredient_code '{entry.ingredient_code}'")
        new_overrides[entry.ingredient_code] = entry.stock_raw_g

    updated = scenario.model_copy(update={"stock_overrides_raw_g": new_overrides})
    store.scenarios[scenario_id] = updated
    return updated


def _resolve_effective_prices(store: InMemoryVaultStore, scenario: Scenario) -> Dict[str, float]:
    base_prices = store.base_prices_by_dataset[scenario.dataset_version_id]
    effective = {code: p.price_idr_per_g for code, p in base_prices.items()}
    effective.update(scenario.price_overrides_idr_per_g)
    return effective


def _resolve_effective_stock(store: InMemoryVaultStore, scenario: Scenario) -> Dict[str, float]:
    base_stock = store.base_stock_by_dataset[scenario.dataset_version_id]
    effective = {code: s.stock_raw_g for code, s in base_stock.items()}
    effective.update(scenario.stock_overrides_raw_g)
    return effective


def build_canonical_input_snapshot(
    store: InMemoryVaultStore,
    scenario: Scenario,
    target: NutritionTargetProfile,
    effective_prices: Dict[str, float],
    effective_stock: Dict[str, float],
    recipes: List[RecipeVariant],
    model_version: str = MODEL_VERSION,
) -> Dict[str, Any]:
    """Build a complete, deterministic snapshot of all optimization inputs (excluding random scenario_id)."""
    return {
        "model_version": model_version,
        "dataset_version_id": str(scenario.dataset_version_id),
        "nutrition_target": {
            "id": str(target.id),
            "cohort": target.cohort,
            "meal_type": target.meal_type,
            "version": target.version,
            "source_ref": target.source_ref,
            "limits": [
                {
                    "nutrient_key": lim.nutrient_key,
                    "min_per_serving": lim.min_per_serving,
                    "max_per_serving": lim.max_per_serving,
                    "unit": lim.unit,
                }
                for lim in sorted(target.limits, key=lambda x: x.nutrient_key)
            ],
        },
        "scenario_params": {
            "meal_type": scenario.meal_type,
            "servings_per_day": scenario.servings_per_day,
            "days": scenario.days,
            "budget_idr_per_serving": scenario.budget_idr_per_serving,
            "max_repeat_per_family": scenario.max_repeat_per_family,
            "excluded_allergens": sorted({a.strip().lower() for a in scenario.excluded_allergens if a.strip()}),
            "source_label": scenario.source_label.value,
        },
        "prices_idr_per_g": dict(sorted(effective_prices.items())),
        "stock_raw_g": dict(sorted(effective_stock.items())),
        "ingredients": [
            {
                "code": ing.code,
                "edible_fraction": ing.edible_fraction,
                "allergens": sorted({a.strip().lower() for a in ing.allergens if a.strip()}),
                "nutrients": ing.nutrients.model_dump(),
            }
            for ing in sorted(store.ingredients_by_code.values(), key=lambda x: x.code)
        ],
        "recipes": [
            {
                "code": r.code,
                "slot": r.slot.value,
                "family": r.family,
                "active": r.active,
                "review_status": r.review_status.value,
                "allergen_tags": sorted({a.strip().lower() for a in r.allergen_tags if a.strip()}),
                "ingredients": [
                    {
                        "ingredient_code": ri.ingredient_code,
                        "raw_g_per_serving": ri.raw_g_per_serving,
                        "retention_factor": ri.retention_factor,
                    }
                    for ri in sorted(r.ingredients, key=lambda x: x.ingredient_code)
                ],
            }
            for r in sorted(recipes, key=lambda x: x.code)
        ],
    }


def compute_snapshot_sha256(snapshot: Dict[str, Any]) -> str:
    encoded = json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def run_optimization(
    store: InMemoryVaultStore,
    scenario_id: UUID,
    time_limit_seconds: float = 10.0,
    forced_raw_result: Optional[RawSolveResult] = None,
) -> OptimizationRunResponse:
    """Solve scenario MILP, independently verify result, lock scenario, and persist run."""
    scenario = store.scenarios.get(scenario_id)
    if scenario is None:
        raise ResourceNotFoundError(f"Scenario '{scenario_id}' not found")

    target = store.targets[scenario.nutrition_target_id]
    effective_prices = _resolve_effective_prices(store, scenario)
    effective_stock = _resolve_effective_stock(store, scenario)

    # Precompute deterministic recipe costs and nutrients
    all_features = precompute_all_recipes(
        store.recipes,
        store.ingredients_by_code,
        effective_prices,
        target.limits,
    )
    features_by_id = {f.recipe_id: f for f in all_features}

    # Build MILP first so validation failures (422) do NOT prematurely lock the scenario
    try:
        built = build_recipe_milp(
            scenario=scenario,
            recipes=store.recipes,
            features_by_id=features_by_id,
            target=target,
            stock_raw_g=effective_stock,
            ingredients_by_code=store.ingredients_by_code,
        )
    except ValueError as exc:
        raise DataValidationError(str(exc)) from exc

    input_snapshot = build_canonical_input_snapshot(
        store=store,
        scenario=scenario,
        target=target,
        effective_prices=effective_prices,
        effective_stock=effective_stock,
        recipes=store.recipes,
        model_version=MODEL_VERSION,
    )
    input_sha256 = compute_snapshot_sha256(input_snapshot)
    price_snapshot_id = f"snap-{input_sha256[:12]}"

    # Lock scenario once valid optimization execution begins so baseline stays immutable (AC-10)
    store.scenarios[scenario_id] = scenario.model_copy(update={"locked": True})

    warnings = [
        "SIMULATION_ONLY: Nilai nutrisi, harga, dan stok adalah data sintetis (DEMO_ONLY) untuk demonstrasi dan belum divalidasi ahli gizi."
    ]

    raw_result = (
        forced_raw_result
        if forced_raw_result is not None
        else solve_built_model(built, time_limit_seconds=time_limit_seconds)
    )

    common_meta = dict(
        scenario_id=scenario.id,
        dataset_version_id=scenario.dataset_version_id,
        price_snapshot_id=price_snapshot_id,
        simulation_only=True,
        best_bound=raw_result.best_bound,
        gap_abs=raw_result.gap_abs,
        gap_rel=raw_result.gap_rel,
        solver_name=raw_result.solver_name,
        solver_version=raw_result.solver_version,
        raw_solver_status=raw_result.raw_solver_status,
        solver_seconds=raw_result.solver_seconds,
        input_sha256=input_sha256,
        model_version=MODEL_VERSION,
        input_snapshot=input_snapshot,
    )

    # Handle ERROR
    if raw_result.solver_status == SolverStatusEnum.ERROR:
        run = OptimizationRunResponse(
            **common_meta,
            solver_status=SolverStatusEnum.ERROR,
            validation_passed=False,
            objective_total_idr=None,
            cost_per_serving_average_idr=None,
            days=[],
            constraint_audit=ConstraintAudit(all_hard_constraints_pass=False),
            warnings=warnings + [f"Solver error: {raw_result.error_message or 'unknown error'}"],
        )
        store.runs[run.run_id] = run
        return run

    # Handle INFEASIBLE
    if raw_result.solver_status == SolverStatusEnum.INFEASIBLE:
        try:
            diag_solver = create_cbc_solver(time_limit_seconds=min(time_limit_seconds, 5.0))
            diagnostics = diagnose_infeasibility(
                scenario,
                store.recipes,
                features_by_id,
                target,
                effective_stock,
                diag_solver,
                ingredients_by_code=store.ingredients_by_code,
            )
        except Exception:
            diagnostics = [
                DiagnosticHint(
                    family="combined",
                    message="Tidak dapat menentukan bottleneck secara terpisah; periksa anggaran, stok, dan target gizi.",
                )
            ]

        run = OptimizationRunResponse(
            **common_meta,
            solver_status=SolverStatusEnum.INFEASIBLE,
            validation_passed=False,
            objective_total_idr=None,
            cost_per_serving_average_idr=None,
            days=[],
            constraint_audit=ConstraintAudit(all_hard_constraints_pass=False),
            constraint_diagnostics=diagnostics,
            warnings=warnings
            + [
                "Tidak ada menu yang memenuhi semua batasan. Jangan gunakan alternatif relaksasi sebagai rekomendasi valid."
            ],
        )
        store.runs[run.run_id] = run
        return run

    # Handle missing/incomplete incumbent for ANY status (OPTIMAL/FEASIBLE/TIME_LIMIT)
    if not raw_result.has_incumbent and raw_result.raw_x_values is None:
        run = OptimizationRunResponse(
            **common_meta,
            solver_status=raw_result.solver_status,
            validation_passed=False,
            objective_total_idr=None,
            cost_per_serving_average_idr=None,
            days=[],
            constraint_audit=ConstraintAudit(all_hard_constraints_pass=False),
            warnings=warnings
            + ["Solver tidak menghasilkan solusi integer lengkap yang dapat diverifikasi."],
        )
        store.runs[run.run_id] = run
        return run

    # Independent verification directly from raw ingredients, prices, stock, target, and raw x
    audit = verify_assignments(
        scenario=scenario,
        assignments_by_day=raw_result.assignments_by_day,
        recipes_by_id=store.recipes_by_id,
        ingredients_by_code=store.ingredients_by_code,
        effective_prices_idr_per_g=effective_prices,
        target=target,
        stock_raw_g=effective_stock,
        raw_x_values=raw_result.raw_x_values,
        reported_objective=raw_result.reported_objective,
    )

    if not audit.all_hard_constraints_pass:
        run = OptimizationRunResponse(
            **common_meta,
            solver_status=raw_result.solver_status,
            validation_passed=False,
            objective_total_idr=None,
            cost_per_serving_average_idr=None,
            days=[],
            constraint_audit=audit,
            warnings=warnings
            + [
                "Solusi ditolak oleh independent validator karena melanggar hard constraint."
            ],
        )
        store.runs[run.run_id] = run
        return run

    # Build verified DayPlan list and MaterialUsage summary from verified assignments
    day_plans: List[DayPlan] = []
    used_by_ingredient: Dict[str, float] = {}
    total_cost_idr = 0.0

    for d in range(1, scenario.days + 1):
        slot_map = raw_result.assignments_by_day[d]
        names_map: Dict[SlotEnum, str] = {}
        day_cost_per_serving = 0.0
        day_nutrients: Dict[str, float] = {lim.nutrient_key: 0.0 for lim in target.limits}

        for slot, rid in slot_map.items():
            feat = features_by_id[rid]
            names_map[slot] = feat.recipe_name
            day_cost_per_serving += feat.cost_idr_per_serving
            for k in day_nutrients:
                day_nutrients[k] += feat.nutrients_per_serving[k]
            for ing_code, raw_g in feat.raw_grams_by_ingredient.items():
                used_by_ingredient[ing_code] = (
                    used_by_ingredient.get(ing_code, 0.0) + raw_g * scenario.servings_per_day
                )

        total_cost_idr += day_cost_per_serving * scenario.servings_per_day
        day_plans.append(
            DayPlan(
                day_index=d,
                recipes_by_slot=slot_map,
                recipe_names_by_slot=names_map,
                daily_cost_idr_per_serving=round(day_cost_per_serving, 2),
                nutrients_per_serving={k: round(v, 3) for k, v in day_nutrients.items()},
            )
        )

    material_usage = [
        MaterialUsage(
            ingredient_code=code,
            ingredient_name=store.ingredients_by_code[code].name,
            used_raw_g=round(used_g, 2),
            available_raw_g=round(effective_stock.get(code, 0.0), 2),
        )
        for code, used_g in sorted(used_by_ingredient.items())
    ]

    avg_cost = total_cost_idr / (scenario.days * scenario.servings_per_day)

    run = OptimizationRunResponse(
        **common_meta,
        solver_status=raw_result.solver_status,
        validation_passed=True,
        objective_total_idr=round(total_cost_idr, 2),
        cost_per_serving_average_idr=round(avg_cost, 2),
        days=day_plans,
        material_usage=material_usage,
        constraint_audit=audit,
        warnings=warnings,
    )
    store.runs[run.run_id] = run
    return run
