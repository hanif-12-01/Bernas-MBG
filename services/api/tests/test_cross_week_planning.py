from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.auth.seed import DEMO_KITCHEN_A_ID
from app.data.synthetic_fixture import DEMO_TARGET_ID
from app.db.models import (
    IngredientORM,
    InventoryLotORM,
    InventoryMovementORM,
    OperationalPlanAssignmentORM,
    StockReservationORM,
    SupplierDeliveryORM,
)
from app.db.session import db_manager
from app.operations.planning import compute_cross_period_stock_context
from tests.conftest import make_authenticated_client


def _create_multiweek_dataset(
    planner,
    qc,
    *,
    tag: str,
    stock_kg: dict[str, float] | None = None,
    expiry_by_code: dict[str, str] | None = None,
    constrained_recipes: bool = False,
) -> str:
    """Create a deterministic isolated synthetic dataset with rich recipes for multi-week testing."""
    ing_csv = (
        "code,name,category,edible_fraction,energy_kcal_100g,protein_g_100g,fat_g_100g,carb_g_100g,fiber_g_100g,allergens,source_type,source_ref,review_status\n"
        "MW_S1,Beras Putih,staple,1.0,360,7.0,0.8,78.0,1.2,,synthetic,DEMO_ONLY,reviewed\n"
        "MW_S2,Jagung Pipil,staple,1.0,350,9.0,4.0,72.0,7.0,,synthetic,DEMO_ONLY,reviewed\n"
        "MW_S3,Kentang Kukus,staple,0.85,87,2.0,0.1,20.0,1.8,,synthetic,DEMO_ONLY,reviewed\n"
        "MW_P1,Dada Ayam,protein,1.0,165,24.0,7.0,0.0,0.0,,synthetic,DEMO_ONLY,reviewed\n"
        "MW_P2,Ikan Kembung,protein,0.8,167,21.0,8.5,0.0,0.0,fish,synthetic,DEMO_ONLY,reviewed\n"
        "MW_P3,Tempe Kedelai,protein,1.0,193,19.0,10.8,9.4,5.0,soy,synthetic,DEMO_ONLY,reviewed\n"
        "MW_P4,Telur Ayam,protein,0.89,155,13.0,11.0,1.1,0.0,egg,synthetic,DEMO_ONLY,reviewed\n"
        "MW_V1,Bayam Hijau,vegetable,0.8,23,2.9,0.4,3.6,2.2,,synthetic,DEMO_ONLY,reviewed\n"
        "MW_V2,Wortel Segar,vegetable,0.9,41,0.9,0.2,9.6,2.8,,synthetic,DEMO_ONLY,reviewed\n"
        "MW_V3,Buncis Segar,vegetable,0.9,31,1.8,0.2,7.0,3.4,,synthetic,DEMO_ONLY,reviewed\n"
        "MW_F1,Pisang Ambon,fruit,0.75,99,1.1,0.2,25.8,2.6,,synthetic,DEMO_ONLY,reviewed\n"
        "MW_F2,Pepaya Matang,fruit,0.75,43,0.5,0.3,10.8,1.7,,synthetic,DEMO_ONLY,reviewed\n"
        "MW_F3,Jeruk Manis,fruit,0.72,47,0.9,0.1,11.8,2.4,,synthetic,DEMO_ONLY,reviewed\n"
        "MW_OIL,Minyak Goreng,seasoning,1.0,884,0.0,100.0,0.0,0.0,,synthetic,DEMO_ONLY,reviewed\n"
    )
    prices_csv = (
        "ingredient_code,price_value,unit,density_g_per_ml,region,observed_at,source_type\n"
        "MW_S1,14000,IDR/kg,,SIMULASI,2026-11-20,synthetic\n"
        "MW_S2,13500,IDR/kg,,SIMULASI,2026-11-20,synthetic\n"
        "MW_S3,15000,IDR/kg,,SIMULASI,2026-11-20,synthetic\n"
        "MW_P1,36000,IDR/kg,,SIMULASI,2026-11-20,synthetic\n"
        "MW_P2,35000,IDR/kg,,SIMULASI,2026-11-20,synthetic\n"
        "MW_P3,17000,IDR/kg,,SIMULASI,2026-11-20,synthetic\n"
        "MW_P4,28000,IDR/kg,,SIMULASI,2026-11-20,synthetic\n"
        "MW_V1,12000,IDR/kg,,SIMULASI,2026-11-20,synthetic\n"
        "MW_V2,13000,IDR/kg,,SIMULASI,2026-11-20,synthetic\n"
        "MW_V3,13500,IDR/kg,,SIMULASI,2026-11-20,synthetic\n"
        "MW_F1,14000,IDR/kg,,SIMULASI,2026-11-20,synthetic\n"
        "MW_F2,11000,IDR/kg,,SIMULASI,2026-11-20,synthetic\n"
        "MW_F3,15000,IDR/kg,,SIMULASI,2026-11-20,synthetic\n"
        "MW_OIL,18000,IDR/liter,0.92,SIMULASI,2026-11-20,synthetic\n"
    )
    default_kg = {
        "MW_S1": 200.0,
        "MW_S2": 200.0,
        "MW_S3": 200.0,
        "MW_P1": 200.0,
        "MW_P2": 200.0,
        "MW_P3": 200.0,
        "MW_P4": 200.0,
        "MW_V1": 200.0,
        "MW_V2": 200.0,
        "MW_V3": 200.0,
        "MW_F1": 200.0,
        "MW_F2": 200.0,
        "MW_F3": 200.0,
        "MW_OIL": 100.0,
    }
    if stock_kg:
        default_kg.update(stock_kg)

    stock_lines = ["ingredient_code,stock_raw_g"] + [
        f"{code},{int(kg * 1000)}" for code, kg in default_kg.items()
    ]
    stock_csv = "\n".join(stock_lines) + "\n"

    if constrained_recipes:
        # Deliberately minimal 2-family set per slot so Week 2 MUST overlap Week 1 families
        recipes_csv = (
            "recipe_code,recipe_name,slot,family,ingredient_code,raw_g_per_serving,retention_factor,allergen_tags,review_status\n"
            "MWR_S1,Nasi Putih,staple,rice,MW_S1,95,0.95,,reviewed\n"
            "MWR_S2,Nasi Jagung,staple,corn,MW_S2,95,0.95,,reviewed\n"
            "MWR_P1,Ayam Panggang,protein,poultry,MW_P1,85,0.92,,reviewed\n"
            "MWR_P1,Ayam Panggang,protein,poultry,MW_OIL,8,1.0,,reviewed\n"
            "MWR_P3,Tempe Bacem,protein,soy,MW_P3,95,0.95,soy,reviewed\n"
            "MWR_P3,Tempe Bacem,protein,soy,MW_OIL,6,1.0,soy,reviewed\n"
            "MWR_V1,Sayur Bayam,vegetable,bayam,MW_V1,95,0.85,,reviewed\n"
            "MWR_V2,Tumis Wortel,vegetable,wortel,MW_V2,95,0.90,,reviewed\n"
            "MWR_F1,Pisang Ambon,fruit,banana,MW_F1,110,1.0,,reviewed\n"
            "MWR_F2,Pepaya Potong,fruit,papaya,MW_F2,120,1.0,,reviewed\n"
        )
    else:
        recipes_csv = (
            "recipe_code,recipe_name,slot,family,ingredient_code,raw_g_per_serving,retention_factor,allergen_tags,review_status\n"
            "MWR_S1,Nasi Putih,staple,rice,MW_S1,95,0.95,,reviewed\n"
            "MWR_S2,Nasi Jagung,staple,corn,MW_S2,95,0.95,,reviewed\n"
            "MWR_S3,Kentang Rebus Beras,staple,tuber,MW_S3,110,0.95,,reviewed\n"
            "MWR_S3,Kentang Rebus Beras,staple,tuber,MW_S1,65,0.95,,reviewed\n"
            "MWR_P1,Ayam Panggang,protein,poultry,MW_P1,85,0.92,,reviewed\n"
            "MWR_P1,Ayam Panggang,protein,poultry,MW_OIL,8,1.0,,reviewed\n"
            "MWR_P2,Ikan Kembung Balado,protein,fish,MW_P2,90,0.90,fish,reviewed\n"
            "MWR_P2,Ikan Kembung Balado,protein,fish,MW_OIL,7,1.0,fish,reviewed\n"
            "MWR_P3,Tempe Bacem,protein,soy,MW_P3,95,0.95,soy,reviewed\n"
            "MWR_P3,Tempe Bacem,protein,soy,MW_OIL,6,1.0,soy,reviewed\n"
            "MWR_P4,Telur Semur,protein,egg,MW_P4,95,0.95,egg,reviewed\n"
            "MWR_P4,Telur Semur,protein,egg,MW_OIL,6,1.0,egg,reviewed\n"
            "MWR_V1,Sayur Bayam,vegetable,bayam,MW_V1,95,0.85,,reviewed\n"
            "MWR_V2,Tumis Wortel,vegetable,wortel,MW_V2,95,0.90,,reviewed\n"
            "MWR_V3,Tumis Buncis,vegetable,buncis,MW_V3,95,0.90,,reviewed\n"
            "MWR_F1,Pisang Ambon,fruit,banana,MW_F1,110,1.0,,reviewed\n"
            "MWR_F2,Pepaya Potong,fruit,papaya,MW_F2,120,1.0,,reviewed\n"
            "MWR_F3,Jeruk Manis,fruit,citrus,MW_F3,120,1.0,,reviewed\n"
        )

    imp = planner.post(
        "/api/v1/datasets/import",
        data={"name": f"CrossWeek {tag} {str(uuid4())[:6]}"},
        files={
            "ingredients_file": ("ingredients.csv", ing_csv.encode("utf-8"), "text/csv"),
            "prices_file": ("prices.csv", prices_csv.encode("utf-8"), "text/csv"),
            "stock_file": ("stock.csv", stock_csv.encode("utf-8"), "text/csv"),
            "recipes_file": ("recipes.csv", recipes_csv.encode("utf-8"), "text/csv"),
        },
    )
    assert imp.status_code == 201, imp.text
    ds_id = imp.json()["dataset_version_id"]

    exp_map = expiry_by_code or {}
    tx_rows = ["event_type,ingredient_code,lot_code,quantity,unit,event_at,expires_at,idempotency_key"]
    for code, kg in default_kg.items():
        if kg <= 0:
            continue
        exp = exp_map.get(code, "2027-12-31")
        tx_rows.append(
            f"OPENING_BALANCE,{code},LOT-{tag}-{code},{kg},kg,2026-11-20T06:00:00Z,{exp},OP-{tag}-{code}-{uuid4().hex[:6]}"
        )
    tx_res = qc.post(
        "/api/v1/inventory/transactions/import",
        data={"dataset_version_id": ds_id, "data_classification": "synthetic", "dry_run": "false"},
        files={"transactions_file": ("tx.csv", ("\n".join(tx_rows) + "\n").encode("utf-8"), "text/csv")},
    )
    assert tx_res.status_code == 200, tx_res.text
    assert tx_res.json()["error_count"] == 0, tx_res.json()
    return ds_id


