from __future__ import annotations

from app.inventory.service import InventoryAvailabilitySummary
from app.scenarios.service import compute_snapshot_sha256


def compute_usable_inventory_sha256(summary: InventoryAvailabilitySummary) -> str:
    """Compute a deterministic SHA-256 fingerprint of verified usable inventory state."""
    canonical = {
        "dataset_version_id": str(summary.dataset_version_id),
        "uses_batch_ledger": bool(summary.uses_batch_ledger),
        "items": [
            {
                "code": item.ingredient_code,
                "usable_raw_g": item.usable_raw_g,
                "recorded_raw_g": item.recorded_raw_g,
                "safety_held_raw_g": item.safety_held_raw_g,
                "rejected_disposed_raw_g": item.rejected_disposed_raw_g,
                "held_lot_codes": list(item.held_lot_codes),
                "incoming_raw_g": item.incoming_raw_g,
                "delivery_status": item.delivery_status,
                "data_quality_status": item.data_quality_status,
            }
            for item in sorted(summary.items, key=lambda i: i.ingredient_code)
        ],
    }
    return compute_snapshot_sha256(canonical)
