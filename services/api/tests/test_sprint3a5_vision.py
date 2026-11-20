from __future__ import annotations

import base64
import io
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from PIL import Image, PngImagePlugin

from app.api.upload_limit import MAX_QC_UPLOAD_BODY
from app.db.models import QCImageORM
from app.db.session import db_manager
from app.vision import provider as providers
from app.vision.comparator import compare_expected_menu_with_observations
from app.vision.image_security import qc_storage_path
from app.vision.schemas import ComparisonStatusEnum, ExpectedMenuSlot
from tests.conftest import make_authenticated_client


def test_openai_adapter_sends_photo_with_strict_schema_and_bounded_retry(monkeypatch) -> None:
    image = b"sanitized-photo-fixture"
    output = {
        "observed_components": [{
            "category": "protein",
            "possible_food_name": "Telur rebus",
            "observation_status": "visible",
            "explanation": "Tampak bulat dan putih.",
        }],
        "uncertain_components": [],
        "limitations": [],
    }
    plan = [ExpectedMenuSlot(slot="protein", recipe_id="chicken-01", recipe_name="Ayam Panggang")]
    calls = []

    def transport(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert request.url == "https://api.openai.com/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer fixture-key"
        assert payload["store"] is False
        assert "Ayam Panggang" not in request.content.decode()
        schema = payload["response_format"]["json_schema"]
        assert schema["strict"] and not schema["schema"]["additionalProperties"]
        sent = payload["messages"][1]["content"][1]["image_url"]["url"]
        assert sent == "data:image/png;base64," + base64.b64encode(image).decode()
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"choices": [{
            "finish_reason": "stop",
            "message": {"content": json.dumps(output)},
        }]})

    real_client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: real_client(transport=httpx.MockTransport(transport), **kwargs))
    result = providers.OpenAIVisionProvider("fixture-key").analyze_food_tray(
        image_bytes=image, mime_type="image/png", expected_menu=plan
    )
    assert len(calls) == 2
    assert result.validated_output.limitations == [providers.BASELINE_LIMITATION]
    assert compare_expected_menu_with_observations(plan, result.validated_output)[0].status == (
        ComparisonStatusEnum.NEEDS_MANUAL_CHECK
    )


def test_provider_rejects_incomplete_outputs_and_has_no_implicit_fallback(monkeypatch) -> None:
    invalid_responses = [
        "{}",
        "[]",
        '{"observed_components":[],"uncertain_components":[],"limitations":[],"safe":true}',
        None,
    ]
    for response in invalid_responses:
        with pytest.raises(providers.VisionOutputValidationError):
            providers.parse_and_validate_vision_json(response)

    monkeypatch.setenv("GIZIOPTIMA_VISION_PROVIDER", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "unrelated-fixture-key")
    monkeypatch.setenv("GIZIOPTIMA_ALLOW_TEST_VISION_PROVIDER", "true")
    with pytest.raises(providers.VisionProviderUnavailableError):
        providers.resolve_vision_provider()
    monkeypatch.setenv("GIZIOPTIMA_VISION_PROVIDER", "deterministic_test")
    monkeypatch.setenv("GIZIOPTIMA_ENV", "production")
    assert providers.get_vision_provider_status()["configured"] is False


