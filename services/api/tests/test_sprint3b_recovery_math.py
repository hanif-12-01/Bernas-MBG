from __future__ import annotations

from itertools import product
from typing import Dict, List, Tuple
from uuid import UUID, uuid5, NAMESPACE_DNS

from app.domain.models.schemas import (
    Ingredient,
    IngredientNutrients,
    NutritionTargetLimit,
    NutritionTargetProfile,
    RecipeFeatures,
    RecipeIngredient,
    RecipeVariant,
    ReviewStatusEnum,
    Scenario,
    SlotEnum,
    SolverStatusEnum,
    SourceTypeEnum,
)
from app.domain.recipe_calculator import precompute_all_recipes
from app.optimizer.model_builder import build_recipe_milp
from app.optimizer.solver import create_cbc_solver, solve_built_model
from app.optimizer.verifier import verify_assignments
from app.recovery.optimizer import count_slot_changes, solve_minimum_disruption_milp


def _uid(name: str) -> UUID:
    return uuid5(NAMESPACE_DNS, f"gizioptima.sprint3b.{name}")


def _build_compact_test_fixture():
    """Create a compact 3-day x 4-slot universe small enough for exact brute-force enumeration."""
    ingredients = {
        "STAPLE_RICE": Ingredient(
            id=_uid("ing_rice"),
            code="STAPLE_RICE",
            name="Beras",
            category="staple",
            edible_fraction=1.0,
            nutrients=IngredientNutrients(
                energy_kcal_100g=360,
                protein_g_100g=7.0,
                fat_g_100g=0.8,
                carb_g_100g=78.0,
                fiber_g_100g=1.2,
                iron_mg_100g=0.8,
            ),
            source_type=SourceTypeEnum.SYNTHETIC,
            source_ref="TEST",
            review_status=ReviewStatusEnum.REVIEWED,
        ),
        "PROT_CHICKEN": Ingredient(
            id=_uid("ing_chicken"),
            code="PROT_CHICKEN",
            name="Ayam",
            category="protein",
            edible_fraction=1.0,
            nutrients=IngredientNutrients(
                energy_kcal_100g=165,
                protein_g_100g=24.0,
                fat_g_100g=7.0,
                carb_g_100g=0.0,
                fiber_g_100g=0.0,
                iron_mg_100g=1.0,
            ),
            source_type=SourceTypeEnum.SYNTHETIC,
            source_ref="TEST",
            review_status=ReviewStatusEnum.REVIEWED,
        ),
        "PROT_FISH": Ingredient(
            id=_uid("ing_fish"),
            code="PROT_FISH",
            name="Ikan",
            category="protein",
            edible_fraction=1.0,
            nutrients=IngredientNutrients(
                energy_kcal_100g=140,
                protein_g_100g=22.0,
                fat_g_100g=4.5,
                carb_g_100g=0.0,
                fiber_g_100g=0.0,
                iron_mg_100g=1.2,
            ),
            source_type=SourceTypeEnum.SYNTHETIC,
            source_ref="TEST",
            review_status=ReviewStatusEnum.REVIEWED,
        ),
        "PROT_TEMPE": Ingredient(
            id=_uid("ing_tempe"),
            code="PROT_TEMPE",
            name="Tempe",
            category="protein",
            edible_fraction=1.0,
            allergens=["soy"],
            nutrients=IngredientNutrients(
                energy_kcal_100g=193,
                protein_g_100g=19.0,
                fat_g_100g=10.8,
                carb_g_100g=9.4,
                fiber_g_100g=5.0,
                iron_mg_100g=2.7,
            ),
            source_type=SourceTypeEnum.SYNTHETIC,
            source_ref="TEST",
            review_status=ReviewStatusEnum.REVIEWED,
        ),
        "VEG_SPINACH": Ingredient(
            id=_uid("ing_spinach"),
            code="VEG_SPINACH",
            name="Bayam",
            category="vegetable",
            edible_fraction=0.9,
            nutrients=IngredientNutrients(
                energy_kcal_100g=23,
                protein_g_100g=2.9,
                fat_g_100g=0.4,
                carb_g_100g=3.6,
                fiber_g_100g=2.2,
                iron_mg_100g=2.7,
            ),
            source_type=SourceTypeEnum.SYNTHETIC,
            source_ref="TEST",
            review_status=ReviewStatusEnum.REVIEWED,
        ),
        "FRUIT_BANANA": Ingredient(
            id=_uid("ing_banana"),
            code="FRUIT_BANANA",
            name="Pisang",
            category="fruit",
            edible_fraction=0.8,
            nutrients=IngredientNutrients(
                energy_kcal_100g=99,
                protein_g_100g=1.1,
                fat_g_100g=0.2,
                carb_g_100g=25.8,
                fiber_g_100g=2.6,
                iron_mg_100g=0.4,
            ),
            source_type=SourceTypeEnum.SYNTHETIC,
            source_ref="TEST",
            review_status=ReviewStatusEnum.REVIEWED,
        ),
    }

    prices_idr_per_g = {
        "STAPLE_RICE": 15.0,   # Rp 15,000/kg
        "PROT_CHICKEN": 40.0,  # Rp 40,000/kg
        "PROT_FISH": 36.0,     # Rp 36,000/kg
        "PROT_TEMPE": 18.0,    # Rp 18,000/kg
        "VEG_SPINACH": 12.0,   # Rp 12,000/kg
        "FRUIT_BANANA": 14.0,  # Rp 14,000/kg
    }

    recipes = [
        RecipeVariant(
            id=_uid("rec_rice"),
            code="R_RICE",
            name="Nasi Putih",
            slot=SlotEnum.STAPLE,
            family="rice",
            review_status=ReviewStatusEnum.REVIEWED,
            active=True,
            ingredients=[RecipeIngredient(ingredient_code="STAPLE_RICE", raw_g_per_serving=120.0)],
        ),
        RecipeVariant(
            id=_uid("rec_chicken"),
            code="R_CHICKEN",
            name="Ayam Panggang",
            slot=SlotEnum.PROTEIN,
            family="poultry",
            review_status=ReviewStatusEnum.REVIEWED,
            active=True,
            ingredients=[RecipeIngredient(ingredient_code="PROT_CHICKEN", raw_g_per_serving=100.0)],
        ),
        RecipeVariant(
            id=_uid("rec_fish"),
            code="R_FISH",
            name="Ikan Kukus",
            slot=SlotEnum.PROTEIN,
            family="fish",
            review_status=ReviewStatusEnum.REVIEWED,
            active=True,
            ingredients=[RecipeIngredient(ingredient_code="PROT_FISH", raw_g_per_serving=100.0)],
        ),
        RecipeVariant(
            id=_uid("rec_tempe"),
            code="R_TEMPE",
            name="Tempe Bacem",
            slot=SlotEnum.PROTEIN,
            family="soy_prot",
            review_status=ReviewStatusEnum.REVIEWED,
            active=True,
            allergen_tags=["soy"],
            ingredients=[RecipeIngredient(ingredient_code="PROT_TEMPE", raw_g_per_serving=110.0)],
        ),
        RecipeVariant(
            id=_uid("rec_draft_fish"),
            code="R_DRAFT",
            name="Ikan Draft (Non-Reviewed)",
            slot=SlotEnum.PROTEIN,
            family="draft_fish",
            review_status=ReviewStatusEnum.DRAFT,
            active=True,
            ingredients=[RecipeIngredient(ingredient_code="PROT_FISH", raw_g_per_serving=90.0)],
        ),
        RecipeVariant(
            id=_uid("rec_spinach"),
            code="R_SPINACH",
            name="Tumis Bayam",
            slot=SlotEnum.VEGETABLE,
            family="greens",
            review_status=ReviewStatusEnum.REVIEWED,
            active=True,
            ingredients=[RecipeIngredient(ingredient_code="VEG_SPINACH", raw_g_per_serving=100.0)],
        ),
        RecipeVariant(
            id=_uid("rec_banana"),
            code="R_BANANA",
            name="Pisang Ambon",
            slot=SlotEnum.FRUIT,
            family="banana",
            review_status=ReviewStatusEnum.REVIEWED,
            active=True,
            ingredients=[RecipeIngredient(ingredient_code="FRUIT_BANANA", raw_g_per_serving=100.0)],
        ),
    ]

    target = NutritionTargetProfile(
        id=_uid("target_std"),
        cohort="SD_7_12",
        meal_type="lunch",
        source_ref="TEST",
        version="1.0",
        review_status=ReviewStatusEnum.REVIEWED,
        limits=[
            NutritionTargetLimit(nutrient_key="energy_kcal", min_per_serving=550.0, max_per_serving=950.0, unit="kcal"),
            NutritionTargetLimit(nutrient_key="protein_g", min_per_serving=24.0, max_per_serving=55.0, unit="g"),
        ],
    )

    scenario = Scenario(
        id=_uid("sc_compact"),
        name="Compact Recovery Test",
        dataset_version_id=_uid("ds_compact"),
        nutrition_target_id=target.id,
        meal_type="lunch",
        servings_per_day=100,
        days=3,
        budget_idr_per_serving=12000.0,
        max_repeat_per_family=3,
        excluded_allergens=[],
    )
    return scenario, ingredients, prices_idr_per_g, recipes, target


