from __future__ import annotations

import math
from decimal import Decimal, InvalidOperation
from typing import Iterable, Optional

from app.domain.models.schemas import Ingredient, NutritionTargetLimit


class UnitConversionError(ValueError):
    """Raised when unit conversion is unsupported, missing density, non-finite, or non-positive."""


class DataValidationError(ValueError):
    """Raised when required nutrition or master data is missing, non-finite, or invalid."""


SUPPORTED_WEIGHT_PRICE_UNITS = {"IDR/kg", "IDR/g"}
SUPPORTED_VOLUME_PRICE_UNITS = {"IDR/liter", "IDR/L"}


def _to_positive_decimal(value: Optional[float], label: str) -> Decimal:
    if value is None or isinstance(value, bool):
        raise UnitConversionError(f"{label} must be a finite positive number, got {value!r}")
    if not isinstance(value, (int, float, Decimal)):
        raise UnitConversionError(f"{label} must be numeric, got {type(value).__name__}")
    if isinstance(value, float) and not math.isfinite(value):
        raise UnitConversionError(f"{label} must be finite, got {value!r}")
    try:
        dec = Decimal(str(value))
    except InvalidOperation as exc:
        raise UnitConversionError(f"Invalid numeric {label}: {value!r}") from exc
    if not dec.is_finite() or dec <= 0:
        raise UnitConversionError(f"{label} must be strictly positive, got {value!r}")
    return dec


def convert_price_to_idr_per_g(
    value: float,
    unit: str,
    density_g_per_ml: Optional[float] = None,
) -> float:
    """Convert an input price into IDR/g using exact Decimal division without silent assumptions.

    - IDR/kg -> exact division by 1000
    - IDR/g  -> identity
    - IDR/liter / IDR/L -> requires reviewed finite density_g_per_ml > 0 (1 liter = 1000 ml)
    - Rejects price <= 0, NaN/Inf, and unknown units.
    """
    dec_val = _to_positive_decimal(value, "Price")

    if not isinstance(unit, str) or not unit.strip():
        raise UnitConversionError(f"Price unit must be a non-empty string, got {unit!r}")

    normalized_unit = unit.strip()
    if normalized_unit == "IDR/kg":
        return float(dec_val / Decimal("1000"))
    if normalized_unit == "IDR/g":
        return float(dec_val)
    if normalized_unit in SUPPORTED_VOLUME_PRICE_UNITS:
        if density_g_per_ml is None:
            raise UnitConversionError(
                f"Unit '{unit}' requires a reviewed positive density_g_per_ml; cannot silently convert to IDR/g"
            )
        dec_density = _to_positive_decimal(density_g_per_ml, "density_g_per_ml")
        grams_per_liter = Decimal("1000") * dec_density
        return float(dec_val / grams_per_liter)

    raise UnitConversionError(
        f"Unsupported price unit '{unit}'. Allowed: IDR/kg, IDR/g, IDR/liter (with density)"
    )


def validate_ingredient_nutrients_for_target(
    ingredient: Ingredient,
    target_limits: Iterable[NutritionTargetLimit],
) -> None:
    """Ensure every nutrient required by the target profile is present, finite, and non-negative.

    Missing nutrients are never silently defaulted to 0 (AC-02).
    """
    if not math.isfinite(ingredient.edible_fraction) or not (0.0 < ingredient.edible_fraction <= 1.0):
        raise DataValidationError(
            f"Ingredient '{ingredient.code}' has invalid edible_fraction={ingredient.edible_fraction!r}"
        )

    for limit in target_limits:
        try:
            val = ingredient.nutrients.get_nutrient(limit.nutrient_key)
        except ValueError as exc:
            raise DataValidationError(str(exc)) from exc

        if val is None:
            raise DataValidationError(
                f"Ingredient '{ingredient.code}' ({ingredient.name}) is missing required nutrient '{limit.nutrient_key}'"
            )
        if not math.isfinite(val):
            raise DataValidationError(
                f"Ingredient '{ingredient.code}' has non-finite value {val!r} for '{limit.nutrient_key}'"
            )
        if val < 0:
            raise DataValidationError(
                f"Ingredient '{ingredient.code}' has negative value {val} for '{limit.nutrient_key}'"
            )
