from __future__ import annotations

import io
import os
from uuid import uuid4

from PIL import Image, PngImagePlugin
from sqlalchemy import select

from app.data.incident_fixture import INCIDENT_DEMO_DATASET_ID
from app.db.models import UserORM
from app.db.session import db_manager
from tests.conftest import make_authenticated_client


def _make_jpeg_with_exif() -> bytes:
    img = Image.new("RGB", (64, 64), color=(190, 80, 50))
    exif = Image.Exif()
    exif[0x010F] = "DemoCameraGPS"
    exif[0x0132] = "2026:11:21 09:00:00"
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif)
    return buf.getvalue()


def _make_clean_png() -> bytes:
    img = Image.new("RGB", (64, 64), color=(40, 140, 90))
    meta = PngImagePlugin.PngInfo()
    meta.add_text("SensitiveTag", "strip-me")
    buf = io.BytesIO()
    img.save(buf, format="PNG", pnginfo=meta)
    return buf.getvalue()


def _minimal_clean_pdf() -> bytes:
    return (
        b"%PDF-1.4\n"
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
        b"2 0 obj << /Type /Pages /Kids [] /Count 0 >> endobj\n"
        b"trailer << /Root 1 0 R >>\n"
        b"%%EOF\n"
    )


def _user_id_by_username(username: str) -> str:
    assert db_manager.SessionLocal is not None
    with db_manager.SessionLocal() as session:
        u = session.execute(select(UserORM).where(UserORM.username == username)).scalar_one()
        return u.id


