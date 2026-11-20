from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.data.synthetic_fixture import build_demo_dataset
from app.db.models import (
    DatasetSourceORM,
    DatasetStockSnapshotORM,
    DatasetVersionORM,
    IngredientMappingORM,
    IngredientNutrientORM,
    IngredientORM,
    IngredientPriceORM,
    InventoryLotORM,
    InventoryMovementORM,
    InventoryReconciliationORM,
    RecipeIngredientORM,
    RecipeVariantORM,
    StockReservationORM,
    SupplierDeliveryORM,
)

INVENTORY_QUALITY_DATASET_ID = UUID("33333333-3333-4333-8333-333333333333")
INVENTORY_QUALITY_FIXTURE_SEED = 20261120
DEFAULT_FIXTURE_PRODUCTION_DATE = datetime(2026, 11, 20, 8, 0, tzinfo=timezone.utc)
DEFAULT_KITCHEN_A_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1")


def seed_inventory_quality_demo_dataset(
    session: Session,
    *,
    kitchen_id: UUID = DEFAULT_KITCHEN_A_ID,
    reference_now: datetime = DEFAULT_FIXTURE_PRODUCTION_DATE,
) -> UUID:
    """Idempotently create an independently authored deterministic inventory-quality synthetic dataset.

    All numbers are synthetic (DEMO_ONLY, seed=20261120), explicitly scoped to kitchen_id,
    never copied from unlicensed external repositories, and demonstrate:
    - Normal verified batches (most ingredients)
    - Partial / allocated / damaged stock: ING007 Daging Ayam Fillet (20 kg recorded, 3 kg damaged, 5 kg reserved = 12 kg usable)
    - Expired batch exclusion: ING012 Bayam Segar (18 kg recorded, 6 kg expired = 12 kg usable)
    - Delayed supplier delivery: ING008 Ikan Kembung (10 kg usable on-hand + 15 kg DELAYED delivery NOT counted as usable)
    - Duplicate receiving event skipped / tracked idempotently
    - Quarantined unit conflict movement (500 g vs 500 kg attempt on ING013 Wortel)
    - Physical count discrepancy: ING009 Tempe Kedelai (25 kg book vs 21 kg verified physical count)
    - Unverified missing-expiry lot: ING016 Brokoli (expiry_known=False -> excluded from confirmed usable)
    - External product -> canonical ingredient mappings (MAPPED, UNMAPPED, AMBIGUOUS, REJECTED, UNIT_ERROR)
    """
    existing = session.get(DatasetVersionORM, str(INVENTORY_QUALITY_DATASET_ID))
    if existing is not None:
        return INVENTORY_QUALITY_DATASET_ID

    rng = random.Random(INVENTORY_QUALITY_FIXTURE_SEED)
    _, base_ings, base_prices, base_stock, base_recipes, _ = build_demo_dataset()

    source_id = str(uuid4())
    session.add(
        DatasetSourceORM(
            id=source_id,
            kitchen_id=str(kitchen_id),
            source_name="GiziOptima Inventory Quality Synthetic Fixture v1 (DEMO_ONLY)",
            source_url="repo://services/api/app/data/inventory_quality_fixture.py",
            license="PROJECT_AUTHORED_INTERNAL_DEMO",
            license_verified=True,
            dataset_type="synthetic",
            retrieved_at=reference_now,
            checksum=f"seed-{INVENTORY_QUALITY_FIXTURE_SEED}",
            allowed_use="DEV_AND_QA_SYNTHETIC_ONLY",
            transformation_notes="Deterministic batch inventory, expiry, reservation, delivery delay, and unit quarantine fixture (DEMO_ONLY).",
            created_at=reference_now,
        )
    )

    session.add(
        DatasetVersionORM(
            id=str(INVENTORY_QUALITY_DATASET_ID),
            kitchen_id=str(kitchen_id),
            name="Simulasi Kualitas Stok & Batch SPPG-A (DEMO_ONLY)",
            source_type="synthetic",
            source_url="repo://services/api/app/data/inventory_quality_fixture.py",
            is_synthetic=True,
            is_active=False,
            review_status="reviewed",
            ingestion_metadata_json={
                "seeded": True,
                "label": "DEMO_ONLY",
                "seed": INVENTORY_QUALITY_FIXTURE_SEED,
                "uses_batch_ledger": True,
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
                dataset_version_id=str(INVENTORY_QUALITY_DATASET_ID),
                code=ing.code,
                name=ing.name,
                category=ing.category,
                edible_fraction=ing.edible_fraction,
                allergens_json=list(ing.allergens),
                source_type="synthetic",
                source_ref="DEMO_ONLY_INV_QUALITY",
                review_status="reviewed",
            )
        )
    session.flush()

    for code, ing in base_ings.items():
        ing_id = ing_id_by_code[code]
        session.add(
            IngredientNutrientORM(
                ingredient_id=ing_id,
                energy_kcal_100g=ing.nutrients.energy_kcal_100g,
                protein_g_100g=ing.nutrients.protein_g_100g,
                fat_g_100g=ing.nutrients.fat_g_100g,
                carb_g_100g=ing.nutrients.carb_g_100g,
                fiber_g_100g=ing.nutrients.fiber_g_100g,
                iron_mg_100g=ing.nutrients.iron_mg_100g,
            )
        )
        pr = base_prices[code]
        session.add(
            IngredientPriceORM(
                id=str(uuid4()),
                dataset_version_id=str(INVENTORY_QUALITY_DATASET_ID),
                ingredient_id=ing_id,
                price_idr_per_g=pr.price_idr_per_g,
                original_value=pr.original_value,
                original_unit=pr.original_unit,
                region="SIMULASI-SPPG-A",
                observed_at=reference_now.date(),
                source_type="synthetic",
            )
        )
        snap = base_stock[code]
        session.add(
            DatasetStockSnapshotORM(
                id=str(uuid4()),
                dataset_version_id=str(INVENTORY_QUALITY_DATASET_ID),
                ingredient_id=ing_id,
                stock_raw_g=snap.stock_raw_g,
                recorded_at=reference_now,
            )
        )

    for rec in base_recipes:
        rec_id = str(uuid4())
        session.add(
            RecipeVariantORM(
                id=rec_id,
                dataset_version_id=str(INVENTORY_QUALITY_DATASET_ID),
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
            session.add(
                RecipeIngredientORM(
                    recipe_id=rec_id,
                    ingredient_id=ing_id_by_code[item.ingredient_code],
                    raw_g_per_serving=item.raw_g_per_serving,
                    retention_factor=item.retention_factor,
                )
            )

    # Create deterministic batch lots across ingredients
    special_codes = {"ING007", "ING012", "ING008", "ING009", "ING016"}
    for code, snap in base_stock.items():
        if code in special_codes:
            continue
        ing_id = ing_id_by_code[code]
        shelf_days = 14 if base_ings[code].category in {"vegetable", "fruit", "protein"} else 180
        exp = reference_now + timedelta(days=shelf_days + rng.randint(1, 7))
        lot_id = str(uuid4())
        session.add(
            InventoryLotORM(
                id=lot_id,
                kitchen_id=str(kitchen_id),
                dataset_version_id=str(INVENTORY_QUALITY_DATASET_ID),
                ingredient_id=ing_id,
                lot_code=f"LOT-{code}-BASE",
                source_id=source_id,
                data_classification="synthetic",
                recorded_raw_g=snap.stock_raw_g,
                damaged_raw_g=0.0,
                expires_at=exp,
                expiry_known=True,
                received_at=reference_now - timedelta(days=1),
                verified_physical_raw_g=snap.stock_raw_g,
                verified_at=reference_now - timedelta(hours=2),
                verification_status="VERIFIED",
                unit_original="kg",
                quantity_original=snap.stock_raw_g / 1000.0,
                notes="Batch awal terverifikasi (DEMO_ONLY)",
                created_at=reference_now,
            )
        )
        session.add(
            InventoryMovementORM(
                id=str(uuid4()),
                kitchen_id=str(kitchen_id),
                dataset_version_id=str(INVENTORY_QUALITY_DATASET_ID),
                ingredient_id=ing_id,
                lot_id=lot_id,
                movement_type="OPENING_BALANCE",
                quantity_delta_raw_g=snap.stock_raw_g,
                original_value=snap.stock_raw_g / 1000.0,
                original_unit="kg",
                idempotency_key=f"SEED-OP-{code}",
                source_document_ref="SEED-INV-Q-01",
                source_id=source_id,
                event_at=reference_now - timedelta(days=1),
                quarantined=False,
                created_at=reference_now,
            )
        )

    # 1. ING007 Daging Ayam Fillet: 20 kg recorded -> 3 kg damaged + 5 kg reserved -> 12 kg usable!
    ayam_id = ing_id_by_code["ING007"]
    ayam_lot_id = str(uuid4())
    session.add(
        InventoryLotORM(
            id=ayam_lot_id,
            kitchen_id=str(kitchen_id),
            dataset_version_id=str(INVENTORY_QUALITY_DATASET_ID),
            ingredient_id=ayam_id,
            lot_code="LOT-AYAM-20261120",
            source_id=source_id,
            data_classification="synthetic",
            recorded_raw_g=20000.0,
            damaged_raw_g=3000.0,
            expires_at=reference_now + timedelta(days=3),
            expiry_known=True,
            received_at=reference_now - timedelta(hours=12),
            verified_physical_raw_g=20000.0,
            verified_at=reference_now - timedelta(hours=2),
            verification_status="VERIFIED",
            unit_original="kg",
            quantity_original=20.0,
            notes="20 kg tercatat; 3 kg mengalami memar/rusak penyimpanan dingin.",
            created_at=reference_now,
        )
    )
    session.add(
        StockReservationORM(
            id=str(uuid4()),
            kitchen_id=str(kitchen_id),
            dataset_version_id=str(INVENTORY_QUALITY_DATASET_ID),
            ingredient_id=ayam_id,
            lot_id=ayam_lot_id,
            reserved_raw_g=5000.0,
            production_date=reference_now,
            status="ACTIVE",
            idempotency_key="SEED-RES-AYAM-01",
            notes="Dialokasikan untuk batch makan siang kelas khusus.",
            created_at=reference_now,
        )
    )
    session.add(
        SupplierDeliveryORM(
            id=str(uuid4()),
            kitchen_id=str(kitchen_id),
            dataset_version_id=str(INVENTORY_QUALITY_DATASET_ID),
            ingredient_id=ayam_id,
            source_id=source_id,
            supplier_name="PT Unggas Segar Simulasi",
            delivery_ref="SJ-AYAM-PARTIAL-01",
            expected_raw_g=20000.0,
            received_raw_g=12000.0,
            original_value=12.0,
            original_unit="kg",
            expected_at=reference_now - timedelta(hours=4),
            confirmed_at=reference_now - timedelta(hours=3),
            status="PARTIAL",
            idempotency_key="SEED-DELIV-AYAM-PARTIAL",
            notes="Pengiriman parsial: 20 kg dipesan, baru 12 kg tiba dan lolos terima.",
            created_at=reference_now,
        )
    )

    # 2. ING012 Bayam Segar: 12 kg fresh + 6 kg expired yesterday
    bayam_id = ing_id_by_code["ING012"]
    session.add(
        InventoryLotORM(
            id=str(uuid4()),
            kitchen_id=str(kitchen_id),
            dataset_version_id=str(INVENTORY_QUALITY_DATASET_ID),
            ingredient_id=bayam_id,
            lot_code="LOT-BAYAM-FRESH",
            source_id=source_id,
            data_classification="synthetic",
            recorded_raw_g=12000.0,
            damaged_raw_g=0.0,
            expires_at=reference_now + timedelta(days=2),
            expiry_known=True,
            received_at=reference_now - timedelta(hours=6),
            verified_physical_raw_g=12000.0,
            verified_at=reference_now - timedelta(hours=1),
            verification_status="VERIFIED",
            unit_original="kg",
            quantity_original=12.0,
            created_at=reference_now,
        )
    )
    session.add(
        InventoryLotORM(
            id=str(uuid4()),
            kitchen_id=str(kitchen_id),
            dataset_version_id=str(INVENTORY_QUALITY_DATASET_ID),
            ingredient_id=bayam_id,
            lot_code="LOT-BAYAM-EXPIRED",
            source_id=source_id,
            data_classification="synthetic",
            recorded_raw_g=6000.0,
            damaged_raw_g=0.0,
            expires_at=reference_now - timedelta(days=1),
            expiry_known=True,
            received_at=reference_now - timedelta(days=4),
            verified_physical_raw_g=6000.0,
            verified_at=reference_now - timedelta(hours=1),
            verification_status="VERIFIED",
            unit_original="kg",
            quantity_original=6.0,
            notes="Batch layu melewati batas kedaluwarsa; wajib dikeluarkan dari stok layak pakai.",
            created_at=reference_now,
        )
    )

    # 3. ING008 Ikan Kembung: 10 kg on-hand + 15 kg DELAYED supplier promise (must NOT count!)
    ikan_id = ing_id_by_code["ING008"]
    session.add(
        InventoryLotORM(
            id=str(uuid4()),
            kitchen_id=str(kitchen_id),
            dataset_version_id=str(INVENTORY_QUALITY_DATASET_ID),
            ingredient_id=ikan_id,
            lot_code="LOT-IKAN-ONHAND",
            source_id=source_id,
            data_classification="synthetic",
            recorded_raw_g=10000.0,
            damaged_raw_g=0.0,
            expires_at=reference_now + timedelta(days=3),
            expiry_known=True,
            received_at=reference_now - timedelta(days=1),
            verified_physical_raw_g=10000.0,
            verified_at=reference_now - timedelta(hours=2),
            verification_status="VERIFIED",
            unit_original="kg",
            quantity_original=10.0,
            created_at=reference_now,
        )
    )
    session.add(
        SupplierDeliveryORM(
            id=str(uuid4()),
            kitchen_id=str(kitchen_id),
            dataset_version_id=str(INVENTORY_QUALITY_DATASET_ID),
            ingredient_id=ikan_id,
            source_id=source_id,
            supplier_name="TPI Pesisir Simulasi",
            delivery_ref="PO-IKAN-DELAY-02",
            expected_raw_g=15000.0,
            received_raw_g=0.0,
            original_value=15.0,
            original_unit="kg",
            expected_at=reference_now + timedelta(hours=4),
            confirmed_at=None,
            status="DELAYED",
            idempotency_key="SEED-DELIV-IKAN-DELAYED",
            notes="Tertunda pengiriman truk berpendingin; tidak boleh dihitung sebelum tiba.",
            created_at=reference_now,
        )
    )

    # 4. ING009 Tempe Kedelai: Book 25 kg vs Physical Count 21 kg (discrepancy detected!)
    tempe_id = ing_id_by_code["ING009"]
    tempe_lot_id = str(uuid4())
    session.add(
        InventoryLotORM(
            id=tempe_lot_id,
            kitchen_id=str(kitchen_id),
            dataset_version_id=str(INVENTORY_QUALITY_DATASET_ID),
            ingredient_id=tempe_id,
            lot_code="LOT-TEMPE-01",
            source_id=source_id,
            data_classification="synthetic",
            recorded_raw_g=25000.0,
            damaged_raw_g=0.0,
            expires_at=reference_now + timedelta(days=3),
            expiry_known=True,
            received_at=reference_now - timedelta(days=1),
            verified_physical_raw_g=21000.0,
            verified_at=reference_now - timedelta(hours=1),
            verification_status="DISCREPANCY",
            unit_original="kg",
            quantity_original=25.0,
            notes="Selisih pencatatan buku 25 kg vs hitung fisik 21 kg.",
            created_at=reference_now,
        )
    )
    session.add(
        InventoryReconciliationORM(
            id=str(uuid4()),
            kitchen_id=str(kitchen_id),
            dataset_version_id=str(INVENTORY_QUALITY_DATASET_ID),
            ingredient_id=tempe_id,
            lot_id=tempe_lot_id,
            recorded_raw_g=25000.0,
            physical_raw_g=21000.0,
            discrepancy_raw_g=-4000.0,
            status="DISCREPANCY_DETECTED",
            counted_by="Petugas Gudang A",
            counted_at=reference_now - timedelta(hours=1),
            notes="Selisih 4 kg perlu verifikasi nota pemakaian.",
            created_at=reference_now,
        )
    )

    # 5. ING016 Brokoli: 8 kg verified + 5 kg missing expiry (expiry_known=False -> excluded!)
    brokoli_id = ing_id_by_code["ING016"]
    session.add(
        InventoryLotORM(
            id=str(uuid4()),
            kitchen_id=str(kitchen_id),
            dataset_version_id=str(INVENTORY_QUALITY_DATASET_ID),
            ingredient_id=brokoli_id,
            lot_code="LOT-BROKOLI-VERIFIED",
            source_id=source_id,
            data_classification="synthetic",
            recorded_raw_g=8000.0,
            damaged_raw_g=0.0,
            expires_at=reference_now + timedelta(days=3),
            expiry_known=True,
            received_at=reference_now - timedelta(hours=8),
            verified_physical_raw_g=8000.0,
            verified_at=reference_now - timedelta(hours=1),
            verification_status="VERIFIED",
            unit_original="kg",
            quantity_original=8.0,
            created_at=reference_now,
        )
    )
    session.add(
        InventoryLotORM(
            id=str(uuid4()),
            kitchen_id=str(kitchen_id),
            dataset_version_id=str(INVENTORY_QUALITY_DATASET_ID),
            ingredient_id=brokoli_id,
            lot_code="LOT-BROKOLI-NOEXP",
            source_id=source_id,
            data_classification="synthetic",
            recorded_raw_g=5000.0,
            damaged_raw_g=0.0,
            expires_at=None,
            expiry_known=False,
            received_at=reference_now - timedelta(days=2),
            verification_status="UNVERIFIED",
            unit_original="kg",
            quantity_original=5.0,
            notes="Tanggal kedaluwarsa kosong; tidak boleh dianggap segar.",
            created_at=reference_now,
        )
    )

    # 6. Quarantined unit conflict movement on ING013 Wortel (500 g claimed as 500 kg)
    wortel_id = ing_id_by_code["ING013"]
    session.add(
        InventoryMovementORM(
            id=str(uuid4()),
            kitchen_id=str(kitchen_id),
            dataset_version_id=str(INVENTORY_QUALITY_DATASET_ID),
            ingredient_id=wortel_id,
            lot_id=None,
            movement_type="ADJUSTMENT",
            quantity_delta_raw_g=0.0,
            original_value=500.0,
            original_unit="g",
            idempotency_key="SEED-QUAR-WORTEL-UNIT",
            source_document_ref="SJ-WORTEL-ERR-500",
            source_id=source_id,
            event_at=reference_now - timedelta(hours=3),
            quarantined=True,
            quarantine_reason="Konflik unit terdeteksi: dokumen sumber 500 g, input mencoba mengklaim 500 kg.",
            created_at=reference_now,
        )
    )

    # 7. Sample Ingredient Mapping Records
    sample_mappings = [
        (
            "SKU-EXT-CHICK-01",
            "Fresh Boneless Chicken Breast 1kg",
            "kg",
            "protein",
            ayam_id,
            "ING007",
            "kg",
            1000.0,
            "MAPPED",
            "reviewed",
            "Pemetaan eksplisit ke Daging Ayam Fillet terverifikasi.",
        ),
        (
            "SKU-EXT-RICE-AMB",
            "Beras Kemasan 5kg",
            "kg",
            "staple",
            None,
            None,
            "kg",
            1000.0,
            "AMBIGUOUS",
            "needs_review",
            "Ambigu antara Beras Putih (ING001) dan Beras Merah (ING002); wajib konfirmasi manual.",
        ),
        (
            "SKU-EXT-LBS-01",
            "Frozen Carrot Pack 10 lbs",
            "lbs",
            "vegetable",
            None,
            "ING013",
            "kg",
            None,
            "UNIT_ERROR",
            "rejected",
            "Satuan non-SI 'lbs' tidak diterima tanpa konversi resmi terverifikasi.",
        ),
    ]
    for (
        ext_code,
        ext_name,
        ext_unit,
        cat,
        ing_fk,
        ing_code,
        std_unit,
        factor,
        m_stat,
        r_stat,
        note,
    ) in sample_mappings:
        session.add(
            IngredientMappingORM(
                id=str(uuid4()),
                kitchen_id=str(kitchen_id),
                dataset_version_id=str(INVENTORY_QUALITY_DATASET_ID),
                source_id=source_id,
                external_product_code=ext_code,
                external_product_name=ext_name,
                external_unit=ext_unit,
                canonical_category=cat,
                ingredient_id=ing_fk,
                ingredient_code=ing_code,
                standard_unit=std_unit,
                conversion_factor_to_g=factor,
                mapping_status=m_stat,
                review_status=r_stat,
                notes=note,
                created_at=reference_now,
            )
        )

    return INVENTORY_QUALITY_DATASET_ID
