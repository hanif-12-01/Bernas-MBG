from __future__ import annotations

import csv
import io
from typing import Dict, List, Optional

from app.domain.models.schemas import Ingredient, OptimizationRunResponse
from app.export.csv_exporter import escape_csv_formula
from app.inventory.service import InventoryAvailabilitySummary
from app.recovery.schemas import ProcurementDeltaItem


def build_procurement_delta(
    *,
    baseline_usage_old_g: Dict[str, float],
    candidate_run: Optional[OptimizationRunResponse],
    ingredients_by_code: Dict[str, Ingredient],
    effective_prices_new: Dict[str, float],
    effective_stock_new_g: Dict[str, Optional[float]],
    availability: Optional[InventoryAvailabilitySummary],
) -> List[ProcurementDeltaItem]:
    """Compute ingredient-level procurement delta separated cleanly from delayed incoming stock."""
    if candidate_run is None or not candidate_run.validation_passed:
        return []

    avail_by_code = {item.ingredient_code: item for item in availability.items} if availability else {}
    cand_usage_g = {mu.ingredient_code: float(mu.used_raw_g) for mu in candidate_run.material_usage}
    all_codes = sorted(set(cand_usage_g.keys()) | set(baseline_usage_old_g.keys()))

    items: List[ProcurementDeltaItem] = []
    for code in all_codes:
        ing = ingredients_by_code.get(code)
        ing_name = ing.name if ing else code
        req_g = cand_usage_g.get(code, 0.0)
        base_g = baseline_usage_old_g.get(code, 0.0)
        if req_g <= 1e-6 and base_g <= 1e-6:
            continue

        usable_g = effective_stock_new_g.get(code)
        usable_kg = round((usable_g / 1000.0) if usable_g is not None else 0.0, 3)
        avail_item = avail_by_code.get(code)
        incoming_kg = round((avail_item.incoming_raw_g / 1000.0) if avail_item else 0.0, 3)
        deliv_status = avail_item.delivery_status if avail_item else "NONE"

        req_kg = round(req_g / 1000.0, 3)
        base_kg = round(base_g / 1000.0, 3)
        delta_kg = round(req_kg - base_kg, 3)
        net_to_buy_kg = round(max(0.0, req_kg - usable_kg), 3)
        unit_price_kg = round(effective_prices_new.get(code, 0.0) * 1000.0, 2)
        est_cost = round(net_to_buy_kg * unit_price_kg, 2)

        if abs(delta_kg) <= 1e-6 and net_to_buy_kg <= 1e-6:
            reason = "Kebutuhan terpenuhi oleh stok siap pakai tanpa perubahan."
        elif net_to_buy_kg > 0 and deliv_status in {"DELAYED", "PARTIAL"}:
            reason = (
                f"Perlu pembelian {net_to_buy_kg:.2f} kg (stok siap pakai {usable_kg:.2f} kg; "
                f"pengiriman {deliv_status} {incoming_kg:.2f} kg tidak dihitung sebagai stok siap)."
            )
        elif delta_kg > 0:
            reason = f"Penambahan kebutuhan +{delta_kg:.2f} kg akibat substitusi menu pengganti."
        elif delta_kg < 0:
            reason = f"Pengurangan kebutuhan {delta_kg:.2f} kg dari resep asli."
        else:
            reason = "Kebutuhan disesuaikan dengan rencana pemulihan."

        items.append(
            ProcurementDeltaItem(
                ingredient_code=code,
                ingredient_name=ing_name,
                baseline_required_kg=base_kg,
                required_kg=req_kg,
                delta_vs_baseline_required_kg=delta_kg,
                usable_on_hand_kg=usable_kg,
                incoming_kg=incoming_kg,
                delivery_status=deliv_status,
                net_to_buy_kg=net_to_buy_kg,
                unit_price_idr_per_kg=unit_price_kg,
                estimated_net_purchase_cost_idr=est_cost,
                reason=reason,
            )
        )

    return items


def export_procurement_delta_to_csv(
    *,
    event_id: str,
    title: str,
    mode: str,
    items: List[ProcurementDeltaItem],
    days_count: Optional[int] = None,
    servings_per_day: Optional[int] = None,
    total_servings: Optional[int] = None,
    total_cost_idr: Optional[float] = None,
) -> str:
    """Render candidate procurement delta to formula-safe UTF-8 CSV."""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerow(["meta_key", "meta_value"])
    writer.writerow(["recovery_event_id", escape_csv_formula(event_id)])
    writer.writerow(["title", escape_csv_formula(title)])
    writer.writerow(["mode", escape_csv_formula(mode)])
    if days_count is not None:
        writer.writerow(["days", days_count])
    if servings_per_day is not None:
        writer.writerow(["servings_per_day", servings_per_day])
    if total_servings is not None:
        writer.writerow(["total_servings", total_servings])
    if total_cost_idr is not None:
        writer.writerow(["total_ingredient_cost_idr", total_cost_idr])
    writer.writerow(
        [
            "compliance_notice",
            "SIMULATION_ONLY (DEMO_ONLY): Daftar kebutuhan pemulihan operasional internal, bukan pengesahan resmi BGN.",
        ]
    )
    writer.writerow([])
    writer.writerow(
        [
            "ingredient_code",
            "ingredient_name",
            "baseline_required_kg",
            "required_kg",
            "delta_vs_baseline_required_kg",
            "usable_on_hand_kg",
            "incoming_not_usable_kg",
            "delivery_status",
            "net_to_buy_kg",
            "unit_price_idr_per_kg",
            "estimated_net_purchase_cost_idr",
            "reason",
        ]
    )
    for row in items:
        writer.writerow(
            [
                escape_csv_formula(row.ingredient_code),
                escape_csv_formula(row.ingredient_name),
                row.baseline_required_kg,
                row.required_kg,
                row.delta_vs_baseline_required_kg,
                row.usable_on_hand_kg,
                row.incoming_kg,
                escape_csv_formula(row.delivery_status),
                row.net_to_buy_kg,
                row.unit_price_idr_per_kg,
                row.estimated_net_purchase_cost_idr,
                escape_csv_formula(row.reason),
            ]
        )
    return buf.getvalue()
