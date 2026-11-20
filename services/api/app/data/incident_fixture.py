from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.data.synthetic_fixture import DEMO_TARGET_ID, build_demo_dataset
from app.db.models import (
    DatasetSourceORM,
    DatasetStockSnapshotORM,
    DatasetVersionORM,
    IngredientNutrientORM,
    IngredientORM,
    IngredientPriceORM,
    InventoryLotORM,
    InventoryMovementORM,
    MenuReviewRecordORM,
    OperationalPlanAssignmentORM,
    RecipeIngredientORM,
    RecipeVariantORM,
    ScenarioORM,
    UserORM,
)
from app.db.repository import SQLiteVaultRepository
from app.domain.models.schemas import ScenarioCreateRequest, SourceTypeEnum
from app.ingestion.unit_converter import convert_price_to_idr_per_g
from app.inventory.service import compute_usable_inventory
from app.operations.service import derive_production_scope
from app.recovery.snapshot import compute_usable_inventory_sha256

INCIDENT_DEMO_DATASET_ID = UUID("55555555-5555-4555-8555-555555555555")
DEFAULT_KITCHEN_A_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1")
DEFAULT_INCIDENT_PROD_DATE = datetime(2026, 11, 23, 8, 0, tzinfo=timezone.utc)


def seed_incident_demo_dataset(
    session: Session,
    *,
    kitchen_id: UUID = DEFAULT_KITCHEN_A_ID,
    reference_now: datetime = DEFAULT_INCIDENT_PROD_DATE,
) -> UUID:
    """Idempotently seed the Sprint 3C Triple-Ingredient Safety Incident demo dataset (DEMO_ONLY).

    Establishes:
    1. DatasetVersion (INCIDENT_DEMO_DATASET_ID) scoped to kitchen_id with multi-lot batch ledger:
       - Daging Ayam Fillet (ING007) split across LOT-3C-AYAM-A (24.0 kg) and LOT-3C-AYAM-B (16.0 kg)
       - Telur Ayam Ras (ING006) in LOT-3C-TELUR-A (40.0 kg)
       - Bayam Segar (ING012) in LOT-3C-BAYAM-A (40.0 kg)
       - Ample clean verified stock (>= 180 kg) for substitute proteins & vegetables.
    2. Baseline APPROVED + ACTIVE operational weekly plan (200 servings/day x 5 days = 1,000 servings)
       priced so ING007 (Chicken), ING006 (Eggs), and ING012 (Spinach) are selected in the active baseline.
    """
    existing = session.get(DatasetVersionORM, str(INCIDENT_DEMO_DATASET_ID))
    if existing is not None:
        return INCIDENT_DEMO_DATASET_ID

    _, base_ings, base_prices, base_stock, base_recipes, _ = build_demo_dataset()

    source_id = str(uuid4())
    session.add(
        DatasetSourceORM(
            id=source_id,
            kitchen_id=str(kitchen_id),
            source_name="GiziOptima Incident Recovery Triple Fixture v1 (DEMO_ONLY)",
            source_url="repo://services/api/app/data/incident_fixture.py",
            license="PROJECT_AUTHORED_INTERNAL_DEMO",
            license_verified=True,
            dataset_type="synthetic",
            retrieved_at=reference_now,
            checksum="incident-triple-safety-v1",
            allowed_use="DEV_AND_QA_SYNTHETIC_ONLY",
            transformation_notes=(
                "Deterministic Sprint 3C triple-ingredient safety incident fixture: "
                "Ayam (24kg A + 16kg B), Telur (40kg), Bayam (40kg) active baseline (DEMO_ONLY)."
            ),
            created_at=reference_now,
        )
    )

    session.add(
        DatasetVersionORM(
            id=str(INCIDENT_DEMO_DATASET_ID),
            kitchen_id=str(kitchen_id),
            name="Dataset Simulasi Insiden Bahan Pangan 3C (Ayam+Telur+Bayam — DEMO_ONLY)",
            source_type="synthetic",
            source_url="repo://services/api/app/data/incident_fixture.py",
            is_synthetic=True,
            is_active=False,
            review_status="reviewed",
            ingestion_metadata_json={
                "seeded": True,
                "label": "DEMO_ONLY",
                "sprint": "3C",
                "scenario_story": "triple_ingredient_incident",
            },
            created_at=reference_now - timedelta(hours=8),
        )
    )
    session.flush()

    demo_price_overrides_idr_per_kg = {
        "ING006": 24000.0,  # Telur Ayam Ras
        "ING007": 28000.0,  # Daging Ayam Fillet
        "ING012": 9000.0,   # Bayam Segar
    }

    ing_id_by_code: dict[str, str] = {}
    for code, ing in base_ings.items():
        ing_id = str(uuid4())
        ing_id_by_code[code] = ing_id
        session.add(
            IngredientORM(
                id=ing_id,
                dataset_version_id=str(INCIDENT_DEMO_DATASET_ID),
                code=ing.code,
                name=ing.name,
                category=ing.category,
                edible_fraction=ing.edible_fraction,
                allergens_json=list(ing.allergens),
                source_type=ing.source_type.value,
                source_ref="DEMO_ONLY Sprint 3C",
                review_status=ing.review_status.value,
            )
        )
    session.flush()

    for code, ing in base_ings.items():
        session.add(
            IngredientNutrientORM(
                ingredient_id=ing_id_by_code[code],
                energy_kcal_100g=ing.nutrients.energy_kcal_100g,
                protein_g_100g=ing.nutrients.protein_g_100g,
                fat_g_100g=ing.nutrients.fat_g_100g,
                carb_g_100g=ing.nutrients.carb_g_100g,
                fiber_g_100g=ing.nutrients.fiber_g_100g,
                iron_mg_100g=ing.nutrients.iron_mg_100g,
            )
        )

    for code, pr in base_prices.items():
        orig_val = demo_price_overrides_idr_per_kg.get(code, pr.original_value)
        per_g = (
            convert_price_to_idr_per_g(orig_val, "IDR/kg")
            if code in demo_price_overrides_idr_per_kg
            else pr.price_idr_per_g
        )
        session.add(
            IngredientPriceORM(
                id=str(uuid4()),
                dataset_version_id=str(INCIDENT_DEMO_DATASET_ID),
                ingredient_id=ing_id_by_code[code],
                price_idr_per_g=per_g,
                original_value=orig_val,
                original_unit="IDR/kg" if code in demo_price_overrides_idr_per_kg else pr.original_unit,
                region=pr.region,
                observed_at=pr.observed_at,
                source_type=pr.source_type.value,
            )
        )

    for code, st in base_stock.items():
        snap_g = (
            40000.0
            if code in {"ING006", "ING007", "ING012"}
            else max(st.stock_raw_g, 180000.0)
        )
        session.add(
            DatasetStockSnapshotORM(
                id=str(uuid4()),
                dataset_version_id=str(INCIDENT_DEMO_DATASET_ID),
                ingredient_id=ing_id_by_code[code],
                stock_raw_g=snap_g,
                recorded_at=reference_now - timedelta(hours=6),
            )
        )

    for rec in base_recipes:
        rec_id = str(uuid4())
        session.add(
            RecipeVariantORM(
                id=rec_id,
                dataset_version_id=str(INCIDENT_DEMO_DATASET_ID),
                code=rec.code,
                name=rec.name,
                slot=rec.slot.value,
                family=rec.family,
                review_status=rec.review_status.value,
                reviewer=rec.reviewer,
                reviewed_at=rec.reviewed_at,
                active=rec.active,
                allergen_tags_json=list(rec.allergen_tags),
            )
        )
        session.flush()
        for item in rec.ingredients:
            raw_g = (
                80.0
                if (rec.code == "R006" and item.ingredient_code == "ING007")
                else item.raw_g_per_serving
            )
            session.add(
                RecipeIngredientORM(
                    recipe_id=rec_id,
                    ingredient_id=ing_id_by_code[item.ingredient_code],
                    raw_g_per_serving=raw_g,
                    retention_factor=item.retention_factor,
                )
            )
    session.flush()

    # Step 2: Optimize clean baseline BEFORE adding holds so ING007, ING006, and ING012 are selected cleanly
    repo = SQLiteVaultRepository(session)
    baseline_sc = repo.create_scenario(
        ScenarioCreateRequest(
            name="Rencana Mingguan SPPG-A (Baseline Aman Sebelum Insiden 3C)",
            dataset_version_id=INCIDENT_DEMO_DATASET_ID,
            nutrition_target_id=DEMO_TARGET_ID,
            servings_per_day=200,
            days=5,
            budget_idr_per_serving=16500.0,
            max_repeat_per_family=2,
            excluded_allergens=[],
            source_label=SourceTypeEnum.SYNTHETIC,
            production_date=reference_now,
        ),
        kitchen_id=kitchen_id,
    )
    baseline_run = repo.run_optimization(baseline_sc.id, kitchen_id=kitchen_id)

    # Step 3: Seed multi-lot verified batch ledger (all clean initially so tests/UI trigger incident live)
    for code, st in base_stock.items():
        ing_id = ing_id_by_code[code]
        if code == "ING007":
            lots_spec = [
                ("LOT-3C-AYAM-A", 24000.0, "Cold Storage Rak 1 (Supplier Ayam Prima — Lot A)"),
                ("LOT-3C-AYAM-B", 16000.0, "Cold Storage Rak 2 (Supplier Cadangan — Lot B Bersih)"),
            ]
        elif code == "ING006":
            lots_spec = [
                ("LOT-3C-TELUR-A", 40000.0, "Rak Kering B1 (Pemasok Telur Sejahtera)"),
            ]
        elif code == "ING012":
            lots_spec = [
                ("LOT-3C-BAYAM-A", 40000.0, "Chiller Sayur C1 (Kebun Segar)"),
            ]
        else:
            qty_g = max(st.stock_raw_g, 180000.0)
            lots_spec = [
                (f"LOT-3C-{code}-01", qty_g, "Gudang Utama SPPG-A"),
            ]

        for idx, (lot_code, qty_g, loc) in enumerate(lots_spec):
            lot_id = str(uuid4())
            session.add(
                InventoryLotORM(
                    id=lot_id,
                    kitchen_id=str(kitchen_id),
                    dataset_version_id=str(INCIDENT_DEMO_DATASET_ID),
                    ingredient_id=ing_id,
                    source_id=source_id,
                    lot_code=lot_code,
                    recorded_raw_g=qty_g,
                    verified_physical_raw_g=qty_g,
                    damaged_raw_g=0.0,
                    expires_at=reference_now + timedelta(days=365 if code != "ING012" else 7),
                    expiry_known=True,
                    received_at=reference_now - timedelta(hours=6),
                    verified_at=reference_now - timedelta(hours=5),
                    verification_status="VERIFIED",
                    safety_hold_status="NONE",
                    data_classification="synthetic",
                    unit_original="kg",
                    quantity_original=round(qty_g / 1000.0, 3),
                    notes=f"{loc} • Mitra Pangan Simulasi (DEMO_ONLY) — Batch awal bersih terverifikasi sebelum insiden",
                    created_at=reference_now - timedelta(hours=6),
                )
            )
            session.add(
                InventoryMovementORM(
                    id=str(uuid4()),
                    kitchen_id=str(kitchen_id),
                    dataset_version_id=str(INCIDENT_DEMO_DATASET_ID),
                    ingredient_id=ing_id,
                    lot_id=lot_id,
                    source_id=source_id,
                    movement_type="OPENING_BALANCE",
                    quantity_delta_raw_g=qty_g,
                    original_value=round(qty_g / 1000.0, 3),
                    original_unit="kg",
                    event_at=reference_now - timedelta(hours=6),
                    idempotency_key=f"INC-3C-OP-{lot_code}-{idx}",
                    source_document_ref=f"OP-3C-{lot_code}",
                    quarantined=False,
                    created_at=reference_now - timedelta(hours=6),
                )
            )
    session.flush()

    planner_row = session.execute(
        select(UserORM).where(UserORM.username == "perencana_menu")
    ).scalar_one_or_none()
    manager_row = session.execute(
        select(UserORM).where(UserORM.username == "kepala_dapur")
    ).scalar_one_or_none()
    if planner_row and manager_row and baseline_run.validation_passed:
        rev_id = str(uuid4())
        session.add(
            MenuReviewRecordORM(
                id=rev_id,
                kitchen_id=str(kitchen_id),
                scenario_id=str(baseline_sc.id),
                run_id=str(baseline_run.run_id),
                dataset_version_id=str(INCIDENT_DEMO_DATASET_ID),
                version_number=1,
                status="APPROVED",
                title="Menu Mingguan SPPG-A (Aktif — Ayam+Telur+Bayam)",
                planner_notes="Menu baseline 5 hari (200 porsi/hari = 1.000 porsi) menggunakan Ayam Fillet, Telur Ayam, dan Bayam Segar.",
                reviewer_notes="Disetujui dan diaktifkan untuk operasional minggu berjalan (DEMO_ONLY).",
                created_by_user_id=planner_row.id,
                submitted_by_user_id=planner_row.id,
                reviewed_by_user_id=manager_row.id,
                submitted_at=reference_now - timedelta(hours=4),
                reviewed_at=reference_now - timedelta(hours=2),
                created_at=reference_now - timedelta(hours=5),
                updated_at=reference_now - timedelta(hours=2),
            )
        )
        session.flush()
        sc_orm = session.execute(
            select(ScenarioORM).where(ScenarioORM.id == str(baseline_sc.id))
        ).scalar_one()
        scope = derive_production_scope(session, sc_orm)
        inv_summary = compute_usable_inventory(
            session,
            kitchen_id=kitchen_id,
            dataset_version_id=INCIDENT_DEMO_DATASET_ID,
            production_date=reference_now,
        )
        inv_sha = compute_usable_inventory_sha256(inv_summary)
        session.add(
            OperationalPlanAssignmentORM(
                id=str(uuid4()),
                kitchen_id=str(kitchen_id),
                dataset_version_id=str(INCIDENT_DEMO_DATASET_ID),
                menu_review_id=rev_id,
                run_id=str(baseline_run.run_id),
                scenario_id=str(baseline_sc.id),
                operational_status="ACTIVE",
                production_date=scope.production_date,
                horizon_days=scope.horizon_days,
                meal_type=scope.meal_type,
                target_cohort=scope.target_cohort,
                batch_label=scope.batch_label,
                active_scope_key=scope.scope_key,
                supersedes_assignment_id=None,
                hold_incident_id=None,
                hold_reason=None,
                held_at=None,
                activated_by_user_id=manager_row.id,
                activated_at=reference_now - timedelta(hours=2),
                superseded_at=None,
                inventory_snapshot_sha256=inv_sha,
                created_at=reference_now - timedelta(hours=2),
                updated_at=reference_now - timedelta(hours=2),
            )
        )

    session.commit()
    return INCIDENT_DEMO_DATASET_ID
