from __future__ import annotations

import copy
import math

import pytest
from fastapi.testclient import TestClient
from pulp.constants import LpSolveStatus

from app.domain.models.schemas import (
    Ingredient,
    IngredientNutrients,
    NutritionTargetLimit,
    PriceOverrideEntry,
    PriceOverridesRequest,
    RecipeIngredient,
    RecipeVariant,
    ReviewStatusEnum,
    ScenarioCreateRequest,
    SlotEnum,
    SolverStatusEnum,
    StockOverrideEntry,
    StockOverridesRequest,
)
from app.domain.recipe_calculator import precompute_all_recipes
from app.ingestion.unit_converter import (
    DataValidationError,
    UnitConversionError,
    convert_price_to_idr_per_g,
    validate_ingredient_nutrients_for_target,
)
from app.main import app
from app.optimizer.model_builder import build_recipe_milp
from app.optimizer.solver import (
    RawSolveResult,
    classify_solve_stats,
    create_cbc_solver,
    solve_built_model,
)
from app.optimizer.verifier import verify_assignments
from app.scenarios.service import (
    _resolve_effective_prices,
    _resolve_effective_stock,
    apply_price_overrides,
    apply_stock_overrides,
    clone_scenario,
    create_scenario,
    run_optimization,
)
from app.scenarios.store import InMemoryVaultStore
from tests.conftest import make_authenticated_client


class _LazyPlannerClient:
    def __init__(self) -> None:
        self._inner: TestClient | None = None

    def _client(self) -> TestClient:
        if self._inner is None:
            self._inner = make_authenticated_client("perencana_menu")
        return self._inner

    def __getattr__(self, name: str):
        if name.startswith("_") or not hasattr(TestClient, name):
            raise AttributeError(name)
        return getattr(self._client(), name)


client = _LazyPlannerClient()


def _solve_fresh_baseline() -> tuple[InMemoryVaultStore, object, RawSolveResult]:
    st = InMemoryVaultStore()
    sc = create_scenario(
        st,
        ScenarioCreateRequest(
            name="Audit Baseline",
            servings_per_day=100,
            days=5,
            budget_idr_per_serving=12000.0,
            max_repeat_per_family=2,
        ),
    )
    target = st.targets[sc.nutrition_target_id]
    prices = _resolve_effective_prices(st, sc)
    stock = _resolve_effective_stock(st, sc)
    feats = precompute_all_recipes(st.recipes, st.ingredients_by_code, prices, target.limits)
    built = build_recipe_milp(
        sc,
        st.recipes,
        {f.recipe_id: f for f in feats},
        target,
        stock,
        ingredients_by_code=st.ingredients_by_code,
    )
    raw = solve_built_model(built, time_limit_seconds=10.0)
    return st, sc, raw


# =====================================================================
# 1. PuLP 4.3.1 / CBC Solver Status & Optimality Proof Audit
# =====================================================================


def test_live_cbc_proves_exact_lp_optimal_status() -> None:
    st, sc, raw = _solve_fresh_baseline()
    assert raw.solver_status == SolverStatusEnum.OPTIMAL
    assert raw.raw_solver_status == "Optimal"
    assert raw.has_incumbent is True
    assert raw.solver_name == "COIN_CMD"
    assert raw.solver_version is not None
    assert raw.reported_objective is not None
    assert raw.best_bound is not None
    assert raw.gap_abs == pytest.approx(0.0, abs=1e-6)
    assert raw.gap_rel == pytest.approx(0.0, abs=1e-9)
    assert raw.raw_x_values is not None and len(raw.raw_x_values) > 0