def _create_approve_and_optionally_activate(
    planner,
    manager,
    *,
    ds_id: str,
    name: str,
    service_dates: list[str],
    servings_per_day: int = 50,
    budget: float = 18000.0,
    max_repeat: int = 2,
    price_overrides: list[dict] | None = None,
    stock_overrides: list[dict] | None = None,
    activate: bool = True,
) -> tuple[dict, dict, dict, dict | None]:
    sc_res = planner.post(
        "/api/v1/scenarios",
        json={
            "name": name,
            "dataset_version_id": ds_id,
            "nutrition_target_id": str(DEMO_TARGET_ID),
            "servings_per_day": servings_per_day,
            "days": len(service_dates),
            "service_dates": service_dates,
            "budget_idr_per_serving": budget,
            "max_repeat_per_family": max_repeat,
            "excluded_allergens": [],
            "source_label": "synthetic",
        },
    )
    assert sc_res.status_code == 201, sc_res.text
    sc = sc_res.json()

    if price_overrides:
        po = planner.patch(
            f"/api/v1/scenarios/{sc['id']}/price-overrides",
            json={"overrides": price_overrides},
        )
        assert po.status_code == 200, po.text
    if stock_overrides:
        so = planner.patch(
            f"/api/v1/scenarios/{sc['id']}/stock-overrides",
            json={"overrides": stock_overrides},
        )
        assert so.status_code == 200, so.text

    run_res = planner.post(f"/api/v1/scenarios/{sc['id']}/optimize")
    assert run_res.status_code == 200, run_res.text
    run = run_res.json()
    assert run["validation_passed"] is True, run

    rev_res = planner.post("/api/v1/menu-reviews", json={"run_id": run["run_id"], "title": name})
    assert rev_res.status_code == 201, rev_res.text
    rev = rev_res.json()

    sub_res = planner.post(f"/api/v1/menu-reviews/{rev['id']}/submit")
    assert sub_res.status_code == 200, sub_res.text

    app_res = manager.post(
        f"/api/v1/menu-reviews/{rev['id']}/review",
        json={"decision": "APPROVED", "reviewer_notes": "Disetujui operasional"},
    )
    assert app_res.status_code == 200, app_res.text
    rev = app_res.json()

    assigned = None
    if activate:
        if rev.get("operational_status") == "ACTIVE":
            plans = manager.get(f"/api/v1/operational-plans?dataset_version_id={ds_id}").json()
            assigned = next(p for p in plans if p["menu_review_id"] == rev["id"])
        else:
            act_res = manager.post(
                "/api/v1/operational-plans/activate",
                json={"menu_review_id": rev["id"], "notes": "Aktivasi eksplisit Kepala Dapur"},
            )
            assert act_res.status_code == 200, act_res.text
            assigned = act_res.json()
    return sc, run, rev, assigned


