from __future__ import annotations

from fastapi.testclient import TestClient

from app.domain.models.schemas import (
    ScenarioCreateRequest,
    SlotEnum,
    SolverStatusEnum,
)
from app.main import app
from app.optimizer.solver import RawSolveResult
from app.scenarios.service import create_scenario, run_optimization
from app.scenarios.store import InMemoryVaultStore
from tests.conftest import make_authenticated_client


class _LazyPlannerClient:
    def __init__(self) -> None:
        self._inner: TestClient | None = None

    def _client(self) -> TestClient:
        if self._inner is None:
            self._inner = make_authenticated_client("perencana_menu")
        return self._inner

    def __getattr__(self, name: str):
        if name.startswith("_") or not hasattr(TestClient, name):
            raise AttributeError(name)
        return getattr(self._client(), name)


client = _LazyPlannerClient()


def test_health_and_dataset_endpoints() -> None:
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json()["simulation_only"] is True

    ing_res = client.get("/api/v1/ingredients")
    assert ing_res.status_code == 200
    assert len(ing_res.json()) == 24

    rec_res = client.get("/api/v1/recipes")
    assert rec_res.status_code == 200
    recipes = rec_res.json()
    assert len(recipes) == 16
    assert all(item["review_status"] == "reviewed" for item in recipes)


def test_s0_baseline_feasible_and_excludes_unreviewed() -> None:
    create_res = client.post(
        "/api/v1/scenarios",
        json={
            "name": "S0 Baseline (SIMULASI)",
            "servings_per_day": 100,
            "days": 5,
            "budget_idr_per_serving": 12000,
            "max_repeat_per_family": 2,
        },
    )
    assert create_res.status_code == 201
    s0_id = create_res.json()["id"]

    opt_res = client.post(f"/api/v1/scenarios/{s0_id}/optimize")
    assert opt_res.status_code == 200
    data = opt_res.json()

    assert data["solver_status"] == "OPTIMAL"
    assert data["validation_passed"] is True
    assert data["simulation_only"] is True
    assert data["constraint_audit"]["all_hard_constraints_pass"] is True
    assert data["constraint_audit"]["violations"] == []
    assert len(data["days"]) == 5
    for d in data["days"]:
        assert set(d["recipes_by_slot"].keys()) == {"staple", "protein", "vegetable", "fruit"}
        assert d["daily_cost_idr_per_serving"] <= 12000.0
        # R017 draft recipe must never be selected
        assert "R017" not in d["recipe_names_by_slot"].values()
        assert "Nasi Mini Unreviewed (DRAFT)" not in d["recipe_names_by_slot"].values()

    # Persisted run lookup works
    run_res = client.get(f"/api/v1/runs/{data['run_id']}")
    assert run_res.status_code == 200
    assert run_res.json()["input_sha256"] == data["input_sha256"]


def test_s1_price_shock_isolates_overrides_and_preserves_baseline() -> None:
    s0_res = client.post(
        "/api/v1/scenarios",
        json={"name": "S0 Base", "budget_idr_per_serving": 12000, "max_repeat_per_family": 2},
    )
    s0_id = s0_res.json()["id"]
    s0_run = client.post(f"/api/v1/scenarios/{s0_id}/optimize").json()
    assert s0_run["validation_passed"] is True

    # Locked baseline must reject direct PATCH (409 Conflict)
    locked_patch = client.patch(
        f"/api/v1/scenarios/{s0_id}/price-overrides",
        json={"overrides": [{"ingredient_code": "ING006", "price_value": 56000, "unit": "IDR/kg"}]},
    )
    assert locked_patch.status_code == 409

    # Clone S0 -> S1 and apply +100% egg price shock
    s1_res = client.post(f"/api/v1/scenarios/{s0_id}/clone", json={"name": "S1 Telur +100%"})
    assert s1_res.status_code == 201
    s1_id = s1_res.json()["id"]

    patch_res = client.patch(
        f"/api/v1/scenarios/{s1_id}/price-overrides",
        json={"overrides": [{"ingredient_code": "ING006", "price_value": 56000, "unit": "IDR/kg"}]},
    )
    assert patch_res.status_code == 200

    s1_run = client.post(f"/api/v1/scenarios/{s1_id}/optimize").json()
    assert s1_run["solver_status"] == "OPTIMAL"
    assert s1_run["validation_passed"] is True
    assert s1_run["input_sha256"] != s0_run["input_sha256"]
    assert s1_run["objective_total_idr"] >= s0_run["objective_total_idr"]

    # Re-fetch S0 run: unchanged
    s0_again = client.get(f"/api/v1/runs/{s0_run['run_id']}").json()
    assert s0_again["objective_total_idr"] == s0_run["objective_total_idr"]


