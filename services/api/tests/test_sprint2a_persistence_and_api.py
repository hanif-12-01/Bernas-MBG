from __future__ import annotations

import concurrent.futures
import csv
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select

from app.data.synthetic_fixture import DEMO_DATASET_ID
from app.db.models import DatasetVersionORM, OptimizationRunORM, ScenarioPriceOverrideORM
from app.db.session import SERVICE_ROOT, create_db_engine, db_manager
from app.export.csv_exporter import escape_csv_formula
from app.main import app
from tests.conftest import TEST_DEMO_PASSWORD, make_authenticated_client


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


def _make_valid_csv_bundle(formula_injection_name: bool = False):
    ing_csv = (
        "code,name,category,edible_fraction,energy_kcal_100g,protein_g_100g,fat_g_100g,carb_g_100g,fiber_g_100g,allergens,source_type,source_ref,review_status\n"
        "C_ING1,Beras Import,staple,1.0,360,7.0,0.8,78.0,1.2,,synthetic,DEMO_ONLY,reviewed\n"
        "C_ING2,Jagung Import,staple,1.0,350,9.0,4.0,72.0,7.0,,synthetic,DEMO_ONLY,reviewed\n"
        "C_ING3,Ayam Import,protein,1.0,165,24.0,7.0,0.0,0.0,,synthetic,DEMO_ONLY,reviewed\n"
        "C_ING4,Tempe Import,protein,1.0,193,19.0,10.8,9.4,5.0,soy,synthetic,DEMO_ONLY,reviewed\n"
        "C_ING5,Bayam Import,vegetable,0.8,23,2.9,0.4,3.6,2.2,,synthetic,DEMO_ONLY,reviewed\n"
        "C_ING6,Wortel Import,vegetable,0.9,41,0.9,0.2,9.6,2.8,,synthetic,DEMO_ONLY,reviewed\n"
        "C_ING7,Pisang Import,fruit,0.75,99,1.1,0.2,25.8,2.6,,synthetic,DEMO_ONLY,reviewed\n"
        "C_ING8,Pepaya Import,fruit,0.75,43,0.5,0.3,10.8,1.7,,synthetic,DEMO_ONLY,reviewed\n"
        "C_ING9,Minyak Import,seasoning,1.0,884,0.0,100.0,0.0,0.0,,synthetic,DEMO_ONLY,reviewed\n"
    )
    prices_csv = (
        "ingredient_code,price_value,unit,density_g_per_ml,region,observed_at,source_type\n"
        "C_ING1,16000,IDR/kg,,SIMULASI,2026-11-19,synthetic\n"
        "C_ING2,14000,IDR/kg,,SIMULASI,2026-11-19,synthetic\n"
        "C_ING3,42000,IDR/kg,,SIMULASI,2026-11-19,synthetic\n"
        "C_ING4,18000,IDR/kg,,SIMULASI,2026-11-19,synthetic\n"
        "C_ING5,12000,IDR/kg,,SIMULASI,2026-11-19,synthetic\n"
        "C_ING6,15000,IDR/kg,,SIMULASI,2026-11-19,synthetic\n"
        "C_ING7,16000,IDR/kg,,SIMULASI,2026-11-19,synthetic\n"
        "C_ING8,12000,IDR/kg,,SIMULASI,2026-11-19,synthetic\n"
        "C_ING9,18400,IDR/liter,0.92,SIMULASI,2026-11-19,synthetic\n"
    )
    stock_csv = (
        "ingredient_code,stock_raw_g\n"
        "C_ING1,50000\n"
        "C_ING2,50000\n"
        "C_ING3,50000\n"
        "C_ING4,50000\n"
        "C_ING5,50000\n"
        "C_ING6,50000\n"
        "C_ING7,50000\n"
        "C_ING8,50000\n"
        "C_ING9,20000\n"
    )
    nasi_name = "=SUM(A1:A10)" if formula_injection_name else "Nasi Import"
    ayam_name = "+CMD|' /C calc'!A0" if formula_injection_name else "Ayam Import Panggang"
    bayam_name = "-2+3" if formula_injection_name else "Tumis Bayam Import"
    pisang_name = "@SUM(1+1)" if formula_injection_name else "Pisang Import"

    recipes_csv = (
        "recipe_code,recipe_name,slot,family,ingredient_code,raw_g_per_serving,retention_factor,allergen_tags,review_status\n"
        f"CR1,{nasi_name},staple,rice,C_ING1,90,0.95,,reviewed\n"
        "CR2,Jagung Import,staple,corn,C_ING2,90,0.95,,reviewed\n"
        f"CR3,{ayam_name},protein,poultry,C_ING3,80,0.92,,reviewed\n"
        f"CR3,{ayam_name},protein,poultry,C_ING9,8,1.0,,reviewed\n"
        "CR4,Tempe Import Bacem,protein,soy,C_ING4,90,0.95,soy,reviewed\n"
        "CR4,Tempe Import Bacem,protein,soy,C_ING9,5,1.0,soy,reviewed\n"
        f"CR5,{bayam_name},vegetable,bayam,C_ING5,90,0.85,,reviewed\n"
        "CR6,Tumis Wortel Import,vegetable,wortel,C_ING6,90,0.90,,reviewed\n"
        f"CR7,{pisang_name},fruit,banana,C_ING7,110,1.0,,reviewed\n"
        "CR8,Pepaya Import,fruit,papaya,C_ING8,120,1.0,,reviewed\n"
    )
    return {
        "ingredients_file": ("ingredients.csv", ing_csv.encode("utf-8"), "text/csv"),
        "prices_file": ("prices.csv", prices_csv.encode("utf-8"), "text/csv"),
        "stock_file": ("stock.csv", stock_csv.encode("utf-8"), "text/csv"),
        "recipes_file": ("recipes.csv", recipes_csv.encode("utf-8"), "text/csv"),
    }