def _create_isolated_ops_dataset(planner, qc) -> str:
    ing_csv = (
        "code,name,category,edible_fraction,energy_kcal_100g,protein_g_100g,fat_g_100g,carb_g_100g,fiber_g_100g,allergens,source_type,source_ref,review_status\n"
        "P_ING1,Beras Putih,staple,1.0,360,7.0,0.8,78.0,1.2,,synthetic,DEMO_ONLY,reviewed\n"
        "P_ING2,Jagung Pipil,staple,1.0,350,9.0,4.0,72.0,7.0,,synthetic,DEMO_ONLY,reviewed\n"
        "P_ING3,Dada Ayam,protein,1.0,165,24.0,7.0,0.0,0.0,,synthetic,DEMO_ONLY,reviewed\n"
        "P_ING4,Tempe Kedelai,protein,1.0,193,19.0,10.8,9.4,5.0,soy,synthetic,DEMO_ONLY,reviewed\n"
        "P_ING5,Bayam Hijau,vegetable,0.8,23,2.9,0.4,3.6,2.2,,synthetic,DEMO_ONLY,reviewed\n"
        "P_ING6,Wortel Segar,vegetable,0.9,41,0.9,0.2,9.6,2.8,,synthetic,DEMO_ONLY,reviewed\n"
        "P_ING7,Pisang Ambon,fruit,0.75,99,1.1,0.2,25.8,2.6,,synthetic,DEMO_ONLY,reviewed\n"
        "P_ING8,Pepaya Matang,fruit,0.75,43,0.5,0.3,10.8,1.7,,synthetic,DEMO_ONLY,reviewed\n"
        "P_ING9,Minyak Goreng,seasoning,1.0,884,0.0,100.0,0.0,0.0,,synthetic,DEMO_ONLY,reviewed\n"
    )
    prices_csv = (
        "ingredient_code,price_value,unit,density_g_per_ml,region,observed_at,source_type\n"
        "P_ING1,15000,IDR/kg,,SIMULASI,2026-11-20,synthetic\n"
        "P_ING2,13000,IDR/kg,,SIMULASI,2026-11-20,synthetic\n"
        "P_ING3,40000,IDR/kg,,SIMULASI,2026-11-20,synthetic\n"
        "P_ING4,17000,IDR/kg,,SIMULASI,2026-11-20,synthetic\n"
        "P_ING5,12000,IDR/kg,,SIMULASI,2026-11-20,synthetic\n"
        "P_ING6,14000,IDR/kg,,SIMULASI,2026-11-20,synthetic\n"
        "P_ING7,15000,IDR/kg,,SIMULASI,2026-11-20,synthetic\n"
        "P_ING8,11000,IDR/kg,,SIMULASI,2026-11-20,synthetic\n"
        "P_ING9,18000,IDR/liter,0.92,SIMULASI,2026-11-20,synthetic\n"
    )
    stock_csv = (
        "ingredient_code,stock_raw_g\n"
        "P_ING1,50000\n"
        "P_ING2,50000\n"
        "P_ING3,50000\n"
        "P_ING4,50000\n"
        "P_ING5,50000\n"
        "P_ING6,50000\n"
        "P_ING7,50000\n"
        "P_ING8,50000\n"
        "P_ING9,20000\n"
    )
    recipes_csv = (
        "recipe_code,recipe_name,slot,family,ingredient_code,raw_g_per_serving,retention_factor,allergen_tags,review_status\n"
        "PR1,Nasi Putih,staple,rice,P_ING1,90,0.95,,reviewed\n"
        "PR2,Nasi Jagung,staple,corn,P_ING2,90,0.95,,reviewed\n"
        "PR3,Ayam Panggang,protein,poultry,P_ING3,80,0.92,,reviewed\n"
        "PR3,Ayam Panggang,protein,poultry,P_ING9,8,1.0,,reviewed\n"
        "PR4,Tempe Bacem,protein,soy,P_ING4,90,0.95,soy,reviewed\n"
        "PR5,Sayur Bayam,vegetable,bayam,P_ING5,90,0.85,,reviewed\n"
        "PR6,Tumis Wortel,vegetable,wortel,P_ING6,90,0.90,,reviewed\n"
        "PR7,Pisang,fruit,banana,P_ING7,110,1.0,,reviewed\n"
        "PR8,Pepaya,fruit,papaya,P_ING8,120,1.0,,reviewed\n"
    )
    imp = planner.post(
        "/api/v1/datasets/import",
        data={"name": f"Post3C Ops Isolation {str(uuid4())[:6]}"},
        files={
            "ingredients_file": ("ingredients.csv", ing_csv.encode("utf-8"), "text/csv"),
            "prices_file": ("prices.csv", prices_csv.encode("utf-8"), "text/csv"),
            "stock_file": ("stock.csv", stock_csv.encode("utf-8"), "text/csv"),
            "recipes_file": ("recipes.csv", recipes_csv.encode("utf-8"), "text/csv"),
        },
    )
    assert imp.status_code == 201, imp.text
    ds_id = imp.json()["dataset_version_id"]

    tx_csv = (
        "event_type,ingredient_code,lot_code,quantity,unit,event_at,expires_at,idempotency_key\n"
        "OPENING_BALANCE,P_ING1,LOT-P-ING1,50,kg,2026-11-20T06:00:00Z,2027-06-30,ISO-P1\n"
        "OPENING_BALANCE,P_ING3,LOT-P-ING3,12,kg,2026-11-20T06:00:00Z,2027-06-30,ISO-P3\n"
        "OPENING_BALANCE,P_ING5,LOT-P-ING5,20,kg,2026-11-20T06:00:00Z,2027-06-30,ISO-P5\n"
    )
    tx_res = qc.post(
        "/api/v1/inventory/transactions/import",
        data={"dataset_version_id": ds_id, "data_classification": "synthetic", "dry_run": "false"},
        files={"transactions_file": ("tx.csv", tx_csv.encode("utf-8"), "text/csv")},
    )
    assert tx_res.status_code == 200, tx_res.text
    return ds_id


