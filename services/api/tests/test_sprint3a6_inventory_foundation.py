from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from app.auth.seed import DEMO_KITCHEN_A_ID, DEMO_KITCHEN_B_ID
from app.data.inventory_quality_fixture import INVENTORY_QUALITY_DATASET_ID
from app.data.synthetic_fixture import DEMO_DATASET_ID
from app.db.models import (
    DatasetVersionORM,
    IngredientORM,
    InventoryLotORM,
    OptimizationRunORM,
    SupplierDeliveryORM,
)
from app.db.session import db_manager, run_alembic_migrations
from app.inventory.mapping import ExternalProductCandidate, evaluate_external_mappings
from app.inventory.service import (
    compute_usable_inventory,
    import_inventory_transactions_csv,
)
from app.inventory.unit_normalizer import normalize_quantity_to_grams
from tests.conftest import make_authenticated_client
from tests.test_sprint2a_persistence_and_api import _make_valid_csv_bundle


def test_source_manifest_and_provenance_endpoints() -> None:
    planner_a = make_authenticated_client("perencana_menu")
    res = planner_a.get("/api/v1/inventory/sources")
    assert res.status_code == 200
    sources = res.json()
    names = {s["source_name"]: s for s in sources}
    assert "CMU MLIP Data Quality — Inventory Management Case Study" in names
    assert names["CMU MLIP Data Quality — Inventory Management Case Study"]["license_verified"] is False
    assert (
        names["CMU MLIP Data Quality — Inventory Management Case Study"]["allowed_use"]
        == "CONCEPTUAL_REFERENCE_ONLY_DO_NOT_COPY_DATA"
    )
    assert "FMCG Batch-Aware Inventory Analytics Pipeline (niil29)" in names
    assert "Badan Pangan Nasional — Publikasi Stok & Rata-rata Harga Pangan (SAPA)" in names


def test_20kg_recorded_12kg_usable_and_optimizer_uses_verified_bound() -> None:
    """Acceptance #2, #4, #5, #6, #12: Hand-verified usable stock vs optimizer binding."""
    planner_a = make_authenticated_client("perencana_menu")
    inv_res = planner_a.get(
        "/api/v1/inventory",
        params={
            "dataset_version_id": str(INVENTORY_QUALITY_DATASET_ID),
            "production_date": "2026-11-20T08:00:00Z",
        },
    )
    assert inv_res.status_code == 200, inv_res.text
    inv = inv_res.json()
    assert inv["uses_batch_ledger"] is True
    by_code = {item["code"]: item for item in inv["items"]}

    # ING007 Daging Ayam Fillet: 20 kg recorded, 3 kg damaged, 5 kg reserved => 12 kg usable
    ayam = by_code["ING007"]
    assert ayam["recorded_raw_g"] == pytest.approx(20000.0)
    assert ayam["damaged_raw_g"] == pytest.approx(3000.0)
    assert ayam["reserved_raw_g"] == pytest.approx(5000.0)
    assert ayam["usable_raw_g"] == pytest.approx(12000.0)
    assert ayam["stock_raw_g"] == pytest.approx(12000.0)
    assert ayam["incoming_raw_g"] == pytest.approx(8000.0)
    assert ayam["delivery_status"] == "PARTIAL"
    assert "20.00 kg" in ayam["availability_explanation"]
    assert "12.00 kg" in ayam["availability_explanation"]

    # ING012 Bayam Segar: 12 kg fresh + 6 kg expired yesterday => 12 kg usable
    bayam = by_code["ING012"]
    assert bayam["recorded_raw_g"] == pytest.approx(18000.0)
    assert bayam["expired_raw_g"] == pytest.approx(6000.0)
    assert bayam["usable_raw_g"] == pytest.approx(12000.0)

    # ING008 Ikan Kembung: 10 kg on-hand + 15 kg DELAYED delivery => 10 kg usable (delayed excluded!)
    ikan = by_code["ING008"]
    assert ikan["recorded_raw_g"] == pytest.approx(10000.0)
    assert ikan["usable_raw_g"] == pytest.approx(10000.0)
    assert ikan["incoming_raw_g"] == pytest.approx(15000.0)
    assert ikan["delivery_status"] == "DELAYED"

    # ING009 Tempe Kedelai: 25 kg book vs 21 kg physical => capped at 21 kg with DISCREPANCY
    tempe = by_code["ING009"]
    assert tempe["recorded_raw_g"] == pytest.approx(25000.0)
    assert tempe["physical_raw_g"] == pytest.approx(21000.0)
    assert tempe["usable_raw_g"] == pytest.approx(21000.0)
    assert tempe["data_quality_status"] == "DISCREPANCY"

    # ING016 Brokoli: 8 kg verified + 5 kg missing-expiry (unverified excluded) => 8 kg usable
    brokoli = by_code["ING016"]
    assert brokoli["recorded_raw_g"] == pytest.approx(13000.0)
    assert brokoli["unverified_raw_g"] == pytest.approx(5000.0)
    assert brokoli["usable_raw_g"] == pytest.approx(8000.0)

    # Run optimization using Inventory Quality dataset at production_date=2026-11-20T08:00:00Z
    sc_res = planner_a.post(
        "/api/v1/scenarios",
        json={
            "name": "Uji Kualitas Stok Batch SPPG-A",
            "dataset_version_id": str(INVENTORY_QUALITY_DATASET_ID),
            "budget_idr_per_serving": 12000,
            "production_date": "2026-11-20T08:00:00Z",
        },
    )
    assert sc_res.status_code == 201, sc_res.text
    sc_id = sc_res.json()["id"]

    opt_res = planner_a.post(f"/api/v1/scenarios/{sc_id}/optimize")
    assert opt_res.status_code == 200, opt_res.text
    run = opt_res.json()
    assert run["validation_passed"] is True
    assert run["solver_status"] in {"OPTIMAL", "FEASIBLE"}
    # Snapshot binds usable stock (12 kg for chicken, 10 kg for ikan kembung, 21 kg tempe)
    assert run["input_snapshot"]["stock_raw_g"]["ING007"] == pytest.approx(12000.0)
    assert run["input_snapshot"]["stock_raw_g"]["ING008"] == pytest.approx(10000.0)
    assert run["input_snapshot"]["stock_raw_g"]["ING009"] == pytest.approx(21000.0)
    assert "inventory_availability" in run["input_snapshot"]


