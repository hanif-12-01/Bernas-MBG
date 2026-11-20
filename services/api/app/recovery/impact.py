from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple
from uuid import UUID

from app.domain.models.schemas import (
    Ingredient,
    NutritionTargetProfile,
    OptimizationRunResponse,
    RecipeFeatures,
    RecipeVariant,
    ReviewStatusEnum,
    Scenario,
    SlotEnum,
)
from app.inventory.service import InventoryAvailabilitySummary
from app.optimizer.model_builder import get_effective_recipe_allergens
from app.recovery.schemas import (
    AffectedIngredientItem,
    AffectedSlotItem,
    CounterfactualBaselineSnapshot,
    DisruptionConditionRequest,
    DisruptionImpactReport,
    DisruptionTypeEnum,
)


def compute_baseline_material_usage(
    baseline_run: OptimizationRunResponse,
    recipes_by_id: Dict[UUID, RecipeVariant],
    servings_per_day: int,
) -> Tuple[Dict[str, float], Dict[str, List[Tuple[int, SlotEnum]]]]:
    """Compute required raw grams and slot references per ingredient for a fixed menu plan."""
    usage_g: Dict[str, float] = {}
    slots_by_ing: Dict[str, List[Tuple[int, SlotEnum]]] = {}
    for day in baseline_run.days:
        for slot, rid in day.recipes_by_slot.items():
            rec = recipes_by_id.get(rid)
            if rec is None:
                continue
            for item in rec.ingredients:
                add_g = float(item.raw_g_per_serving) * float(servings_per_day)
                usage_g[item.ingredient_code] = usage_g.get(item.ingredient_code, 0.0) + add_g
                slots_by_ing.setdefault(item.ingredient_code, []).append((day.day_index, slot))
    return usage_g, slots_by_ing


