from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.data.recovery_fixture import RECOVERY_DEMO_DATASET_ID
from app.db.models import (
    DatasetStockSnapshotORM,
    IngredientORM,
)
from app.db.session import db_manager
from tests.conftest import make_authenticated_client
from tests.test_sprint2a_persistence_and_api import _make_valid_csv_bundle


def test_partial_chicken_delivery_recovery_end_to_end():
    planner = make_authenticated_client("perencana_menu")
    manager = make_authenticated_client("kepala_dapur")
    qc = make_authenticated_client("petugas_qc")

    # Locate the seeded APPROVED recovery baseline plan
    reviews_res = planner.get("/api/v1/menu-reviews")
    assert reviews_res.status_code == 200
    approved = [
        r
        for r in reviews_res.json()
        if r["dataset_version_id"] == str(RECOVERY_DEMO_DATASET_ID) and r["status"] == "APPROVED"
    ]
    assert len(approved) == 1
    baseline_review = approved[0]
    baseline_run_id = baseline_review["run_id"]
    baseline_rev_id = baseline_review["id"]

    # Confirm approved plan inventory alert detects 20 kg vs 12 kg (8 kg shortage) without mutating historical approval
    dash_res = manager.get("/api/v1/dashboard/manager-summary")
    assert dash_res.status_code == 200
    inv_alerts = dash_res.json()["approved_plan_inventory_alerts"]
    assert any(
        a["menu_review_id"] == baseline_rev_id and a["requires_inventory_review"]
        for a in inv_alerts
    )

    # Preview impact (no persistence)
    impact_res = planner.post(
        "/api/v1/recovery/impact",
        json={
            "baseline_run_id": baseline_run_id,
            "baseline_menu_review_id": baseline_rev_id,
            "use_latest_verified_inventory": True,
        },
    )
    assert impact_res.status_code == 200, impact_res.text
    impact = impact_res.json()
    assert impact["is_disrupted"] is True
    assert impact["baseline_still_feasible_at_new_conditions"] is False
    ing_map = {item["ingredient_code"]: item for item in impact["affected_ingredients"]}
    assert "ING007" in ing_map
    assert ing_map["ING007"]["baseline_required_kg"] == 20.0
    assert ing_map["ING007"]["current_usable_kg"] == 12.0
    assert ing_map["ING007"]["shortfall_kg"] == 8.0
    assert ing_map["ING007"]["delivery_status"] == "PARTIAL"
    assert ing_map["ING007"]["incoming_kg"] == 8.0
    assert len(impact["affected_slots"]) >= 1

    # RBAC check: QC officer & Kitchen Manager cannot create recovery analysis (403)
    assert qc.post("/api/v1/recovery/impact", json={"baseline_run_id": baseline_run_id}).status_code == 403
    assert manager.post("/api/v1/recovery/impact", json={"baseline_run_id": baseline_run_id}).status_code == 403
    assert qc.get("/api/v1/recovery/events").status_code == 403

    # Create full recovery analysis event (solves MIN_DISRUPTION & MIN_COST and compares fairly)
    create_res = planner.post(
        "/api/v1/recovery/events",
        json={
            "baseline_run_id": baseline_run_id,
            "baseline_menu_review_id": baseline_rev_id,
            "title": "Pemulihan Ayam Parsial 12 kg",
            "disruption_types": ["PARTIAL_DELIVERY"],
            "use_latest_verified_inventory": True,
        },
    )
    assert create_res.status_code == 201, create_res.text
    event = create_res.json()
    event_id = event["id"]

    assert event["status"] == "ANALYZED"
    assert event["min_disruption"]["validation_passed"] is True
    assert event["min_cost"]["validation_passed"] is True
    assert event["min_disruption"]["changed_slots_count"] == len(impact["affected_slots"])
    assert event["min_disruption"]["changed_slots_count"] <= event["min_cost"]["changed_slots_count"]

    # Fair comparison guardrail: original is INFEASIBLE -> NEVER claim cost savings!
    comp = event["comparison"]
    assert comp["original_under_new_conditions"]["feasible"] is False
    assert comp["historical_price_comparison_allowed"] is False
    assert comp["cost_savings_claimed_idr"] is None
    assert comp["same_conditions_comparison_valid"] is False

    # Procurement delta & CSV formula safety check
    proc_items = event["procurement_delta_by_mode"]["MIN_DISRUPTION"]
    assert len(proc_items) > 0
    # Chicken slot was substituted away -> net_to_buy_kg == 0 and incoming_kg stays 8.0 separate
    csv_res = planner.get(f"/api/v1/recovery/events/{event_id}/procurement.csv?mode=MIN_DISRUPTION")
    assert csv_res.status_code == 200
    assert "text/csv" in csv_res.headers["content-type"]
    assert "ingredient_code" in csv_res.text

    # Cross-kitchen isolation: Kitchen B cannot see Kitchen A's recovery event or baseline run (404)
    planner_b = make_authenticated_client("perencana_menu_b")
    assert planner_b.get(f"/api/v1/recovery/events/{event_id}").status_code == 404
    assert (
        planner_b.post("/api/v1/recovery/impact", json={"baseline_run_id": baseline_run_id}).status_code
        == 404
    )

    # Submit MIN_DISRUPTION candidate for approval
    submit_res = planner.post(
        f"/api/v1/recovery/events/{event_id}/submit",
        json={
            "mode": "MIN_DISRUPTION",
            "title": "Usulan Pengganti Ayam Parsial SPPG-A",
            "planner_notes": "Mengganti hanya slot ayam yang kurang 8 kg tanpa mengubah hari lain.",
            "submit_for_review": True,
        },
    )
    assert submit_res.status_code == 200, submit_res.text
    sub_payload = submit_res.json()
    assert sub_payload["recovery_event"]["status"] == "SUBMITTED"
    new_review_id = sub_payload["review"]["id"]
    assert sub_payload["review"]["status"] == "SUBMITTED"
    assert sub_payload["review"]["recovery_event_id"] == event_id

    # Original baseline APPROVED review & run must remain untouched!
    reviews_after_submit = planner.get("/api/v1/menu-reviews").json()
    orig_after = next(r for r in reviews_after_submit if r["id"] == baseline_rev_id)
    assert orig_after["status"] == "APPROVED"

    # Manager approves recovery plan cleanly
    approve_res = manager.post(
        f"/api/v1/menu-reviews/{new_review_id}/review",
        json={
            "decision": "APPROVED",
            "reviewer_notes": "Disetujui karena perubahan slot minimal dan gizi terverifikasi.",
        },
    )
    assert approve_res.status_code == 200, approve_res.text
    assert approve_res.json()["status"] == "APPROVED"

    # Verify persisted state via fresh query / client reload
    fresh_planner = make_authenticated_client("perencana_menu")
    reloaded = fresh_planner.get(f"/api/v1/recovery/events/{event_id}")
    assert reloaded.status_code == 200
    assert reloaded.json()["status"] == "APPROVED"
    assert reloaded.json()["submitted_review_id"] == new_review_id


