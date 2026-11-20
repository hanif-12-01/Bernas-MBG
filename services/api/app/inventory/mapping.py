from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from uuid import UUID, uuid4

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import IngredientMappingORM, IngredientORM
from app.ingestion.unit_converter import UnitConversionError
from app.inventory.unit_normalizer import normalize_quantity_to_grams

# Incompatible category boundaries: never auto-map or permit mapping across incompatible food groups
INCOMPATIBLE_CATEGORY_GROUPS: Tuple[frozenset[str], ...] = (
    frozenset({"protein", "meat", "poultry", "fish", "seafood", "dairy", "legume", "egg"}),
    frozenset({"staple", "grain", "tuber"}),
    frozenset({"vegetable", "fruit"}),
    frozenset({"seasoning", "oil", "fat"}),
)

# High-level incompatible sub-tokens inside product names (prevent cross-species/nutrition leakage)
INCOMPATIBLE_TOKEN_PAIRS: Tuple[Tuple[str, str], ...] = (
    ("ayam", "ikan"),
    ("chicken", "fish"),
    ("chicken", "ikan"),
    ("ayam", "fish"),
    ("chicken", "beef"),
    ("chicken", "sapi"),
    ("ayam", "sapi"),
    ("beef", "ikan"),
    ("sapi", "fish"),
    ("beras putih", "beras merah"),
    ("white rice", "brown rice"),
    ("telur", "ayam"),
    ("egg", "chicken"),
    ("telur", "chicken"),
    ("egg", "ayam"),
    ("tempe", "tahu"),
    ("minyak", "air"),
    ("oil", "water"),
)


class ExternalProductCandidate(BaseModel):
    external_product_code: str
    external_product_name: str
    external_unit: str
    sample_quantity: float = 1.0
    canonical_category: Optional[str] = None
    target_ingredient_code: Optional[str] = None
    standard_unit: str = "kg"
    density_g_per_ml: Optional[float] = None
    unit_weight_g: Optional[float] = None
    reviewed_by_human: bool = False
    notes: Optional[str] = None


class MappingReportEntry(BaseModel):
    external_product_code: str
    external_product_name: str
    external_unit: str
    canonical_category: Optional[str] = None
    ingredient_code: Optional[str] = None
    ingredient_name: Optional[str] = None
    standard_unit: str
    conversion_factor_to_g: Optional[float] = None
    mapping_status: str  # MAPPED | UNMAPPED | AMBIGUOUS | REJECTED | UNIT_ERROR
    review_status: str
    reason: str
    usable_for_optimizer: bool = False


class IngredientMappingReport(BaseModel):
    dataset_version_id: UUID
    total_records: int
    mapped_count: int
    unmapped_count: int
    ambiguous_count: int
    rejected_count: int
    unit_conversion_errors: int
    entries: List[MappingReportEntry] = Field(default_factory=list)


def _are_categories_incompatible(source_cat: Optional[str], target_cat: str) -> bool:
    if not source_cat:
        return False
    src = source_cat.strip().lower()
    tgt = target_cat.strip().lower()
    if src == tgt:
        return False
    for grp in INCOMPATIBLE_CATEGORY_GROUPS:
        if src in grp and tgt in grp:
            # Fine within exact same group only if identical or sub-alias, else check explicit mismatches
            if {src, tgt} in ({"poultry", "fish"}, {"meat", "fish"}, {"vegetable", "fruit"}, {"egg", "dairy"}):
                return True
            return False
    return True


def _check_name_incompatibility(ext_name: str, target_name: str) -> Optional[str]:
    a = ext_name.strip().lower()
    b = target_name.strip().lower()
    for tok_a, tok_b in INCOMPATIBLE_TOKEN_PAIRS:
        if (tok_a in a and tok_b in b) or (tok_b in a and tok_a in b):
            return f"Produk '{ext_name}' tidak kompatibel dengan bahan '{target_name}' ({tok_a} vs {tok_b})."
    return None


