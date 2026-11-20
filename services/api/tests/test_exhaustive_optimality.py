from __future__ import annotations

import itertools
from datetime import date, datetime, timezone
from uuid import UUID

import pytest

from app.domain.models.schemas import (
    Ingredient,
    IngredientNutrients,
    NutritionTargetLimit,
    NutritionTargetProfile,
    RecipeIngredient,
    RecipeVariant,
    ReviewStatusEnum,
    Scenario,
    ScenarioCreateRequest,
    SlotEnum,
    SolverStatusEnum,
    SourceTypeEnum,
)
from app.domain.recipe_calculator import precompute_all_recipes
from app.optimizer.model_builder import build_recipe_milp, get_effective_recipe_allergens
from app.optimizer.solver import RawSolveResult, solve_built_model
from app.optimizer.verifier import verify_assignments
from app.db.repository import SQLiteVaultRepository
from app.db.session import db_manager


def _build_tiny_exhaustive_instance():
    """2 days, 4 slots, 2 recipes/slot (16^2 = 256 schedules) with binding budget, nutrition, stock, allergen & repeat cap."""
    ingredients = {
        "S1": Ingredient(
            code="S1", name="Beras A", category="staple", edible_fraction=1.0,
            nutrients=IngredientNutrients(energy_kcal_100g=350.0, protein_g_100g=7.0),
        ),
        "S2": Ingredient(
            code="S2", name="Jagung B", category="staple", edible_fraction=1.0,
            nutrients=IngredientNutrients(energy_kcal_100g=340.0, protein_g_100g=9.0),
        ),
        "P1": Ingredient(
            code="P1", name="Tempe A", category="protein", edible_fraction=1.0,
            nutrients=IngredientNutrients(energy_kcal_100g=190.0, protein_g_100g=19.0),
        ),
        "P2": Ingredient(
            code="P2", name="Ayam B", category="protein", edible_fraction=1.0,
            nutrients=IngredientNutrients(energy_kcal_100g=165.0, protein_g_100g=24.0),
        ),
        "P3": Ingredient(
            code="P3", name="Udang Alergen", category="protein", edible_fraction=0.8,
            allergens=["shellfish"],
            nutrients=IngredientNutrients(energy_kcal_100g=100.0, protein_g_100g=22.0),
        ),
        "V1": Ingredient(
            code="V1", name="Bayam A", category="vegetable", edible_fraction=0.75,
            nutrients=IngredientNutrients(energy_kcal_100g=24.0, protein_g_100g=3.0),
        ),
        "V2": Ingredient(
            code="V2", name="Wortel B", category="vegetable", edible_fraction=0.88,
            nutrients=IngredientNutrients(energy_kcal_100g=42.0, protein_g_100g=1.0),
        ),
        "F1": Ingredient(
            code="F1", name="Pepaya A", category="fruit", edible_fraction=0.75,
            nutrients=IngredientNutrients(energy_kcal_100g=45.0, protein_g_100g=0.5),
        ),
        "F2": Ingredient(
            code="F2", name="Pisang B", category="fruit", edible_fraction=0.75,
            nutrients=IngredientNutrients(energy_kcal_100g=100.0, protein_g_100g=1.2),
        ),
    }

    prices = {
        "S1": 15.0,   # cheaper staple
        "S2": 18.0,
        "P1": 16.0,   # cheaper protein, but stock limited to 1 day!
        "P2": 40.0,   # pricier protein
        "P3": 10.0,   # ultra cheap, but shellfish allergen -> MUST be excluded!
        "V1": 10.0,
        "V2": 14.0,
        "F1": 11.0,
        "F2": 16.0,
    }

    # Servings = 10/day, days = 2. P1 uses 80g/serving => 800g/day. Stock=1000g allows AT MOST 1 day of P1!
    stock = {
        "S1": 5000.0,
        "S2": 5000.0,
        "P1": 1000.0,
        "P2": 5000.0,
        "P3": 5000.0,
        "V1": 5000.0,
        "V2": 5000.0,
        "F1": 5000.0,
        "F2": 5000.0,
    }

    now = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)
    def mk(code, name, slot, fam, ings):
        return RecipeVariant(
            code=code, name=name, slot=slot, family=fam,
            review_status=ReviewStatusEnum.REVIEWED, reviewer="AUDIT", reviewed_at=now, active=True,
            ingredients=[RecipeIngredient(ingredient_code=c, raw_g_per_serving=g, retention_factor=ret) for c, g, ret in ings],
        )

    recipes = [
        mk("RS1", "Nasi A", SlotEnum.STAPLE, "rice", [("S1", 90.0, 0.95)]),
        mk("RS2", "Jagung B", SlotEnum.STAPLE, "corn", [("S2", 95.0, 0.95)]),
        mk("RP1", "Tempe A", SlotEnum.PROTEIN, "tempe", [("P1", 80.0, 0.95)]),
        mk("RP2", "Ayam B", SlotEnum.PROTEIN, "chicken", [("P2", 75.0, 0.90)]),
        mk("RP3", "Udang C", SlotEnum.PROTEIN, "shrimp", [("P3", 70.0, 0.95)]),  # excluded via ingredient allergen
        mk("RV1", "Bayam A", SlotEnum.VEGETABLE, "bayam", [("V1", 80.0, 0.85)]),
        mk("RV2", "Wortel B", SlotEnum.VEGETABLE, "wortel", [("V2", 80.0, 0.90)]),
        mk("RF1", "Pepaya A", SlotEnum.FRUIT, "papaya", [("F1", 100.0, 1.0)]),
        mk("RF2", "Pisang B", SlotEnum.FRUIT, "banana", [("F2", 100.0, 1.0)]),
    ]

    target = NutritionTargetProfile(
        cohort="TINY_EXHAUSTIVE",
        meal_type="lunch",
        source_ref="DEMO_ONLY",
        limits=[
            NutritionTargetLimit(nutrient_key="energy_kcal", min_per_serving=450.0, max_per_serving=620.0, unit="kcal"),
            NutritionTargetLimit(nutrient_key="protein_g", min_per_serving=20.0, max_per_serving=40.0, unit="g"),
        ],
    )

    scenario = Scenario(
        name="Tiny Exhaustive Proof",
        dataset_version_id=UUID("11111111-1111-1111-1111-111111111111"),
        nutrition_target_id=target.id,
        servings_per_day=10,
        days=2,
        budget_idr_per_serving=7500.0,
        max_repeat_per_family=1,  # forces distinct families across the 2 days in every slot!
        excluded_allergens=["shellfish"],
        source_label=SourceTypeEnum.SYNTHETIC,
    )
    return scenario, ingredients, prices, stock, recipes, target