def test_classify_solve_stats_never_overclaims_optimal() -> None:
    # GapLimit with gap==0 but WITHOUT "Optimal solution found" log stays FEASIBLE
    st1, _ = classify_solve_stats(
        status=LpSolveStatus.GapLimit,
        has_solution=True,
        objective=1000.0,
        best_bound=1000.0,
        gap_abs=0.0,
        gap_rel=0.0,
        solver_log_status="Stopped on gap",
    )
    assert st1 == SolverStatusEnum.FEASIBLE

    # GapLimit without best_bound stays FEASIBLE even if log says Optimal
    st2, _ = classify_solve_stats(
        status=LpSolveStatus.GapLimit,
        has_solution=True,
        objective=1000.0,
        best_bound=None,
        gap_abs=None,
        gap_rel=0.0,
        solver_log_status="Optimal solution found",
    )
    assert st2 == SolverStatusEnum.FEASIBLE

    # GapLimit with non-zero gap stays FEASIBLE
    st3, _ = classify_solve_stats(
        status=LpSolveStatus.GapLimit,
        has_solution=True,
        objective=1050.0,
        best_bound=1000.0,
        gap_abs=50.0,
        gap_rel=50.0 / 1050.0,
        solver_log_status="Optimal solution found",
    )
    assert st3 == SolverStatusEnum.FEASIBLE

    # GapLimit with full simultaneous proof -> OPTIMAL
    st4, _ = classify_solve_stats(
        status=LpSolveStatus.GapLimit,
        has_solution=True,
        objective=1000.0,
        best_bound=1000.0,
        gap_abs=0.0,
        gap_rel=0.0,
        solver_log_status="Optimal solution found",
    )
    assert st4 == SolverStatusEnum.OPTIMAL

    # Optimal with has_solution=False -> ERROR
    st5, _ = classify_solve_stats(
        status=LpSolveStatus.Optimal,
        has_solution=False,
        objective=1000.0,
        best_bound=1000.0,
        gap_abs=0.0,
        gap_rel=0.0,
        solver_log_status="Optimal solution found",
    )
    assert st5 == SolverStatusEnum.ERROR

    # Optimal with NaN objective -> ERROR
    st6, _ = classify_solve_stats(
        status=LpSolveStatus.Optimal,
        has_solution=True,
        objective=float("nan"),
        best_bound=1000.0,
        gap_abs=None,
        gap_rel=None,
        solver_log_status="Optimal solution found",
    )
    assert st6 == SolverStatusEnum.ERROR

    # GapLimit with has_solution=False -> ERROR
    st7, _ = classify_solve_stats(
        status=LpSolveStatus.GapLimit,
        has_solution=False,
        objective=None,
        best_bound=None,
        gap_abs=None,
        gap_rel=None,
        solver_log_status=None,
    )
    assert st7 == SolverStatusEnum.ERROR


# =====================================================================
# 2. Independent Verifier Post-Solve Mutation Tests
# =====================================================================


def test_mutation_budget_violation_rejected() -> None:
    st, sc, raw = _solve_fresh_baseline()
    target = st.targets[sc.nutrition_target_id]
    prices = _resolve_effective_prices(st, sc)
    stock = _resolve_effective_stock(st, sc)

    # Mutate Day 1 to use the most expensive recipes across slots & set tight budget
    tight_sc = sc.model_copy(update={"budget_idr_per_serving": 6000.0})
    audit = verify_assignments(
        scenario=tight_sc,
        assignments_by_day=raw.assignments_by_day,
        recipes_by_id=st.recipes_by_id,
        ingredients_by_code=st.ingredients_by_code,
        effective_prices_idr_per_g=prices,
        target=target,
        stock_raw_g=stock,
        raw_x_values=raw.raw_x_values,
        reported_objective=raw.reported_objective,
    )
    assert audit.all_hard_constraints_pass is False
    assert any(v.constraint_family == "budget" for v in audit.violations)