def evaluate_fixed_plan_under_conditions(
    *,
    baseline_run: OptimizationRunResponse,
    baseline_scenario: Scenario,
    recipes_by_id: Dict[UUID, RecipeVariant],
    features_by_id_new: Dict[UUID, RecipeFeatures],
    ingredients_by_code: Dict[str, Ingredient],
    target: NutritionTargetProfile,
    effective_prices_new: Dict[str, float],
    effective_stock_new: Dict[str, Optional[float]],
    new_servings_per_day: int,
    new_budget_idr_per_serving: float,
) -> Tuple[CounterfactualBaselineSnapshot, Dict[Tuple[int, SlotEnum], List[str]], Dict[str, float]]:
    """Non-destructively evaluate historical baseline menu against new prices, usable stock, and servings."""
    excluded_allergens: Set[str] = {
        a.strip().lower() for a in baseline_scenario.excluded_allergens if a.strip()
    }
    budget_violations: List[str] = []
    stock_shortages: List[str] = []
    nutrition_or_other_issues: List[str] = []
    slot_reasons: Dict[Tuple[int, SlotEnum], List[str]] = {}
    used_new_g: Dict[str, float] = {}
    family_counts: Dict[str, int] = {}
    total_cost_new = 0.0

    for day in baseline_run.days:
        day_cost_per_serving = 0.0
        day_nutrients: Dict[str, float] = {lim.nutrient_key: 0.0 for lim in target.limits}

        for slot, rid in day.recipes_by_slot.items():
            rec = recipes_by_id.get(rid)
            feat = features_by_id_new.get(rid)
            if rec is None or feat is None:
                msg = f"Hari {day.day_index} {slot.value}: resep tidak ditemukan di dataset."
                nutrition_or_other_issues.append(msg)
                slot_reasons.setdefault((day.day_index, slot), []).append(msg)
                continue

            if not rec.active or rec.review_status != ReviewStatusEnum.REVIEWED:
                msg = f"Hari {day.day_index} {slot.value}: resep {rec.name} berstatus {rec.review_status.value}/nonaktif."
                nutrition_or_other_issues.append(msg)
                slot_reasons.setdefault((day.day_index, slot), []).append(msg)

            recipe_allergens = get_effective_recipe_allergens(rec, ingredients_by_code)
            blocked_allergens = sorted(excluded_allergens & recipe_allergens)
            if blocked_allergens:
                msg = f"Hari {day.day_index} {slot.value}: mengandung alergen terlarang ({', '.join(blocked_allergens)})."
                nutrition_or_other_issues.append(msg)
                slot_reasons.setdefault((day.day_index, slot), []).append(msg)

            family_counts[rec.family] = family_counts.get(rec.family, 0) + 1
            day_cost_per_serving += feat.cost_idr_per_serving
            for lim in target.limits:
                k = lim.nutrient_key
                day_nutrients[k] += feat.nutrients_per_serving.get(k, 0.0)
            for item in rec.ingredients:
                used_new_g[item.ingredient_code] = (
                    used_new_g.get(item.ingredient_code, 0.0)
                    + float(item.raw_g_per_serving) * float(new_servings_per_day)
                )

        total_cost_new += day_cost_per_serving * float(new_servings_per_day)

        if day_cost_per_serving > new_budget_idr_per_serving + 1e-6:
            msg = (
                f"Hari {day.day_index}: biaya Rp{day_cost_per_serving:,.0f}/porsi "
                f"melampaui anggaran Rp{new_budget_idr_per_serving:,.0f}/porsi."
            )
            budget_violations.append(msg)
            for slot in day.recipes_by_slot:
                slot_reasons.setdefault((day.day_index, slot), []).append(msg)

        for lim in target.limits:
            val = day_nutrients.get(lim.nutrient_key, 0.0)
            if lim.min_per_serving is not None and val + 1e-6 < lim.min_per_serving:
                nutrition_or_other_issues.append(
                    f"Hari {day.day_index}: {lim.nutrient_key} = {val:.1f} < batas minimum {lim.min_per_serving:.1f} {lim.unit}."
                )
            if lim.max_per_serving is not None and val - 1e-6 > lim.max_per_serving:
                nutrition_or_other_issues.append(
                    f"Hari {day.day_index}: {lim.nutrient_key} = {val:.1f} > batas maksimum {lim.max_per_serving:.1f} {lim.unit}."
                )

    for family, count in sorted(family_counts.items()):
        if count > baseline_scenario.max_repeat_per_family:
            nutrition_or_other_issues.append(
                f"Pengulangan keluarga resep '{family}' = {count}x melebihi batas {baseline_scenario.max_repeat_per_family}x."
            )

    for code, req_g in sorted(used_new_g.items()):
        ing = ingredients_by_code.get(code)
        ing_name = ing.name if ing else code
        avail_g = effective_stock_new.get(code)
        if avail_g is None:
            msg = f"{ing_name}: stok terverifikasi tidak diketahui (UNKNOWN), butuh {req_g / 1000.0:.2f} kg."
            stock_shortages.append(msg)
        elif req_g > avail_g + 1e-6:
            shortfall_kg = (req_g - avail_g) / 1000.0
            msg = (
                f"{ing_name}: butuh {req_g / 1000.0:.2f} kg, "
                f"siap pakai {avail_g / 1000.0:.2f} kg (kurang {shortfall_kg:.2f} kg)."
            )
            stock_shortages.append(msg)

    for day in baseline_run.days:
        for slot, rid in day.recipes_by_slot.items():
            rec = recipes_by_id.get(rid)
            if rec is None:
                continue
            for item in rec.ingredients:
                code = item.ingredient_code
                req_g = used_new_g.get(code, 0.0)
                avail_g = effective_stock_new.get(code)
                if avail_g is None or req_g > avail_g + 1e-6:
                    ing_name = ingredients_by_code[code].name if code in ingredients_by_code else code
                    shortfall_kg = req_g / 1000.0 if avail_g is None else max(0.0, (req_g - avail_g) / 1000.0)
                    avail_label = "UNKNOWN" if avail_g is None else f"{avail_g / 1000.0:.2f} kg"
                    slot_reasons.setdefault((day.day_index, slot), []).append(
                        f"Kekurangan {ing_name}: butuh {req_g / 1000.0:.2f} kg, tersedia {avail_label} (kurang {shortfall_kg:.2f} kg)."
                    )

    feasible = not budget_violations and not stock_shortages and not nutrition_or_other_issues
    days_count = max(1, baseline_scenario.days)
    total_servings = max(1, days_count * new_servings_per_day)
    avg_cost_new = round(total_cost_new / total_servings, 2)
    avg_daily_new = round(total_cost_new / days_count, 2)
    notes = (
        "Menu asli tetap memenuhi seluruh batasan pada kondisi baru (evaluasi kontrafaktual)."
        if feasible
        else "Menu asli TIDAK LAYAK pada kondisi baru dan tidak boleh dijalankan tanpa penyesuaian."
    )

    counterfactual = CounterfactualBaselineSnapshot(
        label="Menu Asli pada Kondisi Baru (Kontrafaktual)",
        feasible=feasible,
        total_cost_idr=round(total_cost_new, 2),
        cost_per_serving_idr=avg_cost_new,
        days_count=days_count,
        servings_per_day=new_servings_per_day,
        total_servings=total_servings,
        cost_per_day_average_idr=avg_daily_new,
        notes=notes,
        budget_violations=budget_violations,
        stock_shortages=stock_shortages,
        nutrition_or_other_issues=nutrition_or_other_issues,
    )
    return counterfactual, slot_reasons, used_new_g