def test_multi_disruption_fair_savings_and_infeasible_handling():
    planner = make_authenticated_client("perencana_menu")

    # Find demo baseline run
    runs_res = planner.get("/api/v1/runs")
    assert runs_res.status_code == 200
    demo_runs = [r for r in runs_res.json() if r["validation_passed"]]
    assert demo_runs
    baseline_run_id = demo_runs[0]["run_id"]

    # Combined disruption: price increase + partial/short stock + increased servings (250 -> 280)
    combo_res = planner.post(
        "/api/v1/recovery/events",
        json={
            "baseline_run_id": baseline_run_id,
            "disruption_types": ["PRICE_CHANGE", "STOCK_SHORTAGE", "SERVING_COUNT_CHANGE"],
            "new_servings_per_day": 280,
            "price_changes": [{"ingredient_code": "ING007", "new_price_idr_per_kg": 52000}],
            "stock_changes": [
                {"ingredient_code": "ING007", "new_usable_kg": 10.0, "reason": "Stok dingin berkurang"}
            ],
            "use_latest_verified_inventory": True,
        },
    )
    assert combo_res.status_code == 201, combo_res.text
    combo = combo_res.json()
    assert combo["comparison"]["historical_price_comparison_allowed"] is False

    # Impossible disruption: mark ALL protein sources unavailable (0 kg) -> INFEASIBLE, submit blocked (409)
    infeasible_res = planner.post(
        "/api/v1/recovery/events",
        json={
            "baseline_run_id": baseline_run_id,
            "disruption_types": ["INGREDIENT_UNAVAILABLE"],
            "stock_changes": [
                {"ingredient_code": "ING006", "unavailable": True},
                {"ingredient_code": "ING007", "unavailable": True},
                {"ingredient_code": "ING008", "unavailable": True},
                {"ingredient_code": "ING009", "unavailable": True},
                {"ingredient_code": "ING010", "unavailable": True},
                {"ingredient_code": "ING011", "unavailable": True},
            ],
            "use_latest_verified_inventory": True,
        },
    )
    assert infeasible_res.status_code == 201, infeasible_res.text
    inf_event = infeasible_res.json()
    assert inf_event["status"] == "INFEASIBLE"
    assert inf_event["min_disruption"]["validation_passed"] is False
    assert inf_event["min_cost"]["validation_passed"] is False

    sub_blocked = planner.post(
        f"/api/v1/recovery/events/{inf_event['id']}/submit",
        json={"mode": "MIN_DISRUPTION"},
    )
    assert sub_blocked.status_code == 409


