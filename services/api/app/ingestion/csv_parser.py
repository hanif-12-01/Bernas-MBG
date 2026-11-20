from __future__ import annotations

import csv
import io
import math
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID, uuid4

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.models import (
    DatasetStockSnapshotORM,
    DatasetVersionORM,
    IngredientNutrientORM,
    IngredientORM,
    IngredientPriceORM,
    RecipeIngredientORM,
    RecipeVariantORM,
)
from app.domain.models.schemas import ReviewStatusEnum, SlotEnum, SourceTypeEnum
from app.ingestion.unit_converter import UnitConversionError, convert_price_to_idr_per_g

MAX_CSV_BYTES = 2 * 1024 * 1024  # 2 MB per uploaded CSV file
ALLOWED_CONTENT_TYPES = {
    "",
    "text/csv",
    "application/csv",
    "text/plain",
    "application/vnd.ms-excel",
    "application/octet-stream",
}
REQUIRED_INGREDIENT_HEADERS = {
    "code",
    "name",
    "category",
    "edible_fraction",
    "energy_kcal_100g",
    "protein_g_100g",
    "fat_g_100g",
    "carb_g_100g",
}
REQUIRED_STOCK_HEADERS = {"ingredient_code", "stock_raw_g"}
REQUIRED_RECIPE_HEADERS = {
    "recipe_code",
    "recipe_name",
    "slot",
    "ingredient_code",
    "raw_g_per_serving",
    "retention_factor",
    "review_status",
}


class CSVRowError(BaseModel):
    file: str
    row: int
    field: str
    message: str


class DatasetImportResponse(BaseModel):
    dataset_version_id: UUID
    name: str
    source_type: SourceTypeEnum
    is_synthetic: bool
    is_active: bool = False
    ingredients_imported: int
    prices_imported: int
    stock_items_imported: int
    recipes_imported: int
    reviewed_recipes_count: int
    warnings: List[str] = Field(default_factory=list)


class CSVImportValidationError(ValueError):
    def __init__(self, errors: List[CSVRowError]) -> None:
        self.errors = errors
        super().__init__(f"CSV import failed with {len(errors)} validation error(s)")


@dataclass
class UploadedCSVPayload:
    file_key: str
    filename: str
    content_type: str
    raw_bytes: bytes


def _parse_finite_float(
    raw: Optional[str],
    *,
    file: str,
    row: int,
    field: str,
    errors: List[CSVRowError],
    required: bool = True,
    min_exclusive: Optional[float] = None,
    min_inclusive: Optional[float] = None,
    max_inclusive: Optional[float] = None,
) -> Optional[float]:
    text = (raw or "").strip()
    if text == "":
        if required:
            errors.append(
                CSVRowError(
                    file=file,
                    row=row,
                    field=field,
                    message=f"Missing required numeric value for '{field}' (no silent default 0)",
                )
            )
        return None

    lowered = text.lower()
    if lowered in {"nan", "+nan", "-nan", "inf", "+inf", "-inf", "infinity", "+infinity", "-infinity"}:
        errors.append(
            CSVRowError(
                file=file,
                row=row,
                field=field,
                message=f"Non-finite value '{text}' is not allowed for '{field}'",
            )
        )
        return None

    try:
        val = float(text)
    except ValueError:
        errors.append(
            CSVRowError(
                file=file,
                row=row,
                field=field,
                message=f"Invalid numeric value '{text}' for '{field}'",
            )
        )
        return None

    if not math.isfinite(val):
        errors.append(
            CSVRowError(
                file=file,
                row=row,
                field=field,
                message=f"Non-finite numeric value '{text}' for '{field}'",
            )
        )
        return None

    if min_exclusive is not None and val <= min_exclusive:
        errors.append(
            CSVRowError(
                file=file,
                row=row,
                field=field,
                message=f"Value {val} for '{field}' must be > {min_exclusive}",
            )
        )
        return None
    if min_inclusive is not None and val < min_inclusive:
        errors.append(
            CSVRowError(
                file=file,
                row=row,
                field=field,
                message=f"Value {val} for '{field}' must be >= {min_inclusive}",
            )
        )
        return None
    if max_inclusive is not None and val > max_inclusive:
        errors.append(
            CSVRowError(
                file=file,
                row=row,
                field=field,
                message=f"Value {val} for '{field}' must be <= {max_inclusive}",
            )
        )
        return None

    return val