def test_tiny_milp_matches_exhaustive_brute_force_global_optimum() -> None:
    scenario, ingredients, prices, stock, recipes, target = _build_tiny_exhaustive_instance()
    recipes_by_id = {r.id: r for r in recipes}

    # --- 1. Pure-Python exhaustive brute-force enumeration over ALL possible 2-day schedules ---
    by_slot = {s: [r for r in recipes if r.slot == s] for s in SlotEnum}
    daily_combos = list(
        itertools.product(
            by_slot[SlotEnum.STAPLE],
            by_slot[SlotEnum.PROTEIN],
            by_slot[SlotEnum.VEGETABLE],
            by_slot[SlotEnum.FRUIT],
        )
    )
    # 2 * 3 * 2 * 2 = 24 daily combos -> 24^2 = 576 total 2-day schedules
    assert len(daily_combos) == 24

    def eval_recipe_raw(rec: RecipeVariant):
        cost = 0.0
        kcal = 0.0
        prot = 0.0
        raw_g_map = {}
        for item in rec.ingredients:
            ing = ingredients[item.ingredient_code]
            cost += item.raw_g_per_serving * prices[item.ingredient_code]
            ed = item.raw_g_per_serving * ing.edible_fraction
            kcal += (ed / 100.0) * ing.nutrients.energy_kcal_100g * item.retention_factor
            prot += (ed / 100.0) * ing.nutrients.protein_g_100g * item.retention_factor
            raw_g_map[item.ingredient_code] = raw_g_map.get(item.ingredient_code, 0.0) + item.raw_g_per_serving
        return cost, kcal, prot, raw_g_map

    feasible_schedules = []
    for day1, day2 in itertools.product(daily_combos, daily_combos):
        schedule = [day1, day2]
        valid = True
        total_horizon_cost = 0.0
        fam_counts = {}
        usage = {}
        for day_recs in schedule:
            d_cost = 0.0
            d_kcal = 0.0
            d_prot = 0.0
            for rec in day_recs:
                if get_effective_recipe_allergens(rec, ingredients) & {"shellfish"}:
                    valid = False
                    break
                c, k, p, rg = eval_recipe_raw(rec)
                d_cost += c
                d_kcal += k
                d_prot += p
                fam_counts[rec.family] = fam_counts.get(rec.family, 0) + 1
                for code, g in rg.items():
                    usage[code] = usage.get(code, 0.0) + g * scenario.servings_per_day
            if not valid:
                break
            if d_cost > scenario.budget_idr_per_serving + 1e-6:
                valid = False
                break
            if not (450.0 - 1e-6 <= d_kcal <= 620.0 + 1e-6):
                valid = False
                break
            if not (20.0 - 1e-6 <= d_prot <= 40.0 + 1e-6):
                valid = False
                break
            total_horizon_cost += d_cost * scenario.servings_per_day

        if not valid:
            continue
        if any(cnt > scenario.max_repeat_per_family for cnt in fam_counts.values()):
            continue
        if any(used > stock[code] + 1e-6 for code, used in usage.items()):
            continue
        feasible_schedules.append((total_horizon_cost, schedule))

    assert len(feasible_schedules) > 0
    brute_force_min_cost = min(cost for cost, _ in feasible_schedules)

    # --- 2. Solve the exact same instance via PuLP/CBC MILP + independent verifier ---
    feats = precompute_all_recipes(recipes, ingredients, prices, target.limits)
    built = build_recipe_milp(
        scenario=scenario,
        recipes=recipes,
        features_by_id={f.recipe_id: f for f in feats},
        target=target,
        stock_raw_g=stock,
        ingredients_by_code=ingredients,
    )
    raw = solve_built_model(built, time_limit_seconds=10.0)
    assert raw.solver_status == SolverStatusEnum.OPTIMAL
    assert raw.has_incumbent is True
    assert raw.reported_objective is not None

    audit = verify_assignments(
        scenario=scenario,
        assignments_by_day=raw.assignments_by_day,
        recipes_by_id=recipes_by_id,
        ingredients_by_code=ingredients,
        effective_prices_idr_per_g=prices,
        target=target,
        stock_raw_g=stock,
        raw_x_values=raw.raw_x_values,
        reported_objective=raw.reported_objective,
    )
    assert audit.all_hard_constraints_pass is True
    assert raw.reported_objective == pytest.approx(brute_force_min_cost, abs=1e-6)