def test_ac1_explicit_service_dates_and_mid_period_lookup() -> None:
    """AC #1: Plan binds Hari 1..5 to exact service dates (including holiday skip) and resolves mid-period lookups."""
    planner = make_authenticated_client("perencana_menu")
    manager = make_authenticated_client("kepala_dapur")
    qc = make_authenticated_client("petugas_qc")
    ds_id = _create_multiweek_dataset(planner, qc, tag="AC1")

    # Skip Wednesday 2027-01-06 as a holiday
    dates = ["2027-01-04", "2027-01-05", "2027-01-07", "2027-01-08", "2027-01-11"]
    sc, run, rev, assigned = _create_approve_and_optionally_activate(
        planner, manager, ds_id=ds_id, name="Rencana Libur Rabu", service_dates=dates
    )
    assert sc["service_dates"] == dates
    assert run["service_dates"] == dates
    assert [d["service_date"] for d in run["days"]] == dates
    assert assigned is not None
    assert assigned["service_dates"] == dates
    assert assigned["period_start_date"] == "2027-01-04"
    assert assigned["period_end_date"] == "2027-01-11"

    # Mid-period lookup (Day 3 = 2027-01-07)
    eff_mid = manager.get(
        "/api/v1/operational-plans/effective",
        params={"dataset_version_id": ds_id, "service_date": "2027-01-07"},
    )
    assert eff_mid.status_code == 200, eff_mid.text
    body = eff_mid.json()
    assert body["state"] == "ACTIVE"
    assert body["queried_service_date"] == "2027-01-07"
    assert body["matched_day_index"] == 3
    assert body["active_plan"]["id"] == assigned["id"]

    # Holiday date (2027-01-06) must NOT return an active plan
    eff_hol = manager.get(
        "/api/v1/operational-plans/effective",
        params={"dataset_version_id": ds_id, "service_date": "2027-01-06"},
    ).json()
    assert eff_hol["state"] == "NO_PLAN"
    assert eff_hol["active_plan"] is None