def test_single_stock_custodian_lifecycle_revocation_and_rbac() -> None:
    """Invariants 1-4: Single authoritative stock writer per kitchen + immediate live revocation across roles."""
    manager = make_authenticated_client("kepala_dapur")
    planner = make_authenticated_client("perencana_menu")
    qc1 = make_authenticated_client("petugas_qc")
    qc2 = make_authenticated_client("petugas_qc_2")
    qc_b = make_authenticated_client("petugas_qc_b")

    ds_id = _create_isolated_ops_dataset(planner, qc1)
    qc1_id = _user_id_by_username("petugas_qc")
    qc2_id = _user_id_by_username("petugas_qc_2")
    planner_id = _user_id_by_username("perencana_menu")
    qc_b_id = _user_id_by_username("petugas_qc_b")

    try:
        # 1. Initial seed has petugas_qc as active custodian for Kitchen A
        me1 = qc1.get("/api/v1/auth/me").json()
        me2 = qc2.get("/api/v1/auth/me").json()
        assert me1["is_active_stock_custodian"] is True
        assert me2["is_active_stock_custodian"] is False
        assert me2["stock_custodian"]["custodian_username"] == "petugas_qc"

        status_res = manager.get("/api/v1/stock-custodian")
        assert status_res.status_code == 200
        assert len(status_res.json()["eligible_qc_candidates"]) >= 2

        # 2. Cannot assign non-QC (Planner) or cross-kitchen user (qc_b) -> 422
        assert (
            manager.post(
                "/api/v1/stock-custodian/assign",
                json={"custodian_user_id": planner_id},
            ).status_code
            == 422
        )
        assert (
            manager.post(
                "/api/v1/stock-custodian/assign",
                json={"custodian_user_id": qc_b_id},
            ).status_code
            == 422
        )
        # Non-manager cannot assign/revoke -> 403
        assert (
            qc1.post(
                "/api/v1/stock-custodian/assign",
                json={"custodian_user_id": qc2_id},
            ).status_code
            == 403
        )
        assert planner.post("/api/v1/stock-custodian/revoke", json={}).status_code == 403

        # 3. Secondary QC (not active custodian) is blocked (403) from ALL stock & incident & procurement writes
        adj_payload = {
            "dataset_version_id": ds_id,
            "ingredient_code": "P_ING1",
            "lot_code": "LOT-CUST-TEST-01",
            "adjustment_type": "PURCHASE_RECEIPT",
            "quantity": 2.0,
            "unit": "kg",
            "expires_at": "2027-06-30",
        }
        assert qc2.post("/api/v1/inventory/adjustments", json=adj_payload).status_code == 403
        assert planner.post("/api/v1/inventory/adjustments", json=adj_payload).status_code == 403
        assert manager.post("/api/v1/inventory/adjustments", json=adj_payload).status_code == 403
        assert (
            qc2.post(
                "/api/v1/incidents",
                json={
                    "dataset_version_id": ds_id,
                    "ingredient_codes": ["P_ING1"],
                    "category": "SPOILAGE",
                },
            ).status_code
            == 403
        )
        assert (
            qc2.post(
                "/api/v1/procurement/documents",
                json={"dataset_version_id": ds_id, "supplier_name": "Toko Gagal", "purchase_date": "2026-11-21"},
            ).status_code
            == 403
        )
        assert (
            qc2.post(
                "/api/v1/procurement/receipts",
                json={
                    "dataset_version_id": ds_id,
                    "ingredient_code": "P_ING1",
                    "received_quantity": 1.0,
                    "unit": "kg",
                },
            ).status_code
            == 403
        )

        # 4. Manager revokes active custodian -> qc1 IMMEDIATELY sees false on /auth/me and gets 403 on write
        rev_res = manager.post("/api/v1/stock-custodian/revoke", json={"notes": "Serah terima shift"})
        assert rev_res.status_code == 200
        assert rev_res.json()["active_assignment"] is None
        assert qc1.get("/api/v1/auth/me").json()["is_active_stock_custodian"] is False
        assert qc1.post("/api/v1/inventory/adjustments", json=adj_payload).status_code == 403

        # 5. Manager assigns qc2 -> qc2 IMMEDIATELY gains write authority while qc1 stays 403
        assign_res = manager.post(
            "/api/v1/stock-custodian/assign",
            json={"custodian_user_id": qc2_id, "notes": "Penugasan shift 2"},
        )
        assert assign_res.status_code == 200, assign_res.text
        assert assign_res.json()["active_assignment"]["custodian_username"] == "petugas_qc_2"
        assert qc2.get("/api/v1/auth/me").json()["is_active_stock_custodian"] is True
        assert qc1.get("/api/v1/auth/me").json()["is_active_stock_custodian"] is False

        ok_adj = qc2.post("/api/v1/inventory/adjustments", json=adj_payload)
        assert ok_adj.status_code == 200, ok_adj.text
        assert qc1.post("/api/v1/inventory/adjustments", json=adj_payload).status_code == 403
        assert qc_b.get(f"/api/v1/inventory?dataset_version_id={ds_id}").status_code == 404
    finally:
        manager.post(
            "/api/v1/stock-custodian/assign",
            json={"custodian_user_id": qc1_id, "notes": "Restore default seed custodian"},
        )


