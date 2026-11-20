from __future__ import annotations

import concurrent.futures
import csv
import io
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select

from app.data.recovery_fixture import RECOVERY_DEMO_DATASET_ID
from app.data.synthetic_fixture import DEMO_DATASET_ID, DEMO_TARGET_ID
from app.db.models import MenuReviewRecordORM, OperationalPlanAssignmentORM
from app.db.session import db_manager
from tests.conftest import make_authenticated_client
from tests.test_sprint2a_persistence_and_api import _make_valid_csv_bundle


def _import_fresh_dataset_for_stabilization(planner):
    files = _make_valid_csv_bundle()
    res = planner.post(
        "/api/v1/datasets/import",
        data={
            "name": f"Stabilization Dataset {str(uuid4())[:8]}",
            "source_type": "synthetic",
            "is_synthetic": "true",
        },
        files=files,
    )
    assert res.status_code == 201, res.text
    return res.json()["dataset_version_id"]


def test_operational_plan_state_machine_and_transactional_activation():
    planner = make_authenticated_client("perencana_menu")
    manager = make_authenticated_client("kepala_dapur")
    qc = make_authenticated_client("petugas_qc")

    ds_id = _import_fresh_dataset_for_stabilization(planner)
    prod_date = "2026-12-01T08:00:00Z"

    # 1. NO_PLAN initially for this fresh dataset/date scope
    eff0 = manager.get(
        f"/api/v1/operational-plans/effective?dataset_version_id={ds_id}&production_date=2026-12-01"
    )
    assert eff0.status_code == 200, eff0.text
    assert eff0.json()["state"] == "NO_PLAN"
    assert eff0.json()["is_ready_for_execution"] is False

    # Create scenario + run optimization
    sc_res = planner.post(
        "/api/v1/scenarios",
        json={
            "name": "Rencana Awal Stabilisasi",
            "dataset_version_id": ds_id,
            "nutrition_target_id": str(DEMO_TARGET_ID),
            "servings_per_day": 50,
            "days": 2,
            "budget_idr_per_serving": 18000,
            "max_repeat_per_family": 2,
            "excluded_allergens": [],
            "source_label": "synthetic",
            "production_date": prod_date,
        },
    )
    assert sc_res.status_code == 201, sc_res.text
    sc_id = sc_res.json()["id"]

    opt_res = planner.post(f"/api/v1/scenarios/{sc_id}/optimize", json={"time_limit_seconds": 10.0})
    assert opt_res.status_code == 200, opt_res.text
    run1 = opt_res.json()
    assert run1["solver_status"] in {"OPTIMAL", "FEASIBLE"}
    assert run1["days_count"] == 2
    assert run1["servings_per_day"] == 50
    assert run1["total_servings"] == 100
    assert run1["total_menu_slots"] == 8

    # Create & submit draft -> state becomes DRAFT
    rev1_res = planner.post(
        "/api/v1/menu-reviews",
        json={"run_id": run1["run_id"], "title": "Menu Baseline 120 Porsi"},
    )
    assert rev1_res.status_code == 201, rev1_res.text
    rev1_id = rev1_res.json()["id"]

    # Non-approved review cannot be activated (409), and non-manager gets 403
    assert (
        planner.post(
            "/api/v1/operational-plans/activate",
            json={"menu_review_id": rev1_id},
        ).status_code
        == 403
    )
    assert (
        manager.post(
            "/api/v1/operational-plans/activate",
            json={"menu_review_id": rev1_id},
        ).status_code
        == 409
    )

    eff_draft = manager.get(
        f"/api/v1/operational-plans/effective?dataset_version_id={ds_id}&production_date=2026-12-01"
    )
    assert eff_draft.json()["state"] == "DRAFT"

    assert planner.post(f"/api/v1/menu-reviews/{rev1_id}/submit", json={}).status_code == 200
    app1_res = manager.post(
        f"/api/v1/menu-reviews/{rev1_id}/review",
        json={"decision": "APPROVED", "reviewer_notes": "Baseline disetujui"},
    )
    assert app1_res.status_code == 200, app1_res.text
    assert app1_res.json()["operational_status"] == "ACTIVE"

    # Re-activating via effective endpoint shows ACTIVE
    eff_active = qc.get(
        f"/api/v1/operational-plans/effective?dataset_version_id={ds_id}&production_date=2026-12-01"
    )
    assert eff_active.status_code == 200
    assert eff_active.json()["state"] == "ACTIVE"
    assert eff_active.json()["active_plan"]["menu_review_id"] == rev1_id
    first_assign_id = eff_active.json()["active_plan"]["id"]

    # Run a recovery event on same scope -> creates second APPROVED replacement (APPROVED_NOT_ACTIVE until explicit activation)
    rec_ev_res = planner.post(
        "/api/v1/recovery/events",
        json={
            "baseline_run_id": run1["run_id"],
            "baseline_menu_review_id": rev1_id,
            "title": "Simulasi Pergantian Protein Stabilisasi",
            "stock_changes": [
                {"ingredient_code": "C_ING3", "new_usable_kg": 0.0, "unavailable": True}
            ],
            "use_latest_verified_inventory": False,
        },
    )
    assert rec_ev_res.status_code == 201, rec_ev_res.text
    ev_id = rec_ev_res.json()["id"]

    sub2_res = planner.post(
        f"/api/v1/recovery/events/{ev_id}/submit",
        json={"mode": "MIN_DISRUPTION", "title": "Menu Pengganti v2", "submit_for_review": True},
    )
    assert sub2_res.status_code == 200, sub2_res.text
    rev2_id = sub2_res.json()["review"]["id"]

    app2_res = manager.post(
        f"/api/v1/menu-reviews/{rev2_id}/review",
        json={"decision": "APPROVED", "reviewer_notes": "Siap diaktifkan"},
    )
    assert app2_res.status_code == 200, app2_res.text
    # Recovery approval intentionally remains APPROVED_NOT_ACTIVE until explicit transactional activation
    assert app2_res.json()["operational_status"] == "APPROVED_NOT_ACTIVE"

    # Expected active assignment conflict check (stale expected id -> 409)
    stale_expected = manager.post(
        "/api/v1/operational-plans/activate",
        json={
            "menu_review_id": rev2_id,
            "expected_active_assignment_id": str(uuid4()),
        },
    )
    assert stale_expected.status_code == 409

    # Valid explicit activation with idempotency_key
    idem_key = f"act-{uuid4()}"
    act2_res = manager.post(
        "/api/v1/operational-plans/activate",
        json={
            "menu_review_id": rev2_id,
            "expected_active_assignment_id": first_assign_id,
            "notes": "Aktifkan Menu Pengganti v2 secara atomik.",
            "idempotency_key": idem_key,
        },
    )
    assert act2_res.status_code == 200, act2_res.text
    assert act2_res.json()["operational_status"] == "ACTIVE"
    assert act2_res.json()["supersedes_assignment_id"] == first_assign_id

    # Idempotent retry returns the exact same assignment without creating duplicates
    act2_retry = manager.post(
        "/api/v1/operational-plans/activate",
        json={"menu_review_id": rev2_id, "idempotency_key": idem_key},
    )
    assert act2_retry.status_code == 200
    assert act2_retry.json()["id"] == act2_res.json()["id"]

    # Historical MenuReviewRecordORM of v1 remains APPROVED (not altered!) while operational status is SUPERSEDED
    rev1_check = manager.get(f"/api/v1/menu-reviews/{rev1_id}").json()
    assert rev1_check["status"] == "APPROVED"
    assert rev1_check["operational_status"] == "SUPERSEDED"

    eff_final = manager.get(
        f"/api/v1/operational-plans/effective?dataset_version_id={ds_id}&production_date=2026-12-01"
    ).json()
    assert eff_final["state"] == "ACTIVE"
    assert eff_final["active_plan"]["menu_review_id"] == rev2_id
    assert eff_final["superseded_plans_count"] == 1