def _decode_and_read_csv(
    payload: UploadedCSVPayload,
    required_headers: set[str],
    errors: List[CSVRowError],
) -> Tuple[List[str], List[Tuple[int, Dict[str, str]]]]:
    if not payload.filename.lower().endswith(".csv"):
        errors.append(
            CSVRowError(
                file=payload.file_key,
                row=0,
                field="filename",
                message=f"File '{payload.filename}' must have .csv extension",
            )
        )
        return [], []

    ct = (payload.content_type or "").split(";")[0].strip().lower()
    if ct not in ALLOWED_CONTENT_TYPES:
        errors.append(
            CSVRowError(
                file=payload.file_key,
                row=0,
                field="content_type",
                message=f"Unsupported content type '{payload.content_type}'; expected CSV",
            )
        )
        return [], []

    if len(payload.raw_bytes) == 0:
        errors.append(
            CSVRowError(
                file=payload.file_key,
                row=0,
                field="file",
                message="Uploaded CSV file is empty",
            )
        )
        return [], []

    if len(payload.raw_bytes) > MAX_CSV_BYTES:
        errors.append(
            CSVRowError(
                file=payload.file_key,
                row=0,
                field="file",
                message=f"File exceeds max allowed size of {MAX_CSV_BYTES} bytes",
            )
        )
        return [], []

    try:
        decoded = payload.raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        errors.append(
            CSVRowError(
                file=payload.file_key,
                row=0,
                field="encoding",
                message=f"File must be valid UTF-8: {exc}",
            )
        )
        return [], []

    reader = csv.DictReader(io.StringIO(decoded))
    if not reader.fieldnames:
        errors.append(
            CSVRowError(
                file=payload.file_key,
                row=1,
                field="header",
                message="CSV header row is missing",
            )
        )
        return [], []

    headers = [h.strip() for h in reader.fieldnames if h is not None]
    missing = sorted(required_headers - set(headers))
    if missing:
        errors.append(
            CSVRowError(
                file=payload.file_key,
                row=1,
                field="header",
                message=f"Missing required column(s): {', '.join(missing)}",
            )
        )
        return headers, []

    rows: List[Tuple[int, Dict[str, str]]] = []
    for idx, raw_row in enumerate(reader, start=2):
        if None in raw_row:
            errors.append(
                CSVRowError(
                    file=payload.file_key,
                    row=idx,
                    field="columns",
                    message="Row has more columns than header",
                )
            )
            continue
        cleaned = {k.strip(): (v if v is not None else "").strip() for k, v in raw_row.items() if k is not None}
        if all(v == "" for v in cleaned.values()):
            continue
        rows.append((idx, cleaned))

    if not rows:
        errors.append(
            CSVRowError(
                file=payload.file_key,
                row=2,
                field="rows",
                message="CSV contains header but no data rows",
            )
        )

    return headers, rows


def _parse_tags(raw: str) -> List[str]:
    if not raw.strip():
        return []
    sep = ";" if ";" in raw else "|"
    return [t.strip().lower() for t in raw.split(sep) if t.strip()]