def test_fast_2field_incident_and_two_step_disposal_and_hold_guard() -> None:
    """Invariants 5-9: 2-field incident creation, non-bypassable hold, 2-step disposal auth vs execution."""
    manager = make_authenticated_client("kepala_dapur")
    planner = make_authenticated_client("perencana_menu")
    qc = make_authenticated_client("petugas_qc")
    ds_id = _create_isolated_ops_dataset(planner, qc)

    # Fast 2-field incident WITHOUT title/notes -> auto-generated Indonesian title & notes
    fast_res = qc.post(
        "/api/v1/incidents",
        json={
            "dataset_version_id": ds_id,
            "ingredient_codes": ["P_ING5"],
            "category": "SPOILAGE",
        },
    )
    assert fast_res.status_code == 201, fast_res.text
    inc = fast_res.json()
    inc_id = inc["id"]
    assert inc["status"] == "ON_HOLD"
    assert "Tahan Keamanan:" in inc["title"]
    assert inc["notes"]
    assert inc["disposal_authorized"] is False

    # Manual stock adjustment on an ON_HOLD lot MUST be rejected 409
    assert (
        qc.post(
            "/api/v1/inventory/adjustments",
            json={
                "dataset_version_id": ds_id,
                "ingredient_code": "P_ING5",
                "lot_code": inc["affected_lots"][0]["lot_code"],
                "adjustment_type": "STOCK_CORRECTION",
                "quantity": 50.0,
                "unit": "kg",
            },
        ).status_code
        == 409
    )

    # QC CANNOT execute disposal before Kitchen Manager authorizes -> 409
    assert qc.post(f"/api/v1/incidents/{inc_id}/record-disposal", json={}).status_code == 409

    # Planner cannot authorize disposal -> 403
    assert (
        planner.patch(
            f"/api/v1/incidents/{inc_id}/status",
            json={"status": "REJECTED", "dispose_held_lots": True},
        ).status_code
        == 403
    )

    # Manager authorizes disposal WITHOUT mutating lot status yet (remains ON_HOLD until QC executes!)
    auth_res = manager.patch(
        f"/api/v1/incidents/{inc_id}/status",
        json={"status": "REJECTED", "dispose_held_lots": True, "notes": "Otorisasi musnahkan lot rusak"},
    )
    assert auth_res.status_code == 200, auth_res.text
    assert auth_res.json()["disposal_authorized"] is True
    assert all(l["lot_safety_status"] == "ON_HOLD" for l in auth_res.json()["affected_lots"])

    # Manager cannot mutate ledger via /record-disposal -> 403
    assert manager.post(f"/api/v1/incidents/{inc_id}/record-disposal", json={}).status_code == 403

    # Release-hold remains strictly 403
    assert (
        manager.post(
            f"/api/v1/incidents/{inc_id}/release-hold",
            json={"authority_reference": "SELF-UNLOCK"},
        ).status_code
        == 403
    )

    # Active Stock Custodian QC executes disposal -> REJECTED_DISPOSED + DISPOSAL ledger entry
    exec_res = qc.post(
        f"/api/v1/incidents/{inc_id}/record-disposal",
        json={"notes": "Selesai dimusnahkan di TPS organik."},
    )
    assert exec_res.status_code == 200, exec_res.text
    body = exec_res.json()
    assert body["disposal_executed_at"] is not None
    assert all(l["lot_safety_status"] == "REJECTED_DISPOSED" for l in body["affected_lots"])

    # Verify inventory detail exposes DISPOSAL movement & keeps usable == 0 & strips QC pricing
    det_qc = qc.get(f"/api/v1/inventory/P_ING5/detail?dataset_version_id={ds_id}")
    assert det_qc.status_code == 200, det_qc.text
    det_j = det_qc.json()
    assert det_j["ingredient"]["usable_raw_g"] == 0.0
    assert det_j["ingredient"]["rejected_disposed_raw_g"] > 0.0
    assert det_j["ingredient"]["price_idr_per_g"] is None
    assert det_j["ingredient"]["market_references"] == []
    assert any(m["movement_type"] == "DISPOSAL" for m in det_j["recent_movements"])


