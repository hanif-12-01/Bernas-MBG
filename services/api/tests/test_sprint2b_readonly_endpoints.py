from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import make_authenticated_client


def test_readonly_listing_and_inventory_endpoints_and_cors() -> None:
    client = make_authenticated_client("perencana_menu")
    # CORS preflight / header check
    cors_res = client.options(
        "/api/v1/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert cors_res.status_code == 200
    assert cors_res.headers.get("access-control-allow-origin") == "http://localhost:3000"

    # List datasets
    ds_res = client.get("/api/v1/datasets")
    assert ds_res.status_code == 200
    datasets = ds_res.json()
    assert len(datasets) >= 1
    assert any(d["is_active"] is True for d in datasets)

    # Inventory catalog includes prices and stock alongside ingredients
    inv_res = client.get("/api/v1/inventory")
    assert inv_res.status_code == 200
    inv = inv_res.json()
    assert inv["dataset"]["is_active"] is True
    assert len(inv["items"]) == 24
    first = inv["items"][0]
    assert first["price_idr_per_g"] > 0
    assert first["original_price_unit"] == "IDR/kg"
    assert first["stock_raw_g"] >= 0

    # Create + optimize a scenario, then verify GET /scenarios and GET /runs return it
    sc = client.post("/api/v1/scenarios", json={"name": "ReadOnly List Check", "budget_idr_per_serving": 12000}).json()
    run = client.post(f"/api/v1/scenarios/{sc['id']}/optimize").json()
    assert run["validation_passed"] is True

    sc_list = client.get("/api/v1/scenarios").json()
    assert any(s["id"] == sc["id"] for s in sc_list)

    run_list = client.get("/api/v1/runs", params={"scenario_id": sc["id"], "validated_only": True}).json()
    assert len(run_list) >= 1
    assert run_list[0]["run_id"] == run["run_id"]