def test_ac2_and_ac3_prepare_next_week_no_overrides_and_boundary_variety() -> None:
    """AC #2 & AC #3: Prepare Week 2 without retyping config, without inheriting simulation overrides,
    without copying Week 1 verbatim, and minimizing boundary recipe/family repetition."""
    planner = make_authenticated_client("perencana_menu")
    manager = make_authenticated_client("kepala_dapur")
    qc = make_authenticated_client("petugas_qc")
    ds_id = _create_multiweek_dataset(planner, qc, tag="AC23")

    w1_dates = ["2027-01-18", "2027-01-19", "2027-01-20", "2027-01-21", "2027-01-22"]
    _sc1, run1, _rev1, assign1 = _create_approve_and_optionally_activate(
        planner,
        manager,
        ds_id=ds_id,
        name="Minggu 1 AC23",
        service_dates=w1_dates,
        servings_per_day=60,
        budget=18000.0,
        price_overrides=[{"ingredient_code": "MW_P1", "price_value": 55000, "unit": "IDR/kg"}],
        stock_overrides=[{"ingredient_code": "MW_S1", "stock_raw_g": 99000}],
    )
    assert assign1 is not None

    # Fetch defaults for next week
    defs_res = planner.get(
        "/api/v1/scenarios/next-week-defaults",
        params={"source_assignment_id": assign1["id"]},
    )
    assert defs_res.status_code == 200, defs_res.text
    defs = defs_res.json()
    assert defs["suggested_service_dates"] == [
        "2027-01-25",
        "2027-01-26",
        "2027-01-27",
        "2027-01-28",
        "2027-01-29",
    ]
    assert defs["servings_per_day"] == 60
    assert defs["budget_idr_per_serving"] == pytest.approx(18000.0)
    assert defs["history_source_type"] == "OPERATIONAL_PLAN"
    assert "bukan bukti fisik" in defs["history_source_notice"].lower()

    # Prepare Week 2
    prep_res = planner.post(
        "/api/v1/scenarios/prepare-next-week",
        json={"source_assignment_id": assign1["id"], "planner_notes": "Siap ditinjau untuk Minggu 2"},
    )
    assert prep_res.status_code == 201, prep_res.text
    prep = prep_res.json()
    assert prep["validation_passed"] is True
    assert prep["menu_review_status"] == "DRAFT"
    assert prep["service_dates"] == defs["suggested_service_dates"]

    # Must NOT inherit simulation price/stock overrides from Week 1
    sc2 = planner.get(f"/api/v1/scenarios/{prep['scenario_id']}").json()
    assert sc2["price_overrides_idr_per_g"] == {}
    assert sc2["stock_overrides_raw_g"] == {}
    assert sc2["continuation_of_run_id"] == run1["run_id"]

    # Boundary variety: Week 2 Day 1 must avoid repeating Week 1 Day 5 recipes where alternatives exist
    run2 = planner.get(f"/api/v1/runs/{prep['run_id']}").json()
    w1_day5_recipes = set(run1["days"][-1]["recipes_by_slot"].values())
    w2_day1_recipes = set(run2["days"][0]["recipes_by_slot"].values())
    assert len(w1_day5_recipes & w2_day1_recipes) == 0, (
        f"Expected 0 immediate Day 5 -> Day 1 recipe repeats, got {w1_day5_recipes & w2_day1_recipes}"
    )
    assert run2["history_context"]["comparison"]["boundary_day5_to_day1_repeat_count"] == 0
    # Must NOT be an identical verbatim copy of Week 1
    w1_seq = [d["recipes_by_slot"] for d in run1["days"]]
    w2_seq = [d["recipes_by_slot"] for d in run2["days"]]
    assert w1_seq != w2_seq


def test_ac4_constrained_recipes_and_imperfect_history_never_false_infeasible() -> None:
    """AC #4: Limited recipe pool + imperfect prior history still produces a feasible validated Week 2."""
    planner = make_authenticated_client("perencana_menu")
    manager = make_authenticated_client("kepala_dapur")
    qc = make_authenticated_client("petugas_qc")
    ds_id = _create_multiweek_dataset(planner, qc, tag="AC4", constrained_recipes=True)

    w1_dates = ["2027-02-01", "2027-02-02", "2027-02-03", "2027-02-04", "2027-02-05"]
    _sc1, _run1, _rev1, assign1 = _create_approve_and_optionally_activate(
        planner,
        manager,
        ds_id=ds_id,
        name="Minggu 1 Terbatas",
        service_dates=w1_dates,
        max_repeat=3,
    )
    assert assign1 is not None

    prep_res = planner.post(
        "/api/v1/scenarios/prepare-next-week",
        json={"source_assignment_id": assign1["id"]},
    )
    assert prep_res.status_code == 201, prep_res.text
    prep = prep_res.json()
    assert prep["solver_status"] in {"OPTIMAL", "FEASIBLE"}
    assert prep["validation_passed"] is True


def test_ac5_per_date_expiry_prevents_using_expired_lots_on_later_days() -> None:
    """AC #5: Lots expiring mid-week are excluded on/after expiry by both MILP and independent verifier."""
    planner = make_authenticated_client("perencana_menu")
    qc = make_authenticated_client("petugas_qc")

    # MW_P3 (Tempe - cheapest protein!) expires on 2027-02-17 -> valid ONLY on Day 1 (2027-02-15) & Day 2 (2027-02-16)
    ds_id = _create_multiweek_dataset(
        planner,
        qc,
        tag="AC5",
        expiry_by_code={"MW_P3": "2027-02-17T00:00:00Z"},
    )
    dates = ["2027-02-15", "2027-02-16", "2027-02-17", "2027-02-18", "2027-02-19"]
    sc = planner.post(
        "/api/v1/scenarios",
        json={
            "name": "Uji Kedaluwarsa Per Tanggal",
            "dataset_version_id": ds_id,
            "nutrition_target_id": str(DEMO_TARGET_ID),
            "servings_per_day": 50,
            "days": 5,
            "service_dates": dates,
            "budget_idr_per_serving": 18000,
            "max_repeat_per_family": 2,
        },
    ).json()
    run = planner.post(f"/api/v1/scenarios/{sc['id']}/optimize").json()
    assert run["validation_passed"] is True, run
    assert run["constraint_audit"]["all_hard_constraints_pass"] is True

    # Days 3, 4, 5 (2027-02-17..19) MUST NOT serve Tempe Bacem (MW_P3 expired!)
    for dp in run["days"]:
        if dp["service_date"] >= "2027-02-17":
            assert "Tempe" not in dp["recipe_names_by_slot"]["protein"], (
                f"Expired Tempe was scheduled on {dp['service_date']}!"
            )

    # Also verify: if ALL proteins expire before Day 3, optimizer MUST return INFEASIBLE (never serve expired!)
    ds_all_exp = _create_multiweek_dataset(
        planner,
        qc,
        tag="AC5B",
        expiry_by_code={
            "MW_P1": "2027-02-17T00:00:00Z",
            "MW_P2": "2027-02-17T00:00:00Z",
            "MW_P3": "2027-02-17T00:00:00Z",
            "MW_P4": "2027-02-17T00:00:00Z",
        },
    )
    sc_exp = planner.post(
        "/api/v1/scenarios",
        json={
            "name": "Semua Protein Kedaluwarsa Hari 3",
            "dataset_version_id": ds_all_exp,
            "nutrition_target_id": str(DEMO_TARGET_ID),
            "servings_per_day": 50,
            "days": 5,
            "service_dates": dates,
            "budget_idr_per_serving": 18000,
            "max_repeat_per_family": 2,
        },
    ).json()
    run_exp = planner.post(f"/api/v1/scenarios/{sc_exp['id']}/optimize").json()
    assert run_exp["solver_status"] == "INFEASIBLE"
    assert run_exp["validation_passed"] is False