def _brute_force_feasible_menus(
    *,
    scenario: Scenario,
    recipes: List[RecipeVariant],
    features_by_id: Dict[UUID, RecipeFeatures],
    target: NutritionTargetProfile,
    stock_raw_g: Dict[str, float],
    baseline_assignments: Dict[int, Dict[SlotEnum, UUID]],
) -> List[Tuple[int, float, Dict[int, Dict[SlotEnum, UUID]]]]:
    """Exhaustive reference enumerator checking every hard constraint independently."""
    eligible = [
        r
        for r in recipes
        if r.active
        and r.review_status == ReviewStatusEnum.REVIEWED
        and not (set(scenario.excluded_allergens) & set(r.allergen_tags))
    ]
    by_slot = {
        s: [r for r in eligible if r.slot == s]
        for s in SlotEnum
    }
    daily_combos: List[Dict[SlotEnum, RecipeVariant]] = [
        dict(zip(SlotEnum, combo))
        for combo in product(
            by_slot[SlotEnum.STAPLE],
            by_slot[SlotEnum.PROTEIN],
            by_slot[SlotEnum.VEGETABLE],
            by_slot[SlotEnum.FRUIT],
        )
    ]

    feasible: List[Tuple[int, float, Dict[int, Dict[SlotEnum, UUID]]]] = []
    for week in product(daily_combos, repeat=scenario.days):
        total_cost = 0.0
        ing_used_g: Dict[str, float] = {}
        fam_counts: Dict[str, int] = {}
        ok = True
        assigns: Dict[int, Dict[SlotEnum, UUID]] = {}

        for day_idx, day_map in enumerate(week, start=1):
            day_cost = 0.0
            day_nutr: Dict[str, float] = {lim.nutrient_key: 0.0 for lim in target.limits}
            assigns[day_idx] = {}
            for slot, rec in day_map.items():
                feat = features_by_id[rec.id]
                assigns[day_idx][slot] = rec.id
                day_cost += feat.cost_idr_per_serving
                fam_counts[rec.family] = fam_counts.get(rec.family, 0) + 1
                for k in day_nutr:
                    day_nutr[k] += feat.nutrients_per_serving[k]
                for code, rg in feat.raw_grams_by_ingredient.items():
                    ing_used_g[code] = ing_used_g.get(code, 0.0) + rg * scenario.servings_per_day

            if day_cost > scenario.budget_idr_per_serving + 1e-6:
                ok = False
                break
            for lim in target.limits:
                val = day_nutr[lim.nutrient_key]
                if lim.min_per_serving is not None and val + 1e-6 < lim.min_per_serving:
                    ok = False
                if lim.max_per_serving is not None and val - 1e-6 > lim.max_per_serving:
                    ok = False
            if not ok:
                break
            total_cost += day_cost * scenario.servings_per_day

        if not ok:
            continue
        if any(c > scenario.max_repeat_per_family for c in fam_counts.values()):
            continue
        if any(used > stock_raw_g.get(code, 0.0) + 1e-6 for code, used in ing_used_g.items()):
            continue

        swaps = count_slot_changes(baseline_assignments, assigns)
        feasible.append((swaps, round(total_cost, 4), assigns))

    return feasible


