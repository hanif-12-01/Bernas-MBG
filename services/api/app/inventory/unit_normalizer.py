from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Optional

from app.ingestion.unit_converter import UnitConversionError


class PriceProvenanceEnum(str, Enum):
    ACTUAL_SUPPLIER = "ACTUAL_SUPPLIER"
    SYNTHETIC_EXAMPLE = "SYNTHETIC_EXAMPLE"
    OFFICIAL_MARKET_REFERENCE = "OFFICIAL_MARKET_REFERENCE"
    UNKNOWN = "UNKNOWN"


WEIGHT_FACTORS_TO_G: dict[str, Decimal] = {
    "g": Decimal("1"),
    "gram": Decimal("1"),
    "grams": Decimal("1"),
    "gr": Decimal("1"),
    "kg": Decimal("1000"),
    "kilogram": Decimal("1000"),
    "kilograms": Decimal("1000"),
    "ons": Decimal("100"),
    "mg": Decimal("0.001"),
}

VOLUME_FACTORS_TO_ML: dict[str, Decimal] = {
    "ml": Decimal("1"),
    "milliliter": Decimal("1"),
    "milliliters": Decimal("1"),
    "l": Decimal("1000"),
    "liter": Decimal("1000"),
    "liters": Decimal("1000"),
}

ITEM_UNITS: set[str] = {
    "item",
    "items",
    "pcs",
    "pc",
    "unit",
    "butir",
    "buah",
    "potong",
    "ikat",
    "pack",
}

UNSUPPORTED_AMBIGUOUS_UNITS: set[str] = {
    "lb",
    "lbs",
    "pound",
    "pounds",
    "oz",
    "ounce",
    "karung",
    "sak",
    "sack",
    "box",
    "dus",
    "krat",
    "kraton",
}


@dataclass(frozen=True)
class NormalizedQuantity:
    original_value: float
    original_unit: str
    normalized_raw_g: float
    canonical_unit: str
    conversion_factor_to_g: float


def _to_finite_decimal(value: float, label: str, *, allow_zero: bool = True) -> Decimal:
    if value is None or isinstance(value, bool):
        raise UnitConversionError(f"{label} harus berupa angka valid, bukan {value!r}")
    if isinstance(value, float) and not math.isfinite(value):
        raise UnitConversionError(f"{label} tidak boleh NaN atau Inf: {value!r}")
    try:
        dec = Decimal(str(value))
    except InvalidOperation as exc:
        raise UnitConversionError(f"Nilai numerik tidak valid untuk {label}: {value!r}") from exc
    if not dec.is_finite():
        raise UnitConversionError(f"{label} harus finite: {value!r}")
    if allow_zero and dec < 0:
        raise UnitConversionError(f"{label} tidak boleh negatif: {value!r}")
    if not allow_zero and dec <= 0:
        raise UnitConversionError(f"{label} harus lebih besar dari 0: {value!r}")
    return dec


def normalize_quantity_to_grams(
    value: float,
    unit: str,
    *,
    density_g_per_ml: Optional[float] = None,
    unit_weight_g: Optional[float] = None,
    claimed_unit: Optional[str] = None,
    allow_zero: bool = True,
) -> NormalizedQuantity:
    """Deterministically normalize weight, volume (with density), or item count (with unit_weight_g) to grams.

    Rejects:
    - Non-finite or negative values
    - Case/unit mismatches when claimed_unit conflicts with unit (e.g. '500 g' vs '500 kg')
    - Volume without reviewed positive density_g_per_ml
    - Item count without reviewed positive unit_weight_g
    - Ambiguous / non-SI units such as lbs, oz, karung, box without explicit weight
    """
    dec_val = _to_finite_decimal(value, "quantity", allow_zero=allow_zero)
    if not isinstance(unit, str) or not unit.strip():
        raise UnitConversionError("Satuan unit wajib diisi dan tidak boleh kosong.")

    raw_unit = unit.strip()
    norm_unit = raw_unit.lower()

    if claimed_unit is not None and claimed_unit.strip():
        claimed_norm = claimed_unit.strip().lower()
        if claimed_norm != norm_unit:
            raise UnitConversionError(
                f"Konflik unit terdeteksi: dokumen sumber mencantumkan '{raw_unit}', tetapi jalur input mengklaim '{claimed_unit}'. Catatan dikarantina."
            )

    if norm_unit in UNSUPPORTED_AMBIGUOUS_UNITS:
        raise UnitConversionError(
            f"Satuan '{raw_unit}' tidak didukung atau ambigu tanpa faktor konversi terverifikasi."
        )

    if norm_unit in WEIGHT_FACTORS_TO_G:
        factor = WEIGHT_FACTORS_TO_G[norm_unit]
        grams = float(dec_val * factor)
        return NormalizedQuantity(
            original_value=float(dec_val),
            original_unit=raw_unit,
            normalized_raw_g=grams,
            canonical_unit="g",
            conversion_factor_to_g=float(factor),
        )

    if norm_unit in VOLUME_FACTORS_TO_ML:
        if density_g_per_ml is None:
            raise UnitConversionError(
                f"Konversi volume '{raw_unit}' ke gram memerlukan density_g_per_ml yang telah ditinjau."
            )
        dec_density = _to_finite_decimal(density_g_per_ml, "density_g_per_ml", allow_zero=False)
        ml_factor = VOLUME_FACTORS_TO_ML[norm_unit]
        factor_to_g = ml_factor * dec_density
        grams = float(dec_val * factor_to_g)
        return NormalizedQuantity(
            original_value=float(dec_val),
            original_unit=raw_unit,
            normalized_raw_g=grams,
            canonical_unit="g",
            conversion_factor_to_g=float(factor_to_g),
        )

    if norm_unit in ITEM_UNITS:
        if unit_weight_g is None:
            raise UnitConversionError(
                f"Konversi satuan butir/item '{raw_unit}' ke gram memerlukan unit_weight_g yang telah ditinjau."
            )
        dec_item_g = _to_finite_decimal(unit_weight_g, "unit_weight_g", allow_zero=False)
        grams = float(dec_val * dec_item_g)
        return NormalizedQuantity(
            original_value=float(dec_val),
            original_unit=raw_unit,
            normalized_raw_g=grams,
            canonical_unit="g",
            conversion_factor_to_g=float(dec_item_g),
        )

    raise UnitConversionError(
        f"Satuan '{raw_unit}' tidak dikenali. Gunakan kg, g, L/ml (dengan densitas), atau item (dengan berat per unit)."
    )


def classify_price_provenance(
    *,
    source_type: Optional[str],
    is_synthetic: bool,
    explicit_provenance: Optional[str] = None,
) -> PriceProvenanceEnum:
    if explicit_provenance:
        try:
            return PriceProvenanceEnum(explicit_provenance)
        except ValueError:
            return PriceProvenanceEnum.UNKNOWN
    if is_synthetic or source_type == "synthetic":
        return PriceProvenanceEnum.SYNTHETIC_EXAMPLE
    if source_type == "official":
        return PriceProvenanceEnum.OFFICIAL_MARKET_REFERENCE
    if source_type == "uploaded":
        return PriceProvenanceEnum.ACTUAL_SUPPLIER
    return PriceProvenanceEnum.UNKNOWN
