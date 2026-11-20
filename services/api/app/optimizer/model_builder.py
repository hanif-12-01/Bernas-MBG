from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple
from uuid import UUID

import pulp

from app.domain.models.schemas import (
    Ingredient,
    NutritionTargetProfile,
    RecipeFeatures,
    RecipeVariant,
    ReviewStatusEnum,
    Scenario,
    SlotEnum,
)


@dataclass
class BuiltMILPModel:
    problem: pulp.LpProblem
    x_vars: Dict[Tuple[int, UUID], pulp.LpVariable]
    eligible_features: Dict[UUID, RecipeFeatures]
    days: List[int]
    slots: List[SlotEnum]


def _sanitize_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", value.strip())
    return cleaned or "unnamed"


def get_effective_recipe_allergens(
    recipe: RecipeVariant,
    ingredients_by_code: Optional[Dict[str, Ingredient]] = None,
) -> Set[str]:
    """Union explicit recipe allergen tags with underlying ingredient allergen tags."""
    allergens: Set[str] = {a.strip().lower() for a in recipe.allergen_tags if a.strip()}
    if ingredients_by_code is not None:
        for item in recipe.ingredients:
            ing = ingredients_by_code.get(item.ingredient_code)
            if ing is not None:
                allergens.update(a.strip().lower() for a in ing.allergens if a.strip())
    return allergens


def filter_eligible_recipes(
    recipes: List[RecipeVariant],
    features_by_id: Dict[UUID, RecipeFeatures],
    excluded_allergens: List[str],
    ingredients_by_code: Optional[Dict[str, Ingredient]] = None,
) -> Dict[UUID, RecipeFeatures]:
    """Keep only active, reviewed recipes without excluded allergens (AC-03, AC-08)."""
    excluded_set: Set[str] = {a.strip().lower() for a in excluded_allergens if a.strip()}
    eligible: Dict[UUID, RecipeFeatures] = {}

    for rec in recipes:
        if not rec.active:
            continue
        if rec.review_status != ReviewStatusEnum.REVIEWED:
            continue
        recipe_allergens = get_effective_recipe_allergens(rec, ingredients_by_code)
        if excluded_set & recipe_allergens:
            continue
        if rec.id in features_by_id:
            eligible[rec.id] = features_by_id[rec.id]

    return eligible


def build_recipe_milp(
    scenario: Scenario,
    recipes: List[RecipeVariant],
    features_by_id: Dict[UUID, RecipeFeatures],
    target: NutritionTargetProfile,
    stock_raw_g: Dict[str, float],
    ingredients_by_code: Optional[Dict[str, Ingredient]] = None,
) -> BuiltMILPModel:
    """Build recipe-based binary MILP per 04_Engineering/MILP Mathematical Model.md."""
    eligible = filter_eligible_recipes(
        recipes,
        features_by_id,
        scenario.excluded_allergens,
        ingredients_by_code=ingredients_by_code,
    )
    slots = list(SlotEnum)
    days = list(range(1, scenario.days + 1))

    # Validate each slot has at least one eligible recipe before building model
    recipes_by_slot: Dict[SlotEnum, List[RecipeFeatures]] = {s: [] for s in slots}
    for feat in eligible.values():
        recipes_by_slot[feat.slot].append(feat)

    empty_slots = [s.value for s, lst in recipes_by_slot.items() if not lst]
    if empty_slots:
        raise ValueError(
            f"No eligible reviewed recipes available for slot(s): {', '.join(empty_slots)}"
        )

    # Validate stock completeness & finiteness for every ingredient used by eligible recipes
    used_ingredients: Set[str] = {
        ing_code
        for feat in eligible.values()
        for ing_code in feat.raw_grams_by_ingredient
    }
    missing_stock = sorted(code for code in used_ingredients if code not in stock_raw_g)
    if missing_stock:
        raise ValueError(
            f"Missing stock data for ingredient(s) used in eligible recipes: {', '.join(missing_stock)}"
        )
    for code in used_ingredients:
        avail = stock_raw_g[code]
        if not math.isfinite(avail) or avail < 0:
            raise ValueError(f"Invalid stock value {avail!r} for ingredient '{code}'")

    prob = pulp.LpProblem("GiziOptima_Recipe_MILP", pulp.LpMinimize)

    x: Dict[Tuple[int, UUID], pulp.LpVariable] = {
        (d, rid): prob.add_variable(
            f"x_d{d}_{_sanitize_name(eligible[rid].recipe_code)}_{rid.hex[:12]}",
            cat="Binary",
        )
        for d in days
        for rid in eligible
    }

    # Objective: minimize sum_d N_d * sum_r c_r * x_{dr}
    prob += (
        pulp.lpSum(
            scenario.servings_per_day * feat.cost_idr_per_serving * x[(d, rid)]
            for d in days
            for rid, feat in eligible.items()
        ),
        "Total_Procurement_Cost_IDR",
    )

    # 1. Slot coverage: exactly 1 recipe per slot per day
    for d in days:
        for slot in slots:
            prob += (
                pulp.lpSum(x[(d, feat.recipe_id)] for feat in recipes_by_slot[slot]) == 1,
                f"slot_coverage_d{d}_{slot.value}",
            )

    # 2. Per-day per-serving budget
    for d in days:
        prob += (
            pulp.lpSum(feat.cost_idr_per_serving * x[(d, rid)] for rid, feat in eligible.items())
            <= scenario.budget_idr_per_serving,
            f"budget_d{d}",
        )

    # 3 & 4. Nutrition floor & ceiling per day
    for d in days:
        for limit in target.limits:
            k = limit.nutrient_key
            expr = pulp.lpSum(
                feat.nutrients_per_serving[k] * x[(d, rid)] for rid, feat in eligible.items()
            )
            if limit.min_per_serving is not None:
                prob += expr >= limit.min_per_serving, f"nutrient_min_d{d}_{_sanitize_name(k)}"
            if limit.max_per_serving is not None:
                prob += expr <= limit.max_per_serving, f"nutrient_max_d{d}_{_sanitize_name(k)}"

    # 5. Whole-horizon raw ingredient stock (for every ingredient used in eligible recipes)
    for ing_code in sorted(used_ingredients):
        available_g = stock_raw_g[ing_code]
        usage_terms = [
            scenario.servings_per_day * feat.raw_grams_by_ingredient[ing_code] * x[(d, rid)]
            for d in days
            for rid, feat in eligible.items()
            if ing_code in feat.raw_grams_by_ingredient
        ]
        if usage_terms:
            prob += (
                pulp.lpSum(usage_terms) <= available_g,
                f"stock_{_sanitize_name(ing_code)}",
            )

    # 6. Repeat cap per recipe family across plan horizon
    families: Dict[str, List[UUID]] = {}
    for rid, feat in eligible.items():
        families.setdefault(feat.family, []).append(rid)

    for family, rids in sorted(families.items()):
        prob += (
            pulp.lpSum(x[(d, rid)] for d in days for rid in rids)
            <= scenario.max_repeat_per_family,
            f"repeat_cap_{_sanitize_name(family)}",
        )

    return BuiltMILPModel(
        problem=prob,
        x_vars=x,
        eligible_features=eligible,
        days=days,
        slots=slots,
    )