def test_mutation_nutrition_floor_and_ceiling_rejected() -> None:
    st, sc, raw = _solve_fresh_baseline()
    target = st.targets[sc.nutrition_target_id]
    prices = _resolve_effective_prices(st, sc)
    stock = _resolve_effective_stock(st, sc)

    # Floor mutation: require impossibly high protein (50g)
    floor_limits = [
        lim.model_copy(update={"min_per_serving": 50.0, "max_per_serving": 80.0})
        if lim.nutrient_key == "protein_g"
        else lim
        for lim in target.limits
    ]
    floor_target = target.model_copy(update={"limits": floor_limits})
    audit_floor = verify_assignments(
        sc, raw.assignments_by_day, st.recipes_by_id, st.ingredients_by_code, prices, floor_target, stock
    )
    assert audit_floor.all_hard_constraints_pass is False
    assert any(v.constraint_family == "nutrition_floor" for v in audit_floor.violations)

    # Ceiling mutation: cap energy_kcal below actual Day 1 energy (300 kcal)
    ceil_limits = [
        lim.model_copy(update={"min_per_serving": 100.0, "max_per_serving": 300.0})
        if lim.nutrient_key == "energy_kcal"
        else lim
        for lim in target.limits
    ]
    ceil_target = target.model_copy(update={"limits": ceil_limits})
    audit_ceil = verify_assignments(
        sc, raw.assignments_by_day, st.recipes_by_id, st.ingredients_by_code, prices, ceil_target, stock
    )
    assert audit_ceil.all_hard_constraints_pass is False
    assert any(v.constraint_family == "nutrition_ceiling" for v in audit_ceil.violations)


def test_mutation_stock_and_missing_stock_rejected() -> None:
    st, sc, raw = _solve_fresh_baseline()
    target = st.targets[sc.nutrition_target_id]
    prices = _resolve_effective_prices(st, sc)
    stock = _resolve_effective_stock(st, sc)

    # Cut ING001 stock far below usage
    low_stock = dict(stock)
    low_stock["ING001"] = 100.0
    audit1 = verify_assignments(
        sc, raw.assignments_by_day, st.recipes_by_id, st.ingredients_by_code, prices, target, low_stock
    )
    assert audit1.all_hard_constraints_pass is False
    assert any(v.constraint_family == "stock" for v in audit1.violations)

    # Delete ING001 stock key entirely -> must NOT be silently ignored
    missing_stock = dict(stock)
    del missing_stock["ING001"]
    audit2 = verify_assignments(
        sc, raw.assignments_by_day, st.recipes_by_id, st.ingredients_by_code, prices, target, missing_stock
    )
    assert audit2.all_hard_constraints_pass is False
    assert any(v.constraint_family == "stock" and "ING001" in v.detail for v in audit2.violations)


def test_mutation_allergen_recipe_tag_and_ingredient_level_rejected() -> None:
    st, sc, raw = _solve_fresh_baseline()
    target = st.targets[sc.nutrition_target_id]
    prices = _resolve_effective_prices(st, sc)
    stock = _resolve_effective_stock(st, sc)

    # 1. Recipe-tag allergen violation (R005 has egg)
    r005 = next(r for r in st.recipes if r.code == "R005")
    mutated = copy.deepcopy(raw.assignments_by_day)
    mutated[1][SlotEnum.PROTEIN] = r005.id
    sc_no_egg = sc.model_copy(update={"excluded_allergens": ["egg"]})
    audit1 = verify_assignments(
        sc_no_egg, mutated, st.recipes_by_id, st.ingredients_by_code, prices, target, stock
    )
    assert audit1.all_hard_constraints_pass is False
    assert any(v.constraint_family == "allergen" for v in audit1.violations)

    # 2. Ingredient-level allergen violation (recipe forgot to declare allergen_tags!)
    untagged_egg_recipe = RecipeVariant(
        code="R_UNTAGGED_EGG",
        name="Telur Tanpa Tag Alergen",
        slot=SlotEnum.PROTEIN,
        family="untagged_egg",
        review_status=ReviewStatusEnum.REVIEWED,
        active=True,
        allergen_tags=[],  # intentionally omitted!
        ingredients=[RecipeIngredient(ingredient_code="ING006", raw_g_per_serving=70.0)],
    )
    recipes_by_id = dict(st.recipes_by_id)
    recipes_by_id[untagged_egg_recipe.id] = untagged_egg_recipe
    mutated2 = copy.deepcopy(raw.assignments_by_day)
    mutated2[1][SlotEnum.PROTEIN] = untagged_egg_recipe.id

    audit2 = verify_assignments(
        sc_no_egg, mutated2, recipes_by_id, st.ingredients_by_code, prices, target, stock
    )
    assert audit2.all_hard_constraints_pass is False
    assert any(v.constraint_family == "allergen" and "egg" in v.detail for v in audit2.violations)

    # Also ensure model_builder excludes untagged_egg_recipe via ingredient allergens
    feats = precompute_all_recipes(
        st.recipes + [untagged_egg_recipe], st.ingredients_by_code, prices, target.limits
    )
    built = build_recipe_milp(
        sc_no_egg,
        st.recipes + [untagged_egg_recipe],
        {f.recipe_id: f for f in feats},
        target,
        stock,
        ingredients_by_code=st.ingredients_by_code,
    )
    assert untagged_egg_recipe.id not in built.eligible_features