def test_parallel_activation_race_test_g_preserves_single_effective_plan():
    """Stress Test G: Parallel activation calls on same scope must yield at most 1 active_scope_key."""
    planner = make_authenticated_client("perencana_menu")
    manager = make_authenticated_client("kepala_dapur")
    ds_id = _import_fresh_dataset_for_stabilization(planner)

    review_ids: list[str] = []
    for idx in range(2):
        sc_res = planner.post(
            "/api/v1/scenarios",
            json={
                "name": f"Race Scenario {idx}",
                "dataset_version_id": ds_id,
                "nutrition_target_id": str(DEMO_TARGET_ID),
                "servings_per_day": 45 + idx * 5,
                "days": 2,
                "budget_idr_per_serving": 18000,
                "max_repeat_per_family": 2,
                "excluded_allergens": [],
                "source_label": "synthetic",
                "production_date": "2026-12-05T08:00:00Z",
            },
        )
        assert sc_res.status_code == 201
        run_id = planner.post(
            f"/api/v1/scenarios/{sc_res.json()['id']}/optimize", json={"time_limit_seconds": 10.0}
        ).json()["run_id"]
        rev_id = planner.post(
            "/api/v1/menu-reviews", json={"run_id": run_id, "title": f"Race Plan {idx}"}
        ).json()["id"]
        planner.post(f"/api/v1/menu-reviews/{rev_id}/submit", json={})
        manager.post(
            f"/api/v1/menu-reviews/{rev_id}/review",
            json={"decision": "APPROVED", "reviewer_notes": "Disetujui untuk race test"},
        )
        review_ids.append(rev_id)

    def _activate(rid: str):
        c = make_authenticated_client("kepala_dapur")
        return c.post("/api/v1/operational-plans/activate", json={"menu_review_id": rid})

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futs = [pool.submit(_activate, rid) for rid in review_ids]
        responses = [f.result() for f in futs]

    # One or both succeeded sequentially (never 500), and DB has <= 1 ACTIVE row with same scope key
    assert all(r.status_code in {200, 409} for r in responses)
    assert any(r.status_code == 200 for r in responses)

    list_res = manager.get(
        f"/api/v1/operational-plans?dataset_version_id={ds_id}&include_superseded=false"
    )
    assert list_res.status_code == 200
    assert len(list_res.json()) == 1
    assert list_res.json()[0]["operational_status"] == "ACTIVE"