def build_disruption_impact_report(
    *,
    req: DisruptionConditionRequest,
    baseline_run: OptimizationRunResponse,
    baseline_scenario: Scenario,
    baseline_review_id: Optional[UUID],
    baseline_title: str,
    baseline_status: str,
    dataset_name: str,
    production_date: datetime,
    recipes_by_id: Dict[UUID, RecipeVariant],
    features_by_id_new: Dict[UUID, RecipeFeatures],
    ingredients_by_code: Dict[str, Ingredient],
    target: NutritionTargetProfile,
    previous_prices_idr_per_g: Dict[str, float],
    effective_prices_new: Dict[str, float],
    previous_stock_raw_g: Dict[str, Optional[float]],
    effective_stock_new: Dict[str, Optional[float]],
    availability: Optional[InventoryAvailabilitySummary],
    inventory_snapshot_sha256: str,
    new_servings_per_day: int,
    new_budget_idr_per_serving: float,
) -> Tuple[DisruptionImpactReport, CounterfactualBaselineSnapshot]:
    """Identify affected ingredients and broken slots before generating recovery plans."""
    counterfactual, slot_reasons, used_new_g = evaluate_fixed_plan_under_conditions(
        baseline_run=baseline_run,
        baseline_scenario=baseline_scenario,
        recipes_by_id=recipes_by_id,
        features_by_id_new=features_by_id_new,
        ingredients_by_code=ingredients_by_code,
        target=target,
        effective_prices_new=effective_prices_new,
        effective_stock_new=effective_stock_new,
        new_servings_per_day=new_servings_per_day,
        new_budget_idr_per_serving=new_budget_idr_per_serving,
    )

    avail_by_code = {item.ingredient_code: item for item in availability.items} if availability else {}
    stock_override_by_code = {s.ingredient_code: s for s in req.stock_changes}
    price_override_codes = {p.ingredient_code for p in req.price_changes}
    detected_types: Set[DisruptionTypeEnum] = set(req.disruption_types)

    if new_servings_per_day != baseline_scenario.servings_per_day:
        detected_types.add(DisruptionTypeEnum.SERVING_COUNT_CHANGE)
    if req.price_changes:
        detected_types.add(DisruptionTypeEnum.PRICE_CHANGE)

    baseline_usage_old_g, _ = compute_baseline_material_usage(
        baseline_run, recipes_by_id, baseline_scenario.servings_per_day
    )

    affected_ingredients: List[AffectedIngredientItem] = []
    relevant_codes = sorted(
        set(used_new_g.keys())
        | set(stock_override_by_code.keys())
        | price_override_codes
        | {code for code, item in avail_by_code.items() if item.delivery_status in {"DELAYED", "PARTIAL"}}
    )

    for code in relevant_codes:
        ing = ingredients_by_code.get(code)
        if ing is None:
            continue
        req_new_g = used_new_g.get(code, 0.0)
        prev_g = previous_stock_raw_g.get(code)
        curr_g = effective_stock_new.get(code)
        prev_price_kg = round(previous_prices_idr_per_g.get(code, 0.0) * 1000.0, 2)
        curr_price_kg = round(effective_prices_new.get(code, 0.0) * 1000.0, 2)
        price_delta_pct = (
            round(((curr_price_kg - prev_price_kg) / prev_price_kg) * 100.0, 2)
            if prev_price_kg > 0 and abs(curr_price_kg - prev_price_kg) > 1e-6
            else None
        )

        avail_item = avail_by_code.get(code)
        override_item = stock_override_by_code.get(code)
        delivery_status = (
            (override_item.delivery_status.upper() if override_item and override_item.delivery_status else None)
            or (avail_item.delivery_status if avail_item else "NONE")
        )
        incoming_kg = round((avail_item.incoming_raw_g / 1000.0) if avail_item else 0.0, 3)
        if override_item and override_item.expected_delivery_kg is not None and override_item.received_delivery_kg is not None:
            incoming_kg = round(
                max(0.0, override_item.expected_delivery_kg - override_item.received_delivery_kg), 3
            )
            if override_item.received_delivery_kg < override_item.expected_delivery_kg and delivery_status == "NONE":
                delivery_status = "PARTIAL"
        quality_status = avail_item.data_quality_status if avail_item else "SYNTHETIC_BASELINE"

        shortfall_kg = 0.0
        if req_new_g > 0:
            if curr_g is None:
                shortfall_kg = round(req_new_g / 1000.0, 3)
            elif req_new_g > curr_g + 1e-6:
                shortfall_kg = round((req_new_g - curr_g) / 1000.0, 3)

        causes: List[str] = []
        if override_item and override_item.unavailable:
            detected_types.add(DisruptionTypeEnum.INGREDIENT_UNAVAILABLE)
            causes.append("Bahan ditandai tidak tersedia (0 kg).")
        if delivery_status == "DELAYED":
            detected_types.add(DisruptionTypeEnum.SUPPLIER_DELAY)
            causes.append("Pengiriman pemasok tertunda (DELAYED; belum dihitung sebagai stok siap pakai).")
        elif delivery_status == "PARTIAL":
            detected_types.add(DisruptionTypeEnum.PARTIAL_DELIVERY)
            causes.append("Pengiriman pemasok hanya tiba sebagian (PARTIAL).")
        if shortfall_kg > 0:
            detected_types.add(DisruptionTypeEnum.STOCK_SHORTAGE)
            causes.append(
                f"Kebutuhan menu {req_new_g / 1000.0:.2f} kg melebihi stok siap pakai "
                f"({0.0 if curr_g is None else curr_g / 1000.0:.2f} kg) — kurang {shortfall_kg:.2f} kg."
            )
        elif prev_g is not None and curr_g is not None and curr_g + 1e-6 < prev_g:
            detected_types.add(DisruptionTypeEnum.STOCK_SHORTAGE)
            causes.append(
                f"Stok siap pakai turun dari {prev_g / 1000.0:.2f} kg menjadi {curr_g / 1000.0:.2f} kg."
            )
        if price_delta_pct is not None and abs(price_delta_pct) > 1e-6:
            detected_types.add(DisruptionTypeEnum.PRICE_CHANGE)
            causes.append(
                f"Harga berubah dari Rp{prev_price_kg:,.0f}/kg menjadi Rp{curr_price_kg:,.0f}/kg ({price_delta_pct:+.1f}%)."
            )
        if avail_item and avail_item.safety_held_raw_g > 0:
            detected_types.add(DisruptionTypeEnum.SAFETY_HOLD)
            causes.append(
                f"{avail_item.safety_held_raw_g / 1000.0:.2f} kg ditahan keamanan (SAFETY HOLD) pada lot {', '.join(avail_item.held_lot_codes) or '-'}."
            )
        if avail_item and avail_item.rejected_disposed_raw_g > 0:
            detected_types.add(DisruptionTypeEnum.SAFETY_HOLD)
            causes.append(
                f"{avail_item.rejected_disposed_raw_g / 1000.0:.2f} kg telah ditolak/dimusnahkan (REJECTED_DISPOSED)."
            )
        if avail_item and avail_item.expired_raw_g > 0:
            causes.append(f"{avail_item.expired_raw_g / 1000.0:.2f} kg kedaluwarsa dikecualikan.")
        if avail_item and avail_item.damaged_raw_g > 0:
            causes.append(f"{avail_item.damaged_raw_g / 1000.0:.2f} kg rusak/menyusut dikecualikan.")
        if avail_item and avail_item.reserved_raw_g > 0:
            causes.append(f"{avail_item.reserved_raw_g / 1000.0:.2f} kg sudah dialokasikan (reserved).")
        if override_item and override_item.reason:
            causes.append(override_item.reason)

        if causes or shortfall_kg > 0 or code in stock_override_by_code or code in price_override_codes:
            affected_ingredients.append(
                AffectedIngredientItem(
                    ingredient_code=code,
                    ingredient_name=ing.name,
                    baseline_required_kg=round(baseline_usage_old_g.get(code, 0.0) / 1000.0, 3),
                    previous_usable_kg=round(prev_g / 1000.0, 3) if prev_g is not None else None,
                    current_usable_kg=round(curr_g / 1000.0, 3) if curr_g is not None else None,
                    shortfall_kg=shortfall_kg,
                    previous_price_idr_per_kg=prev_price_kg,
                    current_price_idr_per_kg=curr_price_kg,
                    price_delta_pct=price_delta_pct,
                    delivery_status=delivery_status,
                    incoming_kg=incoming_kg,
                    data_quality_status=quality_status,
                    causes=causes,
                )
            )

    affected_slots: List[AffectedSlotItem] = []
    for day in baseline_run.days:
        for slot, rid in day.recipes_by_slot.items():
            reasons = slot_reasons.get((day.day_index, slot), [])
            if not reasons:
                continue
            rec = recipes_by_id.get(rid)
            ing_hits = []
            if rec is not None:
                for item in rec.ingredients:
                    code = item.ingredient_code
                    avail_g = effective_stock_new.get(code)
                    req_g = used_new_g.get(code, 0.0)
                    if avail_g is None or req_g > avail_g + 1e-6:
                        ing_hits.append(code)
            affected_slots.append(
                AffectedSlotItem(
                    day_index=day.day_index,
                    slot=slot,
                    original_recipe_id=rid,
                    original_recipe_name=day.recipe_names_by_slot.get(slot, str(rid)),
                    affected_ingredients=sorted(set(ing_hits)),
                    reasons=list(dict.fromkeys(reasons)),
                )
            )

    is_disrupted = bool(
        affected_ingredients
        or affected_slots
        or not counterfactual.feasible
        or new_servings_per_day != baseline_scenario.servings_per_day
        or abs(new_budget_idr_per_serving - baseline_scenario.budget_idr_per_serving) > 1e-6
    )

    warnings: List[str] = []
    if not counterfactual.feasible:
        warnings.append(
            "Rencana menu yang disetujui sebelumnya tetap tersimpan tanpa diubah, tetapi tidak layak dijalankan pada kondisi terbaru."
        )
    if availability and availability.quarantined_events_count > 0:
        warnings.append(
            f"Terdapat {availability.quarantined_events_count} transaksi inventaris terkarantina yang tidak dihitung sebagai stok siap pakai."
        )

    if counterfactual.feasible:
        summary_message = (
            f"Rencana '{baseline_title}' masih memenuhi seluruh batasan pada kondisi saat ini "
            f"(biaya kontrafaktual Rp{counterfactual.total_cost_idr:,.0f})."
        )
    else:
        summary_message = (
            f"Gangguan memengaruhi {len(affected_slots)} slot menu pada '{baseline_title}' "
            f"({len(affected_ingredients)} bahan terdampak). Optimasi pemulihan diperlukan sebelum eksekusi."
        )

    report = DisruptionImpactReport(
        baseline_run_id=baseline_run.run_id,
        baseline_menu_review_id=baseline_review_id,
        baseline_title=baseline_title,
        baseline_status=baseline_status,
        dataset_version_id=baseline_scenario.dataset_version_id,
        dataset_name=dataset_name,
        production_date=production_date,
        days=baseline_scenario.days,
        baseline_servings_per_day=baseline_scenario.servings_per_day,
        servings_per_day=new_servings_per_day,
        baseline_budget_idr_per_serving=baseline_scenario.budget_idr_per_serving,
        budget_idr_per_serving=new_budget_idr_per_serving,
        inventory_snapshot_sha256=inventory_snapshot_sha256,
        is_disrupted=is_disrupted,
        baseline_still_feasible_at_new_conditions=counterfactual.feasible,
        disruption_types=sorted(detected_types, key=lambda x: x.value),
        affected_ingredients=affected_ingredients,
        affected_slots=affected_slots,
        budget_violations=counterfactual.budget_violations,
        stock_shortages=counterfactual.stock_shortages,
        nutrition_or_other_issues=counterfactual.nutrition_or_other_issues,
        summary_message=summary_message,
        warnings=warnings,
    )
    return report, counterfactual
