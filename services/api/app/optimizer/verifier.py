from __future__ import annotations

import math
from typing import Dict, List, Optional, Set, Tuple
from uuid import UUID

from app.domain.models.schemas import (
    ConstraintAudit,
    ConstraintViolation,
    Ingredient,
    NutritionTargetProfile,
    RecipeVariant,
    ReviewStatusEnum,
    Scenario,
    SlotEnum,
)


def _recompute_recipe_independently(
    recipe: RecipeVariant,
    ingredients_by_code: Dict[str, Ingredient],
    effective_prices_idr_per_g: Dict[str, float],
    target: NutritionTargetProfile,
) -> Tuple[float, Dict[str, float], Dict[str, float], Set[str], List[ConstraintViolation]]:
    """Independently compute cost, nutrients, raw grams, and effective allergens directly from raw master data."""
    violations: List[ConstraintViolation] = []
    cost = 0.0
    nutrients: Dict[str, float] = {lim.nutrient_key: 0.0 for lim in target.limits}
    raw_grams: Dict[str, float] = {}
    allergens: Set[str] = {a.strip().lower() for a in recipe.allergen_tags if a.strip()}

    if not recipe.ingredients:
        violations.append(
            ConstraintViolation(
                constraint_family="recipe_data",
                detail=f"Recipe {recipe.code} has no ingredients",
            )
        )
        return cost, nutrients, raw_grams, allergens, violations

    for item in recipe.ingredients:
        code = item.ingredient_code
        ing = ingredients_by_code.get(code)
        if ing is None:
            violations.append(
                ConstraintViolation(
                    constraint_family="recipe_data",
                    detail=f"Recipe {recipe.code} references unknown ingredient '{code}'",
                )
            )
            continue

        allergens.update(a.strip().lower() for a in ing.allergens if a.strip())

        price = effective_prices_idr_per_g.get(code)
        if price is None or not math.isfinite(price) or price <= 0:
            violations.append(
                ConstraintViolation(
                    constraint_family="price_data",
                    detail=f"Missing or non-positive price for ingredient '{code}'",
                )
            )
            continue

        raw_g = float(item.raw_g_per_serving)
        retention = float(item.retention_factor)
        edible_fraction = float(ing.edible_fraction)
        if not math.isfinite(raw_g) or raw_g <= 0:
            violations.append(
                ConstraintViolation(
                    constraint_family="recipe_data",
                    detail=f"Invalid raw_g_per_serving {raw_g!r} for '{code}' in {recipe.code}",
                )
            )
            continue
        if not math.isfinite(edible_fraction) or not (0.0 < edible_fraction <= 1.0):
            violations.append(
                ConstraintViolation(
                    constraint_family="nutrition_data",
                    detail=f"Invalid edible_fraction {edible_fraction!r} for '{code}'",
                )
            )
            continue
        if not math.isfinite(retention) or not (0.0 < retention <= 1.0):
            violations.append(
                ConstraintViolation(
                    constraint_family="nutrition_data",
                    detail=f"Invalid retention_factor {retention!r} for '{code}' in {recipe.code}",
                )
            )
            continue

        cost += raw_g * price
        raw_grams[code] = raw_grams.get(code, 0.0) + raw_g

        edible_g = raw_g * edible_fraction
        for lim in target.limits:
            try:
                per_100g = ing.nutrients.get_nutrient(lim.nutrient_key)
            except ValueError as exc:
                violations.append(
                    ConstraintViolation(
                        constraint_family="nutrition_data",
                        detail=str(exc),
                    )
                )
                continue
            if per_100g is None or not math.isfinite(per_100g) or per_100g < 0:
                violations.append(
                    ConstraintViolation(
                        constraint_family="nutrition_data",
                        detail=f"Ingredient '{code}' has missing or invalid nutrient '{lim.nutrient_key}': {per_100g!r}",
                    )
                )
                continue
            nutrients[lim.nutrient_key] += (edible_g / 100.0) * float(per_100g) * retention

    return cost, nutrients, raw_grams, allergens, violations