def test_ac6_cross_period_stock_no_double_allocation_no_double_subtraction_and_warning() -> None:
    """AC #6: Unfinished Week 1 commits stock so Week 2 cannot double-allocate; reservations & recorded
    consumption are NOT double-subtracted; promised supplier deliveries are NOT counted; warning is shown."""
    planner = make_authenticated_client("perencana_menu")
    manager = make_authenticated_client("kepala_dapur")
    qc = make_authenticated_client("petugas_qc")

    # Tight rice stock: 25 kg total (both MWR_S1 and MWR_S3 use MW_S1).
    # Week 1 needs ~12.75 kg and Week 2 needs at least 11.25 kg, leaving tight ~12.25 kg budget.
    # Plus a PROMISED supplier delivery of 50 kg that MUST NOT be counted as ready stock!
    ds_id = _create_multiweek_dataset(
        planner,
        qc,
        tag="AC6",
        stock_kg={"MW_S1": 25.0},
    )
    assert db_manager.SessionLocal is not None
    with db_manager.SessionLocal() as session:
        ing_s1 = session.execute(
            select(IngredientORM).where(
                IngredientORM.dataset_version_id == ds_id,
                IngredientORM.code == "MW_S1",
            )
        ).scalar_one()
        session.add(
            SupplierDeliveryORM(
                id=str(uuid4()),
                kitchen_id=str(DEMO_KITCHEN_A_ID),
                dataset_version_id=ds_id,
                ingredient_id=ing_s1.id,
                supplier_name="Pemasok Janji Simulasi",
                delivery_ref="PO-PROMISED-01",
                expected_raw_g=50000.0,
                received_raw_g=0.0,
                original_value=50.0,
                original_unit="kg",
                expected_at=datetime(2027, 3, 2, 8, 0, tzinfo=timezone.utc),
                status="PROMISED",
                idempotency_key=f"PROM-{uuid4().hex[:8]}",
            )
        )
        session.commit()

    w1_dates = ["2027-03-01", "2027-03-02", "2027-03-03", "2027-03-04", "2027-03-05"]
    _sc1, run1, rev1, assign1 = _create_approve_and_optionally_activate(
        planner,
        manager,
        ds_id=ds_id,
        name="Minggu 1 Stok Ketat",
        service_dates=w1_dates,
        servings_per_day=50,
    )
    assert assign1 is not None
    w1_s1_used = next(
        (m["used_raw_g"] for m in run1["material_usage"] if m["ingredient_code"] == "MW_S1"),
        0.0,
    )
    assert w1_s1_used > 0

    # Prepare Week 2 while Week 1 is unfinished (future dates 2027-03-01..05 >= today)
    prep = planner.post(
        "/api/v1/scenarios/prepare-next-week",
        json={"source_assignment_id": assign1["id"]},
    )
    assert prep.status_code == 201, prep.text
    prep_body = prep.json()
    assert prep_body["validation_passed"] is True
    assert prep_body["stock_confirmation_required"] is True
    assert prep_body["stock_confirmation_reason"] is not None

    # Verify Week 2's effective stock for MW_S1 deducted Week 1's uncommitted usage (no double-allocation,
    # and PROMISED 50 kg delivery was NOT counted!)
    run2 = planner.get(f"/api/v1/runs/{prep_body['run_id']}").json()
    w2_s1_avail = run2["input_snapshot"]["stock_raw_g"]["MW_S1"]
    assert w2_s1_avail == pytest.approx(max(0.0, 25000.0 - w1_s1_used), abs=1.0)
    w2_s1_used = next(
        (m["used_raw_g"] for m in run2["material_usage"] if m["ingredient_code"] == "MW_S1"),
        0.0,
    )
    assert w1_s1_used + w2_s1_used <= 25000.0 + 1e-3

    # Now verify NO DOUBLE-SUBTRACTION when reservation + actual PRODUCTION_CONSUMPTION exist for Week 1:
    with db_manager.SessionLocal() as session:
        ing_s1 = session.execute(
            select(IngredientORM).where(
                IngredientORM.dataset_version_id == ds_id,
                IngredientORM.code == "MW_S1",
            )
        ).scalar_one()
        lot_s1 = session.execute(
            select(InventoryLotORM).where(
                InventoryLotORM.dataset_version_id == ds_id,
                InventoryLotORM.ingredient_id == ing_s1.id,
            )
        ).scalar_one()
        # Simulate 2 kg already consumed during Week 1 (reduces recorded_raw_g by 2000 g + records movement)
        consumed_g = min(2000.0, w1_s1_used / 2.0)
        lot_s1.recorded_raw_g -= consumed_g
        lot_s1.verified_physical_raw_g = lot_s1.recorded_raw_g
        session.add(
            InventoryMovementORM(
                id=str(uuid4()),
                kitchen_id=str(DEMO_KITCHEN_A_ID),
                dataset_version_id=ds_id,
                ingredient_id=ing_s1.id,
                lot_id=lot_s1.id,
                movement_type="PRODUCTION_CONSUMPTION",
                quantity_delta_raw_g=-consumed_g,
                original_value=consumed_g / 1000.0,
                original_unit="kg",
                idempotency_key=f"CONS-{uuid4().hex[:8]}",
                event_at=datetime(2027, 3, 2, 8, 0, tzinfo=timezone.utc),
                quarantined=False,
            )
        )
        # Simulate 1 kg reserved for Week 1's menu_review_id
        reserved_g = min(1000.0, max(0.0, w1_s1_used - consumed_g))
        if reserved_g > 0:
            session.add(
                StockReservationORM(
                    id=str(uuid4()),
                    kitchen_id=str(DEMO_KITCHEN_A_ID),
                    dataset_version_id=ds_id,
                    ingredient_id=ing_s1.id,
                    lot_id=lot_s1.id,
                    menu_review_id=rev1["id"],
                    reserved_raw_g=reserved_g,
                    production_date=datetime(2027, 3, 1, 8, 0, tzinfo=timezone.utc),
                    status="ACTIVE",
                    idempotency_key=f"RES-{uuid4().hex[:8]}",
                )
            )
        session.commit()

        ctx = compute_cross_period_stock_context(
            session,
            kitchen_id=DEMO_KITCHEN_A_ID,
            dataset_version_id=UUID(ds_id),
            service_dates=[date(2027, 3, 8), date(2027, 3, 9)],
        )
        # Net remaining for Week 2 MUST STILL equal (25000 - w1_s1_used), NOT (25000 - w1_s1_used - consumed_g - reserved_g)!
        assert ctx.effective_stock["MW_S1"] == pytest.approx(
            max(0.0, 25000.0 - w1_s1_used), abs=1.0
        )