def test_partial_delivery_and_duplicate_delivery_idempotency() -> None:
    """Scenario B & Scenario D + Acceptance #3 & #9: Partial delivery 12/20 kg and duplicate import safety."""
    planner_a = make_authenticated_client("perencana_menu")
    imp_ds = planner_a.post(
        "/api/v1/datasets/import",
        data={"name": "Batch Idempotency & Partial Delivery Test"},
        files=_make_valid_csv_bundle(),
    )
    assert imp_ds.status_code == 201, imp_ds.text
    ds_id = imp_ds.json()["dataset_version_id"]

    # Import baseline (with explicit expiry), a missing-expiry lot (UNVERIFIED), partial delivery (12/20 kg), and unit conflict
    tx_csv = (
        "event_type,ingredient_code,lot_code,quantity,unit,claimed_unit,expected_quantity,expires_at,expiry_known,event_at,idempotency_key,source_document_ref,supplier_name,delivery_status,notes\n"
        "OPENING_BALANCE,C_ING1,LOT-B1,100,kg,,,2027-06-30T23:59:59Z,true,2026-11-20T06:00:00Z,KEY-B1-OP,DOC-01,,,,Initial rice\n"
        "OPENING_BALANCE,C_ING2,LOT-B2-NOEXP,40,kg,,,,false,2026-11-20T06:00:00Z,KEY-B2-NOEXP,DOC-01B,,,,Missing expiry lot must not be treated as fresh\n"
        "SUPPLIER_DELIVERY,C_ING3,LOT-P1,12,kg,,20,2026-11-25T23:59:59Z,true,2026-11-20T06:30:00Z,KEY-P1-DELIV,SJ-P1,Supplier Pangan,PARTIAL,12 of 20 kg received\n"
        "OPENING_BALANCE,C_ING5,LOT-V1,50,kg,,,2026-11-24T23:59:59Z,true,2026-11-20T06:30:00Z,KEY-V1-OP,DOC-02,,,,Veggie stock\n"
        "OPENING_BALANCE,C_ING7,LOT-F1,50,kg,,,2026-11-24T23:59:59Z,true,2026-11-20T06:30:00Z,KEY-F1-OP,DOC-03,,,,Fruit stock\n"
        "GOODS_RECEIPT,C_ING1,LOT-B1,500,g,kg,,,true,2026-11-20T07:00:00Z,KEY-B1-UNITCONFLICT,SJ-ERR,,,,500 g misclaimed as kg\n"
    )
    res1 = planner_a.post(
        "/api/v1/inventory/transactions/import",
        data={
            "dataset_version_id": ds_id,
            "data_classification": "synthetic",
            "dry_run": "false",
        },
        files={"transactions_file": ("tx.csv", tx_csv.encode("utf-8"), "text/csv")},
    )
    assert res1.status_code == 200, res1.text
    j1 = res1.json()
    assert j1["applied_count"] == 5
    assert j1["quarantined_count"] == 1
    assert j1["duplicate_skipped_count"] == 0

    # Repeat the exact same import -> must NOT double stock!
    res2 = planner_a.post(
        "/api/v1/inventory/transactions/import",
        data={
            "dataset_version_id": ds_id,
            "data_classification": "synthetic",
            "dry_run": "false",
        },
        files={"transactions_file": ("tx.csv", tx_csv.encode("utf-8"), "text/csv")},
    )
    assert res2.status_code == 200
    j2 = res2.json()
    assert j2["applied_count"] == 0
    assert j2["duplicate_skipped_count"] == 6

    # Verify inventory reflects exact 12 kg for C_ING3, 100 kg for C_ING1, and UNVERIFIED 40 kg for C_ING2
    inv = planner_a.get("/api/v1/inventory", params={"dataset_version_id": ds_id}).json()
    by_code = {i["code"]: i for i in inv["items"]}
    assert by_code["C_ING3"]["usable_raw_g"] == pytest.approx(12000.0)
    assert by_code["C_ING3"]["incoming_raw_g"] == pytest.approx(8000.0)
    assert by_code["C_ING1"]["usable_raw_g"] == pytest.approx(100000.0)
    assert by_code["C_ING1"]["quarantined_events_count"] == 1
    assert by_code["C_ING2"]["data_quality_status"] == "UNVERIFIED"
    assert by_code["C_ING2"]["unverified_raw_g"] == pytest.approx(40000.0)
    assert by_code["C_ING2"]["usable_raw_g"] == pytest.approx(0.0)