def test_s2_stock_shortage_forces_substitution_and_respects_stock() -> None:
    s2 = client.post(
        "/api/v1/scenarios",
        json={"name": "S2 Stok Tempe & Telur Terbatas", "budget_idr_per_serving": 12000, "max_repeat_per_family": 2},
    ).json()
    s2_id = s2["id"]

    # Restrict Tempe (ING009) to 7500g (at most 1 day * 100 * 75g)
    patch = client.patch(
        f"/api/v1/scenarios/{s2_id}/stock-overrides",
        json={"overrides": [{"ingredient_code": "ING009", "stock_raw_g": 7500.0}]},
    )
    assert patch.status_code == 200

    run = client.post(f"/api/v1/scenarios/{s2_id}/optimize").json()
    assert run["solver_status"] == "OPTIMAL"
    assert run["validation_passed"] is True
    tempe_usage = [u for u in run["material_usage"] if u["ingredient_code"] == "ING009"]
    if tempe_usage:
        assert tempe_usage[0]["used_raw_g"] <= 7500.0 + 1e-6


def test_s3_infeasible_budget_returns_no_menu_and_diagnostics() -> None:
    s3 = client.post(
        "/api/v1/scenarios",
        json={"name": "S3 Budget Mustahil", "budget_idr_per_serving": 3500, "max_repeat_per_family": 2},
    ).json()
    run = client.post(f"/api/v1/scenarios/{s3['id']}/optimize").json()

    assert run["solver_status"] == "INFEASIBLE"
    assert run["validation_passed"] is False
    assert run["objective_total_idr"] is None
    assert run["days"] == []
    assert run["constraint_audit"]["all_hard_constraints_pass"] is False
    assert len(run["constraint_diagnostics"]) >= 1
    assert any(d["family"] == "budget" for d in run["constraint_diagnostics"])


def test_s4_allergen_exclusion_and_repeat_cap() -> None:
    s4 = client.post(
        "/api/v1/scenarios",
        json={
            "name": "S4 Bebas Telur",
            "budget_idr_per_serving": 12000,
            "max_repeat_per_family": 2,
            "excluded_allergens": ["egg"],
        },
    ).json()
    run = client.post(f"/api/v1/scenarios/{s4['id']}/optimize").json()

    assert run["solver_status"] == "OPTIMAL"
    assert run["validation_passed"] is True
    for d in run["days"]:
        assert "Telur Balado & Tahu" not in d["recipe_names_by_slot"].values()


def test_api_rejects_wrong_unit_override() -> None:
    sc = client.post("/api/v1/scenarios", json={"name": "Unit Error Test"}).json()
    bad_unit = client.patch(
        f"/api/v1/scenarios/{sc['id']}/price-overrides",
        json={"overrides": [{"ingredient_code": "ING022", "price_value": 18000, "unit": "IDR/liter"}]},
    )
    assert bad_unit.status_code == 422

    bad_price = client.patch(
        f"/api/v1/scenarios/{sc['id']}/price-overrides",
        json={"overrides": [{"ingredient_code": "ING001", "price_value": -500, "unit": "IDR/kg"}]},
    )
    assert bad_price.status_code == 422


def test_explicit_time_limit_and_error_status_handling() -> None:
    local_store = InMemoryVaultStore()
    sc = create_scenario(local_store, ScenarioCreateRequest(name="Status Handling"))

    # 1. TIME_LIMIT without incumbent -> validation_passed=False, empty days
    tl_empty = RawSolveResult(
        solver_status=SolverStatusEnum.TIME_LIMIT,
        solver_seconds=10.0,
        assignments_by_day={},
        has_incumbent=False,
    )
    run1 = run_optimization(local_store, sc.id, forced_raw_result=tl_empty)
    assert run1.solver_status == SolverStatusEnum.TIME_LIMIT
    assert run1.validation_passed is False
    assert run1.days == []

    # 2. TIME_LIMIT with invalid incumbent (all days assigned to R001 violating repeat_cap & slots)
    sc2 = create_scenario(local_store, ScenarioCreateRequest(name="Bad Incumbent"))
    r001_id = next(r.id for r in local_store.recipes if r.code == "R001")
    bad_incumbent = RawSolveResult(
        solver_status=SolverStatusEnum.TIME_LIMIT,
        solver_seconds=10.0,
        assignments_by_day={
            d: {
                SlotEnum.STAPLE: r001_id,
                SlotEnum.PROTEIN: r001_id,
                SlotEnum.VEGETABLE: r001_id,
                SlotEnum.FRUIT: r001_id,
            }
            for d in range(1, 6)
        },
        has_incumbent=True,
    )
    run2 = run_optimization(local_store, sc2.id, forced_raw_result=bad_incumbent)
    assert run2.validation_passed is False
    assert run2.days == []
    assert len(run2.constraint_audit.violations) > 0

    # 3. ERROR status -> validation_passed=False, empty days
    sc3 = create_scenario(local_store, ScenarioCreateRequest(name="Solver Error"))
    err_res = RawSolveResult(
        solver_status=SolverStatusEnum.ERROR,
        solver_seconds=0.01,
        assignments_by_day={},
        has_incumbent=False,
        error_message="Simulated CBC failure",
    )
    run3 = run_optimization(local_store, sc3.id, forced_raw_result=err_res)
    assert run3.solver_status == SolverStatusEnum.ERROR
    assert run3.validation_passed is False
    assert run3.days == []
