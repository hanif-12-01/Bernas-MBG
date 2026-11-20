from __future__ import annotations

import pytest

from app.domain.models.schemas import (
    Ingredient,
    IngredientNutrients,
    NutritionTargetLimit,
    RecipeIngredient,
    RecipeVariant,
    ReviewStatusEnum,
    SlotEnum,
)
from app.domain.recipe_calculator import calculate_recipe_features
from app.ingestion.unit_converter import (
    DataValidationError,
    UnitConversionError,
    convert_price_to_idr_per_g,
)


def test_idr_per_kg_exact_conversion() -> None:
    assert convert_price_to_idr_per_g(16000, "IDR/kg") == pytest.approx(16.0)
    assert convert_price_to_idr_per_g(25.5, "IDR/g") == pytest.approx(25.5)


@pytest.mark.parametrize("bad_price", [0.0, -100.0])
def test_reject_non_positive_price(bad_price: float) -> None:
    with pytest.raises(UnitConversionError):
        convert_price_to_idr_per_g(bad_price, "IDR/kg")


def test_reject_liter_without_density_and_accept_with_density() -> None:
    with pytest.raises(UnitConversionError):
        convert_price_to_idr_per_g(18000, "IDR/liter")

    # With reviewed density 0.92 g/ml: 1 L = 920 g
    per_g = convert_price_to_idr_per_g(18400, "IDR/liter", density_g_per_ml=0.92)
    assert per_g == pytest.approx(20.0)


def test_reject_unknown_unit() -> None:
    with pytest.raises(UnitConversionError):
        convert_price_to_idr_per_g(10000, "IDR/ikat")


def test_reject_missing_required_nutrient_no_silent_zero() -> None:
    ing = Ingredient(
        code="ING_MISS",
        name="Bahan Tanpa Protein",
        category="test",
        edible_fraction=0.8,
        nutrients=IngredientNutrients(energy_kcal_100g=100.0, protein_g_100g=None),
    )
    recipe = RecipeVariant(
        code="R_TEST",
        name="Test Recipe",
        slot=SlotEnum.PROTEIN,
        family="test",
        review_status=ReviewStatusEnum.REVIEWED,
        ingredients=[RecipeIngredient(ingredient_code="ING_MISS", raw_g_per_serving=50.0)],
    )
    limits = [
        NutritionTargetLimit(nutrient_key="energy_kcal", min_per_serving=100.0, unit="kcal"),
        NutritionTargetLimit(nutrient_key="protein_g", min_per_serving=10.0, unit="g"),
    ]
    with pytest.raises(DataValidationError):
        calculate_recipe_features(recipe, {"ING_MISS": ing}, {"ING_MISS": 10.0}, limits)


def test_deterministic_cost_and_nutrient_formula() -> None:
    # raw_g = 100, price = 20 IDR/g => cost = 2000 IDR
    # edible = 0.8, protein_100g = 25, retention = 0.9 => (100 * 0.8 / 100) * 25 * 0.9 = 18.0 g
    ing = Ingredient(
        code="ING_OK",
        name="Bahan Uji",
        category="protein",
        edible_fraction=0.8,
        nutrients=IngredientNutrients(energy_kcal_100g=200.0, protein_g_100g=25.0),
    )
    recipe = RecipeVariant(
        code="R_OK",
        name="Resep Uji",
        slot=SlotEnum.PROTEIN,
        family="test",
        review_status=ReviewStatusEnum.REVIEWED,
        ingredients=[
            RecipeIngredient(
                ingredient_code="ING_OK",
                raw_g_per_serving=100.0,
                retention_factor=0.9,
            )
        ],
    )
    limits = [
        NutritionTargetLimit(nutrient_key="energy_kcal", min_per_serving=50.0, unit="kcal"),
        NutritionTargetLimit(nutrient_key="protein_g", min_per_serving=5.0, unit="g"),
    ]
    feat = calculate_recipe_features(recipe, {"ING_OK": ing}, {"ING_OK": 20.0}, limits)
    assert feat.cost_idr_per_serving == pytest.approx(2000.0)
    assert feat.nutrients_per_serving["protein_g"] == pytest.approx(18.0)
    assert feat.nutrients_per_serving["energy_kcal"] == pytest.approx(144.0)