# =====================================================================
# 1. Alembic Migration Roundtrip Test (upgrade -> downgrade -> upgrade)
# =====================================================================


def test_alembic_migration_upgrade_downgrade_roundtrip(tmp_path: Path) -> None:
    mig_db = tmp_path / "alembic_roundtrip.db"
    url = f"sqlite:///{mig_db.as_posix()}"

    cfg = Config(str(SERVICE_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(SERVICE_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)

    command.upgrade(cfg, "head")
    eng = create_db_engine(url)
    tables = set(inspect(eng).get_table_names())
    expected_tables = {
        "dataset_versions",
        "ingredients",
        "ingredient_nutrients",
        "ingredient_prices",
        "dataset_stock_snapshots",
        "recipe_variants",
        "recipe_ingredients",
        "nutrition_targets",
        "nutrition_target_limits",
        "scenarios",
        "scenario_price_overrides",
        "scenario_stock_overrides",
        "optimization_runs",
        "run_assignments",
        "run_metrics",
        "run_material_usage",
        "operational_plan_assignments",
        "ingredient_incidents",
        "incident_affected_lots",
        "incident_actions",
        "incident_images",
    }
    assert expected_tables.issubset(tables)
    eng.dispose()

    command.downgrade(cfg, "base")
    eng2 = create_db_engine(url)
    tables_after_down = set(inspect(eng2).get_table_names())
    assert "scenarios" not in tables_after_down
    assert "optimization_runs" not in tables_after_down
    assert "operational_plan_assignments" not in tables_after_down
    assert "ingredient_incidents" not in tables_after_down
    eng2.dispose()

    command.upgrade(cfg, "head")
    eng3 = create_db_engine(url)
    assert expected_tables.issubset(set(inspect(eng3).get_table_names()))
    eng3.dispose()


# =====================================================================
# 2. Real Cross-Process Restart Persistence Test
# =====================================================================


def test_real_process_restart_persistence(tmp_path: Path) -> None:
    db_file = tmp_path / "restart_persist.db"
    db_url = f"sqlite:///{db_file.as_posix()}"
    env = dict(os.environ)
    env["GIZIOPTIMA_DATABASE_URL"] = db_url
    env["GIZIOPTIMA_SEED_DEMO_ACCOUNTS"] = "true"
    env["GIZIOPTIMA_DEMO_PASSWORD"] = TEST_DEMO_PASSWORD

    # Process 1: create baseline, optimize, clone, price shock, optimize
    script_proc1 = f"""
import json
from fastapi.testclient import TestClient
from app.main import app

c = TestClient(app)
login = c.post("/api/v1/auth/login", json={{"username": "perencana_menu", "password": "{TEST_DEMO_PASSWORD}"}}).json()
c.headers.update({{"X-CSRF-Token": login["csrf_token"]}})
s0 = c.post("/api/v1/scenarios", json={{"name": "Restart Base", "days": 5, "servings_per_day": 100, "budget_idr_per_serving": 12000}}).json()
r0 = c.post(f"/api/v1/scenarios/{{s0['id']}}/optimize").json()
s1 = c.post(f"/api/v1/scenarios/{{s0['id']}}/clone", json={{"name": "Restart Shock"}}).json()
c.patch(f"/api/v1/scenarios/{{s1['id']}}/price-overrides", json={{"overrides": [{{"ingredient_code": "ING006", "price_value": 56000, "unit": "IDR/kg"}}]}})
r1 = c.post(f"/api/v1/scenarios/{{s1['id']}}/optimize").json()
print(json.dumps({{
    "s0_id": s0["id"], "r0_id": r0["run_id"], "r0_obj": r0["objective_total_idr"], "r0_sha": r0["input_sha256"],
    "s1_id": s1["id"], "r1_id": r1["run_id"], "r1_obj": r1["objective_total_idr"], "r1_sha": r1["input_sha256"],
}}))
"""
    p1 = subprocess.run(
        [sys.executable, "-c", script_proc1],
        cwd=str(SERVICE_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    out1 = json.loads(p1.stdout.strip().splitlines()[-1])

    # Process 2 (fresh interpreter, brand-new process): read persisted scenarios, runs, comparison & CSV export
    script_proc2 = f"""
import json
from fastapi.testclient import TestClient
from app.main import app

c = TestClient(app)
login = c.post("/api/v1/auth/login", json={{"username": "perencana_menu", "password": "{TEST_DEMO_PASSWORD}"}}).json()
c.headers.update({{"X-CSRF-Token": login["csrf_token"]}})
s0 = c.get("/api/v1/scenarios/{out1['s0_id']}").json()
r0 = c.get("/api/v1/runs/{out1['r0_id']}").json()
r1 = c.get("/api/v1/runs/{out1['r1_id']}").json()
comp = c.get("/api/v1/comparisons", params={{"base_id": "{out1['r0_id']}", "candidate_id": "{out1['r1_id']}"}}).json()
exp = c.get("/api/v1/runs/{out1['r0_id']}/export.csv")
print(json.dumps({{
    "s0_locked": s0["locked"],
    "r0_obj": r0["objective_total_idr"],
    "r0_sha": r0["input_sha256"],
    "r0_days": len(r0["days"]),
    "r1_obj": r1["objective_total_idr"],
    "comp_basis": comp["compatibility"]["comparison_basis"],
    "exp_status": exp.status_code,
    "exp_has_sha": "{out1['r0_sha']}" in exp.text,
}}))
"""
    p2 = subprocess.run(
        [sys.executable, "-c", script_proc2],
        cwd=str(SERVICE_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    out2 = json.loads(p2.stdout.strip().splitlines()[-1])

    assert out2["s0_locked"] is True
    assert out2["r0_obj"] == out1["r0_obj"]
    assert out2["r0_sha"] == out1["r0_sha"]
    assert out2["r0_days"] == 5
    assert out2["r1_obj"] == out1["r1_obj"]
    assert out2["comp_basis"] == "input_price_or_constraint_change"
    assert out2["exp_status"] == 200
    assert out2["exp_has_sha"] is True


# =====================================================================
# 3. CSV Dataset Import (Valid, Atomic Rejection, Never Replaces Active)
# =====================================================================


def test_csv_import_creates_new_inactive_version_and_optimizes() -> None:
    files = _make_valid_csv_bundle(formula_injection_name=False)
    res = client.post(
        "/api/v1/datasets/import",
        data={"name": "Imported Synthetic v2", "source_type": "synthetic", "is_synthetic": "true"},
        files=files,
    )
    assert res.status_code == 201
    body = res.json()
    assert body["is_active"] is False
    assert body["ingredients_imported"] == 9
    assert body["recipes_imported"] == 8
    new_ds_id = body["dataset_version_id"]

    # Active dataset MUST still be the original DEMO_DATASET_ID (24 ingredients)
    active_ings = client.get("/api/v1/ingredients").json()
    assert len(active_ings) == 24

    # Imported dataset can be queried & optimized independently
    imported_ings = client.get("/api/v1/ingredients", params={"dataset_version_id": new_ds_id}).json()
    assert len(imported_ings) == 9

    sc = client.post(
        "/api/v1/scenarios",
        json={
            "name": "Scenario on Imported CSV",
            "dataset_version_id": new_ds_id,
            "days": 2,
            "servings_per_day": 50,
            "budget_idr_per_serving": 12000,
            "max_repeat_per_family": 2,
        },
    ).json()
    run = client.post(f"/api/v1/scenarios/{sc['id']}/optimize").json()
    assert run["solver_status"] == "OPTIMAL"
    assert run["validation_passed"] is True
    assert run["dataset_version_id"] == new_ds_id


def test_csv_import_atomic_rollback_on_row_errors_nan_units_and_encoding() -> None:
    with db_manager.SessionLocal() as session:
        count_before = len(session.execute(select(DatasetVersionORM)).scalars().all())

    # 1. NaN nutrient + missing nutrient + IDR/liter without density + unmapped ingredient
    bad_ing = (
        "code,name,category,edible_fraction,energy_kcal_100g,protein_g_100g,fat_g_100g,carb_g_100g,fiber_g_100g\n"
        "B1,Bad NaN,staple,1.0,NaN,7.0,0.8,78.0,1.0\n"
        "B2,Missing Prot,staple,1.0,300,,0.8,78.0,1.0\n"
    )
    bad_prices = (
        "ingredient_code,price_value,unit,density_g_per_ml,observed_at\n"
        "B1,18000,IDR/liter,,2026-11-19\n"
        "UNKNOWN_CODE,10000,IDR/kg,,2026-11-19\n"
    )
    bad_stock = "ingredient_code,stock_raw_g\nB1,1000\nB2,-50\n"
    bad_rec = (
        "recipe_code,recipe_name,slot,ingredient_code,raw_g_per_serving,retention_factor,review_status\n"
        "BR1,Bad Recipe,staple,B1,50,1.5,reviewed\n"
    )

    res = client.post(
        "/api/v1/datasets/import",
        data={"name": "Broken Dataset"},
        files={
            "ingredients_file": ("ingredients.csv", bad_ing.encode("utf-8"), "text/csv"),
            "prices_file": ("prices.csv", bad_prices.encode("utf-8"), "text/csv"),
            "stock_file": ("stock.csv", bad_stock.encode("utf-8"), "text/csv"),
            "recipes_file": ("recipes.csv", bad_rec.encode("utf-8"), "text/csv"),
        },
    )
    assert res.status_code == 422
    errs = res.json()["detail"]["errors"]
    assert len(errs) >= 5
    err_fields = {(e["file"], e["field"]) for e in errs}
    assert ("ingredients_file", "energy_kcal_100g") in err_fields
    assert ("ingredients_file", "protein_g_100g") in err_fields
    assert ("prices_file", "unit") in err_fields
    assert ("prices_file", "ingredient_code") in err_fields
    assert ("stock_file", "stock_raw_g") in err_fields

    # 2. Invalid UTF-8 & wrong file extension
    res2 = client.post(
        "/api/v1/datasets/import",
        data={"name": "Bad Encoding"},
        files={
            "ingredients_file": ("ingredients.txt", b"\xff\xfeinvalid", "application/pdf"),
            "prices_file": ("prices.csv", b"ingredient_code,price_idr_per_kg\n", "text/csv"),
            "stock_file": ("stock.csv", b"ingredient_code,stock_raw_g\n", "text/csv"),
            "recipes_file": ("recipes.csv", b"recipe_code,recipe_name,slot,ingredient_code,raw_g_per_serving,retention_factor,review_status\n", "text/csv"),
        },
    )
    assert res2.status_code == 422

    # Verify ZERO partial dataset_versions were written (atomic rejection)
    with db_manager.SessionLocal() as session:
        count_after = len(session.execute(select(DatasetVersionORM)).scalars().all())
    assert count_after == count_before


# =====================================================================
# 4. Scenario Comparison Correctness (Task 3)
# =====================================================================


def test_comparison_distinguishes_price_shock_infeasible_and_apples_to_apples() -> None:
    # S0a and S0b: identical inputs -> apples_to_apples_optimization
    s0a = client.post("/api/v1/scenarios", json={"name": "Comp Base A", "budget_idr_per_serving": 12000}).json()
    r0a = client.post(f"/api/v1/scenarios/{s0a['id']}/optimize").json()
    s0b = client.post("/api/v1/scenarios", json={"name": "Comp Base B", "budget_idr_per_serving": 12000}).json()
    r0b = client.post(f"/api/v1/scenarios/{s0b['id']}/optimize").json()

    cmp_same = client.get("/api/v1/comparisons", params={"base_id": r0a["run_id"], "candidate_id": r0b["run_id"]})
    assert cmp_same.status_code == 200
    d_same = cmp_same.json()
    assert d_same["compatibility"]["apples_to_apples_comparable"] is True
    assert d_same["compatibility"]["comparison_basis"] == "apples_to_apples_optimization"
    assert d_same["cost_comparison"]["cost_savings_achieved_idr"] == 0.0
    assert len(d_same["nutrient_comparison"]) >= 5
    for nc in d_same["nutrient_comparison"]:
        if nc["min_per_serving"] is not None:
            assert nc["base_min_margin_above_floor"] >= -1e-3

    # S1: price shock -> NOT apples-to-apples savings, MUST report changed_prices & savings=None
    s1 = client.post(f"/api/v1/scenarios/{s0a['id']}/clone", json={"name": "Comp Shock"}).json()
    client.patch(
        f"/api/v1/scenarios/{s1['id']}/price-overrides",
        json={"overrides": [{"ingredient_code": "ING006", "price_value": 56000, "unit": "IDR/kg"}]},
    )
    r1 = client.post(f"/api/v1/scenarios/{s1['id']}/optimize").json()
    cmp_shock = client.get("/api/v1/comparisons", params={"base_id": r0a["run_id"], "candidate_id": r1["run_id"]}).json()
    assert cmp_shock["compatibility"]["same_prices"] is False
    assert cmp_shock["compatibility"]["apples_to_apples_comparable"] is False
    assert cmp_shock["compatibility"]["comparison_basis"] == "input_price_or_constraint_change"
    assert any(p["ingredient_code"] == "ING006" for p in cmp_shock["compatibility"]["changed_prices"])
    assert cmp_shock["cost_comparison"]["delta_total_idr"] is not None
    assert cmp_shock["cost_comparison"]["cost_savings_achieved_idr"] is None
    assert cmp_shock["cost_comparison"]["cost_savings_pct"] is None

    # S3: infeasible -> MUST NOT report cost savings or delta_total_idr
    s3 = client.post("/api/v1/scenarios", json={"name": "Comp Infeasible", "budget_idr_per_serving": 3500}).json()
    r3 = client.post(f"/api/v1/scenarios/{s3['id']}/optimize").json()
    assert r3["solver_status"] == "INFEASIBLE"
    cmp_inf = client.get("/api/v1/comparisons", params={"base_id": r0a["run_id"], "candidate_id": r3["run_id"]}).json()
    assert cmp_inf["compatibility"]["comparison_basis"] == "not_comparable_infeasible"
    assert cmp_inf["cost_comparison"]["delta_total_idr"] is None
    assert cmp_inf["cost_comparison"]["cost_savings_achieved_idr"] is None
    assert cmp_inf["cost_comparison"]["cost_savings_pct"] is None


# =====================================================================
# 5. Secure CSV Export & Formula Injection Escaping (Task 4)
# =====================================================================


def test_csv_export_matches_persisted_run_escapes_formulas_and_blocks_infeasible() -> None:
    # Unit test direct formula escape helper
    assert escape_csv_formula("=SUM(A1)") == "'=SUM(A1)"
    assert escape_csv_formula("+1+1") == "'+1+1"
    assert escape_csv_formula("-2+3") == "'-2+3"
    assert escape_csv_formula("@SUM(1)") == "'@SUM(1)"
    assert escape_csv_formula("\t=1+1") == "'\t=1+1"
    assert escape_csv_formula(" =1+1") == "' =1+1"
    assert escape_csv_formula(7182.0) == 7182.0

    # End-to-end: import dataset with formula-injection recipe names, optimize, export CSV
    files = _make_valid_csv_bundle(formula_injection_name=True)
    imp = client.post(
        "/api/v1/datasets/import",
        data={"name": "Formula Escape Test", "source_type": "synthetic", "is_synthetic": "true"},
        files=files,
    ).json()
    sc = client.post(
        "/api/v1/scenarios",
        json={
            "name": "Formula Export Scenario",
            "dataset_version_id": imp["dataset_version_id"],
            "days": 2,
            "servings_per_day": 50,
            "budget_idr_per_serving": 12000,
            "max_repeat_per_family": 1,
        },
    ).json()
    run = client.post(f"/api/v1/scenarios/{sc['id']}/optimize").json()
    assert run["validation_passed"] is True

    exp = client.get(f"/api/v1/runs/{run['run_id']}/export.csv")
    assert exp.status_code == 200
    assert "text/csv" in exp.headers["content-type"]

    rows = list(csv.reader(io.StringIO(exp.text)))
    meta = {r[0]: r[1] for r in rows if len(r) == 2 and r[0] != "meta_key"}
    assert meta["simulation_only"] == "true"
    assert meta["run_id"] == run["run_id"]
    assert meta["scenario_id"] == sc["id"]
    assert meta["dataset_version_id"] == imp["dataset_version_id"]
    assert meta["input_sha256"] == run["input_sha256"]

    # Locate menu table rows and check formula escaping + exact persisted cost match
    header_idx = next(i for i, r in enumerate(rows) if r and r[0] == "day_index")
    data_rows = rows[header_idx + 1 :]
    assert len(data_rows) == 8  # 2 days * 4 slots
    for dr in data_rows:
        recipe_name_cell = dr[3]
        assert not recipe_name_cell.startswith(("=", "+", "-", "@", "\t", "\r"))
    # Verify escaped formulas actually appear in exported names
    exported_names = {dr[3] for dr in data_rows}
    assert "'=SUM(A1:A10)" in exported_names
    assert "'+CMD|' /C calc'!A0" in exported_names
    assert "'-2+3" in exported_names
    assert "'@SUM(1+1)" in exported_names

    # Shopping list succeeds for valid run
    shop = client.get(f"/api/v1/runs/{run['run_id']}/shopping-list")
    assert shop.status_code == 200
    assert len(shop.json()) > 0

    # Infeasible run MUST return 409 on both export.csv and shopping-list
    sc_inf = client.post("/api/v1/scenarios", json={"name": "Export Blocked", "budget_idr_per_serving": 3500}).json()
    run_inf = client.post(f"/api/v1/scenarios/{sc_inf['id']}/optimize").json()
    assert run_inf["solver_status"] == "INFEASIBLE"
    assert client.get(f"/api/v1/runs/{run_inf['run_id']}/export.csv").status_code == 409
    assert client.get(f"/api/v1/runs/{run_inf['run_id']}/shopping-list").status_code == 409


# =====================================================================
# 6. Transaction Rollback & Concurrent Modifications
# =====================================================================


def test_atomic_override_rollback_and_concurrent_optimizations() -> None:
    sc = client.post("/api/v1/scenarios", json={"name": "Rollback Test"}).json()
    sc_id = sc["id"]

    # Batch with 1 valid entry and 1 invalid unit -> MUST roll back entire batch (zero overrides persisted)
    bad_batch = client.patch(
        f"/api/v1/scenarios/{sc_id}/price-overrides",
        json={
            "overrides": [
                {"ingredient_code": "ING001", "price_value": 20000, "unit": "IDR/kg"},
                {"ingredient_code": "ING022", "price_value": 18000, "unit": "IDR/liter"},
            ]
        },
    )
    assert bad_batch.status_code == 422
    reloaded_sc = client.get(f"/api/v1/scenarios/{sc_id}").json()
    assert reloaded_sc["price_overrides_idr_per_g"] == {}

    # Concurrent clone & optimize operations against SQLite WAL
    def _worker(idx: int) -> bool:
        c = make_authenticated_client("perencana_menu")
        s = c.post("/api/v1/scenarios", json={"name": f"Concurrent {idx}", "budget_idr_per_serving": 12000}).json()
        r = c.post(f"/api/v1/scenarios/{s['id']}/optimize").json()
        return r["solver_status"] == "OPTIMAL" and r["validation_passed"] is True

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(_worker, range(4)))
    assert all(results)
