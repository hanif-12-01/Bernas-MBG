from __future__ import annotations

from typing import Dict, List
from uuid import UUID

from app.data.synthetic_fixture import build_demo_dataset
from app.domain.models.schemas import (
    DatasetVersion,
    Ingredient,
    IngredientPrice,
    NutritionTargetProfile,
    OptimizationRunResponse,
    RecipeVariant,
    Scenario,
    StockItem,
)


class InMemoryVaultStore:
    """In-memory repository initialized with the DEMO_ONLY synthetic fixture for Sprint 1 POC."""

    def __init__(self) -> None:
        (
            dataset,
            ingredients_by_code,
            prices_by_code,
            stock_by_code,
            recipes,
            target,
        ) = build_demo_dataset()

        self.datasets: Dict[UUID, DatasetVersion] = {dataset.id: dataset}
        self.ingredients_by_code: Dict[str, Ingredient] = ingredients_by_code
        self.base_prices_by_dataset: Dict[UUID, Dict[str, IngredientPrice]] = {
            dataset.id: prices_by_code
        }
        self.base_stock_by_dataset: Dict[UUID, Dict[str, StockItem]] = {
            dataset.id: stock_by_code
        }
        self.recipes: List[RecipeVariant] = recipes
        self.recipes_by_id: Dict[UUID, RecipeVariant] = {r.id: r for r in recipes}
        self.targets: Dict[UUID, NutritionTargetProfile] = {target.id: target}

        self.scenarios: Dict[UUID, Scenario] = {}
        self.runs: Dict[UUID, OptimizationRunResponse] = {}
        self.default_dataset_id: UUID = dataset.id
        self.default_target_id: UUID = target.id


store = InMemoryVaultStore()