def test_inventory_jakarta_dates_real_supplier_and_fefo_coverage() -> None:
    """Invariants 10-12: Jakarta date parsing, unrecorded supplier stays None, deterministic FEFO forecast."""
    planner = make_authenticated_client("perencana_menu")
    qc = make_authenticated_client("petugas_qc")

    # Date-only YYYY-MM-DD production_date parses in Asia/Jakarta (08:00 WIB -> 01:00 UTC)
    inv_res = planner.get(
        f"/api/v1/inventory?dataset_version_id={INCIDENT_DEMO_DATASET_ID}&production_date=2026-11-23"
    )
    assert inv_res.status_code == 200, inv_res.text
    inv_j = inv_res.json()
    assert inv_j["production_date"].startswith("2026-11-23T01:00:00")

    ing007 = next(i for i in inv_j["items"] if i["code"] == "ING007")
    assert ing007["coverage"] is not None
    assert ing007["coverage"]["coverage_status"] in {
        "SUFFICIENT",
        "LOW_COVERAGE",
        "EXPIRES_BEFORE_USE",
        "UNVERIFIED_OR_HELD",
    }
    assert "estimasi" in ing007["coverage"]["disclaimer"].lower()

    # Lots without recorded supplier_name return None (never fabricated from source_ref)
    ds_id = _create_isolated_ops_dataset(planner, qc)
    det_res = qc.get(f"/api/v1/inventory/P_ING1/detail?dataset_version_id={ds_id}&production_date=2026-11-20")
    assert det_res.status_code == 200
    assert det_res.json()["ingredient"]["price_idr_per_g"] is None
    assert det_res.json()["ingredient"]["latest_supplier_name"] is None
    assert det_res.json()["ingredient"]["lots"][0]["supplier_name"] is None


