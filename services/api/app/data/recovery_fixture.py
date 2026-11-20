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
    SupplierDeliveryORM,
    UserORM,
)
from app.db.repository import SQLiteVaultRepository
from app.domain.models.schemas import ScenarioCreateRequest, SourceTypeEnum
from app.ingestion.unit_converter import convert_price_to_idr_per_g
from app.operations.service import derive_production_scope

RECOVERY_DEMO_DATASET_ID = UUID("44444444-4444-4444-8444-444444444444")
DEFAULT_KITCHEN_A_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1")
DEFAULT_RECOVERY_PROD_DATE = datetime(2026, 11, 20, 8, 0, tzinfo=timezone.utc)


def seed_recovery_demo_dataset(
    session: Session,
    *,
    kitchen_id: UUID = DEFAULT_KITCHEN_A_ID,
    reference_now: datetime = DEFAULT_RECOVERY_PROD_DATE,
) -> UUID:
    """Idempotently seed the Sprint 3B Partial Chicken Delivery demo scenario (DEMO_ONLY).

    Establishes:
    1. DatasetVersion (RECOVERY_DEMO_DATASET_ID) scoped to kitchen_id with verified lots.
    2. Baseline APPROVED weekly plan (250 servings/day x 5 days) originally optimized when
       Daging Ayam Fillet (ING007) had 20.00 kg available and R006 used exact 20.00 kg (80 g x 250).
    3. Subsequent PARTIAL supplier delivery event where only 12.00 kg arrived (8.00 kg short),
       leaving the approved plan intact in history while triggering an 8.00 kg shortage alert
       and feasible single-slot substitution recovery.
    """
    existing = session.get(DatasetVersionORM, str(RECOVERY_DEMO_DATASET_ID))
    if existing is not None:
        baseline_rev = session.execute(
            select(MenuReviewRecordORM).where(
                MenuReviewRecordORM.kitchen_id == str(kitchen_id),
                MenuReviewRecordORM.dataset_version_id == str(RECOVERY_DEMO_DATASET_ID),
                MenuReviewRecordORM.status == "APPROVED",
            )
            .order_by(MenuReviewRecordORM.reviewed_at.asc())
            .limit(1)
        ).scalar_one_or_none()
        if baseline_rev is not None:
            has_op = session.execute(
                select(OperationalPlanAssignmentORM).where(
                    OperationalPlanAssignmentORM.kitchen_id == str(kitchen_id),
                    OperationalPlanAssignmentORM.dataset_version_id == str(RECOVERY_DEMO_DATASET_ID),
                )
            ).scalars().first()
            if has_op is None:
                sc_orm = session.get(ScenarioORM, baseline_rev.scenario_id)
                if sc_orm is not None:
                    scope = derive_production_scope(session, sc_orm)
                    existing_scope = session.execute(
                        select(OperationalPlanAssignmentORM).where(
                            OperationalPlanAssignmentORM.active_scope_key == scope.scope_key
                        )
                    ).scalar_one_or_none()
                    if existing_scope is None:
                        session.add(
                            OperationalPlanAssignmentORM(
                                id=str(uuid4()),
                                kitchen_id=str(kitchen_id),
                                dataset_version_id=str(RECOVERY_DEMO_DATASET_ID),
                                menu_review_id=baseline_rev.id,
                                run_id=baseline_rev.run_id,
                                scenario_id=baseline_rev.scenario_id,
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
                                activated_by_user_id=baseline_rev.reviewed_by_user_id,
                                activated_at=baseline_rev.reviewed_at or reference_now,
                                superseded_at=None,
                                inventory_snapshot_sha256=None,
                                created_at=baseline_rev.reviewed_at or reference_now,
                                updated_at=baseline_rev.reviewed_at or reference_now,
                            )
                        )
                        session.commit()
        return RECOVERY_DEMO_DATASET_ID

    _, base_ings, base_prices, base_stock, base_recipes, _ = build_demo_dataset()

    source_id = str(uuid4())
    session.add(
        DatasetSourceORM(
            id=source_id,
            kitchen_id=str(kitchen_id),
            source_name="GiziOptima Recovery Partial Chicken Fixture v1 (DEMO_ONLY)",
            source_url="repo://services/api/app/data/recovery_fixture.py",
            license="PROJECT_AUTHORED_INTERNAL_DEMO",
            license_verified=True,
            dataset_type="synthetic",
            retrieved_at=reference_now,
            checksum="recovery-partial-chicken-v1",
            allowed_use="DEV_AND_QA_SYNTHETIC_ONLY",
            transformation_notes=(
                "Deterministic Sprint 3B partial chicken delivery demo: "
                "20 kg planned vs 12 kg verified delivered usable (DEMO_ONLY)."
            ),
            created_at=reference_now,
        )
    )

    session.add(
        DatasetVersionORM(
            id=str(RECOVERY_DEMO_DATASET_ID),
            kitchen_id=str(kitchen_id),
            name="Simulasi Pemulihan Ayam Parsial SPPG-A (DEMO_ONLY)",
            source_type="synthetic",
            source_url="repo://services/api/app/data/recovery_fixture.py",
            is_synthetic=True,
            is_active=False,
            review_status="reviewed",
            ingestion_metadata_json={
                "seeded": True,
                "label": "DEMO_ONLY",
                "sprint": "3B",
                "scenario_story": "partial_chicken_delivery",
            },
            created_at=reference_now,
        )
    )
    session.flush()

    ing_id_by_code: dict[str, str] = {}
    for code, ing in base_ings.items():
        ing_id = str(uuid4())
        ing_id_by_code[code] = ing_id
        session.add(
            IngredientORM(
                id=ing_id,
                dataset_version_id=str(RECOVERY_DEMO_DATASET_ID),
                code=ing.code,
                name=ing.name,
                category=ing.category,
                edible_fraction=ing.edible_fraction,
                allergens_json=list(ing.allergens),
                source_type=ing.source_type.value,
                source_ref="DEMO_ONLY Sprint 3B",
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
        # Set initial ING007 price competitively so baseline MILP naturally includes 1 chicken day (20.00 kg)
        orig_val = 28000.0 if code == "ING007" else pr.original_value
        per_g = (
            convert_price_to_idr_per_g(orig_val, "IDR/kg")
            if code == "ING007"
            else pr.price_idr_per_g
        )
        session.add(
            IngredientPriceORM(
                id=str(uuid4()),
                dataset_version_id=str(RECOVERY_DEMO_DATASET_ID),
                ingredient_id=ing_id_by_code[code],
                price_idr_per_g=per_g,
                original_value=orig_val,
                original_unit=pr.original_unit,
                region=pr.region,
                observed_at=pr.observed_at,
                source_type=pr.source_type.value,
            )
        )

    for code, st in base_stock.items():
        # Baseline starts with ample stock and exact 20.00 kg chicken (250 servings x 80 g)
        baseline_stock_g = 20000.0 if code == "ING007" else max(st.stock_raw_g, 150000.0)
        session.add(
            DatasetStockSnapshotORM(
                id=str(uuid4()),
                dataset_version_id=str(RECOVERY_DEMO_DATASET_ID),
                ingredient_id=ing_id_by_code[code],
                stock_raw_g=baseline_stock_g,
                recorded_at=reference_now - timedelta(hours=6),
            )
        )

    for rec in base_recipes:
        rec_id = str(uuid4())
        session.add(
            RecipeVariantORM(
                id=rec_id,
                dataset_version_id=str(RECOVERY_DEMO_DATASET_ID),
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
            # Make R006 chicken 80 g/serving so 250 servings = exact 20.00 kg
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

    # Step 2: Run & approve baseline weekly menu BEFORE partial delivery reduces chicken to 12 kg
    repo = SQLiteVaultRepository(session)
    baseline_sc = repo.create_scenario(
        ScenarioCreateRequest(
            name="Menu Mingguan SPPG-A (Baseline Ayam 20 kg)",
            dataset_version_id=RECOVERY_DEMO_DATASET_ID,
            nutrition_target_id=DEMO_TARGET_ID,
            servings_per_day=250,
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
                dataset_version_id=str(RECOVERY_DEMO_DATASET_ID),
                version_number=1,
                status="APPROVED",
                title="Menu Mingguan SPPG-A (Disetujui — Butuh 20 kg Ayam)",
                planner_notes="Menu baseline 5 hari (250 porsi/hari) disetujui sebelum perubahan pengiriman.",
                reviewer_notes="Disetujui untuk pelaksanaan minggu ini (DEMO_ONLY).",
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
        sc_orm = session.get(ScenarioORM, str(baseline_sc.id))
        if sc_orm is not None:
            scope = derive_production_scope(session, sc_orm)
            existing_op = session.execute(
                select(OperationalPlanAssignmentORM).where(
                    OperationalPlanAssignmentORM.active_scope_key == scope.scope_key
                )
            ).scalar_one_or_none()
            if existing_op is None:
                session.add(
                    OperationalPlanAssignmentORM(
                        id=str(uuid4()),
                        kitchen_id=str(kitchen_id),
                        dataset_version_id=str(RECOVERY_DEMO_DATASET_ID),
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
                        inventory_snapshot_sha256=None,
                        created_at=reference_now - timedelta(hours=2),
                        updated_at=reference_now - timedelta(hours=2),
                    )
                )

    # Step 3: Record verified batch ledger reflecting PARTIAL chicken delivery (12.00 kg arrived of 20.00 kg)
    for code, st in base_stock.items():
        ing_id = ing_id_by_code[code]
        if code == "ING007":
            session.add(
                SupplierDeliveryORM(
                    id=str(uuid4()),
                    kitchen_id=str(kitchen_id),
                    dataset_version_id=str(RECOVERY_DEMO_DATASET_ID),
                    ingredient_id=ing_id,
                    source_id=source_id,
                    supplier_name="PT Unggas Nusantara (Simulasi DEMO_ONLY)",
                    delivery_ref="SJ-AYAM-PARSIAL-001",
                    expected_raw_g=20000.0,
                    received_raw_g=12000.0,
                    original_value=12.0,
                    original_unit="kg",
                    expected_at=reference_now - timedelta(hours=1),
                    confirmed_at=reference_now - timedelta(minutes=30),
                    status="PARTIAL",
                    idempotency_key="REC-3B-DELIV-ING007-PARTIAL-12KG",
                    notes="Supplier hanya mampu mengirim 12 kg dari 20 kg rencana; sisa 8 kg tertunda.",
                    created_at=reference_now - timedelta(minutes=30),
                )
            )
            lot_id = str(uuid4())
            session.add(
                InventoryLotORM(
                    id=lot_id,
                    kitchen_id=str(kitchen_id),
                    dataset_version_id=str(RECOVERY_DEMO_DATASET_ID),
                    ingredient_id=ing_id,
                    source_id=source_id,
                    lot_code="LOT-AYAM-PARSIAL-01",
                    recorded_raw_g=12000.0,
                    verified_physical_raw_g=12000.0,
                    damaged_raw_g=0.0,
                    expires_at=reference_now + timedelta(days=14),
                    expiry_known=True,
                    received_at=reference_now - timedelta(minutes=25),
                    verified_at=reference_now - timedelta(minutes=25),
                    verification_status="VERIFIED",
                    data_classification="synthetic",
                    unit_original="kg",
                    quantity_original=12.0,
                    notes="Penerimaan parsial terverifikasi 12 kg dari 20 kg (DEMO_ONLY)",
                    created_at=reference_now - timedelta(minutes=25),
                )
            )
            session.add(
                InventoryMovementORM(
                    id=str(uuid4()),
                    kitchen_id=str(kitchen_id),
                    dataset_version_id=str(RECOVERY_DEMO_DATASET_ID),
                    ingredient_id=ing_id,
                    lot_id=lot_id,
                    source_id=source_id,
                    movement_type="GOODS_RECEIPT",
                    quantity_delta_raw_g=12000.0,
                    original_value=12.0,
                    original_unit="kg",
                    event_at=reference_now - timedelta(minutes=25),
                    idempotency_key="REC-3B-ING007-PARTIAL-12KG",
                    source_document_ref="SJ-AYAM-PARSIAL-001",
                    quarantined=False,
                    created_at=reference_now - timedelta(minutes=25),
                )
            )
        else:
            qty_g = max(st.stock_raw_g, 150000.0)
            lot_id = str(uuid4())
            session.add(
                InventoryLotORM(
                    id=lot_id,
                    kitchen_id=str(kitchen_id),
                    dataset_version_id=str(RECOVERY_DEMO_DATASET_ID),
                    ingredient_id=ing_id,
                    source_id=source_id,
                    lot_code=f"LOT-3B-{code}-01",
                    recorded_raw_g=qty_g,
                    verified_physical_raw_g=qty_g,
                    damaged_raw_g=0.0,
                    expires_at=reference_now + timedelta(days=365),
                    expiry_known=True,
                    received_at=reference_now - timedelta(hours=6),
                    verified_at=reference_now - timedelta(hours=6),
                    verification_status="VERIFIED",
                    data_classification="synthetic",
                    unit_original="kg",
                    quantity_original=qty_g / 1000.0,
                    notes="Batch awal terverifikasi (DEMO_ONLY)",
                    created_at=reference_now - timedelta(hours=6),
                )
            )
            session.add(
                InventoryMovementORM(
                    id=str(uuid4()),
                    kitchen_id=str(kitchen_id),
                    dataset_version_id=str(RECOVERY_DEMO_DATASET_ID),
                    ingredient_id=ing_id,
                    lot_id=lot_id,
                    source_id=source_id,
                    movement_type="OPENING_BALANCE",
                    quantity_delta_raw_g=qty_g,
                    original_value=qty_g / 1000.0,
                    original_unit="kg",
                    event_at=reference_now - timedelta(hours=6),
                    idempotency_key=f"REC-3B-OP-{code}",
                    source_document_ref=f"OP-3B-{code}",
                    quarantined=False,
                    created_at=reference_now - timedelta(hours=6),
                )
            )

    session.commit()
    return RECOVERY_DEMO_DATASET_ID