def evaluate_external_mappings(
    session: Session,
    *,
    kitchen_id: UUID,
    dataset_version_id: UUID,
    candidates: List[ExternalProductCandidate],
    source_id: Optional[str] = None,
    reviewer_user_id: Optional[UUID] = None,
    persist: bool = True,
) -> IngredientMappingReport:
    """Validate and optionally persist external SKU -> canonical ingredient -> GiziOptima ingredient mappings.

    Rules enforced:
    - Never infer nutritional equivalence solely from similar names.
    - Prevent cross-matching incompatible categories or food tokens.
    - Require explicit conversion factors for volume (density_g_per_ml) or item count (unit_weight_g).
    - High-impact mappings remain 'needs_review' until reviewed_by_human=True.
    - Unmapped / ambiguous / rejected / unit_error rows never enter MILP optimization.
    """
    ing_rows = list(
        session.execute(
            select(IngredientORM).where(IngredientORM.dataset_version_id == str(dataset_version_id))
        )
        .scalars()
        .all()
    )
    ing_by_code: Dict[str, IngredientORM] = {r.code: r for r in ing_rows}

    entries: List[MappingReportEntry] = []
    mapped_count = 0
    unmapped_count = 0
    ambiguous_count = 0
    rejected_count = 0
    unit_errors = 0

    for cand in candidates:
        ext_name_low = cand.external_product_name.strip().lower()

        # 1. Validate unit conversion first
        conv_factor: Optional[float] = None
        try:
            norm = normalize_quantity_to_grams(
                cand.sample_quantity,
                cand.external_unit,
                density_g_per_ml=cand.density_g_per_ml,
                unit_weight_g=cand.unit_weight_g,
                allow_zero=False,
            )
            conv_factor = norm.conversion_factor_to_g
        except UnitConversionError as exc:
            unit_errors += 1
            entries.append(
                MappingReportEntry(
                    external_product_code=cand.external_product_code,
                    external_product_name=cand.external_product_name,
                    external_unit=cand.external_unit,
                    canonical_category=cand.canonical_category,
                    ingredient_code=cand.target_ingredient_code,
                    standard_unit=cand.standard_unit,
                    mapping_status="UNIT_ERROR",
                    review_status="rejected",
                    reason=str(exc),
                    usable_for_optimizer=False,
                )
            )
            if persist:
                _upsert_mapping_orm(
                    session,
                    kitchen_id=kitchen_id,
                    dataset_version_id=dataset_version_id,
                    source_id=source_id,
                    cand=cand,
                    ing=None,
                    conv_factor=None,
                    mapping_status="UNIT_ERROR",
                    review_status="rejected",
                    reviewer_user_id=None,
                    notes=str(exc),
                )
            continue

        # 2. If no explicit target ingredient code provided, check ambiguity / unmapped (never auto-guess)
        if not cand.target_ingredient_code:
            # Check if name matches multiple ingredients -> AMBIGUOUS, else UNMAPPED
            matches = [
                ing
                for ing in ing_rows
                if any(
                    len(tok) >= 4 and tok in ext_name_low
                    for tok in ing.name.lower().split()
                )
            ]
            if len(matches) >= 2:
                ambiguous_count += 1
                names = ", ".join(m.code for m in matches[:4])
                reason = f"Nama produk '{cand.external_product_name}' ambigu terhadap beberapa bahan ({names}); wajib penetapan eksplisit."
                status = "AMBIGUOUS"
            else:
                unmapped_count += 1
                reason = "Belum memiliki kode bahan kanonik GiziOptima (tidak diinferensi otomatis)."
                status = "UNMAPPED"

            entries.append(
                MappingReportEntry(
                    external_product_code=cand.external_product_code,
                    external_product_name=cand.external_product_name,
                    external_unit=cand.external_unit,
                    canonical_category=cand.canonical_category,
                    standard_unit=cand.standard_unit,
                    conversion_factor_to_g=conv_factor,
                    mapping_status=status,
                    review_status="needs_review",
                    reason=reason,
                    usable_for_optimizer=False,
                )
            )
            if persist:
                _upsert_mapping_orm(
                    session,
                    kitchen_id=kitchen_id,
                    dataset_version_id=dataset_version_id,
                    source_id=source_id,
                    cand=cand,
                    ing=None,
                    conv_factor=conv_factor,
                    mapping_status=status,
                    review_status="needs_review",
                    reviewer_user_id=None,
                    notes=reason,
                )
            continue

        # 3. Validate target ingredient exists and is compatible
        target_ing = ing_by_code.get(cand.target_ingredient_code.strip())
        if target_ing is None:
            rejected_count += 1
            reason = f"Target ingredient_code '{cand.target_ingredient_code}' tidak ditemukan di dataset."
            entries.append(
                MappingReportEntry(
                    external_product_code=cand.external_product_code,
                    external_product_name=cand.external_product_name,
                    external_unit=cand.external_unit,
                    canonical_category=cand.canonical_category,
                    ingredient_code=cand.target_ingredient_code,
                    standard_unit=cand.standard_unit,
                    conversion_factor_to_g=conv_factor,
                    mapping_status="REJECTED",
                    review_status="rejected",
                    reason=reason,
                    usable_for_optimizer=False,
                )
            )
            if persist:
                _upsert_mapping_orm(
                    session,
                    kitchen_id=kitchen_id,
                    dataset_version_id=dataset_version_id,
                    source_id=source_id,
                    cand=cand,
                    ing=None,
                    conv_factor=conv_factor,
                    mapping_status="REJECTED",
                    review_status="rejected",
                    reviewer_user_id=None,
                    notes=reason,
                )
            continue

        incompat_msg = _check_name_incompatibility(cand.external_product_name, target_ing.name)
        if incompat_msg or _are_categories_incompatible(cand.canonical_category, target_ing.category):
            rejected_count += 1
            reason = incompat_msg or (
                f"Kategori tidak kompatibel: '{cand.canonical_category}' vs '{target_ing.category}'."
            )
            entries.append(
                MappingReportEntry(
                    external_product_code=cand.external_product_code,
                    external_product_name=cand.external_product_name,
                    external_unit=cand.external_unit,
                    canonical_category=cand.canonical_category,
                    ingredient_code=target_ing.code,
                    ingredient_name=target_ing.name,
                    standard_unit=cand.standard_unit,
                    conversion_factor_to_g=conv_factor,
                    mapping_status="REJECTED",
                    review_status="rejected",
                    reason=reason,
                    usable_for_optimizer=False,
                )
            )
            if persist:
                _upsert_mapping_orm(
                    session,
                    kitchen_id=kitchen_id,
                    dataset_version_id=dataset_version_id,
                    source_id=source_id,
                    cand=cand,
                    ing=target_ing,
                    conv_factor=conv_factor,
                    mapping_status="REJECTED",
                    review_status="rejected",
                    reviewer_user_id=None,
                    notes=reason,
                )
            continue

        # 4. Valid mapping — check human review gate
        rev_status = "reviewed" if cand.reviewed_by_human else "needs_review"
        mapped_count += 1
        reason = (
            "Pemetaan dan faktor konversi unit telah diverifikasi operator."
            if cand.reviewed_by_human
            else "Pemetaan cocok tetapi masih menunggu peninjauan manusia (needs_review)."
        )
        entries.append(
            MappingReportEntry(
                external_product_code=cand.external_product_code,
                external_product_name=cand.external_product_name,
                external_unit=cand.external_unit,
                canonical_category=cand.canonical_category or target_ing.category,
                ingredient_code=target_ing.code,
                ingredient_name=target_ing.name,
                standard_unit=cand.standard_unit,
                conversion_factor_to_g=conv_factor,
                mapping_status="MAPPED",
                review_status=rev_status,
                reason=reason,
                usable_for_optimizer=cand.reviewed_by_human,
            )
        )
        if persist:
            _upsert_mapping_orm(
                session,
                kitchen_id=kitchen_id,
                dataset_version_id=dataset_version_id,
                source_id=source_id,
                cand=cand,
                ing=target_ing,
                conv_factor=conv_factor,
                mapping_status="MAPPED",
                review_status=rev_status,
                reviewer_user_id=reviewer_user_id if cand.reviewed_by_human else None,
                notes=cand.notes or reason,
            )

    return IngredientMappingReport(
        dataset_version_id=dataset_version_id,
        total_records=len(candidates),
        mapped_count=mapped_count,
        unmapped_count=unmapped_count,
        ambiguous_count=ambiguous_count,
        rejected_count=rejected_count,
        unit_conversion_errors=unit_errors,
        entries=entries,
    )