def test_procurement_evidence_security_and_goods_receipt_ledger() -> None:
    """Invariants 13-17: EXIF-stripped image, malicious PDF blocked, cross-kitchen 404, goods receipt safety rules."""
    manager = make_authenticated_client("kepala_dapur")
    planner = make_authenticated_client("perencana_menu")
    qc = make_authenticated_client("petugas_qc")
    qc_b = make_authenticated_client("petugas_qc_b")

    ds_id = _create_isolated_ops_dataset(planner, qc)
    kitchen_a_runs = planner.get("/api/v1/runs").json()
    assert len(kitchen_a_runs) >= 1
    valid_run_id = kitchen_a_runs[0]["run_id"]

    # Nonexistent / cross-kitchen linked_run_id must return 404 (not 500 AttributeError)
    missing_run_res = qc.post(
        "/api/v1/procurement/documents",
        json={
            "dataset_version_id": ds_id,
            "linked_run_id": str(uuid4()),
            "supplier_name": "CV Tidak Valid",
        },
    )
    assert missing_run_res.status_code == 404

    # 1. QC Custodian creates manual purchase record with linked_run_id (blank prices stay None)
    doc_res = qc.post(
        "/api/v1/procurement/documents",
        json={
            "dataset_version_id": ds_id,
            "linked_run_id": valid_run_id,
            "supplier_name": "CV Sumber Pangan Nusantara",
            "invoice_number": "INV-2026-1121-01",
            "purchase_date": "2026-11-21",
            "total_amount_idr": 640000.0,
            "lines": [
                {
                    "ingredient_code": "P_ING3",
                    "item_name": "Dada Ayam Segar",
                    "quantity": 16.0,
                    "unit": "kg",
                }
            ],
        },
    )
    assert doc_res.status_code == 201, doc_res.text
    doc = doc_res.json()
    doc_id = doc["id"]
    assert doc["evidence_status"] == "NO_EVIDENCE"
    assert doc["lines"][0]["unit_price_idr"] is None

    # Cannot mark VERIFIED_MATCH before evidence file is uploaded -> 409
    assert (
        manager.patch(
            f"/api/v1/procurement/documents/{doc_id}/review",
            json={"decision": "VERIFIED_MATCH"},
        ).status_code
        == 409
    )

    # 2. Malicious PDF with /JavaScript must be rejected 422
    bad_pdf = b"%PDF-1.4\n1 0 obj << /OpenAction << /S /JavaScript /JS (app.alert(1)) >> >> endobj\n%%EOF\n"
    assert (
        qc.post(
            f"/api/v1/procurement/documents/{doc_id}/evidence",
            files={"file": ("evil.pdf", bad_pdf, "application/pdf")},
        ).status_code
        == 422
    )

    # 3. Upload EXIF-laden JPEG -> sanitized, EXIF stripped, RECEIPT_UPLOADED, private download headers
    up_res = qc.post(
        f"/api/v1/procurement/documents/{doc_id}/evidence",
        files={"file": ("../../etc/nota_ayam.jpg", _make_jpeg_with_exif(), "image/jpeg")},
    )
    assert up_res.status_code == 200, up_res.text
    up_doc = up_res.json()
    assert up_doc["evidence_status"] == "RECEIPT_UPLOADED"
    assert up_doc["exif_stripped"] is True
    assert "/" not in up_doc["document_original_filename"]

    dl = manager.get(up_doc["evidence_url"])
    assert dl.status_code == 200
    assert dl.headers["cache-control"] == "private, no-store"
    assert dl.headers["x-content-type-options"] == "nosniff"
    with Image.open(io.BytesIO(dl.content)) as img:
        assert len(img.getexif()) == 0

    # Cross-kitchen 404 isolation
    assert qc_b.get(f"/api/v1/procurement/documents/{doc_id}").status_code == 404
    assert qc_b.get(up_doc["evidence_url"]).status_code == 404

    # 4. Valid clean PDF upload works with strict CSP header on download
    pdf_up = qc.post(
        f"/api/v1/procurement/documents/{doc_id}/evidence",
        files={"file": ("faktur_bersih.pdf", _minimal_clean_pdf(), "application/pdf")},
    )
    assert pdf_up.status_code == 200
    pdf_dl = manager.get(pdf_up.json()["evidence_url"])
    assert pdf_dl.status_code == 200
    assert pdf_dl.headers["content-security-policy"] == "default-src 'none'; frame-ancestors 'none'"

    # 5. Goods receipt with missing expiry stays UNVERIFIED (0 kg usable!)
    unexp_res = qc.post(
        "/api/v1/procurement/receipts",
        json={
            "dataset_version_id": ds_id,
            "purchase_document_id": doc_id,
            "ingredient_code": "P_ING3",
            "lot_code": "LOT-GR-NOEXP-01",
            "received_quantity": 5.0,
            "unit": "kg",
            "condition_status": "GOOD",
        },
    )
    assert unexp_res.status_code == 201, unexp_res.text
    assert unexp_res.json()["lot_verification_status"] == "UNVERIFIED"
    assert unexp_res.json()["usable_added_raw_g"] == 0.0

    # 6. Goods receipt DAMAGED -> 0 kg usable
    dmg_res = qc.post(
        "/api/v1/procurement/receipts",
        json={
            "dataset_version_id": ds_id,
            "purchase_document_id": doc_id,
            "ingredient_code": "P_ING3",
            "lot_code": "LOT-GR-DMG-01",
            "received_quantity": 3.0,
            "unit": "kg",
            "expiry_date": "2027-06-30",
            "condition_status": "DAMAGED",
        },
    )
    assert dmg_res.status_code == 201
    assert dmg_res.json()["usable_added_raw_g"] == 0.0

    # 7. Goods receipt GOOD + valid expiry -> VERIFIED, +8 kg usable reflected in /inventory with real supplier!
    good_res = qc.post(
        "/api/v1/procurement/receipts",
        json={
            "dataset_version_id": ds_id,
            "purchase_document_id": doc_id,
            "ingredient_code": "P_ING3",
            "lot_code": "LOT-GR-GOOD-01",
            "received_quantity": 8.0,
            "unit": "kg",
            "expiry_date": "2027-06-30",
            "condition_status": "GOOD",
            "notes": "Kondisi dingin baik, suhu 4C.",
        },
    )
    assert good_res.status_code == 201, good_res.text
    assert good_res.json()["lot_verification_status"] == "VERIFIED"
    assert good_res.json()["usable_added_raw_g"] == 8000.0
    assert good_res.json()["supplier_name"] == "CV Sumber Pangan Nusantara"

    assert planner.get(f"/api/v1/procurement/documents/{doc_id}").json()["evidence_status"] == "GOODS_RECEIVED"
    rev_res = manager.patch(
        f"/api/v1/procurement/documents/{doc_id}/review",
        json={"decision": "VERIFIED_MATCH", "notes": "Faktur dan kuantitas cocok."},
    )
    assert rev_res.status_code == 200
    assert rev_res.json()["evidence_status"] == "VERIFIED_MATCH"

    det_after = qc.get(f"/api/v1/inventory/P_ING3/detail?dataset_version_id={ds_id}").json()
    good_lot = next(l for l in det_after["ingredient"]["lots"] if l["lot_code"] == "LOT-GR-GOOD-01")
    assert good_lot["supplier_name"] == "CV Sumber Pangan Nusantara"
    assert good_lot["usable_raw_g"] == 8000.0