def test_unknown_missing_inventory_blocks_imaginary_stock_in_optimizer() -> None:
    """Scenario G & Acceptance #8: Missing inventory stays UNKNOWN and optimizer refuses to invent stock."""
    planner_a = make_authenticated_client("perencana_menu")
    imp_ds = planner_a.post(
        "/api/v1/datasets/import",
        data={"name": "Unknown Stock Block Test"},
        files=_make_valid_csv_bundle(),
    )
    assert imp_ds.status_code == 201
    ds_id = imp_ds.json()["dataset_version_id"]

    # Import batch receipt only for other ingredients; omit C_ING3 completely AND delete flat snapshot for C_ING3 to simulate missing record
    assert db_manager.SessionLocal is not None
    with db_manager.SessionLocal() as session:
        c3_ing = (
            session.query(IngredientORM)
            .filter(IngredientORM.dataset_version_id == ds_id, IngredientORM.code == "C_ING3")
            .one()
        )
        from app.db.models import DatasetStockSnapshotORM

        session.query(DatasetStockSnapshotORM).filter(
            DatasetStockSnapshotORM.dataset_version_id == ds_id,
            DatasetStockSnapshotORM.ingredient_id == c3_ing.id,
        ).delete()
        session.commit()

    tx_csv = (
        "event_type,ingredient_code,lot_code,quantity,unit,event_at,expires_at,idempotency_key\n"
        "OPENING_BALANCE,C_ING1,LOT-B1,50,kg,2026-11-20T06:00:00Z,2026-12-30T23:59:59Z,UNK-B1\n"
        "OPENING_BALANCE,C_ING2,LOT-B2,50,kg,2026-11-20T06:00:00Z,2026-12-30T23:59:59Z,UNK-B2\n"
        "OPENING_BALANCE,C_ING4,LOT-B4,50,kg,2026-11-20T06:00:00Z,2026-11-25T23:59:59Z,UNK-B4\n"
        "OPENING_BALANCE,C_ING5,LOT-V1,50,kg,2026-11-20T06:00:00Z,2026-11-25T23:59:59Z,UNK-V1\n"
        "OPENING_BALANCE,C_ING6,LOT-V2,50,kg,2026-11-20T06:00:00Z,2026-11-25T23:59:59Z,UNK-V2\n"
        "OPENING_BALANCE,C_ING7,LOT-F1,50,kg,2026-11-20T06:00:00Z,2026-11-25T23:59:59Z,UNK-F1\n"
        "OPENING_BALANCE,C_ING8,LOT-F2,50,kg,2026-11-20T06:00:00Z,2026-11-25T23:59:59Z,UNK-F2\n"
        "OPENING_BALANCE,C_ING9,LOT-S1,20,kg,2026-11-20T06:00:00Z,2026-12-30T23:59:59Z,UNK-S1\n"
    )
    r_tx = planner_a.post(
        "/api/v1/inventory/transactions/import",
        data={"dataset_version_id": ds_id},
        files={"transactions_file": ("tx.csv", tx_csv.encode("utf-8"), "text/csv")},
    )
    assert r_tx.status_code == 200

    inv = planner_a.get("/api/v1/inventory", params={"dataset_version_id": ds_id}).json()
    by_code = {i["code"]: i for i in inv["items"]}
    assert by_code["C_ING3"]["data_quality_status"] == "UNKNOWN"
    assert by_code["C_ING3"]["usable_raw_g"] is None

    sc = planner_a.post(
        "/api/v1/scenarios",
        json={"name": "Missing Stock Scenario", "dataset_version_id": ds_id, "budget_idr_per_serving": 12000},
    ).json()
    opt_res = planner_a.post(f"/api/v1/scenarios/{sc['id']}/optimize")
    assert opt_res.status_code == 422
    assert "Missing stock data" in opt_res.json()["detail"]


