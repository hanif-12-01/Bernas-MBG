from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

from fastapi.testclient import TestClient

from app.api.routes import auth
from app.auth.rate_limit import RateLimiter
from app.main import app
from tests.conftest import make_authenticated_client
from tests.test_sprint2a_persistence_and_api import _make_valid_csv_bundle


def test_login_limits_and_production_cookie(monkeypatch) -> None:
    monkeypatch.setattr(auth, "_login_account_limit", RateLimiter(2, 60))
    monkeypatch.setattr(auth, "_login_peer_limit", RateLimiter(10, 60))
    monkeypatch.setenv("GIZIOPTIMA_ENV", "production")
    client = TestClient(app)
    bad_credentials = {"username": "unknown_login_test_user", "password": "wrong-password"}
    for _ in range(2):
        assert client.post("/api/v1/auth/login", json=bad_credentials).status_code == 401
    limited = client.post("/api/v1/auth/login", json=bad_credentials)
    assert limited.status_code == 429
    assert int(limited.headers["Retry-After"]) > 0
    assert auth._cookie_secure_flag()


def test_private_csv_dataset_can_only_be_used_by_importing_kitchen() -> None:
    planner_a = make_authenticated_client("perencana_menu")
    planner_b = make_authenticated_client("perencana_menu_b")
    import_response = planner_a.post(
        "/api/v1/datasets/import",
        data={"name": "Private Kitchen A CSV"},
        files=_make_valid_csv_bundle(),
    )
    assert import_response.status_code == 201, import_response.text
    dataset_id = import_response.json()["dataset_version_id"]
    assert dataset_id in {row["id"] for row in planner_a.get("/api/v1/datasets").json()}
    assert dataset_id not in {row["id"] for row in planner_b.get("/api/v1/datasets").json()}
    assert planner_b.get(f"/api/v1/datasets/{dataset_id}").status_code == 404
    for endpoint in ("inventory", "ingredients", "recipes"):
        assert planner_b.get(
            f"/api/v1/{endpoint}", params={"dataset_version_id": dataset_id}
        ).status_code == 404

    scenario_payload = {"name": "Private CSV Plan", "dataset_version_id": dataset_id}
    assert planner_b.post("/api/v1/scenarios", json=scenario_payload).status_code == 404
    local_scenario = planner_a.post("/api/v1/scenarios", json=scenario_payload)
    assert local_scenario.status_code == 201
    assert local_scenario.json()["dataset_version_id"] == dataset_id


def test_cli_onboarding_role_changes_password_reset_and_revocation(
    isolated_sqlite_test_db: Path,
) -> None:
    env = {
        **os.environ,
        "GIZIOPTIMA_DATABASE_URL": f"sqlite:///{isolated_sqlite_test_db.as_posix()}",
    }
    cli = Path(__file__).resolve().parents[1] / "scripts" / "manage_access.py"
    password = "OnboardingTest!2026"
    new_password = "UpdatedOnboarding!2026"
    username = "onboarding_test"
    kitchen = "TEST-ONBOARDING"

    def run(*args: str, secret: str | None = None) -> None:
        command = [sys.executable, str(cli), *args]
        if secret is not None:
            command.append("--password-stdin")
        result = subprocess.run(
            command, env=env, input=f"{secret}\n" if secret else "",
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, result.stderr
        assert secret is None or secret not in result.stdout

    def login(client: TestClient, candidate: str, **attributes: str):
        return client.post(
            "/api/v1/auth/login",
            json={"username": username, "password": candidate, **attributes},
        )

    run("create-kitchen", "--code", kitchen, "--name", "Onboarding Kitchen", "--region", "Bandung")
    run(
        "create-user", username, "--email", "onboarding@example.com", "--name", "Onboarding User",
        "--kitchen", kitchen, "--role", "MENU_PLANNER", secret=password,
    )
    client = TestClient(app)
    first_login = login(client, password)
    assert first_login.status_code == 200
    assert first_login.json()["active_kitchen_code"] == kitchen
    assert first_login.json()["active_role"] == "MENU_PLANNER"

    run("set-membership", username, "--kitchen", kitchen, "--role", "QC_OFFICER")
    assert client.get("/api/v1/auth/me").status_code == 401
    assert login(client, password).json()["active_role"] == "QC_OFFICER"
    run("set-membership", username, "--kitchen", "SPPG-SIM-B", "--role", "MENU_PLANNER", "--default")
    assert login(client, password).json()["active_kitchen_code"] == "SPPG-SIM-B"
    run("remove-membership", username, "--kitchen", "SPPG-SIM-B")
    assert client.get("/api/v1/auth/me").status_code == 401
    assert login(client, password).json()["active_kitchen_code"] == kitchen

    run("reset-password", username, secret=new_password)
    assert client.get("/api/v1/auth/me").status_code == 401
    assert login(client, password).status_code == 401
    assert login(client, new_password).status_code == 200
    run("disable-user", username)
    assert client.get("/api/v1/auth/me").status_code == 401
    assert login(client, new_password).status_code == 401
    run("enable-user", username)
    assert login(client, new_password).status_code == 200