def test_pemeriksaan_sajian_works_when_ai_disabled_and_dashboards() -> None:
    """Invariants 18-20: AI-optional manual Pemeriksaan Sajian + Planner/QC/Manager dashboards."""
    manager = make_authenticated_client("kepala_dapur")
    planner = make_authenticated_client("perencana_menu")
    qc = make_authenticated_client("petugas_qc")

    pl_sum = planner.get("/api/v1/dashboard/planner-summary")
    assert pl_sum.status_code == 200, pl_sum.text
    assert "open_incidents_requiring_recovery" in pl_sum.json()

    sc = planner.post(
        "/api/v1/scenarios",
        json={
            "name": "Sajian Tanpa AI Test",
            "days": 5,
            "servings_per_day": 100,
            "budget_idr_per_serving": 12000,
        },
    ).json()
    run = planner.post(f"/api/v1/scenarios/{sc['id']}/optimize").json()
    rev = planner.post(
        "/api/v1/menu-reviews",
        json={"run_id": run["run_id"], "title": "Menu Uji Pemeriksaan Sajian Manual"},
    ).json()
    planner.post(f"/api/v1/menu-reviews/{rev['id']}/submit")
    manager.post(
        f"/api/v1/menu-reviews/{rev['id']}/review",
        json={"decision": "APPROVED", "reviewer_notes": "Siap uji pemeriksaan sajian"},
    )

    prev_provider = os.environ.get("GIZIOPTIMA_VISION_PROVIDER")
    os.environ["GIZIOPTIMA_VISION_PROVIDER"] = "disabled"
    try:
        insp_res = qc.post(
            "/api/v1/qc/inspections",
            json={"run_id": run["run_id"], "menu_review_id": rev["id"], "day_index": 2},
        )
        assert insp_res.status_code == 201, insp_res.text
        insp = insp_res.json()
        insp_id = insp["id"]

        up = qc.post(
            f"/api/v1/qc/inspections/{insp_id}/images",
            files={"file": ("nampan_hari2.png", _make_clean_png(), "image/png")},
        )
        assert up.status_code == 201, up.text

        assert qc.post(f"/api/v1/qc/inspections/{insp_id}/analyze").status_code == 503

        patch_obs = qc.patch(
            f"/api/v1/qc/inspections/{insp_id}/observations",
            json={
                "corrected_components": [
                    {
                        "slot": slot["slot"],
                        "confirmed_status": "visible",
                        "observed_food_name": slot["recipe_name"],
                    }
                    for slot in insp["expected_menu"]
                ],
                "notes": "Diperiksa manual tanpa bantuan AI — seluruh komponen lengkap.",
                "request_retake": False,
            },
        )
        assert patch_obs.status_code == 200, patch_obs.text
        assert patch_obs.json()["status"] == "HUMAN_REVIEWED"

        sub_res = qc.post(
            f"/api/v1/qc/inspections/{insp_id}/submit",
            json={"qc_notes": "Siap dibagikan (verifikasi manual QC)."},
        )
        assert sub_res.status_code == 200, sub_res.text
        assert sub_res.json()["status"] == "SUBMITTED"

        mgr_rev = manager.post(
            f"/api/v1/qc/inspections/{insp_id}/review",
            json={
                "outcome": "ACCEPTED_FOR_RECORD",
                "manager_notes": "Foto sajian manual disetujui.",
            },
        )
        assert mgr_rev.status_code == 200, mgr_rev.text
        assert mgr_rev.json()["status"] == "REVIEWED"
    finally:
        if prev_provider is None:
            os.environ.pop("GIZIOPTIMA_VISION_PROVIDER", None)
        else:
            os.environ["GIZIOPTIMA_VISION_PROVIDER"] = prev_provider