def test_unit_conversions_and_mapping_guardrails() -> None:
    """Acceptance #7: Explicit conversions, density gate, item weight gate, ambiguity & mismatch rejection."""
    # Exact decimal conversions
    assert normalize_quantity_to_grams(1.5, "kg").normalized_raw_g == pytest.approx(1500.0)
    assert normalize_quantity_to_grams(500, "g").normalized_raw_g == pytest.approx(500.0)
    assert normalize_quantity_to_grams(2, "liter", density_g_per_ml=0.92).normalized_raw_g == pytest.approx(1840.0)
    assert normalize_quantity_to_grams(10, "butir", unit_weight_g=55.0).normalized_raw_g == pytest.approx(550.0)

    planner_a = make_authenticated_client("perencana_menu")
    res = planner_a.post(
        "/api/v1/inventory/mappings/validate",
        json={
            "dataset_version_id": str(DEMO_DATASET_ID),
            "persist": True,
            "candidates": [
                {
                    "external_product_code": "MAP-CHICK-OK",
                    "external_product_name": "Dada Ayam Fillet Tanpa Tulang",
                    "external_unit": "kg",
                    "canonical_category": "protein",
                    "target_ingredient_code": "ING007",
                    "reviewed_by_human": True,
                },
                {
                    "external_product_code": "MAP-INCOMPAT",
                    "external_product_name": "Fresh Chicken Breast",
                    "external_unit": "kg",
                    "canonical_category": "protein",
                    "target_ingredient_code": "ING008",  # Ikan Kembung -> must reject!
                    "reviewed_by_human": True,
                },
                {
                    "external_product_code": "MAP-AMBIG",
                    "external_product_name": "Beras Super 25kg",
                    "external_unit": "kg",
                },
                {
                    "external_product_code": "MAP-BADUNIT",
                    "external_product_name": "Kentang 10 lbs",
                    "external_unit": "lbs",
                    "target_ingredient_code": "ING003",
                },
            ],
        },
    )
    assert res.status_code == 200, res.text
    report = res.json()
    assert report["mapped_count"] == 1
    assert report["rejected_count"] == 1
    assert report["ambiguous_count"] == 1
    assert report["unit_conversion_errors"] == 1
    by_ext = {e["external_product_code"]: e for e in report["entries"]}
    assert by_ext["MAP-CHICK-OK"]["usable_for_optimizer"] is True
    assert by_ext["MAP-INCOMPAT"]["mapping_status"] == "REJECTED"
    assert by_ext["MAP-AMBIG"]["mapping_status"] == "AMBIGUOUS"
    assert by_ext["MAP-BADUNIT"]["mapping_status"] == "UNIT_ERROR"