def test_mutation_repeat_cap_rejected() -> None:
    st, sc, raw = _solve_fresh_baseline()
    target = st.targets[sc.nutrition_target_id]
    prices = _resolve_effective_prices(st, sc)
    stock = _resolve_effective_stock(st, sc)

    r001 = next(r for r in st.recipes if r.code == "R001")
    mutated = copy.deepcopy(raw.assignments_by_day)
    # Force R001 (family='rice') on Days 1, 2, 3 (> max_repeat_per_family=2)
    mutated[1][SlotEnum.STAPLE] = r001.id
    mutated[2][SlotEnum.STAPLE] = r001.id
    mutated[3][SlotEnum.STAPLE] = r001.id

    audit = verify_assignments(
        sc, mutated, st.recipes_by_id, st.ingredients_by_code, prices, target, stock
    )
    assert audit.all_hard_constraints_pass is False
    assert any(v.constraint_family == "repeat_cap" for v in audit.violations)


def test_mutation_slot_coverage_extra_day_and_unreviewed_rejected() -> None:
    st, sc, raw = _solve_fresh_baseline()
    target = st.targets[sc.nutrition_target_id]
    prices = _resolve_effective_prices(st, sc)
    stock = _resolve_effective_stock(st, sc)

    # 1. Missing slot on Day 2
    m_missing = copy.deepcopy(raw.assignments_by_day)
    del m_missing[2][SlotEnum.FRUIT]
    a1 = verify_assignments(sc, m_missing, st.recipes_by_id, st.ingredients_by_code, prices, target, stock)
    assert a1.all_hard_constraints_pass is False
    assert any(v.constraint_family == "slot_coverage" for v in a1.violations)

    # 2. Wrong slot recipe (staple placed into protein slot)
    r001 = next(r for r in st.recipes if r.code == "R001")
    m_wrong_slot = copy.deepcopy(raw.assignments_by_day)
    m_wrong_slot[1][SlotEnum.PROTEIN] = r001.id
    a2 = verify_assignments(sc, m_wrong_slot, st.recipes_by_id, st.ingredients_by_code, prices, target, stock)
    assert a2.all_hard_constraints_pass is False
    assert any(v.constraint_family == "slot_coverage" for v in a2.violations)

    # 3. Extraneous day 6
    m_extra_day = copy.deepcopy(raw.assignments_by_day)
    m_extra_day[6] = copy.deepcopy(raw.assignments_by_day[1])
    a3 = verify_assignments(sc, m_extra_day, st.recipes_by_id, st.ingredients_by_code, prices, target, stock)
    assert a3.all_hard_constraints_pass is False
    assert any(v.constraint_family == "slot_coverage" and "Unexpected day" in v.detail for v in a3.violations)

    # 4. Unreviewed draft recipe R017 injected
    r017 = next(r for r in st.recipes if r.code == "R017")
    m_draft = copy.deepcopy(raw.assignments_by_day)
    m_draft[1][SlotEnum.STAPLE] = r017.id
    a4 = verify_assignments(sc, m_draft, st.recipes_by_id, st.ingredients_by_code, prices, target, stock)
    assert a4.all_hard_constraints_pass is False
    assert any(v.constraint_family == "allowed" and "unreviewed" in v.detail for v in a4.violations)