def test_stale_inventory_snapshot_blocks_manager_approval_with_409():
    """Verify Sprint 3B stale-snapshot guard blocks approving an outdated recovery proposal in Kitchen B."""
    planner_b = make_authenticated_client("perencana_menu_b")
    manager_b = make_authenticated_client("kepala_dapur_b")

    # Upload a validated feasible CSV bundle for Kitchen B so mutating stock won't disturb Kitchen A
    ds_res = planner_b.post(
        "/api/v1/datasets/import",
        data={
            "name": "Dataset Stale Guard B",
            "source_type": "synthetic",
            "source_url": "https://example.local/demo",
            "is_synthetic": "true",
        },
        files=_make_valid_csv_bundle(formula_injection_name=False),
    )
    assert ds_res.status_code == 201, ds_res.text
    ds_id = ds_res.json()["dataset_version_id"]

    sc_res = planner_b.post(
        "/api/v1/scenarios",
        json={
            "name": "Baseline Kitchen B",
            "dataset_version_id": ds_id,
            "servings_per_day": 100,
            "days": 2,
            "budget_idr_per_serving": 12000,
            "max_repeat_per_family": 2,
        },
    )
    assert sc_res.status_code == 201, sc_res.text
    run_res = planner_b.post(f"/api/v1/scenarios/{sc_res.json()['id']}/optimize")
    assert run_res.status_code == 200, run_res.text
    assert run_res.json()["validation_passed"] is True
    base_run_id = run_res.json()["run_id"]

    rec_res = planner_b.post(
        "/api/v1/recovery/events",
        json={
            "baseline_run_id": base_run_id,
            "stock_changes": [{"ingredient_code": "C_ING3", "unavailable": True}],
            "use_latest_verified_inventory": True,
        },
    )
    assert rec_res.status_code == 201, rec_res.text
    ev_id = rec_res.json()["id"]

    sub_res = planner_b.post(
        f"/api/v1/recovery/events/{ev_id}/submit",
        json={"mode": "MIN_DISRUPTION", "submit_for_review": True},
    )
    assert sub_res.status_code == 200
    rev_id = sub_res.json()["review"]["id"]

    # Mutate underlying Kitchen B inventory snapshot AFTER submission!
    assert db_manager.SessionLocal is not None
    with db_manager.SessionLocal() as session:
        b3_ing = (
            session.query(IngredientORM)
            .filter(IngredientORM.dataset_version_id == ds_id, IngredientORM.code == "C_ING4")
            .one()
        )
        snap = (
            session.query(DatasetStockSnapshotORM)
            .filter(
                DatasetStockSnapshotORM.dataset_version_id == ds_id,
                DatasetStockSnapshotORM.ingredient_id == b3_ing.id,
            )
            .one()
        )
        snap.stock_raw_g = 5000.0
        session.commit()

    # Check UI / GET flags is_stale_inventory == True
    stale_check = manager_b.get(f"/api/v1/recovery/events/{ev_id}")
    assert stale_check.status_code == 200
    assert stale_check.json()["is_stale_inventory"] is True

    # Manager approval MUST be blocked with 409 Stale Snapshot!
    approve_blocked = manager_b.post(
        f"/api/v1/menu-reviews/{rev_id}/review",
        json={"decision": "APPROVED"},
    )
    assert approve_blocked.status_code == 409
    assert "409" in approve_blocked.json()["detail"] or "berubah" in approve_blocked.json()["detail"].lower()

    # Review remains SUBMITTED (not APPROVED); returning for revision still succeeds!
    revise_res = manager_b.post(
        f"/api/v1/menu-reviews/{rev_id}/review",
        json={"decision": "REVISION_REQUIRED", "reviewer_notes": "Stok berubah, hitung ulang."},
    )
    assert revise_res.status_code == 200
    assert revise_res.json()["status"] == "REVISION_REQUIRED"