def test_feasible_not_proven_optimal_and_time_limit_persistence() -> None:
    """Verify FEASIBLE (non-zero gap) and TIME_LIMIT runs persist honestly and obey verifier/export gates."""
    with db_manager.SessionLocal() as session:
        repo = SQLiteVaultRepository(session)
        sc = repo.create_scenario(ScenarioCreateRequest(name="Gap & TimeLimit Persistence"))
        # First run real solve to get a valid incumbent assignment
        sc_ref = repo.create_scenario(ScenarioCreateRequest(name="Ref Solve"))
        ref_run = repo.run_optimization(sc_ref.id)
        assert ref_run.validation_passed is True
        valid_assign = {d.day_index: dict(d.recipes_by_slot) for d in ref_run.days}

        # 1. Simulate FEASIBLE-but-not-proven-OPTIMAL (gap > 0) with valid verified incumbent
        feasible_raw = RawSolveResult(
            solver_status=SolverStatusEnum.FEASIBLE,
            solver_seconds=0.5,
            assignments_by_day=valid_assign,
            has_incumbent=True,
            raw_x_values=None,
            reported_objective=ref_run.objective_total_idr,
            best_bound=(ref_run.objective_total_idr or 0.0) - 25000.0,
            gap_abs=25000.0,
            gap_rel=0.0066,
            solver_name="COIN_CMD",
            solver_version="Devel",
            raw_solver_status="GapLimit",
        )
        run_feas = repo.run_optimization(sc.id, forced_raw_result=feasible_raw)
        assert run_feas.solver_status == SolverStatusEnum.FEASIBLE
        assert run_feas.validation_passed is True
        assert run_feas.gap_abs == pytest.approx(25000.0)

        # 2. Reload from DB and verify exact solver_status & gap preserved
        reloaded = repo.get_run(run_feas.run_id)
        assert reloaded.solver_status == SolverStatusEnum.FEASIBLE
        assert reloaded.validation_passed is True
        assert reloaded.gap_abs == pytest.approx(25000.0)
        assert reloaded.best_bound == pytest.approx(feasible_raw.best_bound)

        # 3. Simulate TIME_LIMIT with NO incumbent -> persisted with validation_passed=False & empty days
        sc_tl = repo.create_scenario(ScenarioCreateRequest(name="TimeLimit Empty"))
        tl_raw = RawSolveResult(
            solver_status=SolverStatusEnum.TIME_LIMIT,
            solver_seconds=10.0,
            assignments_by_day={},
            has_incumbent=False,
            solver_name="COIN_CMD",
            raw_solver_status="TimeLimit",
        )
        run_tl = repo.run_optimization(sc_tl.id, forced_raw_result=tl_raw)
        assert run_tl.solver_status == SolverStatusEnum.TIME_LIMIT
        assert run_tl.validation_passed is False
        assert run_tl.days == []
