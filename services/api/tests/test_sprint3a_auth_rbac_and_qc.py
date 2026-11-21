from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import List

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.db.session import SERVICE_ROOT, db_manager
from app.main import app
from app.vision.provider import (
    VisionOutputValidationError,
    VisionProvider,
    VisionProviderError,
    parse_and_validate_vision_json,
)
from app.vision.schemas import ExpectedMenuSlot
from app.vision.service import analyze_inspection_with_ai
from tests.conftest import TEST_DEMO_PASSWORD, make_authenticated_client


def _make_jpeg_bytes_with_exif(width: int = 128, height: int = 128) -> bytes:
    img = Image.new("RGB", (width, height), color=(210, 180, 120))
    exif = Image.Exif()
    exif[0x010F] = "CameraVendorSecret"
    exif[0x0110] = "DeviceModel123"
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif.tobytes())
    return buf.getvalue()


def _make_png_bytes(width: int = 96, height: int = 96) -> bytes:
    img = Image.new("RGB", (width, height), color=(120, 190, 140))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# =====================================================================
# 1. Authentication, HttpOnly Cookie, CSRF, and Logout
# =====================================================================


def test_unauthenticated_protected_endpoints_return_401() -> None:
    anon = TestClient(app)
    assert anon.get("/api/v1/health").status_code == 200

    for method, path in [
        ("GET", "/api/v1/auth/me"),
        ("GET", "/api/v1/datasets"),
        ("GET", "/api/v1/inventory"),
        ("GET", "/api/v1/scenarios"),
        ("GET", "/api/v1/runs"),
        ("GET", "/api/v1/menu-reviews"),
        ("GET", "/api/v1/qc/inspections"),
        ("GET", "/api/v1/dashboard/manager-summary"),
        ("GET", "/api/v1/dashboard/qc-summary"),
    ]:
        res = anon.request(method, path)
        assert res.status_code == 401, f"{method} {path} returned {res.status_code}"


def test_login_csrf_enforcement_and_logout_revocation() -> None:
    c = TestClient(app)

    # Wrong password -> 401
    bad = c.post("/api/v1/auth/login", json={"username": "perencana_menu", "password": "wrong-password"})
    assert bad.status_code == 401

    # Valid login sets HttpOnly session cookie + returns csrf_token
    ok = c.post(
        "/api/v1/auth/login",
        json={"username": "perencana_menu", "password": TEST_DEMO_PASSWORD},
    )
    assert ok.status_code == 200
    body = ok.json()
    assert body["active_role"] == "MENU_PLANNER"
    assert body["csrf_token"]
    assert "gizioptima_session" in c.cookies

    # Mutating cookie-authenticated request WITHOUT X-CSRF-Token -> 403
    no_csrf = c.post("/api/v1/scenarios", json={"name": "No CSRF Attempt"})
    assert no_csrf.status_code == 403

    # Mutating request WITH valid X-CSRF-Token -> 201
    c.headers.update({"X-CSRF-Token": body["csrf_token"]})
    with_csrf = c.post("/api/v1/scenarios", json={"name": "With CSRF OK"})
    assert with_csrf.status_code == 201

    # Logout revokes server-side session immediately
    out = c.post("/api/v1/auth/logout")
    assert out.status_code == 200
    assert c.get("/api/v1/auth/me").status_code == 401


# =====================================================================
# 2. Backend-Enforced RBAC Permission Matrix & Cross-Kitchen Isolation
# =====================================================================