def test_mutation_binary_integrality_and_duplicate_slot_in_raw_x_rejected() -> None:
    st, sc, raw = _solve_fresh_baseline()
    target = st.targets[sc.nutrition_target_id]
    prices = _resolve_effective_prices(st, sc)
    stock = _resolve_effective_stock(st, sc)
    assert raw.raw_x_values is not None

    r001 = next(r for r in st.recipes if r.code == "R001")
    r002 = next(r for r in st.recipes if r.code == "R002")

    # 1. Fractional values: x[1, R001] = 0.6, x[1, R002] = 0.4
    frac_x = dict(raw.raw_x_values)
    frac_x[(1, r001.id)] = 0.6
    frac_x[(1, r002.id)] = 0.4
    a1 = verify_assignments(
        sc, raw.assignments_by_day, st.recipes_by_id, st.ingredients_by_code, prices, target, stock, raw_x_values=frac_x
    )
    assert a1.all_hard_constraints_pass is False
    assert any(v.constraint_family == "integrality" for v in a1.violations)

    # 2. Duplicate slot selection in raw x: BOTH R001=1.0 and R002=1.0 on Day 1
    dup_x = dict(raw.raw_x_values)
    dup_x[(1, r001.id)] = 1.0
    dup_x[(1, r002.id)] = 1.0
    a2 = verify_assignments(
        sc, raw.assignments_by_day, st.recipes_by_id, st.ingredients_by_code, prices, target, stock, raw_x_values=dup_x
    )
    assert a2.all_hard_constraints_pass is False
    assert any(v.constraint_family == "slot_coverage" and "2 selected" in v.detail for v in a2.violations)

    # 3. NaN / out-of-bounds (-0.1, 1.05) in raw x
    for bad_val in (float("nan"), -0.1, 1.05):
        bad_x = dict(raw.raw_x_values)
        bad_x[(1, r001.id)] = bad_val
        a_bad = verify_assignments(
            sc, raw.assignments_by_day, st.recipes_by_id, st.ingredients_by_code, prices, target, stock, raw_x_values=bad_x
        )
        assert a_bad.all_hard_constraints_pass is False
        assert any(v.constraint_family == "integrality" for v in a_bad.violations)


def test_mutation_tampered_objective_rejected_end_to_end() -> None:
    st, sc, raw = _solve_fresh_baseline()
    assert raw.reported_objective is not None
    tampered = RawSolveResult(
        solver_status=SolverStatusEnum.OPTIMAL,
        solver_seconds=raw.solver_seconds,
        assignments_by_day=raw.assignments_by_day,
        has_incumbent=True,
        raw_x_values=raw.raw_x_values,
        reported_objective=raw.reported_objective + 500.0,
        best_bound=raw.best_bound,
        gap_abs=raw.gap_abs,
        gap_rel=raw.gap_rel,
        solver_name=raw.solver_name,
        solver_version=raw.solver_version,
        raw_solver_status=raw.raw_solver_status,
    )
    run = run_optimization(st, sc.id, forced_raw_result=tampered)
    assert run.validation_passed is False
    assert run.days == []
    assert any(v.constraint_family == "objective_consistency" for v in run.constraint_audit.violations)


# =====================================================================
# 3. Nutrient, Cost, Unit & Dimensional Consistency Audit
# =====================================================================