def test_min_disruption_matches_brute_force_and_stage2_tiebreaker():
    scenario, ingredients, prices, recipes, target = _build_compact_test_fixture()
    features = {
        f.recipe_id: f
        for f in precompute_all_recipes(recipes, ingredients, prices, target.limits)
    }

    # Baseline menu uses Chicken (expensive) on Day 1 & Day 2, Fish on Day 3
    baseline = {
        1: {
            SlotEnum.STAPLE: _uid("rec_rice"),
            SlotEnum.PROTEIN: _uid("rec_chicken"),
            SlotEnum.VEGETABLE: _uid("rec_spinach"),
            SlotEnum.FRUIT: _uid("rec_banana"),
        },
        2: {
            SlotEnum.STAPLE: _uid("rec_rice"),
            SlotEnum.PROTEIN: _uid("rec_chicken"),
            SlotEnum.VEGETABLE: _uid("rec_spinach"),
            SlotEnum.FRUIT: _uid("rec_banana"),
        },
        3: {
            SlotEnum.STAPLE: _uid("rec_rice"),
            SlotEnum.PROTEIN: _uid("rec_fish"),
            SlotEnum.VEGETABLE: _uid("rec_spinach"),
            SlotEnum.FRUIT: _uid("rec_banana"),
        },
    }

    # Partial chicken shortage: previously needed 20 kg (2 days x 10 kg), now only 10 kg available!
    # Also tempe (Rp 18k/kg, 110g = Rp 1,980/serv) is cheaper than fish (Rp 36k/kg, 100g = Rp 3,600/serv).
    new_stock = {
        "STAPLE_RICE": 100000.0,
        "PROT_CHICKEN": 10000.0,  # Enough for only ONE chicken day!
        "PROT_FISH": 50000.0,
        "PROT_TEMPE": 50000.0,
        "VEG_SPINACH": 100000.0,
        "FRUIT_BANANA": 100000.0,
    }

    all_feasible = _brute_force_feasible_menus(
        scenario=scenario,
        recipes=recipes,
        features_by_id=features,
        target=target,
        stock_raw_g=new_stock,
        baseline_assignments=baseline,
    )
    assert all_feasible, "Test universe must have feasible schedules"

    expected_d_min = min(swaps for swaps, _cost, _a in all_feasible)
    expected_stage2_cost = min(cost for swaps, cost, _a in all_feasible if swaps == expected_d_min)
    expected_min_cost = min(cost for _swaps, cost, _a in all_feasible)

    outcome = solve_minimum_disruption_milp(
        scenario=scenario,
        recipes=recipes,
        features_by_id=features,
        target=target,
        stock_raw_g=new_stock,
        baseline_assignments=baseline,
        ingredients_by_code=ingredients,
    )
    assert outcome.raw_result.solver_status == SolverStatusEnum.OPTIMAL
    assert outcome.min_changed_slots == expected_d_min == 1
    assert count_slot_changes(baseline, outcome.raw_result.assignments_by_day) == expected_d_min
    assert round(float(outcome.raw_result.reported_objective), 2) == round(expected_stage2_cost, 2)

    audit = verify_assignments(
        scenario=scenario,
        assignments_by_day=outcome.raw_result.assignments_by_day,
        recipes_by_id={r.id: r for r in recipes},
        ingredients_by_code=ingredients,
        effective_prices_idr_per_g=prices,
        target=target,
        stock_raw_g=new_stock,
        raw_x_values=outcome.raw_result.raw_x_values,
        reported_objective=outcome.raw_result.reported_objective,
    )
    assert audit.all_hard_constraints_pass is True

    # Also verify global Min-Cost mode picks strictly cheaper (or equal) schedule with more swaps (tempe all 3 days!)
    built_cost = build_recipe_milp(
        scenario=scenario,
        recipes=recipes,
        features_by_id=features,
        target=target,
        stock_raw_g=new_stock,
        ingredients_by_code=ingredients,
    )
    raw_cost = solve_built_model(built_cost, solver=create_cbc_solver())
    assert raw_cost.solver_status == SolverStatusEnum.OPTIMAL
    assert round(float(raw_cost.reported_objective), 2) == round(expected_min_cost, 2)
    assert expected_min_cost < expected_stage2_cost
    assert count_slot_changes(baseline, raw_cost.assignments_by_day) > expected_d_min