def test_ac7_safety_hold_lots_excluded_in_next_week() -> None:
    """AC #7: Lots placed on SAFETY HOLD are excluded from Week 2 usable stock."""
    planner = make_authenticated_client("perencana_menu")
    manager = make_authenticated_client("kepala_dapur")
    qc = make_authenticated_client("petugas_qc")
    ds_id = _create_multiweek_dataset(planner, qc, tag="AC7")

    w1_dates = ["2027-03-15", "2027-03-16", "2027-03-17", "2027-03-18", "2027-03-19"]
    _sc1, _run1, _rev1, assign1 = _create_approve_and_optionally_activate(
        planner, manager, ds_id=ds_id, name="Minggu 1 AC7", service_dates=w1_dates
    )
    assert assign1 is not None

    # Hold MW_P3 (Tempe - cheapest protein) via incident
    inc = qc.post(
        "/api/v1/incidents",
        json={
            "title": "Tempe Berjamur AC7",
            "category": "SPOILAGE",
            "severity": "HIGH",
            "dataset_version_id": ds_id,
            "affected_lots": [{"lot_code": "LOT-AC7-MW_P3"}],
            "auto_hold_matching_lots": False,
        },
    )
    assert inc.status_code == 201, inc.text

    prep = planner.post(
        "/api/v1/scenarios/prepare-next-week",
        json={"source_assignment_id": assign1["id"]},
    )
    assert prep.status_code == 201, prep.text
    run2 = planner.get(f"/api/v1/runs/{prep.json()['run_id']}").json()
    assert run2["validation_passed"] is True
    assert run2["input_snapshot"]["stock_raw_g"]["MW_P3"] == pytest.approx(0.0)
    used_codes = {m["ingredient_code"] for m in run2["material_usage"] if m["used_raw_g"] > 0}
    assert "MW_P3" not in used_codes


def test_ac8_block_overlapping_active_plans_same_dates_and_scope() -> None:
    """AC #8: Activating a second plan that overlaps ANY service date of an active plan returns 409."""
    planner = make_authenticated_client("perencana_menu")
    manager = make_authenticated_client("kepala_dapur")
    qc = make_authenticated_client("petugas_qc")
    ds_id = _create_multiweek_dataset(planner, qc, tag="AC8")

    w1_dates = ["2027-04-05", "2027-04-06", "2027-04-07", "2027-04-08", "2027-04-09"]
    _sc1, _run1, _rev1, assign1 = _create_approve_and_optionally_activate(
        planner, manager, ds_id=ds_id, name="Minggu 1 AC8", service_dates=w1_dates
    )
    assert assign1 is not None

    # Second plan starts Thursday 2027-04-08 (overlaps Thu & Fri with Week 1!)
    overlap_dates = ["2027-04-08", "2027-04-09", "2027-04-12", "2027-04-13", "2027-04-14"]
    _sc2, _run2, rev2, _ = _create_approve_and_optionally_activate(
        planner,
        manager,
        ds_id=ds_id,
        name="Rencana Tumpang Tindih",
        service_dates=overlap_dates,
        activate=False,
    )
    # Approval did NOT auto-activate because of date overlap
    assert rev2["operational_status"] == "APPROVED_NOT_ACTIVE"

    # Explicit activation MUST be blocked with 409 Conflict
    act_conflict = manager.post(
        "/api/v1/operational-plans/activate",
        json={"menu_review_id": rev2["id"]},
    )
    assert act_conflict.status_code == 409, act_conflict.text
    assert "tumpang tindih" in act_conflict.json()["detail"].lower()

    # Week 1 stays ACTIVE on 2027-04-08
    eff = manager.get(
        "/api/v1/operational-plans/effective",
        params={"dataset_version_id": ds_id, "service_date": "2027-04-08"},
    ).json()
    assert eff["active_plan"]["id"] == assign1["id"]