def test_role_permission_matrix_and_cross_kitchen_isolation() -> None:
    planner_a = make_authenticated_client("perencana_menu")
    manager_a = make_authenticated_client("kepala_dapur")
    qc_a = make_authenticated_client("petugas_qc")
    planner_b = make_authenticated_client("perencana_menu_b")
    manager_b = make_authenticated_client("kepala_dapur_b")
    qc_b = make_authenticated_client("petugas_qc_b")

    # Planner A creates and optimizes a valid baseline in Kitchen A
    sc_a = planner_a.post(
        "/api/v1/scenarios",
        json={"name": "Kitchen A Plan", "days": 5, "servings_per_day": 100, "budget_idr_per_serving": 12000},
    )
    assert sc_a.status_code == 201
    sc_a_id = sc_a.json()["id"]

    run_a = planner_a.post(f"/api/v1/scenarios/{sc_a_id}/optimize")
    assert run_a.status_code == 200
    run_a_id = run_a.json()["run_id"]
    assert run_a.json()["validation_passed"] is True

    # Manager A cannot create scenarios, optimize, or create QC inspections (403)
    assert manager_a.post("/api/v1/scenarios", json={"name": "Blocked"}).status_code == 403
    assert manager_a.post(f"/api/v1/scenarios/{sc_a_id}/optimize").status_code == 403
    assert manager_a.post("/api/v1/menu-reviews", json={"run_id": run_a_id}).status_code == 403
    assert (
        manager_a.post("/api/v1/qc/inspections", json={"run_id": run_a_id, "day_index": 1}).status_code
        == 403
    )
    assert manager_a.get("/api/v1/dashboard/manager-summary").status_code == 200

    # Planner A cannot access manager/QC dashboards or create QC inspections (403)
    assert planner_a.get("/api/v1/dashboard/manager-summary").status_code == 403
    assert planner_a.get("/api/v1/dashboard/qc-summary").status_code == 403
    assert (
        planner_a.post("/api/v1/qc/inspections", json={"run_id": run_a_id, "day_index": 1}).status_code
        == 403
    )

    # QC Officer A can inspect non-financial inventory availability (pricing & market references stripped!)
    qc_inv = qc_a.get("/api/v1/inventory")
    assert qc_inv.status_code == 200
    assert all(
        item.get("price_idr_per_g") is None
        and item.get("original_price_value") is None
        and item.get("price_provenance") is None
        and item.get("market_references") == []
        for item in qc_inv.json()["items"]
    )
    # QC Officer A cannot view financial shopping list, export CSV, comparisons, or optimize (403)
    assert qc_a.get(f"/api/v1/runs/{run_a_id}/shopping-list").status_code == 403
    assert qc_a.get(f"/api/v1/runs/{run_a_id}/export.csv").status_code == 403
    assert qc_a.post("/api/v1/scenarios", json={"name": "QC Blocked"}).status_code == 403
    assert qc_a.get("/api/v1/dashboard/manager-summary").status_code == 403
    assert qc_a.get("/api/v1/dashboard/qc-summary").status_code == 200

    # Cross-kitchen isolation: Kitchen B users CANNOT see or touch Kitchen A records!
    assert planner_b.get(f"/api/v1/scenarios/{sc_a_id}").status_code == 404
    assert planner_b.get(f"/api/v1/runs/{run_a_id}").status_code == 404
    assert all(s["id"] != sc_a_id for s in planner_b.get("/api/v1/scenarios").json())
    assert all(r["run_id"] != run_a_id for r in planner_b.get("/api/v1/runs").json())
    assert (
        qc_b.post("/api/v1/qc/inspections", json={"run_id": run_a_id, "day_index": 1}).status_code
        == 404
    )
    assert manager_b.get(f"/api/v1/runs/{run_a_id}").status_code == 404


# =====================================================================
# 3. Menu Operational Review State Transitions
# =====================================================================