def test_cost_portion_and_slot_metrics_reconciled_across_api_and_csv():
    planner = make_authenticated_client("perencana_menu")
    manager = make_authenticated_client("kepala_dapur")

    # Inspect RECOVERY_DEMO_DATASET_ID active operational plan (5 days x 250 servings = 1,250 servings, 20 slots)
    eff = manager.get(
        f"/api/v1/operational-plans/effective?dataset_version_id={RECOVERY_DEMO_DATASET_ID}"
    )
    assert eff.status_code == 200, eff.text
    eff_json = eff.json()
    assert eff_json["state"] == "ACTIVE"
    ap = eff_json["active_plan"]
    assert ap["horizon_days"] == 5
    assert ap["servings_per_day"] == 250
    assert ap["total_servings"] == 1250
    assert ap["total_menu_slots"] == 20

    # Cross-check run endpoint
    run = planner.get(f"/api/v1/runs/{ap['run_id']}").json()
    assert run["days_count"] == 5
    assert run["servings_per_day"] == 250
    assert run["total_servings"] == 1250
    assert run["total_menu_slots"] == 20
    assert round(run["objective_total_idr"] / 1250, 2) == run["cost_per_serving_average_idr"]
    assert round(run["objective_total_idr"] / 5, 2) == run["cost_per_day_average_idr"]
    assert ap["total_cost_idr"] == run["objective_total_idr"]

    # Cross-check menu review response
    rev = manager.get(f"/api/v1/menu-reviews/{ap['menu_review_id']}").json()
    assert rev["days_count"] == 5
    assert rev["servings_per_day"] == 250
    assert rev["total_servings"] == 1250
    assert rev["cost_per_day_average_idr"] == run["cost_per_day_average_idr"]

    # Cross-check CSV export headers match exact API numbers
    csv_res = planner.get(f"/api/v1/runs/{ap['run_id']}/export.csv")
    assert csv_res.status_code == 200
    rows = list(csv.reader(io.StringIO(csv_res.text)))
    meta = {r[0]: r[1] for r in rows if len(r) >= 2}
    assert meta["servings_per_day"] == "250"
    assert meta["days"] == "5"
    assert meta["total_servings"] == "1250"
    assert meta["total_menu_slots"] == "20"
    assert float(meta["total_ingredient_cost_idr"]) == run["objective_total_idr"]
    assert float(meta["cost_per_day_average_idr"]) == run["cost_per_day_average_idr"]
    assert float(meta["cost_per_serving_average_idr"]) == run["cost_per_serving_average_idr"]