def test_ac9_reject_activation_when_stock_changes_after_optimization() -> None:
    """AC #9: Activation is rejected (409) if stock changes / drops after optimization."""
    planner = make_authenticated_client("perencana_menu")
    manager = make_authenticated_client("kepala_dapur")
    qc = make_authenticated_client("petugas_qc")
    ds_id = _create_multiweek_dataset(planner, qc, tag="AC9")

    w1_dates = ["2027-04-19", "2027-04-20", "2027-04-21", "2027-04-22", "2027-04-23"]
    _sc1, _run1, _rev1, assign1 = _create_approve_and_optionally_activate(
        planner, manager, ds_id=ds_id, name="Minggu 1 AC9", service_dates=w1_dates
    )
    assert assign1 is not None

    prep = planner.post(
        "/api/v1/scenarios/prepare-next-week",
        json={"source_assignment_id": assign1["id"]},
    ).json()
    rev2_id = prep["menu_review_id"]
    assert planner.post(f"/api/v1/menu-reviews/{rev2_id}/submit").status_code == 200
    app_res = manager.post(
        f"/api/v1/menu-reviews/{rev2_id}/review",
        json={"decision": "APPROVED", "reviewer_notes": "Setujui Minggu 2 sebelum stok berubah"},
    )
    assert app_res.status_code == 200
    assert app_res.json()["operational_status"] == "APPROVED_NOT_ACTIVE"

    # Now custodian records damage changing usable stock after optimization/approval
    adj = qc.post(
        "/api/v1/inventory/adjustments",
        json={
            "dataset_version_id": ds_id,
            "ingredient_code": "MW_S1",
            "lot_code": "LOT-AC9-MW_S1",
            "adjustment_type": "SPOILAGE_DAMAGE",
            "quantity": 195.0,
            "unit": "kg",
            "notes": "Beras terkena bocor atap gudang",
        },
    )
    assert adj.status_code == 200, adj.text

    # Activation MUST be rejected with 409 Conflict (stale snapshot / stock insufficient)
    act_res = manager.post(
        "/api/v1/operational-plans/activate",
        json={"menu_review_id": rev2_id},
    )
    assert act_res.status_code == 409, act_res.text


def test_ac10_preserve_week1_version_and_use_post_recovery_active_history() -> None:
    """AC #10: Previous week version is preserved; Week 2 reads post-Recovery active replacement history
    (not superseded pre-recovery draft)."""
    planner = make_authenticated_client("perencana_menu")
    manager = make_authenticated_client("kepala_dapur")
    qc = make_authenticated_client("petugas_qc")
    ds_id = _create_multiweek_dataset(planner, qc, tag="AC10")

    w1_dates = ["2027-05-03", "2027-05-04", "2027-05-05", "2027-05-06", "2027-05-07"]
    _sc1, run1, rev1, assign1 = _create_approve_and_optionally_activate(
        planner, manager, ds_id=ds_id, name="Minggu 1 v1 Awal", service_dates=w1_dates
    )
    assert assign1 is not None

    # Hold one of Week 1's used protein ingredients (Tempe MW_P3) -> Week 1 goes ON_HOLD
    inc = qc.post(
        "/api/v1/incidents",
        json={
            "title": "Insiden Tempe Minggu 1 AC10",
            "category": "SPOILAGE",
            "severity": "CRITICAL",
            "dataset_version_id": ds_id,
            "affected_lots": [{"lot_code": "LOT-AC10-MW_P3"}],
            "auto_hold_matching_lots": False,
        },
    )
    assert inc.status_code == 201, inc.text
    inc_id = inc.json()["id"]

    # Recover & activate replacement v2 for Week 1
    rec = planner.post(
        f"/api/v1/incidents/{inc_id}/start-recovery",
        json={"production_date": "2027-05-03T08:00:00Z"},
    )
    assert rec.status_code == 201, rec.text
    ev = rec.json()
    assert ev["status"] == "ANALYZED", ev

    sub_rec = planner.post(
        f"/api/v1/recovery/events/{ev['id']}/submit",
        json={"mode": "MIN_DISRUPTION", "title": "Minggu 1 v2 Pemulihan", "submit_for_review": True},
    )
    assert sub_rec.status_code == 200, sub_rec.text
    rev_v2_id = sub_rec.json()["review"]["id"]
    run_v2_id = sub_rec.json()["review"]["run_id"]

    app_v2 = manager.post(
        f"/api/v1/menu-reviews/{rev_v2_id}/review",
        json={"decision": "APPROVED", "reviewer_notes": "Setujui pemulihan"},
    )
    assert app_v2.status_code == 200, app_v2.text

    act_v2 = manager.post(
        "/api/v1/operational-plans/activate",
        json={"menu_review_id": rev_v2_id},
    )
    assert act_v2.status_code == 200, act_v2.text
    assign_v2 = act_v2.json()
    assert assign_v2["supersedes_assignment_id"] == assign1["id"]

    # Confirm v1 is preserved as SUPERSEDED (not deleted!)
    all_plans = manager.get(f"/api/v1/operational-plans?dataset_version_id={ds_id}").json()
    by_id = {p["id"]: p for p in all_plans}
    assert by_id[assign1["id"]]["operational_status"] == "SUPERSEDED"
    assert by_id[assign_v2["id"]]["operational_status"] == "ACTIVE"

    # Prepare Week 2: history MUST reference v2 (post-Recovery active run), NOT superseded v1!
    prep2 = planner.post(
        "/api/v1/scenarios/prepare-next-week",
        json={"source_assignment_id": assign_v2["id"]},
    )
    assert prep2.status_code == 201, prep2.text
    hctx = prep2.json()["history_context"]
    assert hctx["previous_run_id"] == run_v2_id
    assert hctx["previous_run_id"] != run1["run_id"]
    assert hctx["previous_plan_title"] == "Minggu 1 v2 Pemulihan"


