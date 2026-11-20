from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Dict, List, Tuple
from uuid import UUID

from app.domain.models.schemas import (
    DatasetVersion,
    Ingredient,
    IngredientNutrients,
    IngredientPrice,
    NutritionTargetLimit,
    NutritionTargetProfile,
    RecipeIngredient,
    RecipeVariant,
    ReviewStatusEnum,
    SlotEnum,
    SourceTypeEnum,
    StockItem,
)
from app.ingestion.unit_converter import convert_price_to_idr_per_g

DEMO_DATASET_ID = UUID("11111111-1111-1111-1111-111111111111")
DEMO_TARGET_ID = UUID("22222222-2222-2222-2222-222222222222")


def build_demo_dataset() -> Tuple[
    DatasetVersion,
    Dict[str, Ingredient],
    Dict[str, IngredientPrice],
    Dict[str, StockItem],
    List[RecipeVariant],
    NutritionTargetProfile,
]:
    """Return an explicit DEMO_ONLY synthetic dataset for 5 days / 100 servings/day.

    Includes 24 ingredients, 16 reviewed recipe variants (4 per slot),
    and 1 draft/unreviewed recipe variant (R017) to verify AC-03 exclusion.
    All numeric values are synthetic illustrations for Sprint 1 PoC only.
    """
    dataset = DatasetVersion(
        id=DEMO_DATASET_ID,
        name="GiziOptima Synthetic Fixture v0.1 (DEMO_ONLY)",
        source_type=SourceTypeEnum.SYNTHETIC,
        source_url="vault://04_Engineering/Fixtures and Examples",
        is_synthetic=True,
        review_status=ReviewStatusEnum.REVIEWED,
    )

    raw_ingredients = [
        ("ING001", "Beras Putih", "staple", 1.0, [], 360.0, 6.8, 0.7, 78.9, 0.8, 0.8, 16000.0, 45000.0),
        ("ING002", "Beras Merah", "staple", 1.0, [], 355.0, 7.5, 2.2, 76.0, 3.5, 1.5, 20000.0, 30000.0),
        ("ING003", "Kentang", "staple", 0.85, [], 87.0, 2.0, 0.1, 20.0, 2.2, 0.8, 18000.0, 60000.0),
        ("ING004", "Jagung Pipil", "staple", 1.0, [], 350.0, 9.0, 4.0, 72.0, 7.0, 2.5, 14000.0, 35000.0),
        ("ING005", "Ubi Jalar Kuning", "staple", 0.85, [], 108.0, 1.4, 0.3, 25.0, 3.0, 0.7, 12000.0, 50000.0),
        ("ING006", "Telur Ayam Ras", "protein", 0.88, ["egg"], 155.0, 12.6, 10.6, 1.1, 0.0, 1.8, 28000.0, 35000.0),
        ("ING007", "Daging Ayam Fillet", "protein", 1.0, [], 165.0, 24.0, 7.0, 0.0, 0.0, 1.1, 44000.0, 30000.0),
        ("ING008", "Ikan Kembung", "protein", 0.80, ["fish"], 167.0, 21.3, 8.2, 0.0, 0.0, 1.5, 38000.0, 30000.0),
        ("ING009", "Tempe Kedelai", "protein", 1.0, ["soy"], 193.0, 19.0, 10.8, 9.4, 5.0, 2.7, 18000.0, 40000.0),
        ("ING010", "Tahu Putih", "protein", 1.0, ["soy"], 80.0, 8.5, 4.8, 1.9, 0.6, 1.6, 14000.0, 40000.0),
        ("ING011", "Ikan Lele", "protein", 0.75, ["fish"], 135.0, 18.5, 6.0, 0.0, 0.0, 1.2, 30000.0, 35000.0),
        ("ING012", "Bayam Segar", "vegetable", 0.75, [], 23.0, 2.9, 0.4, 3.6, 2.2, 2.7, 12000.0, 45000.0),
        ("ING013", "Wortel", "vegetable", 0.88, [], 41.0, 0.9, 0.2, 9.6, 2.8, 0.3, 15000.0, 45000.0),
        ("ING014", "Kangkung", "vegetable", 0.70, [], 22.0, 2.8, 0.3, 3.5, 2.1, 2.3, 10000.0, 45000.0),
        ("ING015", "Buncis", "vegetable", 0.90, [], 31.0, 1.8, 0.2, 7.0, 2.7, 1.0, 16000.0, 40000.0),
        ("ING016", "Brokoli", "vegetable", 0.80, [], 34.0, 2.8, 0.4, 6.6, 2.6, 0.7, 28000.0, 30000.0),
        ("ING017", "Labu Siam", "vegetable", 0.85, [], 19.0, 0.8, 0.1, 4.5, 1.7, 0.3, 10000.0, 45000.0),
        ("ING018", "Pisang Ambon", "fruit", 0.75, [], 99.0, 1.1, 0.2, 25.8, 2.6, 0.3, 16000.0, 50000.0),
        ("ING019", "Pepaya", "fruit", 0.75, [], 43.0, 0.5, 0.3, 10.8, 1.7, 0.2, 12000.0, 50000.0),
        ("ING020", "Jeruk Manis", "fruit", 0.72, [], 47.0, 0.9, 0.1, 11.8, 2.4, 0.1, 22000.0, 45000.0),
        ("ING021", "Semangka", "fruit", 0.60, [], 30.0, 0.6, 0.2, 7.6, 0.4, 0.2, 11000.0, 60000.0),
        ("ING022", "Minyak Goreng Sawit", "seasoning", 1.0, [], 884.0, 0.0, 100.0, 0.0, 0.0, 0.0, 18000.0, 15000.0),
        ("ING023", "Bumbu Dasar Bawang", "seasoning", 0.92, [], 50.0, 1.5, 0.2, 11.0, 1.8, 0.5, 32000.0, 15000.0),
        ("ING024", "Kacang Merah", "protein", 1.0, [], 333.0, 22.0, 1.2, 60.0, 15.0, 6.5, 26000.0, 20000.0),
    ]

    ingredients_by_code: Dict[str, Ingredient] = {}
    prices_by_code: Dict[str, IngredientPrice] = {}
    stock_by_code: Dict[str, StockItem] = {}

    for (
        code,
        name,
        category,
        edible,
        allergens,
        kcal,
        prot,
        fat,
        carb,
        fiber,
        iron,
        price_kg,
        stock_g,
    ) in raw_ingredients:
        ingredients_by_code[code] = Ingredient(
            code=code,
            name=name,
            category=category,
            edible_fraction=edible,
            allergens=allergens,
            nutrients=IngredientNutrients(
                energy_kcal_100g=kcal,
                protein_g_100g=prot,
                fat_g_100g=fat,
                carb_g_100g=carb,
                fiber_g_100g=fiber,
                iron_mg_100g=iron,
            ),
            source_type=SourceTypeEnum.SYNTHETIC,
            source_ref="DEMO_ONLY",
            review_status=ReviewStatusEnum.REVIEWED,
        )
        prices_by_code[code] = IngredientPrice(
            ingredient_code=code,
            price_idr_per_g=convert_price_to_idr_per_g(price_kg, "IDR/kg"),
            original_value=price_kg,
            original_unit="IDR/kg",
            region="SIMULASI",
            observed_at=date(2026, 11, 19),
            source_type=SourceTypeEnum.SYNTHETIC,
            dataset_version_id=DEMO_DATASET_ID,
        )
        stock_by_code[code] = StockItem(ingredient_code=code, stock_raw_g=stock_g)

    reviewed_at = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)

    def make_recipe(
        code: str,
        name: str,
        slot: SlotEnum,
        family: str,
        items: List[Tuple[str, float, float]],
        allergens: List[str],
        status: ReviewStatusEnum = ReviewStatusEnum.REVIEWED,
    ) -> RecipeVariant:
        return RecipeVariant(
            code=code,
            name=name,
            slot=slot,
            family=family,
            review_status=status,
            reviewer="DEMO_TECHNICAL_CHECK" if status == ReviewStatusEnum.REVIEWED else None,
            reviewed_at=reviewed_at if status == ReviewStatusEnum.REVIEWED else None,
            active=True,
            allergen_tags=allergens,
            ingredients=[
                RecipeIngredient(
                    ingredient_code=c,
                    raw_g_per_serving=g,
                    retention_factor=ret,
                )
                for c, g, ret in items
            ],
        )

    recipes: List[RecipeVariant] = [
        # Staple (4 reviewed)
        make_recipe("R001", "Nasi Putih", SlotEnum.STAPLE, "rice", [("ING001", 90.0, 0.95)], []),
        make_recipe("R002", "Nasi Merah", SlotEnum.STAPLE, "red_rice", [("ING002", 90.0, 0.95)], []),
        make_recipe("R003", "Nasi Jagung", SlotEnum.STAPLE, "corn_rice", [("ING001", 55.0, 0.95), ("ING004", 40.0, 0.95)], []),
        make_recipe("R004", "Kentang & Ubi Panggang", SlotEnum.STAPLE, "tuber", [("ING003", 140.0, 0.92), ("ING005", 140.0, 0.92), ("ING022", 4.0, 1.0)], []),
        # Protein (4 reviewed)
        make_recipe("R005", "Telur Balado & Tahu", SlotEnum.PROTEIN, "egg", [("ING006", 70.0, 0.95), ("ING010", 60.0, 0.95), ("ING022", 5.0, 1.0), ("ING023", 6.0, 0.9)], ["egg", "soy"]),
        make_recipe("R006", "Ayam Tumis Kecap", SlotEnum.PROTEIN, "poultry", [("ING007", 75.0, 0.92), ("ING022", 5.0, 1.0), ("ING023", 8.0, 0.9)], []),
        make_recipe("R007", "Ikan Kembung Goreng", SlotEnum.PROTEIN, "fish", [("ING008", 85.0, 0.90), ("ING022", 7.0, 1.0), ("ING023", 6.0, 0.9)], ["fish"]),
        make_recipe("R008", "Tempe & Kacang Merah Semur", SlotEnum.PROTEIN, "plant_protein", [("ING009", 75.0, 0.95), ("ING024", 25.0, 0.92), ("ING022", 5.0, 1.0), ("ING023", 6.0, 0.9)], ["soy"]),
        # Vegetable (4 reviewed)
        make_recipe("R009", "Tumis Bayam Wortel", SlotEnum.VEGETABLE, "leafy_green", [("ING012", 80.0, 0.85), ("ING013", 40.0, 0.90), ("ING022", 4.0, 1.0), ("ING023", 4.0, 0.9)], []),
        make_recipe("R010", "Tumis Kangkung", SlotEnum.VEGETABLE, "water_spinach", [("ING014", 90.0, 0.85), ("ING022", 4.0, 1.0), ("ING023", 4.0, 0.9)], []),
        make_recipe("R011", "Oseng Buncis Wortel", SlotEnum.VEGETABLE, "pod_veg", [("ING015", 65.0, 0.90), ("ING013", 45.0, 0.90), ("ING022", 4.0, 1.0), ("ING023", 4.0, 0.9)], []),
        make_recipe("R012", "Sup Brokoli Labu", SlotEnum.VEGETABLE, "crucifer", [("ING016", 55.0, 0.88), ("ING017", 65.0, 0.90), ("ING023", 4.0, 0.9)], []),
        # Fruit (4 reviewed)
        make_recipe("R013", "Pisang Ambon", SlotEnum.FRUIT, "banana", [("ING018", 110.0, 1.0)], []),
        make_recipe("R014", "Pepaya Potong", SlotEnum.FRUIT, "papaya", [("ING019", 130.0, 1.0)], []),
        make_recipe("R015", "Jeruk Manis", SlotEnum.FRUIT, "citrus", [("ING020", 120.0, 1.0)], []),
        make_recipe("R016", "Semangka Potong", SlotEnum.FRUIT, "melon", [("ING021", 150.0, 1.0)], []),
        # Unreviewed draft recipe (AC-03: must NEVER be selected by optimizer)
        make_recipe(
            "R017",
            "Nasi Mini Unreviewed (DRAFT)",
            SlotEnum.STAPLE,
            "draft_rice",
            [("ING001", 40.0, 0.95)],
            [],
            status=ReviewStatusEnum.DRAFT,
        ),
    ]

    target = NutritionTargetProfile(
        id=DEMO_TARGET_ID,
        cohort="DEMO_ONLY_SISWA",
        meal_type="lunch",
        source_ref="DEMO_ONLY_SYNTHETIC",
        version="0.1-synthetic",
        review_status=ReviewStatusEnum.DRAFT,
        limits=[
            NutritionTargetLimit(nutrient_key="energy_kcal", min_per_serving=480.0, max_per_serving=780.0, unit="kcal"),
            NutritionTargetLimit(nutrient_key="protein_g", min_per_serving=16.0, max_per_serving=40.0, unit="g"),
            NutritionTargetLimit(nutrient_key="fat_g", min_per_serving=10.0, max_per_serving=35.0, unit="g"),
            NutritionTargetLimit(nutrient_key="carb_g", min_per_serving=55.0, max_per_serving=120.0, unit="g"),
            NutritionTargetLimit(nutrient_key="fiber_g", min_per_serving=3.5, max_per_serving=None, unit="g"),
        ],
    )

    return dataset, ingredients_by_code, prices_by_code, stock_by_code, recipes, target