def test_cross_kitchen_isolation_and_no_double_subtraction_invariant() -> None:
    """Acceptance #10 & accounting invariant: Expired lot never double-subtracts damaged; kitchen B isolated."""
    planner_b = make_authenticated_client("perencana_menu_b")
    assert (
        planner_b.get(
            "/api/v1/inventory",
            params={"dataset_version_id": str(INVENTORY_QUALITY_DATASET_ID)},
        ).status_code
        == 404
    )
    assert (
        planner_b.get(
            "/api/v1/inventory/availability",
            params={"dataset_version_id": str(INVENTORY_QUALITY_DATASET_ID)},
        ).status_code
        == 404
    )

    # Also test expired lot with damaged_raw_g does not double-subtract from a separate fresh lot
    assert db_manager.SessionLocal is not None
    with db_manager.SessionLocal() as session:
        test_ds_id = uuid4()
        session.add(
            DatasetVersionORM(
                id=str(test_ds_id),
                kitchen_id=str(DEMO_KITCHEN_A_ID),
                name="Double-Count Guard Test",
                source_type="synthetic",
                is_synthetic=True,
                review_status="reviewed",
            )
        )
        session.flush()
        ing_id = str(uuid4())
        session.add(
            IngredientORM(
                id=ing_id,
                dataset_version_id=str(test_ds_id),
                code="TEST_CHICK",
                name="Ayam Uji",
                category="protein",
                edible_fraction=1.0,
                allergens_json=[],
            )
        )
        session.flush()
        # Fresh lot: 15 kg; Expired lot: 10 kg WITH 4 kg damaged inside that same expired lot
        session.add(
            InventoryLotORM(
                id=str(uuid4()),
                kitchen_id=str(DEMO_KITCHEN_A_ID),
                dataset_version_id=str(test_ds_id),
                ingredient_id=ing_id,
                lot_code="LOT-FRESH",
                recorded_raw_g=15000.0,
                damaged_raw_g=0.0,
                expires_at=datetime(2026, 11, 25, tzinfo=timezone.utc),
                expiry_known=True,
                verification_status="VERIFIED",
            )
        )
        session.add(
            InventoryLotORM(
                id=str(uuid4()),
                kitchen_id=str(DEMO_KITCHEN_A_ID),
                dataset_version_id=str(test_ds_id),
                ingredient_id=ing_id,
                lot_code="LOT-EXPIRED",
                recorded_raw_g=10000.0,
                damaged_raw_g=4000.0,
                expires_at=datetime(2026, 11, 18, tzinfo=timezone.utc),
                expiry_known=True,
                verification_status="VERIFIED",
            )
        )
        # Unrelated Kitchen B lot for the same dataset_version_id must never count for Kitchen A!
        session.add(
            InventoryLotORM(
                id=str(uuid4()),
                kitchen_id=str(DEMO_KITCHEN_B_ID),
                dataset_version_id=str(test_ds_id),
                ingredient_id=ing_id,
                lot_code="LOT-KITCHEN-B",
                recorded_raw_g=99000.0,
                damaged_raw_g=0.0,
                expires_at=datetime(2026, 11, 25, tzinfo=timezone.utc),
                expiry_known=True,
                verification_status="VERIFIED",
            )
        )
        session.commit()

        summary = compute_usable_inventory(
            session,
            kitchen_id=DEMO_KITCHEN_A_ID,
            dataset_version_id=test_ds_id,
            production_date=datetime(2026, 11, 20, 8, 0, tzinfo=timezone.utc),
        )
        assert len(summary.items) == 1
        item = summary.items[0]
        assert item.recorded_raw_g == pytest.approx(25000.0)
        assert item.expired_raw_g == pytest.approx(10000.0)
        assert item.damaged_raw_g == pytest.approx(0.0)
        assert item.usable_raw_g == pytest.approx(15000.0)