def test_ac11_ac12_ac13_manual_approval_non_disruption_and_qc_date_binding() -> None:
    """AC #11, AC #12, AC #13:
    - Submitting/approving Week 2 NEVER modifies/deactivates running Week 1.
    - Non-managers get 403 on activation; unapproved reviews get 409.
    - QC resolves the exact active plan and day_index by service_date and rejects mismatches (409).
    - Submitted QC execution upgrades future history source from OPERATIONAL_PLAN to VERIFIED_EXECUTION/MIXED.
    """
    planner = make_authenticated_client("perencana_menu")
    manager = make_authenticated_client("kepala_dapur")
    qc = make_authenticated_client("petugas_qc")
    ds_id = _create_multiweek_dataset(planner, qc, tag="AC1113")

    w1_dates = ["2027-05-17", "2027-05-18", "2027-05-19", "2027-05-20", "2027-05-21"]
    _sc1, run1, rev1, assign1 = _create_approve_and_optionally_activate(
        planner, manager, ds_id=ds_id, name="Minggu 1 Berjalan", service_dates=w1_dates
    )
    assert assign1 is not None

    # Prepare Week 2 (DRAFT)
    prep2 = planner.post(
        "/api/v1/scenarios/prepare-next-week",
        json={"source_assignment_id": assign1["id"], "name": "Minggu 2 Mendatang"},
    ).json()
    rev2_id = prep2["menu_review_id"]
    run2_id = prep2["run_id"]
    w2_dates = prep2["service_dates"]
    assert w2_dates == ["2027-05-24", "2027-05-25", "2027-05-26", "2027-05-27", "2027-05-28"]

    # AC #12: Planner & QC get 403 on activation; Manager gets 409 on DRAFT
    assert planner.post("/api/v1/operational-plans/activate", json={"menu_review_id": rev2_id}).status_code == 403
    assert qc.post("/api/v1/operational-plans/activate", json={"menu_review_id": rev2_id}).status_code == 403
    assert manager.post("/api/v1/operational-plans/activate", json={"menu_review_id": rev2_id}).status_code == 409

    # Submit Week 2 -> AC #13: Week 1 MUST remain ACTIVE and untouched
    assert planner.post(f"/api/v1/menu-reviews/{rev2_id}/submit").status_code == 200
    assert manager.post("/api/v1/operational-plans/activate", json={"menu_review_id": rev2_id}).status_code == 409
    eff_w1_check1 = qc.get(
        "/api/v1/operational-plans/effective",
        params={"dataset_version_id": ds_id, "service_date": "2027-05-19"},
    ).json()
    assert eff_w1_check1["active_plan"]["id"] == assign1["id"]
    assert eff_w1_check1["matched_day_index"] == 3

    # Manager approves Week 2 -> stays APPROVED_NOT_ACTIVE (NO auto-activation!) & Week 1 untouched
    app2 = manager.post(
        f"/api/v1/menu-reviews/{rev2_id}/review",
        json={"decision": "APPROVED", "reviewer_notes": "Siap diaktifkan untuk Minggu 2"},
    )
    assert app2.status_code == 200, app2.text
    assert app2.json()["operational_status"] == "APPROVED_NOT_ACTIVE"

    # QC cannot run routine inspection on APPROVED_NOT_ACTIVE Week 2 yet (409)
    qc_unactive = qc.post(
        "/api/v1/qc/inspections",
        json={"run_id": run2_id, "menu_review_id": rev2_id, "day_index": 1, "service_date": "2027-05-24"},
    )
    assert qc_unactive.status_code == 409

    # Manager explicitly activates Week 2 -> both non-overlapping weeks are ACTIVE on their respective dates!
    act2 = manager.post(
        "/api/v1/operational-plans/activate",
        json={"menu_review_id": rev2_id, "notes": "Aktifkan Minggu 2"},
    )
    assert act2.status_code == 200, act2.text
    assign2 = act2.json()
    assert assign2["operational_status"] == "ACTIVE"

    # AC #11: QC resolves Week 1 on 2027-05-19 (Day 3) and Week 2 on 2027-05-26 (Day 3)
    eff_w1 = qc.get(
        "/api/v1/operational-plans/effective",
        params={"dataset_version_id": ds_id, "service_date": "2027-05-19"},
    ).json()
    assert eff_w1["active_plan"]["id"] == assign1["id"]
    assert eff_w1["matched_day_index"] == 3

    eff_w2 = qc.get(
        "/api/v1/operational-plans/effective",
        params={"dataset_version_id": ds_id, "service_date": "2027-05-26"},
    ).json()
    assert eff_w2["active_plan"]["id"] == assign2["id"]
    assert eff_w2["matched_day_index"] == 3

    # QC inspection with wrong day_index for service_date -> 409 Conflict
    qc_bad_day = qc.post(
        "/api/v1/qc/inspections",
        json={"run_id": run2_id, "menu_review_id": rev2_id, "day_index": 1, "service_date": "2027-05-26"},
    )
    assert qc_bad_day.status_code == 409

    # QC inspection with matching service_date & day_index -> 201 Created with service_date echoed
    qc_ok = qc.post(
        "/api/v1/qc/inspections",
        json={"run_id": run2_id, "menu_review_id": rev2_id, "day_index": 3, "service_date": "2027-05-26"},
    )
    assert qc_ok.status_code == 201, qc_ok.text
    assert qc_ok.json()["service_date"] == "2027-05-26"

    # Also verify Priority 1 trust order: if a QC inspection on Week 2 Day 3 is SUBMITTED, Week 3 defaults
    # report MIXED (combining verified execution + operational plan)!
    from PIL import Image
    import io

    img = Image.new("RGB", (64, 64), color=(120, 180, 90))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    insp_id = qc_ok.json()["id"]
    assert (
        qc.post(
            f"/api/v1/qc/inspections/{insp_id}/images",
            files={"file": ("tray.jpg", buf.getvalue(), "image/jpeg")},
        ).status_code
        == 201
    )
    expected_slots = qc_ok.json()["expected_menu"]
    assert (
        qc.patch(
            f"/api/v1/qc/inspections/{insp_id}/observations",
            json={
                "corrected_components": [
                    {
                        "slot": s["slot"],
                        "confirmed_status": "visible",
                        "observed_food_name": s["recipe_name"],
                    }
                    for s in expected_slots
                ],
                "notes": "Terverifikasi fisik oleh QC",
            },
        ).status_code
        == 200
    )
    assert qc.post(f"/api/v1/qc/inspections/{insp_id}/submit").status_code == 200

    defs_w3 = planner.get(
        "/api/v1/scenarios/next-week-defaults",
        params={"source_assignment_id": assign2["id"]},
    ).json()
    assert defs_w3["history_source_type"] == "MIXED"