def _upsert_mapping_orm(
    session: Session,
    *,
    kitchen_id: UUID,
    dataset_version_id: UUID,
    source_id: Optional[str],
    cand: ExternalProductCandidate,
    ing: Optional[IngredientORM],
    conv_factor: Optional[float],
    mapping_status: str,
    review_status: str,
    reviewer_user_id: Optional[UUID],
    notes: Optional[str],
) -> None:
    existing = session.execute(
        select(IngredientMappingORM).where(
            IngredientMappingORM.kitchen_id == str(kitchen_id),
            IngredientMappingORM.dataset_version_id == str(dataset_version_id),
            IngredientMappingORM.external_product_code == cand.external_product_code,
        )
    ).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if existing is None:
        session.add(
            IngredientMappingORM(
                id=str(uuid4()),
                kitchen_id=str(kitchen_id),
                dataset_version_id=str(dataset_version_id),
                source_id=source_id,
                external_product_code=cand.external_product_code,
                external_product_name=cand.external_product_name,
                external_unit=cand.external_unit,
                canonical_category=cand.canonical_category,
                ingredient_id=ing.id if ing else None,
                ingredient_code=ing.code if ing else cand.target_ingredient_code,
                standard_unit=cand.standard_unit,
                conversion_factor_to_g=conv_factor,
                density_g_per_ml=cand.density_g_per_ml,
                unit_weight_g=cand.unit_weight_g,
                mapping_status=mapping_status,
                review_status=review_status,
                reviewer_user_id=str(reviewer_user_id) if reviewer_user_id else None,
                reviewed_at=now if reviewer_user_id else None,
                notes=notes,
                created_at=now,
            )
        )
    else:
        existing.external_product_name = cand.external_product_name
        existing.external_unit = cand.external_unit
        existing.canonical_category = cand.canonical_category
        existing.ingredient_id = ing.id if ing else None
        existing.ingredient_code = ing.code if ing else cand.target_ingredient_code
        existing.standard_unit = cand.standard_unit
        existing.conversion_factor_to_g = conv_factor
        existing.density_g_per_ml = cand.density_g_per_ml
        existing.unit_weight_g = cand.unit_weight_g
        existing.mapping_status = mapping_status
        existing.review_status = review_status
        existing.reviewer_user_id = str(reviewer_user_id) if reviewer_user_id else None
        existing.reviewed_at = now if reviewer_user_id else None
        existing.notes = notes