def verify_assignments(
    scenario: Scenario,
    assignments_by_day: Dict[int, Dict[SlotEnum, UUID]],
    recipes_by_id: Dict[UUID, RecipeVariant],
    ingredients_by_code: Dict[str, Ingredient],
    effective_prices_idr_per_g: Dict[str, float],
    target: NutritionTargetProfile,
    stock_raw_g: Dict[str, float],
    raw_x_values: Optional[Dict[Tuple[int, UUID], Optional[float]]] = None,
    reported_objective: Optional[float] = None,
    tolerance: float = 1e-6,
    usable_stock_by_day: Optional[Dict[int, Dict[str, float]]] = None,
) -> ConstraintAudit:
    """Independently re-compute and audit all hard constraints from raw master data and decision variables.

    Does NOT trust optimizer-precomputed RecipeFeatures or optimizer-reported constraint audits.
    """
    violations: List[ConstraintViolation] = []
    expected_days = set(range(1, scenario.days + 1))
    excluded_set: Set[str] = {a.strip().lower() for a in scenario.excluded_allergens if a.strip()}
    family_counts: Dict[str, int] = {}
    ingredient_usage: Dict[str, float] = {}
    ingredient_usage_by_day: Dict[int, Dict[str, float]] = {
        d: {} for d in range(1, scenario.days + 1)
    }
    recomputed_total_cost = 0.0

    # 0. Verify raw binary / integrality constraints and slot counts directly on x_{dr}
    if raw_x_values is not None:
        selected_counts_by_day_slot: Dict[Tuple[int, SlotEnum], List[UUID]] = {
            (d, s): [] for d in expected_days for s in SlotEnum
        }
        for (d, rid), val in raw_x_values.items():
            if val is None or not math.isfinite(val):
                violations.append(
                    ConstraintViolation(
                        constraint_family="integrality",
                        detail=f"Decision variable x[{d}, {rid}] is None or non-finite ({val!r})",
                    )
                )
                continue
            near_zero = abs(val) <= tolerance
            near_one = abs(val - 1.0) <= tolerance
            if not (near_zero or near_one):
                violations.append(
                    ConstraintViolation(
                        constraint_family="integrality",
                        detail=f"Decision variable x[{d}, {rid}] violates binary integrality",
                        expected=1.0 if val >= 0.5 else 0.0,
                        actual=val,
                    )
                )
            if val > 0.5:
                if d not in expected_days:
                    violations.append(
                        ConstraintViolation(
                            constraint_family="slot_coverage",
                            detail=f"Selected variable on out-of-range day {d}",
                        )
                    )
                    continue
                rec = recipes_by_id.get(rid)
                if rec is None:
                    violations.append(
                        ConstraintViolation(
                            constraint_family="allowed",
                            detail=f"Selected variable references unknown recipe {rid}",
                        )
                    )
                    continue
                selected_counts_by_day_slot[(d, rec.slot)].append(rid)

        for (d, slot), rids in selected_counts_by_day_slot.items():
            if len(rids) != 1:
                violations.append(
                    ConstraintViolation(
                        constraint_family="slot_coverage",
                        detail=f"Day {d} slot {slot.value} has {len(rids)} selected recipes in raw x (expected exactly 1)",
                        expected=1.0,
                        actual=float(len(rids)),
                    )
                )
            else:
                assigned_rid = assignments_by_day.get(d, {}).get(slot)
                if assigned_rid != rids[0]:
                    violations.append(
                        ConstraintViolation(
                            constraint_family="slot_coverage",
                            detail=f"Day {d} slot {slot.value} assignment ({assigned_rid}) disagrees with raw x ({rids[0]})",
                        )
                    )

    # 1. Reject extraneous days outside 1..scenario.days
    extra_days = sorted(set(assignments_by_day.keys()) - expected_days)
    if extra_days:
        violations.append(
            ConstraintViolation(
                constraint_family="slot_coverage",
                detail=f"Unexpected day indices outside 1..{scenario.days}: {extra_days}",
            )
        )

    # 2. Check every day 1..days
    for d in range(1, scenario.days + 1):
        day_slots = assignments_by_day.get(d, {})
        if set(day_slots.keys()) != set(SlotEnum):
            violations.append(
                ConstraintViolation(
                    constraint_family="slot_coverage",
                    detail=f"Day {d} does not contain exactly all 4 required slots",
                )
            )
            continue

        day_cost = 0.0
        day_nutrients: Dict[str, float] = {lim.nutrient_key: 0.0 for lim in target.limits}

        for slot, rid in day_slots.items():
            rec = recipes_by_id.get(rid)
            if rec is None:
                violations.append(
                    ConstraintViolation(
                        constraint_family="allowed",
                        detail=f"Day {d} slot {slot.value} references unknown recipe {rid}",
                    )
                )
                continue

            if rec.slot != slot:
                violations.append(
                    ConstraintViolation(
                        constraint_family="slot_coverage",
                        detail=f"Recipe {rec.code} assigned to slot {slot.value} belongs to {rec.slot.value}",
                    )
                )
            if not rec.active or rec.review_status != ReviewStatusEnum.REVIEWED:
                violations.append(
                    ConstraintViolation(
                        constraint_family="allowed",
                        detail=f"Recipe {rec.code} is inactive or unreviewed ({rec.review_status.value})",
                    )
                )

            rec_cost, rec_nutrients, rec_raw_grams, effective_allergens, data_viols = (
                _recompute_recipe_independently(
                    rec, ingredients_by_code, effective_prices_idr_per_g, target
                )
            )
            violations.extend(data_viols)

            overlap = excluded_set & effective_allergens
            if overlap:
                violations.append(
                    ConstraintViolation(
                        constraint_family="allergen",
                        detail=f"Recipe {rec.code} contains excluded allergen(s): {', '.join(sorted(overlap))}",
                    )
                )

            day_cost += rec_cost
            for k in day_nutrients:
                day_nutrients[k] += rec_nutrients[k]

            family_counts[rec.family] = family_counts.get(rec.family, 0) + 1
            for ing_code, raw_g in rec_raw_grams.items():
                used_today = raw_g * scenario.servings_per_day
                ingredient_usage[ing_code] = ingredient_usage.get(ing_code, 0.0) + used_today
                ingredient_usage_by_day[d][ing_code] = (
                    ingredient_usage_by_day[d].get(ing_code, 0.0) + used_today
                )

        recomputed_total_cost += day_cost * scenario.servings_per_day

        if day_cost > scenario.budget_idr_per_serving + tolerance:
            violations.append(
                ConstraintViolation(
                    constraint_family="budget",
                    detail=f"Day {d} cost/serving exceeds budget",
                    expected=scenario.budget_idr_per_serving,
                    actual=round(day_cost, 6),
                )
            )

        for lim in target.limits:
            val = day_nutrients[lim.nutrient_key]
            if lim.min_per_serving is not None and val < lim.min_per_serving - tolerance:
                violations.append(
                    ConstraintViolation(
                        constraint_family="nutrition_floor",
                        detail=f"Day {d} {lim.nutrient_key} below minimum",
                        expected=lim.min_per_serving,
                        actual=round(val, 6),
                    )
                )
            if lim.max_per_serving is not None and val > lim.max_per_serving + tolerance:
                violations.append(
                    ConstraintViolation(
                        constraint_family="nutrition_ceiling",
                        detail=f"Day {d} {lim.nutrient_key} above maximum",
                        expected=lim.max_per_serving,
                        actual=round(val, 6),
                    )
                )

    # 3. Raw ingredient stock check (explicitly reject missing/negative stock)
    for ing_code, used in sorted(ingredient_usage.items()):
        if ing_code not in stock_raw_g:
            violations.append(
                ConstraintViolation(
                    constraint_family="stock",
                    detail=f"Ingredient {ing_code} has no stock record",
                    expected=0.0,
                    actual=round(used, 4),
                )
            )
            continue
        avail = stock_raw_g[ing_code]
        if not math.isfinite(avail) or avail < 0:
            violations.append(
                ConstraintViolation(
                    constraint_family="stock",
                    detail=f"Ingredient {ing_code} has invalid stock value {avail!r}",
                )
            )
            continue
        if used > avail + tolerance:
            violations.append(
                ConstraintViolation(
                    constraint_family="stock",
                    detail=f"Ingredient {ing_code} usage exceeds available stock",
                    expected=avail,
                    actual=round(used, 4),
                )
            )

    # 3b. Per-date FEFO expiry suffix stock audit (if per-date stock bounds provided)
    if usable_stock_by_day is not None:
        all_used_codes = sorted(ingredient_usage.keys())
        for d_start in range(1, scenario.days + 1):
            day_stock_map = usable_stock_by_day.get(d_start)
            if day_stock_map is None:
                continue
            for ing_code in all_used_codes:
                if ing_code not in day_stock_map:
                    continue
                avail_from_d = day_stock_map[ing_code]
                suffix_used = sum(
                    ingredient_usage_by_day[k].get(ing_code, 0.0)
                    for k in range(d_start, scenario.days + 1)
                )
                if suffix_used > avail_from_d + tolerance:
                    violations.append(
                        ConstraintViolation(
                            constraint_family="stock_expiry",
                            detail=(
                                f"Ingredient {ing_code} usage from day {d_start}..{scenario.days} "
                                f"exceeds stock unexpired at day {d_start}"
                            ),
                            expected=avail_from_d,
                            actual=round(suffix_used, 4),
                        )
                    )

    # 4. Repeat cap check
    for family, cnt in sorted(family_counts.items()):
        if cnt > scenario.max_repeat_per_family:
            violations.append(
                ConstraintViolation(
                    constraint_family="repeat_cap",
                    detail=f"Family '{family}' repeated {cnt} times (limit {scenario.max_repeat_per_family})",
                    expected=float(scenario.max_repeat_per_family),
                    actual=float(cnt),
                )
            )

    # 5. Reported objective consistency check (if provided)
    if reported_objective is not None:
        obj_tol = max(1e-4, 1e-7 * abs(recomputed_total_cost))
        if not math.isfinite(reported_objective) or abs(reported_objective - recomputed_total_cost) > obj_tol:
            violations.append(
                ConstraintViolation(
                    constraint_family="objective_consistency",
                    detail="Reported solver objective disagrees with independently recomputed total cost",
                    expected=round(recomputed_total_cost, 6),
                    actual=reported_objective if math.isfinite(reported_objective) else None,
                )
            )

    return ConstraintAudit(
        all_hard_constraints_pass=len(violations) == 0,
        tolerance=tolerance,
        violations=violations,
    )