def test_phase2_market_reference_separation_and_phase3_authorization_and_approved_alert() -> None:
    """Phase 2 + Phase 3 + Acceptance #11, #14, #15."""
    planner_a = make_authenticated_client("perencana_menu")
    manager_a = make_authenticated_client("kepala_dapur")

    # 1. Phase 2: Manual Indonesian Market Price Reference import stays separate from supplier prices
    mkt_csv = (
        "commodity_code,commodity_name,canonical_ingredient_code,region,observed_date,price_value,unit,published_at,quality_status,notes\n"
        "BAP-AYAM,Daging Ayam Ras (Referensi Pasar),ING007,DKI Jakarta,2026-11-18,39000,IDR/kg,2026-11-18,REFERENCE_ONLY,Bapanas manual CSV\n"
    )
    mkt_res = planner_a.post(
        "/api/v1/market-references/import",
        data={"source_name": "Bapanas Panel Harga (Impor Manual Terotorisasi)"},
        files={"market_file": ("bapanas.csv", mkt_csv.encode("utf-8"), "text/csv")},
    )
    assert mkt_res.status_code == 201, mkt_res.text
    assert mkt_res.json()["price_provenance"] == "OFFICIAL_MARKET_REFERENCE"

    # Check DEMO dataset supplier/synthetic price for ING007 was NOT overwritten (still 44000)!
    demo_inv = planner_a.get("/api/v1/inventory", params={"dataset_version_id": str(DEMO_DATASET_ID)}).json()
    demo_by_code = {i["code"]: i for i in demo_inv["items"]}
    assert demo_by_code["ING007"]["original_price_value"] == pytest.approx(44000.0)
    assert demo_by_code["ING007"]["price_provenance"] == "SYNTHETIC_EXAMPLE"
    assert demo_by_code["ING007"]["market_references"][0]["price_value"] == pytest.approx(39000.0)

    # 2. Phase 3: Importing pilot_real without authorization_confirmed=true must fail 403
    pilot_csv = (
        "event_type,ingredient_code,lot_code,quantity,unit,event_at,expires_at,idempotency_key\n"
        "OPENING_BALANCE,ING007,LOT-PILOT-AYAM,15,kg,2026-11-20T06:00:00Z,2026-11-25T23:59:59Z,PILOT-AYAM-01\n"
    )
    denied = planner_a.post(
        "/api/v1/inventory/transactions/import",
        data={
            "dataset_version_id": str(INVENTORY_QUALITY_DATASET_ID),
            "data_classification": "pilot_real",
            "authorization_confirmed": "false",
        },
        files={"transactions_file": ("pilot.csv", pilot_csv.encode("utf-8"), "text/csv")},
    )
    assert denied.status_code == 403

    # 3. Acceptance #15: Approved plan retains snapshot & emits review-needed alert when stock drops
    sc = planner_a.post(
        "/api/v1/scenarios",
        json={
            "name": "Rencana Disetujui Sebelum Stok Turun",
            "dataset_version_id": str(INVENTORY_QUALITY_DATASET_ID),
            "budget_idr_per_serving": 12000,
            "production_date": "2026-11-20T08:00:00Z",
        },
    ).json()
    run = planner_a.post(f"/api/v1/scenarios/{sc['id']}/optimize").json()
    assert run["validation_passed"] is True
    original_sha = run["input_sha256"]

    rev = planner_a.post(
        "/api/v1/menu-reviews",
        json={"run_id": run["run_id"], "title": "Rencana Tetap Terjaga Snapshotnya"},
    ).json()
    planner_a.post(f"/api/v1/menu-reviews/{rev['id']}/submit")
    approved = manager_a.post(
        f"/api/v1/menu-reviews/{rev['id']}/review",
        json={"decision": "APPROVED", "reviewer_notes": "Disetujui awal"},
    )
    assert approved.status_code == 200

    # Reduce Beras Putih (ING001) lot drastically via damage/disposal so approved plan needs review
    drop_csv = (
        "event_type,ingredient_code,lot_code,quantity,unit,event_at,idempotency_key\n"
        "DAMAGE,ING001,LOT-ING001-BASE,44.5,kg,2026-11-20T09:00:00Z,DROP-BERAS-ALERT-01\n"
    )
    drop_res = planner_a.post(
        "/api/v1/inventory/transactions/import",
        data={"dataset_version_id": str(INVENTORY_QUALITY_DATASET_ID)},
        files={"transactions_file": ("drop.csv", drop_csv.encode("utf-8"), "text/csv")},
    )
    assert drop_res.status_code == 200

    # Historical approved review and run snapshot MUST NOT be overwritten or silently unapproved
    stored_rev = manager_a.get(f"/api/v1/menu-reviews/{rev['id']}").json()
    assert stored_rev["status"] == "APPROVED"
    stored_run = manager_a.get(f"/api/v1/runs/{run['run_id']}").json()
    assert stored_run["input_sha256"] == original_sha

    # Dashboard & Inventory explicitly surface alert requiring review
    mgr_sum = manager_a.get("/api/v1/dashboard/manager-summary").json()
    alert_ids = {a["menu_review_id"] for a in mgr_sum["approved_plan_inventory_alerts"]}
    assert rev["id"] in alert_ids

    # CSV template download works cleanly
    tpl = planner_a.get("/api/v1/inventory/templates/market-references")
    assert tpl.status_code == 200
    assert "commodity_code" in tpl.text