def test_menu_review_workflow_and_infeasible_guard() -> None:
    planner = make_authenticated_client("perencana_menu")
    manager = make_authenticated_client("kepala_dapur")
    manager_b = make_authenticated_client("kepala_dapur_b")

    # Infeasible run MUST NOT be allowed to create menu review (409)
    sc_inf = planner.post(
        "/api/v1/scenarios", json={"name": "Inf Plan", "budget_idr_per_serving": 3500}
    ).json()
    run_inf = planner.post(f"/api/v1/scenarios/{sc_inf['id']}/optimize").json()
    assert run_inf["validation_passed"] is False
    assert planner.post("/api/v1/menu-reviews", json={"run_id": run_inf["run_id"]}).status_code == 409

    # Valid run -> DRAFT -> SUBMITTED -> REVISION_REQUIRED -> new v2 -> APPROVED
    sc = planner.post(
        "/api/v1/scenarios", json={"name": "Review Flow Plan", "budget_idr_per_serving": 12000}
    ).json()
    run = planner.post(f"/api/v1/scenarios/{sc['id']}/optimize").json()

    v1 = planner.post(
        "/api/v1/menu-reviews",
        json={"run_id": run["run_id"], "title": "Rencana Minggu 1", "planner_notes": "Draft awal"},
    )
    assert v1.status_code == 201
    v1_id = v1.json()["id"]
    assert v1.json()["status"] == "DRAFT"
    assert v1.json()["version_number"] == 1

    # Manager cannot review DRAFT before submission (409)
    assert (
        manager.post(
            f"/api/v1/menu-reviews/{v1_id}/review",
            json={"decision": "APPROVED"},
        ).status_code
        == 409
    )

    # Planner submits v1
    sub = planner.post(f"/api/v1/menu-reviews/{v1_id}/submit", json={"planner_notes": "Siap ditinjau"})
    assert sub.status_code == 200
    assert sub.json()["status"] == "SUBMITTED"

    # Planner cannot self-approve (403)
    assert (
        planner.post(
            f"/api/v1/menu-reviews/{v1_id}/review", json={"decision": "APPROVED"}
        ).status_code
        == 403
    )

    # Kitchen B Manager cannot review Kitchen A submission (404)
    assert (
        manager_b.post(
            f"/api/v1/menu-reviews/{v1_id}/review", json={"decision": "APPROVED"}
        ).status_code
        == 404
    )

    # Revision request without notes -> 422
    assert (
        manager.post(
            f"/api/v1/menu-reviews/{v1_id}/review",
            json={"decision": "REVISION_REQUIRED", "reviewer_notes": ""},
        ).status_code
        == 422
    )

    # Revision request with notes -> REVISION_REQUIRED
    rev = manager.post(
        f"/api/v1/menu-reviews/{v1_id}/review",
        json={"decision": "REVISION_REQUIRED", "reviewer_notes": "Mohon ganti menu buah hari 3."},
    )
    assert rev.status_code == 200
    assert rev.json()["status"] == "REVISION_REQUIRED"

    # Historical v1 cannot be re-submitted (409); create v2 instead
    assert planner.post(f"/api/v1/menu-reviews/{v1_id}/submit").status_code == 409
    v2 = planner.post("/api/v1/menu-reviews", json={"run_id": run["run_id"], "title": "Rencana Minggu 1 Revisi"}).json()
    assert v2["version_number"] == 2
    planner.post(f"/api/v1/menu-reviews/{v2['id']}/submit")
    approved = manager.post(
        f"/api/v1/menu-reviews/{v2['id']}/review",
        json={"decision": "APPROVED", "reviewer_notes": "Disetujui operasional untuk minggu 1."},
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "APPROVED"
    assert "bukan validasi gizi profesional" in approved.json()["approval_scope_notice"].lower()


# =====================================================================
# 4. Image Security, AI Provider Failures, Human-in-the-Loop & QC Flow
# =====================================================================


def test_qc_image_security_ai_errors_human_review_and_manager_approval(monkeypatch) -> None:
    planner = make_authenticated_client("perencana_menu")
    manager = make_authenticated_client("kepala_dapur")
    qc = make_authenticated_client("petugas_qc")
    qc_b = make_authenticated_client("petugas_qc_b")

    sc = planner.post(
        "/api/v1/scenarios", json={"name": "QC Target Menu", "budget_idr_per_serving": 12000}
    ).json()
    run = planner.post(f"/api/v1/scenarios/{sc['id']}/optimize").json()
    mr = planner.post("/api/v1/menu-reviews", json={"run_id": run["run_id"]}).json()
    planner.post(f"/api/v1/menu-reviews/{mr['id']}/submit")
    manager.post(f"/api/v1/menu-reviews/{mr['id']}/review", json={"decision": "APPROVED"})

    # QC creates inspection
    insp_res = qc.post(
        "/api/v1/qc/inspections",
        json={"run_id": run["run_id"], "menu_review_id": mr["id"], "day_index": 1, "meal_batch_code": "BATCH-H1-01"},
    )
    assert insp_res.status_code == 201
    insp = insp_res.json()
    insp_id = insp["id"]
    assert insp["status"] == "CREATED"
    assert len(insp["expected_menu"]) == 4

    # Security 1: Reject spoofed extension with non-image magic bytes (422)
    spoof = qc.post(
        f"/api/v1/qc/inspections/{insp_id}/images",
        files={"file": ("../../evil.jpg", b"<html>not an image</html>", "image/jpeg")},
    )
    assert spoof.status_code == 422

    # Security 2: Reject oversized file > 5MB (422)
    oversized = qc.post(
        f"/api/v1/qc/inspections/{insp_id}/images",
        files={"file": ("huge.jpg", b"\xff\xd8\xff" + b"\x00" * (5 * 1024 * 1024 + 10), "image/jpeg")},
    )
    assert oversized.status_code == 422

    # Security 3: Upload valid JPEG with EXIF & traversal filename -> sanitized, EXIF stripped!
    jpeg_with_exif = _make_jpeg_bytes_with_exif()
    up = qc.post(
        f"/api/v1/qc/inspections/{insp_id}/images",
        files={"file": ("../../tray_photo.jpg", jpeg_with_exif, "image/jpeg")},
    )
    assert up.status_code == 201
    img_info = up.json()
    assert img_info["exif_stripped"] is True
    assert ".." not in img_info["original_filename_sanitized"]

    # Authorized kitchen user can fetch image & stored bytes have NO EXIF tags
    fetched = qc.get(img_info["image_url"])
    assert fetched.status_code == 200
    assert fetched.headers["content-type"] == "image/jpeg"
    with Image.open(io.BytesIO(fetched.content)) as saved_img:
        assert len(saved_img.getexif()) == 0

    # Unauthenticated & Cross-kitchen image access DENIED!
    assert TestClient(app).get(img_info["image_url"]).status_code == 401
    assert qc_b.get(img_info["image_url"]).status_code == 404

    # Untrusted invalid model JSON validation test
    with pytest.raises(VisionOutputValidationError):
        parse_and_validate_vision_json("NOT JSON AT ALL")
    with pytest.raises(VisionOutputValidationError):
        parse_and_validate_vision_json('{"observed_components": [{"category": "invalid_cat"}]}')

    # Unconfigured provider -> honest 503
    monkeypatch.setenv("GIZIOPTIMA_VISION_PROVIDER", "")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GIZIOPTIMA_ALLOW_TEST_VISION_PROVIDER", raising=False)
    assert qc.post(f"/api/v1/qc/inspections/{insp_id}/analyze").status_code == 503

    # Failing provider transport -> 502
    class _BrokenProvider(VisionProvider):
        provider_name = "broken"
        provider_mode = "live"
        is_live_ai = True
        model_identifier = "broken-1"

        def analyze_food_tray(self, *, image_bytes: bytes, mime_type: str, expected_menu: List[ExpectedMenuSlot]):
            raise VisionProviderError("Simulated timeout")

    monkeypatch.setenv("GIZIOPTIMA_VISION_PROVIDER", "deterministic_test")
    assert db_manager.SessionLocal is not None
    with db_manager.SessionLocal() as s:
        from app.auth.dependencies import AuthContext
        from app.auth.schemas import RoleEnum
        from uuid import UUID

        me = qc.get("/api/v1/auth/me").json()
        fake_auth = AuthContext(
            session_id=UUID("00000000-0000-0000-0000-000000000001"),
            user_id=UUID(me["user_id"]),
            username=me["username"],
            email=me["email"],
            full_name=me["full_name"],
            kitchen_id=UUID(me["active_kitchen_id"]),
            kitchen_code=me["active_kitchen_code"],
            kitchen_name=me["active_kitchen_name"],
            role=RoleEnum.QC_OFFICER,
            csrf_token="x",
            memberships=[],
        )
        with pytest.raises(Exception) as exc_info:
            analyze_inspection_with_ai(s, fake_auth, UUID(insp_id), provider_override=_BrokenProvider())
        assert getattr(exc_info.value, "status_code", None) == 502

    # Run deterministic test provider analysis -> AI_ANALYZED (explicitly non-live)
    analyzed = qc.post(f"/api/v1/qc/inspections/{insp_id}/analyze")
    assert analyzed.status_code == 200
    a_body = analyzed.json()
    assert a_body["status"] == "AI_ANALYZED"
    assert len(a_body["ai_observations"]) == 1
    obs = a_body["ai_observations"][0]
    assert obs["provider_mode"] == "test_deterministic"
    assert obs["is_live_ai"] is False
    # Findings cover visible, uncertain, and missing expected components
    statuses = {f["status"] for f in obs["comparison_findings"]}
    assert "visual_match" in statuses
    assert "uncertain" in statuses
    assert "missing_expected" in statuses

    # Cannot submit before human review (409)
    assert qc.post(f"/api/v1/qc/inspections/{insp_id}/submit").status_code == 409

    # Human-in-the-loop review & correction (must preserve original AI observation untouched!)
    original_obs_snapshot = json.dumps(obs["validated_output"], sort_keys=True)
    patched = qc.patch(
        f"/api/v1/qc/inspections/{insp_id}/observations",
        json={
            "corrected_components": [
                {"slot": "staple", "confirmed_status": "visible", "observed_food_name": "Nasi Putih"},
                {"slot": "protein", "confirmed_status": "visible", "observed_food_name": "Lauk Protein Sesuai"},
                {"slot": "vegetable", "confirmed_status": "visible", "observed_food_name": "Sayur Bayam Bening", "officer_note": "Dikonfirmasi langsung"},
                {"slot": "fruit", "confirmed_status": "not_visible", "observed_food_name": "Buah belum diletakkan di nampan", "officer_note": "Sedang disiapkan terpisah"},
            ],
            "notes": "Buah masih di kotak terpisah saat foto diambil.",
            "request_retake": False,
        },
    )
    assert patched.status_code == 200
    p_body = patched.json()
    assert p_body["status"] == "HUMAN_REVIEWED"
    assert len(p_body["human_reviews"]) == 1
    # Original AI observation MUST remain strictly immutable!
    assert json.dumps(p_body["ai_observations"][0]["validated_output"], sort_keys=True) == original_obs_snapshot

    # Submit inspection -> SUBMITTED
    submitted = qc.post(f"/api/v1/qc/inspections/{insp_id}/submit")
    assert submitted.status_code == 200
    assert submitted.json()["status"] == "SUBMITTED"

    # QC cannot self-approve (403); Manager reviews -> REVIEWED (ACCEPTED_FOR_RECORD)
    assert (
        qc.post(
            f"/api/v1/qc/inspections/{insp_id}/review",
            json={"outcome": "ACCEPTED_FOR_RECORD"},
        ).status_code
        == 403
    )
    reviewed = manager.post(
        f"/api/v1/qc/inspections/{insp_id}/review",
        json={
            "outcome": "ACCEPTED_FOR_RECORD",
            "manager_notes": "Dicatat untuk arsip operasional dapur; pastikan buah lengkap sebelum pembagian.",
        },
    )
    assert reviewed.status_code == 200
    r_body = reviewed.json()
    assert r_body["status"] == "REVIEWED"
    assert r_body["review_outcome"] == "ACCEPTED_FOR_RECORD"

    # Audit history contains full traceable events
    audits = manager.get("/api/v1/auth/audit-events", params={"limit": 50}).json()
    actions = {ev["action"] for ev in audits}
    assert "menu_review.approved" in actions
    assert "qc_inspection.created" in actions
    assert "qc_inspection.image_uploaded" in actions
    assert "qc_inspection.ai_analyzed" in actions
    assert "qc_inspection.human_reviewed" in actions
    assert "qc_inspection.submitted" in actions
    assert "qc_inspection.reviewed_accepted_for_record" in actions


# =====================================================================
# 5. Cross-Process Restart Persistence for QC & Audit Trail
# =====================================================================


def test_qc_and_audit_persist_across_process_restart(tmp_path: Path) -> None:
    db_file = tmp_path / "sprint3a_restart.db"
    qc_dir = tmp_path / "qc_imgs"
    env = dict(os.environ)
    env["GIZIOPTIMA_DATABASE_URL"] = f"sqlite:///{db_file.as_posix()}"
    env["GIZIOPTIMA_QC_STORAGE_DIR"] = str(qc_dir)
    env["GIZIOPTIMA_VISION_PROVIDER"] = "deterministic_test"
    env["GIZIOPTIMA_SEED_DEMO_ACCOUNTS"] = "true"
    env["GIZIOPTIMA_DEMO_PASSWORD"] = TEST_DEMO_PASSWORD

    p1_script = f"""
import io, json
from PIL import Image
from fastapi.testclient import TestClient
from app.main import app

def login(username):
    c = TestClient(app)
    r = c.post("/api/v1/auth/login", json={{"username": username, "password": "{TEST_DEMO_PASSWORD}"}}).json()
    c.headers.update({{"X-CSRF-Token": r["csrf_token"]}})
    return c

planner = login("perencana_menu")
manager = login("kepala_dapur")
qc = login("petugas_qc")

sc = planner.post("/api/v1/scenarios", json={{"name": "Persist QC", "budget_idr_per_serving": 12000}}).json()
run = planner.post(f"/api/v1/scenarios/{{sc['id']}}/optimize").json()
mr = planner.post("/api/v1/menu-reviews", json={{"run_id": run["run_id"]}}).json()
planner.post(f"/api/v1/menu-reviews/{{mr['id']}}/submit")
manager.post(f"/api/v1/menu-reviews/{{mr['id']}}/review", json={{"decision": "APPROVED"}})

insp = qc.post("/api/v1/qc/inspections", json={{"run_id": run["run_id"], "menu_review_id": mr["id"], "day_index": 1}}).json()
buf = io.BytesIO()
Image.new("RGB", (64, 64), (100, 150, 100)).save(buf, format="PNG")
qc.post(f"/api/v1/qc/inspections/{{insp['id']}}/images", files={{"file": ("sample.png", buf.getvalue(), "image/png")}})
qc.post(f"/api/v1/qc/inspections/{{insp['id']}}/analyze")
qc.patch(f"/api/v1/qc/inspections/{{insp['id']}}/observations", json={{
    "corrected_components": [{{"slot": "staple", "confirmed_status": "visible", "observed_food_name": "Nasi Putih"}}],
    "notes": "Terverifikasi"
}})
qc.post(f"/api/v1/qc/inspections/{{insp['id']}}/submit")
manager.post(f"/api/v1/qc/inspections/{{insp['id']}}/review", json={{"outcome": "ACCEPTED_FOR_RECORD"}})
print(json.dumps({{"insp_id": insp["id"], "mr_id": mr["id"]}}))
"""
    p1 = subprocess.run(
        [sys.executable, "-c", p1_script],
        cwd=str(SERVICE_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    ids = json.loads(p1.stdout.strip().splitlines()[-1])

    p2_script = f"""
import json
from fastapi.testclient import TestClient
from app.main import app

c = TestClient(app)
r = c.post("/api/v1/auth/login", json={{"username": "kepala_dapur", "password": "{TEST_DEMO_PASSWORD}"}}).json()
c.headers.update({{"X-CSRF-Token": r["csrf_token"]}})
insp = c.get("/api/v1/qc/inspections/{ids['insp_id']}").json()
mr = c.get("/api/v1/menu-reviews/{ids['mr_id']}").json()
audits = c.get("/api/v1/auth/audit-events", params={{"limit": 30}}).json()
print(json.dumps({{
    "insp_status": insp["status"],
    "insp_outcome": insp["review_outcome"],
    "ai_obs_count": len(insp["ai_observations"]),
    "human_rev_count": len(insp["human_reviews"]),
    "mr_status": mr["status"],
    "audit_count": len(audits),
}}))
"""
    p2 = subprocess.run(
        [sys.executable, "-c", p2_script],
        cwd=str(SERVICE_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    res = json.loads(p2.stdout.strip().splitlines()[-1])
    assert res["insp_status"] == "REVIEWED"
    assert res["insp_outcome"] == "ACCEPTED_FOR_RECORD"
    assert res["ai_obs_count"] == 1
    assert res["human_rev_count"] == 1
    assert res["mr_status"] == "APPROVED"
    assert res["audit_count"] >= 7