def test_zero_disruption_when_baseline_remains_feasible():
    scenario, ingredients, prices, recipes, target = _build_compact_test_fixture()
    features = {
        f.recipe_id: f
        for f in precompute_all_recipes(recipes, ingredients, prices, target.limits)
    }
    baseline = {
        1: {
            SlotEnum.STAPLE: _uid("rec_rice"),
            SlotEnum.PROTEIN: _uid("rec_chicken"),
            SlotEnum.VEGETABLE: _uid("rec_spinach"),
            SlotEnum.FRUIT: _uid("rec_banana"),
        },
        2: {
            SlotEnum.STAPLE: _uid("rec_rice"),
            SlotEnum.PROTEIN: _uid("rec_fish"),
            SlotEnum.VEGETABLE: _uid("rec_spinach"),
            SlotEnum.FRUIT: _uid("rec_banana"),
        },
        3: {
            SlotEnum.STAPLE: _uid("rec_rice"),
            SlotEnum.PROTEIN: _uid("rec_fish"),
            SlotEnum.VEGETABLE: _uid("rec_spinach"),
            SlotEnum.FRUIT: _uid("rec_banana"),
        },
    }
    ample_stock = {code: 100000.0 for code in ingredients}

    outcome = solve_minimum_disruption_milp(
        scenario=scenario,
        recipes=recipes,
        features_by_id=features,
        target=target,
        stock_raw_g=ample_stock,
        baseline_assignments=baseline,
        ingredients_by_code=ingredients,
    )
    assert outcome.raw_result.solver_status == SolverStatusEnum.OPTIMAL
    assert outcome.min_changed_slots == 0
    assert outcome.raw_result.assignments_by_day == baseline