@pytest.mark.parametrize("bad_val", [float("nan"), float("inf"), float("-inf"), 0.0, -5.0])
def test_non_finite_and_invalid_prices_rejected(bad_val: float) -> None:
    with pytest.raises(UnitConversionError):
        convert_price_to_idr_per_g(bad_val, "IDR/kg")


@pytest.mark.parametrize("bad_density", [float("nan"), float("inf"), 0.0, -0.9])
def test_invalid_density_rejected_for_liter(bad_density: float) -> None:
    with pytest.raises(UnitConversionError):
        convert_price_to_idr_per_g(18400.0, "IDR/liter", density_g_per_ml=bad_density)


def test_decimal_exact_conversion_and_dimensional_horizon_consistency() -> None:
    # Exact Decimal division avoids float drift (18400 / 920 == 20.0 exactly)
    assert convert_price_to_idr_per_g(18400, "IDR/liter", density_g_per_ml=0.92) == 20.0
    assert convert_price_to_idr_per_g(16000, "IDR/kg") == 16.0

    # End-to-end horizon cost & independent nutrient dimensional check
    st = InMemoryVaultStore()
    sc = create_scenario(st, ScenarioCreateRequest(name="Dimensional Audit"))
    run = run_optimization(st, sc.id)
    assert run.validation_passed is True
    assert run.objective_total_idr is not None
    assert run.cost_per_serving_average_idr is not None

    sum_daily_horizon = sum(d.daily_cost_idr_per_serving * sc.servings_per_day for d in run.days)
    assert run.objective_total_idr == pytest.approx(sum_daily_horizon, abs=0.05)
    assert run.cost_per_serving_average_idr == pytest.approx(
        run.objective_total_idr / (sc.days * sc.servings_per_day), abs=0.01
    )

    # Independently recompute Day 1 nutrients from raw master data and compare
    prices = _resolve_effective_prices(st, sc)
    day1 = run.days[0]
    recomputed_kcal = 0.0
    recomputed_prot = 0.0
    recomputed_cost = 0.0
    for rid in day1.recipes_by_slot.values():
        rec = st.recipes_by_id[rid]
        for item in rec.ingredients:
            ing = st.ingredients_by_code[item.ingredient_code]
            recomputed_cost += item.raw_g_per_serving * prices[item.ingredient_code]
            edible_g = item.raw_g_per_serving * ing.edible_fraction
            recomputed_kcal += (edible_g / 100.0) * ing.nutrients.energy_kcal_100g * item.retention_factor
            recomputed_prot += (edible_g / 100.0) * ing.nutrients.protein_g_100g * item.retention_factor

    assert day1.daily_cost_idr_per_serving == pytest.approx(recomputed_cost, abs=0.01)
    assert day1.nutrients_per_serving["energy_kcal"] == pytest.approx(recomputed_kcal, abs=1e-3)
    assert day1.nutrients_per_serving["protein_g"] == pytest.approx(recomputed_prot, abs=1e-3)


def test_reject_non_finite_nutrient_in_validation() -> None:
    ing = Ingredient.model_construct(
        code="ING_NAN",
        name="NaN Ingredient",
        category="test",
        edible_fraction=1.0,
        allergens=[],
        nutrients=IngredientNutrients.model_construct(energy_kcal_100g=float("nan")),
    )
    with pytest.raises(DataValidationError):
        validate_ingredient_nutrients_for_target(
            ing, [NutritionTargetLimit(nutrient_key="energy_kcal", min_per_serving=100.0, unit="kcal")]
        )


# =====================================================================
# 4. Scenario Integrity, Lock Safety & Reproducibility Audit
# =====================================================================


