from __future__ import annotations

import math
from typing import Dict, Iterable, List

from app.domain.models.schemas import (
    Ingredient,
    NutritionTargetLimit,
    RecipeFeatures,
    RecipeVariant,
)
from app.ingestion.unit_converter import (
    DataValidationError,
    validate_ingredient_nutrients_for_target,
)


def calculate_recipe_features(
    recipe: RecipeVariant,
    ingredients_by_code: Dict[str, Ingredient],
    prices_idr_per_g: Dict[str, float],
    target_limits: Iterable[NutritionTargetLimit],
) -> RecipeFeatures:
    """Deterministically compute full-precision cost (raw_g * IDR/g) and nutrients (edible_fraction * retention)."""
    limits_list = list(target_limits)
    total_cost = 0.0
    nutrients_sum: Dict[str, float] = {lim.nutrient_key: 0.0 for lim in limits_list}
    raw_grams: Dict[str, float] = {}

    for item in recipe.ingredients:
        code = item.ingredient_code
        if code not in ingredients_by_code:
            raise DataValidationError(
                f"Recipe '{recipe.code}' references unmapped ingredient '{code}'"
            )
        if code not in prices_idr_per_g:
            raise DataValidationError(
                f"Missing price for ingredient '{code}' used in recipe '{recipe.code}'"
            )
        price = prices_idr_per_g[code]
        if not math.isfinite(price) or price <= 0:
            raise DataValidationError(
                f"Invalid price {price!r} for ingredient '{code}'"
            )

        raw_g = float(item.raw_g_per_serving)
        retention = float(item.retention_factor)
        if not math.isfinite(raw_g) or raw_g <= 0:
            raise DataValidationError(
                f"Invalid raw_g_per_serving {raw_g!r} for '{code}' in recipe '{recipe.code}'"
            )
        if not math.isfinite(retention) or not (0.0 < retention <= 1.0):
            raise DataValidationError(
                f"Invalid retention_factor {retention!r} for '{code}' in recipe '{recipe.code}'"
            )

        ing = ingredients_by_code[code]
        validate_ingredient_nutrients_for_target(ing, limits_list)

        raw_grams[code] = raw_grams.get(code, 0.0) + raw_g
        total_cost += raw_g * float(price)

        edible_g = raw_g * float(ing.edible_fraction)
        for lim in limits_list:
            per_100g = ing.nutrients.get_nutrient(lim.nutrient_key)
            assert per_100g is not None
            nutrients_sum[lim.nutrient_key] += (
                (edible_g / 100.0) * float(per_100g) * retention
            )

    return RecipeFeatures(
        recipe_id=recipe.id,
        recipe_code=recipe.code,
        recipe_name=recipe.name,
        slot=recipe.slot,
        family=recipe.family,
        cost_idr_per_serving=total_cost,
        nutrients_per_serving=nutrients_sum,
        raw_grams_by_ingredient=raw_grams,
    )


def precompute_all_recipes(
    recipes: Iterable[RecipeVariant],
    ingredients_by_code: Dict[str, Ingredient],
    prices_idr_per_g: Dict[str, float],
    target_limits: Iterable[NutritionTargetLimit],
) -> List[RecipeFeatures]:
    """Compute RecipeFeatures for all provided recipes."""
    limits_list = list(target_limits)
    return [
        calculate_recipe_features(recipe, ingredients_by_code, prices_idr_per_g, limits_list)
        for recipe in recipes
    ]