def test_infeasible_respects_draft_and_allergen_exclusions():
    base_scenario, ingredients, prices, recipes, target = _build_compact_test_fixture()
    scenario = base_scenario.model_copy(update={"excluded_allergens": ["soy"]})
    features = {
        f.recipe_id: f
        for f in precompute_all_recipes(recipes, ingredients, prices, target.limits)
    }
    baseline = {
        1: {
            SlotEnum.STAPLE: _uid("rec_rice"),
            SlotEnum.PROTEIN: _uid("rec_chicken"),
            SlotEnum.VEGETABLE: _uid("rec_spinach"),
            SlotEnum.FRUIT: _uid("rec_banana"),
        },
        2: {
            SlotEnum.STAPLE: _uid("rec_rice"),
            SlotEnum.PROTEIN: _uid("rec_chicken"),
            SlotEnum.VEGETABLE: _uid("rec_spinach"),
            SlotEnum.FRUIT: _uid("rec_banana"),
        },
        3: {
            SlotEnum.STAPLE: _uid("rec_rice"),
            SlotEnum.PROTEIN: _uid("rec_chicken"),
            SlotEnum.VEGETABLE: _uid("rec_spinach"),
            SlotEnum.FRUIT: _uid("rec_banana"),
        },
    }
    # Zero chicken, insufficient fish -> only tempe (blocked by soy allergen) and R_DRAFT (unreviewed) exist -> MUST be INFEASIBLE!
    tight_stock = {
        "STAPLE_RICE": 100000.0,
        "PROT_CHICKEN": 0.0,
        "PROT_FISH": 5000.0,  # Not enough for even 1 serving day (needs 10 kg)
        "PROT_TEMPE": 100000.0,
        "VEG_SPINACH": 100000.0,
        "FRUIT_BANANA": 100000.0,
    }

    outcome = solve_minimum_disruption_milp(
        scenario=scenario,
        recipes=recipes,
        features_by_id=features,
        target=target,
        stock_raw_g=tight_stock,
        baseline_assignments=baseline,
        ingredients_by_code=ingredients,
    )
    assert outcome.raw_result.solver_status == SolverStatusEnum.INFEASIBLE
    assert outcome.min_changed_slots is None