def test_provider_does_not_retry_read_timeout_or_expose_upstream_error(monkeypatch) -> None:
    real_client = httpx.Client
    requests = []

    def transport(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        raise httpx.ReadTimeout("private-fixture-details", request=request)

    monkeypatch.setattr(httpx, "Client", lambda **kwargs: real_client(transport=httpx.MockTransport(transport), **kwargs))
    with pytest.raises(providers.VisionProviderError, match="melebihi batas waktu") as error:
        providers.OpenAIVisionProvider("fixture-key").analyze_food_tray(
            image_bytes=b"fixture", mime_type="image/png", expected_menu=[]
        )
    assert len(requests) == 1
    assert "private-fixture-details" not in str(error.value)


def test_qc_current_photo_review_followup_and_expiry(isolated_sqlite_test_db: Path) -> None:
    planner = make_authenticated_client("perencana_menu")
    manager = make_authenticated_client("kepala_dapur")
    qc = make_authenticated_client("petugas_qc")
    other_qc = make_authenticated_client("petugas_qc_b")
    scenario = planner.post(
        "/api/v1/scenarios",
        json={"name": "Sprint 3A.5 QC evidence", "budget_idr_per_serving": 12000, "days": 2},
    ).json()
    run = planner.post(f"/api/v1/scenarios/{scenario['id']}/optimize").json()
    request = {"run_id": run["run_id"], "day_index": 1, "meal_batch_code": f"QC-{uuid4()}"}
    url = "/api/v1/qc/inspections"
    assert qc.post(url, json=request).status_code == 409
    review = planner.post("/api/v1/menu-reviews", json={"run_id": run["run_id"]}).json()
    assert planner.post(f"/api/v1/menu-reviews/{review['id']}/submit").status_code == 200
    assert qc.post(url, json=request).status_code == 409
    assert manager.post(f"/api/v1/menu-reviews/{review['id']}/review", json={"decision": "APPROVED"}).status_code == 200
    created = qc.post(url, json=request)
    assert created.status_code == 201, created.text
    inspection = created.json()
    assert inspection["menu_review_id"] == review["id"]
    assert qc.post(url, json={**request, "day_index": 2}).status_code == 409
    detail = f"{url}/{inspection['id']}"

    payload = io.BytesIO()
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("PrivateMarker", "Original source metadata")
    Image.new("RGB", (64, 64), "brown").save(payload, "PNG", pnginfo=metadata)

    def upload() -> dict:
        res = qc.post(f"{detail}/images", files={"file": ("photo.png", payload.getvalue(), "image/png")})
        assert res.status_code == 201, res.text
        return res.json()

    oversized = b"x" * (MAX_QC_UPLOAD_BODY + 1)
    assert qc.post(
        f"{detail}/images", files={"file": ("large.png", oversized, "image/png")}
    ).status_code == 413
    boundary = "test-upload-boundary"
    multipart_header = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="large.png"\r\n'
        "Content-Type: image/png\r\n\r\n"
    ).encode()
    assert qc.post(
        f"{detail}/images",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        content=iter((multipart_header, oversized, f"\r\n--{boundary}--\r\n".encode())),
    ).status_code == 413
    image = upload()
    read = qc.get(image["image_url"])
    assert read.headers["cache-control"] == "private, no-store"
    with Image.open(io.BytesIO(read.content)) as stored:
        assert "PrivateMarker" not in stored.info

    analyze = f"{detail}/analyze"
    first = qc.post(analyze, params={"image_id": image["id"]})
    assert first.status_code == 200, first.text
    first_id = first.json()["ai_observations"][-1]["id"]
    changes = {
        "ai_observation_id": first_id,
        "corrected_components": [
            {"slot": slot["slot"], "confirmed_status": "visible", "observed_food_name": slot["recipe_name"]}
            for slot in inspection["expected_menu"]
        ],
    }
    observations = f"{detail}/observations"
    assert qc.patch(observations, json=changes).status_code == 200
    latest = upload()
    assert qc.get(detail).json()["status"] == "CREATED"
    assert qc.post(f"{detail}/submit").status_code == 409
    assert qc.post(analyze, params={"image_id": image["id"]}).status_code == 409
    assert qc.patch(observations, json=changes).status_code == 409
    result = qc.post(analyze, params={"image_id": latest["id"]})
    assert result.status_code == 200
    assert qc.patch(observations, json=changes).status_code == 409
    changes["ai_observation_id"] = result.json()["ai_observations"][-1]["id"]
    assert qc.patch(observations, json=changes).status_code == 200
    assert qc.post(f"{detail}/submit").status_code == 200

    retake = manager.post(f"{detail}/review", json={
        "outcome": "RETAKE_REQUIRED", "manager_notes": "Ambil foto dengan pencahayaan lebih baik."
    })
    assert retake.status_code == 200
    next_inspection = {**request, "previous_inspection_id": inspection["id"]}
    assert other_qc.post(url, json=next_inspection).status_code == 404
    followup = qc.post(url, json=next_inspection)
    assert followup.status_code == 201, followup.text
    audit_events = manager.get("/api/v1/auth/audit-events", params={"limit": 25}).json()
    followup_event = next(event for event in audit_events if event["entity_id"] == followup.json()["id"])
    assert followup_event["metadata"]["previous_inspection_id"] == inspection["id"]

    assert db_manager.SessionLocal is not None
    with db_manager.SessionLocal() as session:
        record = session.get(QCImageORM, image["id"])
        assert record
        record.created_at = datetime.now(timezone.utc) - timedelta(days=31)
        path = qc_storage_path(record.storage_key)
        session.commit()
    assert qc.get(image["image_url"]).status_code == 410
    assert other_qc.get(image["image_url"]).status_code == 404
    assert path.is_file()

    purge = [sys.executable, "scripts/purge_expired_qc_images.py"]
    service_root = Path(__file__).resolve().parents[1]
    env = dict(os.environ, GIZIOPTIMA_DATABASE_URL=f"sqlite:///{isolated_sqlite_test_db.as_posix()}")
    dry = subprocess.run(purge, cwd=service_root, env=env, check=True, capture_output=True, text=True)
    assert "eligible=1 deleted=0" in dry.stdout and path.is_file()
    done = subprocess.run([*purge, "--apply"], cwd=service_root, env=env, check=True, capture_output=True, text=True)
    assert "eligible=1 deleted=1" in done.stdout and not path.exists()
    assert qc.get(detail).json()["review_outcome"] == "RETAKE_REQUIRED"