def test_reproducibility_hash_deterministic_across_identical_scenarios() -> None:
    st = InMemoryVaultStore()
    sc_a = create_scenario(st, ScenarioCreateRequest(name="Run A"))
    sc_b = create_scenario(st, ScenarioCreateRequest(name="Run B"))

    run_a = run_optimization(st, sc_a.id)
    run_b = run_optimization(st, sc_b.id)

    assert run_a.validation_passed is True
    assert run_b.validation_passed is True
    # Identical optimization inputs must yield identical canonical input_sha256
    assert run_a.input_sha256 == run_b.input_sha256
    assert run_a.objective_total_idr == run_b.objective_total_idr
    assert run_a.model_version == "recipe-milp-v0.1"
    assert run_a.solver_name == "COIN_CMD"
    assert run_a.solver_version is not None
    assert run_a.dataset_version_id == st.default_dataset_id
    assert "nutrition_target" in run_a.input_snapshot
    assert "prices_idr_per_g" in run_a.input_snapshot
    assert "stock_raw_g" in run_a.input_snapshot
    assert "recipes" in run_a.input_snapshot

    # Cloning and changing stock changes hash without mutating baseline
    sc_c = clone_scenario(st, sc_a.id)
    apply_stock_overrides(
        st, sc_c.id, StockOverridesRequest(overrides=[StockOverrideEntry(ingredient_code="ING009", stock_raw_g=10000.0)])
    )
    run_c = run_optimization(st, sc_c.id)
    assert run_c.input_sha256 != run_a.input_sha256
    assert st.scenarios[sc_a.id].stock_overrides_raw_g == {}


def test_failed_422_optimization_does_not_lock_scenario() -> None:
    st = InMemoryVaultStore()
    # Exclude all protein allergens + make poultry inactive via local store copy
    poultry = next(r for r in st.recipes if r.code == "R006")
    st.recipes = [r.model_copy(update={"active": False}) if r.id == poultry.id else r for r in st.recipes]
    st.recipes_by_id = {r.id: r for r in st.recipes}

    sc = create_scenario(
        st,
        ScenarioCreateRequest(
            name="Empty Protein Slot",
            excluded_allergens=["egg", "fish", "soy"],
        ),
    )
    with pytest.raises(DataValidationError):
        run_optimization(st, sc.id)

    # Scenario must remain unlocked after a 422 pre-solve failure
    assert st.scenarios[sc.id].locked is False


def test_infeasible_allergen_and_stock_diagnostics() -> None:
    # 1. Allergen exclusion leaves only poultry (max 2 repeats for 5 days -> INFEASIBLE)
    sc1 = client.post(
        "/api/v1/scenarios",
        json={
            "name": "Allergen Bottleneck",
            "budget_idr_per_serving": 12000,
            "max_repeat_per_family": 2,
            "excluded_allergens": ["egg", "fish", "soy"],
        },
    ).json()
    r1 = client.post(f"/api/v1/scenarios/{sc1['id']}/optimize").json()
    assert r1["solver_status"] == "INFEASIBLE"
    assert r1["validation_passed"] is False
    assert r1["days"] == []
    diag_families = {d["family"] for d in r1["constraint_diagnostics"]}
    assert "allergen" in diag_families or "repeat_cap" in diag_families

    # 2. Zero stock across all staple grains -> INFEASIBLE with stock hint
    sc2 = client.post("/api/v1/scenarios", json={"name": "Zero Staple Stock"}).json()
    client.patch(
        f"/api/v1/scenarios/{sc2['id']}/stock-overrides",
        json={
            "overrides": [
                {"ingredient_code": "ING001", "stock_raw_g": 0.0},
                {"ingredient_code": "ING002", "stock_raw_g": 0.0},
                {"ingredient_code": "ING003", "stock_raw_g": 0.0},
                {"ingredient_code": "ING004", "stock_raw_g": 0.0},
                {"ingredient_code": "ING005", "stock_raw_g": 0.0},
            ]
        },
    )
    r2 = client.post(f"/api/v1/scenarios/{sc2['id']}/optimize").json()
    assert r2["solver_status"] == "INFEASIBLE"
    assert r2["validation_passed"] is False
    assert r2["days"] == []
    assert any(d["family"] == "stock" for d in r2["constraint_diagnostics"])
