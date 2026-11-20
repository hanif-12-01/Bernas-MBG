from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.auth.seed import seed_development_demo_accounts
from app.db.session import db_manager
from app.main import app

TEST_DEMO_PASSWORD = "TestPassword!2026"


def make_authenticated_client(username: str = "perencana_menu") -> TestClient:
    """Create a TestClient signed in via real /api/v1/auth/login with HttpOnly cookie + CSRF header."""
    c = TestClient(app)
    res = c.post(
        "/api/v1/auth/login",
        json={"username": username, "password": TEST_DEMO_PASSWORD},
    )
    assert res.status_code == 200, f"Login failed for {username}: {res.status_code} {res.text}"
    csrf = res.json()["csrf_token"]
    c.headers.update({"X-CSRF-Token": csrf})
    return c


@pytest.fixture(scope="session", autouse=True)
def isolated_sqlite_test_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    db_file = tmp_path_factory.mktemp("gizioptima_db") / "test_suite.db"
    qc_dir = tmp_path_factory.mktemp("gizioptima_qc_images")
    os.environ["GIZIOPTIMA_QC_STORAGE_DIR"] = str(qc_dir)
    os.environ["GIZIOPTIMA_VISION_PROVIDER"] = "deterministic_test"

    db_url = f"sqlite:///{db_file.as_posix()}"
    db_manager.configure(db_url, run_migrations=True)
    assert db_manager.SessionLocal is not None
    with db_manager.SessionLocal() as session:
        seed_development_demo_accounts(session, demo_password=TEST_DEMO_PASSWORD)
    return db_file