def import_dataset_from_csv(
    session: Session,
    *,
    name: str,
    source_type: SourceTypeEnum,
    source_url: Optional[str],
    is_synthetic: bool,
    kitchen_id: UUID,
    ingredients_csv: UploadedCSVPayload,
    prices_csv: UploadedCSVPayload,
    stock_csv: UploadedCSVPayload,
    recipes_csv: UploadedCSVPayload,
) -> DatasetImportResponse:
    """Validate four CSVs and stage an immutable, inactive dataset version for commit."""
    errors: List[CSVRowError] = []

    ing_headers, ing_rows = _decode_and_read_csv(ingredients_csv, REQUIRED_INGREDIENT_HEADERS, errors)
    price_headers, price_rows = _decode_and_read_csv(prices_csv, {"ingredient_code"}, errors)
    _, stock_rows = _decode_and_read_csv(stock_csv, REQUIRED_STOCK_HEADERS, errors)
    _, recipe_rows = _decode_and_read_csv(recipes_csv, REQUIRED_RECIPE_HEADERS, errors)

    # Validate price schema supports either (price_idr_per_kg) or (price_value + unit)
    price_has_kg_col = "price_idr_per_kg" in price_headers
    price_has_unit_cols = {"price_value", "unit"}.issubset(set(price_headers))
    if price_headers and not (price_has_kg_col or price_has_unit_cols):
        errors.append(
            CSVRowError(
                file="prices_file",
                row=1,
                field="header",
                message="prices_file must contain either 'price_idr_per_kg' or both 'price_value' and 'unit'",
            )
        )

    # 1. Parse ingredients
    parsed_ingredients: Dict[str, Dict[str, Any]] = {}
    has_fiber_col = "fiber_g_100g" in ing_headers
    has_iron_col = "iron_mg_100g" in ing_headers

    for row_num, r in ing_rows:
        code = r.get("code", "")
        ing_name = r.get("name", "")
        category = r.get("category", "")
        if not code:
            errors.append(CSVRowError(file="ingredients_file", row=row_num, field="code", message="code is required"))
            continue
        if code in parsed_ingredients:
            errors.append(
                CSVRowError(file="ingredients_file", row=row_num, field="code", message=f"Duplicate ingredient code '{code}'")
            )
            continue
        if not ing_name:
            errors.append(CSVRowError(file="ingredients_file", row=row_num, field="name", message="name is required"))
        if not category:
            errors.append(CSVRowError(file="ingredients_file", row=row_num, field="category", message="category is required"))

        edible = _parse_finite_float(
            r.get("edible_fraction"),
            file="ingredients_file",
            row=row_num,
            field="edible_fraction",
            errors=errors,
            min_exclusive=0.0,
            max_inclusive=1.0,
        )
        kcal = _parse_finite_float(
            r.get("energy_kcal_100g"),
            file="ingredients_file",
            row=row_num,
            field="energy_kcal_100g",
            errors=errors,
            min_inclusive=0.0,
        )
        prot = _parse_finite_float(
            r.get("protein_g_100g"),
            file="ingredients_file",
            row=row_num,
            field="protein_g_100g",
            errors=errors,
            min_inclusive=0.0,
        )
        fat = _parse_finite_float(
            r.get("fat_g_100g"),
            file="ingredients_file",
            row=row_num,
            field="fat_g_100g",
            errors=errors,
            min_inclusive=0.0,
        )
        carb = _parse_finite_float(
            r.get("carb_g_100g"),
            file="ingredients_file",
            row=row_num,
            field="carb_g_100g",
            errors=errors,
            min_inclusive=0.0,
        )
        fiber = (
            _parse_finite_float(
                r.get("fiber_g_100g"),
                file="ingredients_file",
                row=row_num,
                field="fiber_g_100g",
                errors=errors,
                required=True,
                min_inclusive=0.0,
            )
            if has_fiber_col
            else None
        )
        iron = (
            _parse_finite_float(
                r.get("iron_mg_100g"),
                file="ingredients_file",
                row=row_num,
                field="iron_mg_100g",
                errors=errors,
                required=False,
                min_inclusive=0.0,
            )
            if has_iron_col
            else None
        )

        row_source_type = r.get("source_type") or source_type.value
        try:
            SourceTypeEnum(row_source_type)
        except ValueError:
            errors.append(
                CSVRowError(
                    file="ingredients_file",
                    row=row_num,
                    field="source_type",
                    message=f"Invalid source_type '{row_source_type}'",
                )
            )
        row_review_status = r.get("review_status") or ReviewStatusEnum.DRAFT.value
        try:
            ReviewStatusEnum(row_review_status)
        except ValueError:
            errors.append(
                CSVRowError(
                    file="ingredients_file",
                    row=row_num,
                    field="review_status",
                    message=f"Invalid review_status '{row_review_status}'",
                )
            )

        parsed_ingredients[code] = {
            "id": str(uuid4()),
            "code": code,
            "name": ing_name,
            "category": category,
            "edible_fraction": edible,
            "allergens": _parse_tags(r.get("allergens", "")),
            "energy_kcal_100g": kcal,
            "protein_g_100g": prot,
            "fat_g_100g": fat,
            "carb_g_100g": carb,
            "fiber_g_100g": fiber,
            "iron_mg_100g": iron,
            "source_type": row_source_type,
            "source_ref": r.get("source_ref") or ("DEMO_ONLY" if is_synthetic else "UPLOADED"),
            "review_status": row_review_status,
        }

    # 2. Parse prices
    parsed_prices: Dict[str, Dict[str, Any]] = {}
    for row_num, r in price_rows:
        code = r.get("ingredient_code", "")
        if code not in parsed_ingredients:
            errors.append(
                CSVRowError(
                    file="prices_file",
                    row=row_num,
                    field="ingredient_code",
                    message=f"Unmapped ingredient_code '{code}' (not present in ingredients_file)",
                )
            )
            continue
        if code in parsed_prices:
            errors.append(
                CSVRowError(
                    file="prices_file",
                    row=row_num,
                    field="ingredient_code",
                    message=f"Duplicate price entry for ingredient_code '{code}'",
                )
            )
            continue

        if price_has_unit_cols and r.get("price_value", "") != "":
            raw_price_field = "price_value"
            raw_price_str = r.get("price_value")
            unit_str = r.get("unit", "")
        else:
            raw_price_field = "price_idr_per_kg"
            raw_price_str = r.get("price_idr_per_kg")
            unit_str = r.get("unit") or "IDR/kg"

        val = _parse_finite_float(
            raw_price_str,
            file="prices_file",
            row=row_num,
            field=raw_price_field,
            errors=errors,
            min_exclusive=0.0,
        )
        density = _parse_finite_float(
            r.get("density_g_per_ml"),
            file="prices_file",
            row=row_num,
            field="density_g_per_ml",
            errors=errors,
            required=False,
            min_exclusive=0.0,
        )
        idr_per_g = None
        if val is not None:
            try:
                idr_per_g = convert_price_to_idr_per_g(val, unit_str, density_g_per_ml=density)
            except UnitConversionError as exc:
                errors.append(
                    CSVRowError(file="prices_file", row=row_num, field="unit", message=str(exc))
                )

        obs_raw = r.get("observed_at") or date.today().isoformat()
        obs_date: Optional[date] = None
        try:
            obs_date = date.fromisoformat(obs_raw)
        except ValueError:
            errors.append(
                CSVRowError(
                    file="prices_file",
                    row=row_num,
                    field="observed_at",
                    message=f"Invalid ISO date '{obs_raw}'; expected YYYY-MM-DD",
                )
            )

        p_source_type = r.get("source_type") or source_type.value
        try:
            SourceTypeEnum(p_source_type)
        except ValueError:
            errors.append(
                CSVRowError(
                    file="prices_file",
                    row=row_num,
                    field="source_type",
                    message=f"Invalid source_type '{p_source_type}'",
                )
            )

        parsed_prices[code] = {
            "price_idr_per_g": idr_per_g,
            "original_value": val,
            "original_unit": unit_str,
            "region": r.get("region") or ("SIMULASI" if is_synthetic else "UPLOADED"),
            "observed_at": obs_date or date.today(),
            "source_type": p_source_type,
        }

    # 3. Parse stock
    parsed_stock: Dict[str, float] = {}
    for row_num, r in stock_rows:
        code = r.get("ingredient_code", "")
        if code not in parsed_ingredients:
            errors.append(
                CSVRowError(
                    file="stock_file",
                    row=row_num,
                    field="ingredient_code",
                    message=f"Unmapped ingredient_code '{code}' (not present in ingredients_file)",
                )
            )
            continue
        if code in parsed_stock:
            errors.append(
                CSVRowError(
                    file="stock_file",
                    row=row_num,
                    field="ingredient_code",
                    message=f"Duplicate stock entry for ingredient_code '{code}'",
                )
            )
            continue
        stock_val = _parse_finite_float(
            r.get("stock_raw_g"),
            file="stock_file",
            row=row_num,
            field="stock_raw_g",
            errors=errors,
            min_inclusive=0.0,
        )
        if stock_val is not None:
            parsed_stock[code] = stock_val

    # 4. Parse recipes & composition
    parsed_recipes: Dict[str, Dict[str, Any]] = {}
    for row_num, r in recipe_rows:
        rcode = r.get("recipe_code", "")
        rname = r.get("recipe_name", "")
        slot_raw = r.get("slot", "").lower()
        icode = r.get("ingredient_code", "")
        rstatus = r.get("review_status", "").lower()

        if not rcode:
            errors.append(CSVRowError(file="recipes_file", row=row_num, field="recipe_code", message="recipe_code is required"))
            continue
        if not rname:
            errors.append(CSVRowError(file="recipes_file", row=row_num, field="recipe_name", message="recipe_name is required"))
        try:
            SlotEnum(slot_raw)
        except ValueError:
            errors.append(
                CSVRowError(
                    file="recipes_file",
                    row=row_num,
                    field="slot",
                    message=f"Invalid slot '{slot_raw}'; must be one of staple, protein, vegetable, fruit",
                )
            )
        try:
            ReviewStatusEnum(rstatus)
        except ValueError:
            errors.append(
                CSVRowError(
                    file="recipes_file",
                    row=row_num,
                    field="review_status",
                    message=f"Invalid review_status '{rstatus}'",
                )
            )

        if icode not in parsed_ingredients:
            errors.append(
                CSVRowError(
                    file="recipes_file",
                    row=row_num,
                    field="ingredient_code",
                    message=f"Unmapped ingredient_code '{icode}' in recipe '{rcode}'",
                )
            )
        else:
            if icode not in parsed_prices:
                errors.append(
                    CSVRowError(
                        file="recipes_file",
                        row=row_num,
                        field="ingredient_code",
                        message=f"Ingredient '{icode}' used by recipe '{rcode}' has no price in prices_file",
                    )
                )
            if icode not in parsed_stock:
                errors.append(
                    CSVRowError(
                        file="recipes_file",
                        row=row_num,
                        field="ingredient_code",
                        message=f"Ingredient '{icode}' used by recipe '{rcode}' has no stock in stock_file",
                    )
                )

        raw_g = _parse_finite_float(
            r.get("raw_g_per_serving"),
            file="recipes_file",
            row=row_num,
            field="raw_g_per_serving",
            errors=errors,
            min_exclusive=0.0,
        )
        retention = _parse_finite_float(
            r.get("retention_factor"),
            file="recipes_file",
            row=row_num,
            field="retention_factor",
            errors=errors,
            min_exclusive=0.0,
            max_inclusive=1.0,
        )

        family = r.get("family") or rcode.lower()
        allergens = _parse_tags(r.get("allergen_tags", ""))
        active_raw = (r.get("active") or "true").lower()
        active = active_raw not in {"false", "0", "no"}

        if rcode not in parsed_recipes:
            parsed_recipes[rcode] = {
                "id": str(uuid4()),
                "code": rcode,
                "name": rname,
                "slot": slot_raw,
                "family": family,
                "review_status": rstatus,
                "active": active,
                "allergen_tags": allergens,
                "ingredients": {},
            }
        else:
            existing_rec = parsed_recipes[rcode]
            if existing_rec["name"] != rname or existing_rec["slot"] != slot_raw or existing_rec["review_status"] != rstatus:
                errors.append(
                    CSVRowError(
                        file="recipes_file",
                        row=row_num,
                        field="recipe_code",
                        message=f"Inconsistent metadata across rows for recipe '{rcode}'",
                    )
                )
            if icode in existing_rec["ingredients"]:
                errors.append(
                    CSVRowError(
                        file="recipes_file",
                        row=row_num,
                        field="ingredient_code",
                        message=f"Duplicate ingredient '{icode}' in recipe '{rcode}'",
                    )
                )

        if raw_g is not None and retention is not None and icode:
            parsed_recipes[rcode]["ingredients"][icode] = {
                "raw_g_per_serving": raw_g,
                "retention_factor": retention,
            }

    # Atomic rejection if ANY validation error occurred
    if errors:
        raise CSVImportValidationError(errors)

    # Atomic DB write into a NEW immutable dataset_version (is_active=False)
    ds_id = uuid4()
    now = datetime.now(timezone.utc)
    reviewed_count = sum(
        1 for rec in parsed_recipes.values() if rec["review_status"] == ReviewStatusEnum.REVIEWED.value
    )

    try:
        session.add(
            DatasetVersionORM(
                id=str(ds_id),
                kitchen_id=str(kitchen_id),
                name=name,
                source_type=source_type.value,
                source_url=source_url,
                is_synthetic=is_synthetic,
                is_active=False,  # Never silently replace active dataset
                review_status=ReviewStatusEnum.DRAFT.value,
                ingestion_metadata_json={
                    "files": {
                        "ingredients_file": ingredients_csv.filename,
                        "prices_file": prices_csv.filename,
                        "stock_file": stock_csv.filename,
                        "recipes_file": recipes_csv.filename,
                    },
                    "counts": {
                        "ingredients": len(parsed_ingredients),
                        "prices": len(parsed_prices),
                        "stock": len(parsed_stock),
                        "recipes": len(parsed_recipes),
                        "reviewed_recipes": reviewed_count,
                    },
                    "label": "DEMO_ONLY" if is_synthetic else "UPLOADED_UNVERIFIED",
                },
                created_at=now,
            )
        )
        session.flush()

        for code, ing in parsed_ingredients.items():
            session.add(
                IngredientORM(
                    id=ing["id"],
                    dataset_version_id=str(ds_id),
                    code=ing["code"],
                    name=ing["name"],
                    category=ing["category"],
                    edible_fraction=ing["edible_fraction"],
                    allergens_json=ing["allergens"],
                    source_type=ing["source_type"],
                    source_ref=ing["source_ref"],
                    review_status=ing["review_status"],
                )
            )
        session.flush()

        for code, ing in parsed_ingredients.items():
            session.add(
                IngredientNutrientORM(
                    ingredient_id=ing["id"],
                    energy_kcal_100g=ing["energy_kcal_100g"],
                    protein_g_100g=ing["protein_g_100g"],
                    fat_g_100g=ing["fat_g_100g"],
                    carb_g_100g=ing["carb_g_100g"],
                    fiber_g_100g=ing["fiber_g_100g"],
                    iron_mg_100g=ing["iron_mg_100g"],
                )
            )

        for code, pr in parsed_prices.items():
            session.add(
                IngredientPriceORM(
                    id=str(uuid4()),
                    dataset_version_id=str(ds_id),
                    ingredient_id=parsed_ingredients[code]["id"],
                    price_idr_per_g=pr["price_idr_per_g"],
                    original_value=pr["original_value"],
                    original_unit=pr["original_unit"],
                    region=pr["region"],
                    observed_at=pr["observed_at"],
                    source_type=pr["source_type"],
                )
            )

        for code, st_g in parsed_stock.items():
            session.add(
                DatasetStockSnapshotORM(
                    id=str(uuid4()),
                    dataset_version_id=str(ds_id),
                    ingredient_id=parsed_ingredients[code]["id"],
                    stock_raw_g=st_g,
                    recorded_at=now,
                )
            )

        for rcode, rec in parsed_recipes.items():
            session.add(
                RecipeVariantORM(
                    id=rec["id"],
                    dataset_version_id=str(ds_id),
                    code=rec["code"],
                    name=rec["name"],
                    slot=rec["slot"],
                    family=rec["family"],
                    review_status=rec["review_status"],
                    reviewer="CSV_IMPORT" if rec["review_status"] == "reviewed" else None,
                    reviewed_at=now if rec["review_status"] == "reviewed" else None,
                    active=rec["active"],
                    allergen_tags_json=rec["allergen_tags"],
                )
            )
        session.flush()

        for rcode, rec in parsed_recipes.items():
            for icode, comp in rec["ingredients"].items():
                session.add(
                    RecipeIngredientORM(
                        recipe_id=rec["id"],
                        ingredient_id=parsed_ingredients[icode]["id"],
                        raw_g_per_serving=comp["raw_g_per_serving"],
                        retention_factor=comp["retention_factor"],
                    )
                )

        session.flush()
    except Exception:
        session.rollback()
        raise

    warnings = [
        "Dataset baru disimpan sebagai versi immutable terpisah (is_active=false); dataset aktif sebelumnya tidak diubah."
    ]
    if is_synthetic:
        warnings.append("Dataset ditandai synthetic (DEMO_ONLY) dan belum melalui validasi ahli gizi.")

    return DatasetImportResponse(
        dataset_version_id=ds_id,
        name=name,
        source_type=source_type,
        is_synthetic=is_synthetic,
        is_active=False,
        ingredients_imported=len(parsed_ingredients),
        prices_imported=len(parsed_prices),
        stock_items_imported=len(parsed_stock),
        recipes_imported=len(parsed_recipes),
        reviewed_recipes_count=reviewed_count,
        warnings=warnings,
    )
