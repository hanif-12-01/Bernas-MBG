from __future__ import annotations

import io
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from PIL import Image
from sqlalchemy import text

from app.data.incident_fixture import INCIDENT_DEMO_DATASET_ID
from app.data.synthetic_fixture import DEMO_TARGET_ID
from app.db.models import (
    IngredientORM,
    InventoryLotORM,
    InventoryMovementORM,
    MealBatchORM,
)
from app.db.session import SERVICE_ROOT, create_db_engine, db_manager
from tests.conftest import TEST_DEMO_PASSWORD, make_authenticated_client
from tests.test_sprint2a_persistence_and_api import _make_valid_csv_bundle


def _make_jpeg_with_exif_bytes() -> bytes:
    img = Image.new("RGB", (64, 64), color=(180, 70, 40))
    exif = img.getexif()
    exif[0x010F] = "GPS-Test-Camera-Manufacturer"
    exif[0x0110] = "FieldCamera-X100"
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif.tobytes())
    return buf.getvalue()


def _create_isolated_dataset_with_proteins(
    planner, manager, *, prod_date: str = "2026-12-10T08:00:00Z"
):
    files = _make_valid_csv_bundle()
    ds_res = planner.post(
        "/api/v1/datasets/import",
        data={
            "name": f"Incident Test DS {str(uuid4())[:8]}",
            "source_type": "synthetic",
            "is_synthetic": "true",
        },
        files=files,
    )
    assert ds_res.status_code == 201, ds_res.text
    ds_id = ds_res.json()["dataset_version_id"]

    # Create scenario + optimize + approve + seed verified lots for clean protein lots
    sc_res = planner.post(
        "/api/v1/scenarios",
        json={
            "name": "Skenario Dasar Tes Insiden",
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
    opt_res = planner.post(
        f"/api/v1/scenarios/{sc_res.json()['id']}/optimize", json={"time_limit_seconds": 10.0}
    )
    assert opt_res.status_code == 200, opt_res.text
    run_id = opt_res.json()["run_id"]
    rev_res = planner.post(
        "/api/v1/menu-reviews", json={"run_id": run_id, "title": "Menu Tes Insiden"}
    )
    assert rev_res.status_code == 201, rev_res.text
    rev_id = rev_res.json()["id"]
    assert planner.post(f"/api/v1/menu-reviews/{rev_id}/submit", json={}).status_code == 200
    assert (
        manager.post(
            f"/api/v1/menu-reviews/{rev_id}/review",
            json={"decision": "APPROVED", "reviewer_notes": "Siap uji insiden"},
        ).status_code
        == 200
    )

    # Seed verified lots in CSV batch ledger for all 9 ingredients
    rows_csv = [
        "event_type,ingredient_code,lot_code,quantity,unit,event_at,expires_at,idempotency_key"
    ]
    for idx in range(1, 10):
        rows_csv.append(
            f"OPENING_BALANCE,C_ING{idx},LOT-T-{ds_id[:4]}-ING{idx},250,kg,2026-12-09T08:00:00Z,2027-06-01T00:00:00Z,IDEMP-{ds_id[:8]}-{idx}"
        )
    imp_res = planner.post(
        "/api/v1/inventory/transactions/import",
        data={
            "dataset_version_id": ds_id,
            "data_classification": "synthetic",
            "dry_run": "false",
        },
        files={"transactions_file": ("lots.csv", "\n".join(rows_csv).encode("utf-8"), "text/csv")},
    )
    assert imp_res.status_code == 200, imp_res.text
    return ds_id, run_id, rev_id


def test_a_triple_ingredient_incident_recovery_and_activation_end_to_end():
    """Stress Test A: Triple ingredient incident on INCIDENT_DEMO_DATASET_ID -> hold, recovery, activation, QC handoff."""
    qc = make_authenticated_client("petugas_qc")
    planner = make_authenticated_client("perencana_menu")
    manager = make_authenticated_client("kepala_dapur")

    # 1. Confirm seeded baseline active operational plan uses 200 porsi/hari x 5 hari = 1,000 porsi
    eff0 = manager.get(
        f"/api/v1/operational-plans/effective?dataset_version_id={INCIDENT_DEMO_DATASET_ID}"
    )
    assert eff0.status_code == 200, eff0.text
    assert eff0.json()["state"] == "ACTIVE"
    orig_active = eff0.json()["active_plan"]
    orig_rev_id = orig_active["menu_review_id"]
    orig_assign_id = orig_active["id"]

    # Confirm baseline run actually selected ING007 (Chicken), ING006 (Eggs), and ING012 (Spinach)
    orig_run = planner.get(f"/api/v1/runs/{orig_active['run_id']}").json()
    used_codes = {m["ingredient_code"] for m in orig_run["material_usage"] if m["used_raw_g"] > 0}
    assert {"ING007", "ING006", "ING012"}.issubset(used_codes), f"Baseline missed target ingredients: {used_codes}"

    # 2. QC checks /inventory/lots (without pricing!) and reports ONE multi-ingredient incident
    lots_res = qc.get(f"/api/v1/inventory/lots?dataset_version_id={INCIDENT_DEMO_DATASET_ID}")
    assert lots_res.status_code == 200, lots_res.text
    assert "price_idr_per_g" not in lots_res.text

    inc_res = qc.post(
        "/api/v1/incidents",
        json={
            "title": "Suspek Basi Ayam Lot A + Telur Retak + Bayam Layu",
            "category": "SPOILAGE",
            "severity": "CRITICAL",
            "notes": "Ditemukan bau asam pada LOT-3C-AYAM-A (Lot B masih baik), telur retak/berbau pada LOT-3C-TELUR-A, dan daun bayam berlendir pada LOT-3C-BAYAM-A.",
            "dataset_version_id": str(INCIDENT_DEMO_DATASET_ID),
            "affected_lots": [
                {"lot_code": "LOT-3C-AYAM-A", "reason_detail": "Bau asam cold storage rak 1; LOT-3C-AYAM-B masih bersih"},
                {"lot_code": "LOT-3C-TELUR-A", "reason_detail": "Cangkang retak & bau tidak wajar"},
                {"lot_code": "LOT-3C-BAYAM-A", "reason_detail": "Daun layu berlendir"},
            ],
            "auto_hold_matching_lots": False,
        },
    )
    assert inc_res.status_code == 201, inc_res.text
    inc = inc_res.json()
    inc_id = inc["id"]
    assert inc["status"] == "ON_HOLD"
    assert sorted(inc["affected_ingredient_codes"]) == ["ING006", "ING007", "ING012"]
    assert {l["lot_code"] for l in inc["affected_lots"]} == {
        "LOT-3C-AYAM-A",
        "LOT-3C-TELUR-A",
        "LOT-3C-BAYAM-A",
    }
    assert all(l["lot_safety_status"] == "ON_HOLD" for l in inc["affected_lots"])
    # 24 kg Ayam A + 40 kg Telur + 40 kg Bayam = 104 kg held; LOT-3C-AYAM-B (16 kg) stays clean!
    assert inc["total_held_kg"] == 104.0
    assert inc["total_clean_remaining_kg"] == 16.0

    # 3. Active plan must immediately transition to ON_HOLD while historical review stays APPROVED
    eff_hold = qc.get(
        f"/api/v1/operational-plans/effective?dataset_version_id={INCIDENT_DEMO_DATASET_ID}"
    ).json()
    assert eff_hold["state"] == "ACTIVE_ON_HOLD"
    assert eff_hold["is_ready_for_execution"] is False
    assert eff_hold["held_plan"]["hold_incident_id"] == inc_id
    assert planner.get(f"/api/v1/menu-reviews/{orig_rev_id}").json()["status"] == "APPROVED"

    # Routine QC inspection on ON_HOLD plan must be BLOCKED (409)
    qc_blocked = qc.post(
        "/api/v1/qc/inspections",
        json={"run_id": orig_active["run_id"], "menu_review_id": orig_rev_id, "day_index": 1},
    )
    assert qc_blocked.status_code == 409

    # 4. Verify usable inventory counts clean Chicken (16 kg PARTIAL_SAFETY_HOLD) and 0 kg Eggs & Spinach (SAFETY_HOLD)
    cat_res = planner.get(
        f"/api/v1/inventory?dataset_version_id={INCIDENT_DEMO_DATASET_ID}&production_date=2026-11-23T08:00:00Z"
    )
    assert cat_res.status_code == 200
    items_by_code = {i["code"]: i for i in cat_res.json()["items"]}
    assert items_by_code["ING007"]["usable_raw_g"] == 16000.0
    assert items_by_code["ING007"]["safety_held_raw_g"] == 24000.0
    assert items_by_code["ING007"]["data_quality_status"] == "PARTIAL_SAFETY_HOLD"
    assert items_by_code["ING006"]["usable_raw_g"] == 0.0
    assert items_by_code["ING006"]["data_quality_status"] == "SAFETY_HOLD"
    assert items_by_code["ING012"]["usable_raw_g"] == 0.0
    assert items_by_code["ING012"]["data_quality_status"] == "SAFETY_HOLD"

    # 5. Menu Planner triggers recovery from incident -> SOLVED OPTIMAL using 0g Eggs, 0g Spinach, <=16kg Chicken!
    rec_res = planner.post(
        f"/api/v1/incidents/{inc_id}/start-recovery",
        json={"production_date": "2026-11-23T08:00:00Z"},
    )
    assert rec_res.status_code == 201, rec_res.text
    ev = rec_res.json()
    assert ev["incident_id"] == inc_id
    assert ev["status"] == "ANALYZED"
    assert ev["min_disruption"]["validation_passed"] is True
    rec_run = ev["min_disruption"]["run_detail"]
    rec_usage = {m["ingredient_code"]: m["used_raw_g"] for m in rec_run["material_usage"]}
    assert rec_usage.get("ING006", 0.0) == 0.0
    assert rec_usage.get("ING012", 0.0) == 0.0
    assert rec_usage.get("ING007", 0.0) <= 16000.0 + 1e-6

    # 6. Submit, approve (remains APPROVED_NOT_ACTIVE), and explicitly activate
    sub_res = planner.post(
        f"/api/v1/recovery/events/{ev['id']}/submit",
        json={"mode": "MIN_DISRUPTION", "title": "Menu Pengganti Aman 3C", "submit_for_review": True},
    )
    assert sub_res.status_code == 200, sub_res.text
    new_rev_id = sub_res.json()["review"]["id"]

    app_res = manager.post(
        f"/api/v1/menu-reviews/{new_rev_id}/review",
        json={"decision": "APPROVED", "reviewer_notes": "Menu pengganti aman tanpa telur/bayam dan dalam batas ayam bersih."},
    )
    assert app_res.status_code == 200, app_res.text
    assert app_res.json()["operational_status"] == "APPROVED_NOT_ACTIVE"

    act_res = manager.post(
        "/api/v1/operational-plans/activate",
        json={
            "menu_review_id": new_rev_id,
            "expected_active_assignment_id": orig_assign_id,
            "notes": "Ganti penuh rencana ON_HOLD dengan rencana aman.",
        },
    )
    assert act_res.status_code == 200, act_res.text
    assert act_res.json()["operational_status"] == "ACTIVE"
    assert act_res.json()["supersedes_assignment_id"] == orig_assign_id

    # 7. Old plan is SUPERSEDED (QC blocked with 409), new plan is ACTIVE (QC defaults & succeeds!)
    assert (
        qc.post(
            "/api/v1/qc/inspections",
            json={"run_id": orig_active["run_id"], "menu_review_id": orig_rev_id, "day_index": 1},
        ).status_code
        == 409
    )
    qc_summary = qc.get("/api/v1/dashboard/qc-summary").json()
    assert any(p["menu_review_id"] == new_rev_id for p in qc_summary["effective_operational_plans"])

    qc_ok = qc.post(
        "/api/v1/qc/inspections",
        json={"run_id": ev["min_disruption"]["run_id"], "menu_review_id": new_rev_id, "day_index": 1},
    )
    assert qc_ok.status_code == 201, qc_ok.text
    assert qc_ok.json()["plan_operational_status"] == "ACTIVE"


def test_b_and_c_infeasibility_and_safety_hold_bypass_blocks():
    """Stress Tests B & C: True infeasibility returns diagnostics (no mock menu) & ALL bypass vectors are blocked."""
    qc = make_authenticated_client("petugas_qc")
    planner = make_authenticated_client("perencana_menu")
    manager = make_authenticated_client("kepala_dapur")

    ds_id, run_id, rev_id = _create_isolated_dataset_with_proteins(
        planner, manager, prod_date="2026-12-10T08:00:00Z"
    )

    # Hold ALL protein ingredients (C_ING3 and C_ING4) -> recovery must be honestly INFEASIBLE
    inc_res = qc.post(
        "/api/v1/incidents",
        json={
            "title": "Kerusakan Total Protein C_ING3 & C_ING4",
            "category": "TEMPERATURE_EXCURSION",
            "severity": "CRITICAL",
            "notes": "Chiller protein rusak total; seluruh C_ING3 dan C_ING4 berpotensi tidak aman.",
            "dataset_version_id": ds_id,
            "ingredient_codes": ["C_ING3", "C_ING4"],
            "auto_hold_matching_lots": True,
        },
    )
    assert inc_res.status_code == 201, inc_res.text
    inc_id = inc_res.json()["id"]

    # C1: Attempting release-hold inside app -> 403 + forensic RELEASE_ATTEMPT_BLOCKED action
    rel_res = manager.post(
        f"/api/v1/incidents/{inc_id}/release-hold",
        json={"authority_reference": "INTERNAL-OVERRIDE", "notes": "Coba lepaskan sepihak"},
    )
    assert rel_res.status_code == 403
    actions = manager.get(f"/api/v1/incidents/{inc_id}/actions").json()
    assert any(a["action_type"] == "RELEASE_ATTEMPT_BLOCKED" for a in actions)

    # C2: Direct scenario stock override above clean remaining (0 kg) -> 409 Conflict
    sc2 = planner.post(
        "/api/v1/scenarios",
        json={
            "name": "Bypass Override Test",
            "dataset_version_id": ds_id,
            "nutrition_target_id": str(DEMO_TARGET_ID),
            "servings_per_day": 100,
            "days": 5,
            "budget_idr_per_serving": 18000,
            "max_repeat_per_family": 2,
            "excluded_allergens": [],
            "source_label": "synthetic",
            "production_date": "2026-12-10T08:00:00Z",
        },
    ).json()
    bypass_patch = planner.patch(
        f"/api/v1/scenarios/{sc2['id']}/stock-overrides",
        json={"overrides": [{"ingredient_code": "C_ING3", "stock_raw_g": 100000.0}]},
    )
    assert bypass_patch.status_code == 409

    # C3: Recovery bypass attempts (use_latest_verified_inventory=False OR stock_changes raising C_ING3) -> 409
    assert (
        planner.post(
            "/api/v1/recovery/events",
            json={
                "baseline_menu_review_id": rev_id,
                "use_latest_verified_inventory": False,
            },
        ).status_code
        == 409
    )
    assert (
        planner.post(
            "/api/v1/recovery/events",
            json={
                "baseline_menu_review_id": rev_id,
                "use_latest_verified_inventory": True,
                "stock_changes": [{"ingredient_code": "C_ING3", "new_usable_kg": 50.0}],
            },
        ).status_code
        == 409
    )

    # B: Honest INFEASIBLE result with diagnostics & blocked submit
    rec_inf = planner.post(
        f"/api/v1/incidents/{inc_id}/start-recovery",
        json={"production_date": "2026-12-10T08:00:00Z"},
    )
    assert rec_inf.status_code == 201, rec_inf.text
    ev_inf = rec_inf.json()
    assert ev_inf["status"] == "INFEASIBLE"
    assert ev_inf["min_disruption"]["validation_passed"] is False
    assert ev_inf["min_cost"]["validation_passed"] is False
    assert len(ev_inf["min_cost"]["constraint_diagnostics"]) >= 1
    assert (
        planner.post(
            f"/api/v1/recovery/events/{ev_inf['id']}/submit",
            json={"mode": "MIN_DISRUPTION", "submit_for_review": True},
        ).status_code
        == 409
    )

    # C4: Manager disposes lots -> REJECTED_DISPOSED stays permanently excluded (0 kg usable)
    disp_res = manager.patch(
        f"/api/v1/incidents/{inc_id}/status",
        json={"status": "REJECTED", "notes": "Lot dimusnahkan sesuai SOP.", "dispose_held_lots": True},
    )
    assert disp_res.status_code == 200
    assert all(l["lot_safety_status"] == "REJECTED_DISPOSED" for l in disp_res.json()["affected_lots"])
    cat_after = planner.get(f"/api/v1/inventory?dataset_version_id={ds_id}").json()
    c_ing3 = next(i for i in cat_after["items"] if i["code"] == "C_ING3")
    assert c_ing3["usable_raw_g"] == 0.0
    assert c_ing3["rejected_disposed_raw_g"] > 0.0


def test_d_e_and_f_exposure_rbac_cross_kitchen_images_and_stale_guard():
    """Stress Tests D, E, F: Exposure paths, EXIF image security, RBAC/isolation, and mid-recovery stale guard."""
    qc = make_authenticated_client("petugas_qc")
    planner = make_authenticated_client("perencana_menu")
    manager = make_authenticated_client("kepala_dapur")
    planner_b = make_authenticated_client("perencana_menu_b")

    ds_id, run_id, rev_id = _create_isolated_dataset_with_proteins(
        planner, manager, prod_date="2026-12-15T08:00:00Z"
    )

    # Identify whichever protein ingredient the solved run actually used so BOTH batch & consumption trigger!
    run_detail = planner.get(f"/api/v1/runs/{run_id}").json()
    used_codes = [m["ingredient_code"] for m in run_detail["material_usage"] if m["used_raw_g"] > 0]
    target_prot_code = next(c for c in ("C_ING3", "C_ING4") if c in used_codes)

    # Seed PRODUCTION_CONSUMPTION movement & MealBatchORM for target_prot_code so exposure is flagged!
    assert db_manager.SessionLocal is not None
    with db_manager.SessionLocal() as session:
        from sqlalchemy import select as sa_select

        ing_target = session.execute(
            sa_select(IngredientORM).where(
                IngredientORM.dataset_version_id == ds_id,
                IngredientORM.code == target_prot_code,
            )
        ).scalar_one()
        lot_target = session.execute(
            sa_select(InventoryLotORM).where(
                InventoryLotORM.dataset_version_id == ds_id,
                InventoryLotORM.ingredient_id == ing_target.id,
            )
        ).scalar_one()
        session.add(
            InventoryMovementORM(
                id=str(uuid4()),
                kitchen_id=lot_target.kitchen_id,
                dataset_version_id=ds_id,
                ingredient_id=ing_target.id,
                lot_id=lot_target.id,
                movement_type="PRODUCTION_CONSUMPTION",
                quantity_delta_raw_g=-4000.0,
                original_value=-4.0,
                original_unit="kg",
                idempotency_key=f"EXP-{uuid4()}",
                event_at=datetime.now(timezone.utc),
                quarantined=False,
            )
        )
        session.add(
            MealBatchORM(
                id=str(uuid4()),
                kitchen_id=lot_target.kitchen_id,
                menu_review_id=rev_id,
                run_id=run_id,
                day_index=1,
                meal_type="lunch",
                batch_code=f"BATCH-EXP-{str(uuid4())[:6]}",
                planned_servings=100,
            )
        )
        session.commit()

    # D: Report incident on target_prot_code -> detects POTENTIAL_PRODUCTION_EXPOSURE (consumption + batch)
    inc_res = qc.post(
        "/api/v1/incidents",
        json={
            "title": f"Paparan {target_prot_code} Batch Siap Masak",
            "category": "SUSPECTED_CONTAMINATION",
            "severity": "CRITICAL",
            "notes": "Indikasi kontaminasi terdeteksi setelah sebagian stok diambil dapur.",
            "dataset_version_id": ds_id,
            "ingredient_codes": [target_prot_code],
        },
    )
    assert inc_res.status_code == 201, inc_res.text
    inc = inc_res.json()
    inc_id = inc["id"]
    assert inc["exposure_status"] == "POTENTIAL_PRODUCTION_EXPOSURE"
    assert len(inc["production_exposures"]) >= 2

    # E1: EXIF-stripped evidence photo upload & private authenticated retrieval + Kitchen B 404 isolation
    up_res = qc.post(
        f"/api/v1/incidents/{inc_id}/images",
        files={"file": ("bukti_ayam.jpg", _make_jpeg_with_exif_bytes(), "image/jpeg")},
    )
    assert up_res.status_code == 201, up_res.text
    img_info = up_res.json()
    assert img_info["exif_stripped"] is True

    dl_res = manager.get(img_info["image_url"])
    assert dl_res.status_code == 200
    assert dl_res.headers.get("cache-control") == "private, no-store"
    # Verify EXIF GPS/camera tags are stripped!
    decoded = Image.open(io.BytesIO(dl_res.content))
    assert len(decoded.getexif()) == 0

    # Cross-kitchen B -> 404 on incident, impact, image, operational plans
    assert planner_b.get(f"/api/v1/incidents/{inc_id}").status_code == 404
    assert planner_b.get(f"/api/v1/incidents/{inc_id}/impact").status_code == 404
    assert planner_b.get(img_info["image_url"]).status_code == 404

    # QC_OFFICER cannot call /start-recovery or dispose/close incident (403)
    assert qc.post(f"/api/v1/incidents/{inc_id}/start-recovery", json={}).status_code == 403
    assert (
        qc.patch(
            f"/api/v1/incidents/{inc_id}/status",
            json={"status": "CLOSED", "notes": "Coba tutup oleh QC"},
        ).status_code
        == 403
    )

    # F: Start recovery cleanly -> THEN report a NEW hold on C_ING5 (Spinach) -> prior recovery submission MUST return 409 Stale Snapshot!
    rec_res = planner.post(
        f"/api/v1/incidents/{inc_id}/start-recovery",
        json={"production_date": "2026-12-15T08:00:00Z"},
    )
    assert rec_res.status_code == 201, rec_res.text
    ev_id = rec_res.json()["id"]

    # Hold another ingredient used in the menu (C_ING5) mid-flight -> snapshot changes!
    assert (
        qc.post(
            "/api/v1/incidents",
            json={
                "title": "Insiden Susulan Sayur C_ING5",
                "category": "SPOILAGE",
                "severity": "HIGH",
                "notes": "Sayur bayam tambahan ternyata ikut layu.",
                "dataset_version_id": ds_id,
                "ingredient_codes": ["C_ING5"],
            },
        ).status_code
        == 201
    )

    stale_submit = planner.post(
        f"/api/v1/recovery/events/{ev_id}/submit",
        json={"mode": "MIN_DISRUPTION", "submit_for_review": True},
    )
    assert stale_submit.status_code == 409


def test_h_real_process_restart_persistence_and_integrity(tmp_path: Path):
    """Stress Test H: Incident, held lots, operational plans, and audit logs survive full Python process restart."""
    db_file = tmp_path / "sprint3c_restart.db"
    qc_dir = tmp_path / "sprint3c_qc_imgs"
    qc_dir.mkdir(parents=True, exist_ok=True)
    db_url = f"sqlite:///{db_file.as_posix()}"

    env = dict(os.environ)
    env["GIZIOPTIMA_DATABASE_URL"] = db_url
    env["GIZIOPTIMA_SEED_DEMO_ACCOUNTS"] = "true"
    env["GIZIOPTIMA_DEMO_PASSWORD"] = TEST_DEMO_PASSWORD
    env["GIZIOPTIMA_QC_STORAGE_DIR"] = str(qc_dir)
    env["GIZIOPTIMA_VISION_PROVIDER"] = "deterministic_test"

    script1 = """
import json
from fastapi.testclient import TestClient
from app.main import app
from app.data.incident_fixture import INCIDENT_DEMO_DATASET_ID

with TestClient(app) as qc:
    login = qc.post("/api/v1/auth/login", json={"username": "petugas_qc", "password": %r}).json()
    qc.headers["X-CSRF-Token"] = login["csrf_token"]
    inc = qc.post("/api/v1/incidents", json={
        "title": "Insiden Restart Test",
        "category": "SPOILAGE",
        "severity": "HIGH",
        "notes": "Uji persistensi lintas proses pada LOT-3C-TELUR-A.",
        "dataset_version_id": str(INCIDENT_DEMO_DATASET_ID),
        "affected_lots": [{"lot_code": "LOT-3C-TELUR-A"}],
        "auto_hold_matching_lots": False,
    }).json()
    print(json.dumps({"incident_id": inc["id"]}))
""" % TEST_DEMO_PASSWORD

    p1 = subprocess.run(
        [sys.executable, "-c", script1],
        cwd=str(SERVICE_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    import json

    incident_id = json.loads(p1.stdout.strip().splitlines()[-1])["incident_id"]

    script2 = """
import json
from fastapi.testclient import TestClient
from app.main import app
from app.data.incident_fixture import INCIDENT_DEMO_DATASET_ID

with TestClient(app) as mgr:
    login = mgr.post("/api/v1/auth/login", json={"username": "kepala_dapur", "password": %r}).json()
    mgr.headers["X-CSRF-Token"] = login["csrf_token"]
    inc = mgr.get(f"/api/v1/incidents/%s").json()
    eff = mgr.get(f"/api/v1/operational-plans/effective?dataset_version_id={INCIDENT_DEMO_DATASET_ID}").json()
    print(json.dumps({
        "inc_status": inc["status"],
        "lot_status": inc["affected_lots"][0]["lot_safety_status"],
        "eff_state": eff["state"],
        "hold_inc": eff["held_plan"]["hold_incident_id"],
    }))
""" % (TEST_DEMO_PASSWORD, incident_id)

    p2 = subprocess.run(
        [sys.executable, "-c", script2],
        cwd=str(SERVICE_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    state = json.loads(p2.stdout.strip().splitlines()[-1])
    assert state["inc_status"] == "ON_HOLD"
    assert state["lot_status"] == "ON_HOLD"
    assert state["eff_state"] == "ACTIVE_ON_HOLD"
    assert state["hold_inc"] == incident_id

    eng = create_db_engine(db_url)
    with eng.connect() as conn:
        qc_res = conn.execute(text("PRAGMA quick_check")).scalar()
        fk_res = conn.execute(text("PRAGMA foreign_key_check")).fetchall()
    eng.dispose()
    assert qc_res == "ok"
    assert fk_res == []
