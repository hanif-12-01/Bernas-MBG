from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from uuid import UUID, uuid4

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.data.synthetic_fixture import DEMO_DATASET_ID, DEMO_TARGET_ID
from app.db.models import (
    DatasetStockSnapshotORM,
    DatasetVersionORM,
    IngredientNutrientORM,
    IngredientORM,
    IngredientPriceORM,
    MenuReviewRecordORM,
    NutritionTargetORM,
    OptimizationRunORM,
    RecipeIngredientORM,
    RecipeVariantORM,
    RunAssignmentORM,
    RunMaterialUsageORM,
    RunMetricORM,
    ScenarioORM,
    ScenarioPriceOverrideORM,
    ScenarioStockOverrideORM,
)
from app.domain.models.schemas import (
    ConstraintAudit,
    DatasetVersion,
    DayPlan,
    DiagnosticHint,
    Ingredient,
    IngredientNutrients,
    IngredientPrice,
    MaterialUsage,
    NutritionTargetLimit,
    NutritionTargetProfile,
    OptimizationRunResponse,
    PriceOverridesRequest,
    RecipeIngredient,
    RecipeVariant,
    ReviewStatusEnum,
    Scenario,
    ScenarioCloneRequest,
    ScenarioCreateRequest,
    SlotEnum,
    SolverStatusEnum,
    SourceTypeEnum,
    StockItem,
    StockOverridesRequest,
)
from app.domain.recipe_calculator import precompute_all_recipes
from app.ingestion.unit_converter import (
    DataValidationError,
    convert_price_to_idr_per_g,
)
from app.inventory.service import InventoryAvailabilitySummary, compute_usable_inventory
from app.optimizer.diagnostics import diagnose_infeasibility
from app.optimizer.model_builder import build_recipe_milp
from app.optimizer.solver import RawSolveResult, create_cbc_solver, solve_built_model
from app.optimizer.verifier import verify_assignments
from app.scenarios.service import (
    MODEL_VERSION,
    ResourceNotFoundError,
    ScenarioConflictError,
    ResourceNotFoundError,
    ScenarioConflictError,
    compute_snapshot_sha256,
)


def _to_dataset_schema(row: DatasetVersionORM) -> DatasetVersion:
    return DatasetVersion(
        id=UUID(row.id),
        name=row.name,
        source_type=SourceTypeEnum(row.source_type),
        source_url=row.source_url,
        is_synthetic=row.is_synthetic,
        review_status=ReviewStatusEnum(row.review_status),
        created_at=row.created_at,
    )


class SQLiteVaultRepository:
    """Transactional SQLAlchemy 2 repository for persistent GiziOptima state."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def visible_dataset_ids(self, kitchen_id: UUID):
        return select(DatasetVersionORM.id).where(
            or_(
                DatasetVersionORM.kitchen_id == str(kitchen_id),
                DatasetVersionORM.id == str(DEMO_DATASET_ID),
            )
        )

    def get_active_dataset_id(self, kitchen_id: Optional[UUID] = None) -> UUID:
        stmt = (
            select(DatasetVersionORM.id)
            .where(DatasetVersionORM.is_active.is_(True))
            .order_by(DatasetVersionORM.created_at.desc())
            .limit(1)
        )
        if kitchen_id is not None:
            stmt = stmt.where(DatasetVersionORM.id.in_(self.visible_dataset_ids(kitchen_id)))
        found = self.session.execute(stmt).scalar_one_or_none()
        if found is None:
            return DEMO_DATASET_ID
        return UUID(found)

    def get_default_target_id(self) -> UUID:
        row = self.session.get(NutritionTargetORM, str(DEMO_TARGET_ID))
        if row is not None:
            return DEMO_TARGET_ID
        stmt = select(NutritionTargetORM.id).limit(1)
        found = self.session.execute(stmt).scalar_one_or_none()
        if found is None:
            raise ResourceNotFoundError("No nutrition target profile exists in database")
        return UUID(found)

    def get_dataset(self, dataset_id: UUID, kitchen_id: Optional[UUID] = None) -> DatasetVersion:
        return _to_dataset_schema(self.get_dataset_orm(dataset_id, kitchen_id=kitchen_id))

    def get_dataset_orm(self, dataset_id: UUID, kitchen_id: Optional[UUID] = None) -> DatasetVersionORM:
        row = self.session.get(DatasetVersionORM, str(dataset_id))
        if row is None or (
            kitchen_id is not None
            and dataset_id != DEMO_DATASET_ID
            and row.kitchen_id != str(kitchen_id)
        ):
            raise ResourceNotFoundError(f"Dataset '{dataset_id}' not found")
        return row

    def list_datasets(self, kitchen_id: Optional[UUID] = None) -> List[DatasetVersionORM]:
        stmt = select(DatasetVersionORM).order_by(DatasetVersionORM.created_at.desc())
        if kitchen_id is not None:
            stmt = stmt.where(DatasetVersionORM.id.in_(self.visible_dataset_ids(kitchen_id)))
        return list(self.session.execute(stmt).scalars().all())

    def list_scenarios(
        self, kitchen_id: Optional[UUID] = None, *, approved_only: bool = False
    ) -> List[Scenario]:
        stmt = (
            select(ScenarioORM)
            .options(
                selectinload(ScenarioORM.price_overrides),
                selectinload(ScenarioORM.stock_overrides),
            )
            .order_by(ScenarioORM.created_at.desc())
        )
        if kitchen_id is not None:
            stmt = stmt.where(
                ScenarioORM.kitchen_id == str(kitchen_id),
                ScenarioORM.dataset_version_id.in_(self.visible_dataset_ids(kitchen_id)),
            )
        if approved_only:
            stmt = stmt.where(self._has_approved_review(ScenarioORM.id, MenuReviewRecordORM.scenario_id))
        rows = list(self.session.execute(stmt).scalars().all())
        return [self._scenario_orm_to_schema(r) for r in rows]

    def list_runs(
        self,
        scenario_id: Optional[UUID] = None,
        validated_only: bool = False,
        kitchen_id: Optional[UUID] = None,
        *,
        approved_only: bool = False,
    ) -> List[OptimizationRunORM]:
        stmt = select(OptimizationRunORM).order_by(OptimizationRunORM.created_at.desc())
        if kitchen_id is not None:
            stmt = stmt.join(ScenarioORM, OptimizationRunORM.scenario_id == ScenarioORM.id).where(
                ScenarioORM.kitchen_id == str(kitchen_id),
                OptimizationRunORM.dataset_version_id.in_(self.visible_dataset_ids(kitchen_id)),
            )
        if scenario_id is not None:
            stmt = stmt.where(OptimizationRunORM.scenario_id == str(scenario_id))
        if validated_only:
            stmt = stmt.where(OptimizationRunORM.validation_passed.is_(True))
        if approved_only:
            stmt = stmt.where(self._has_approved_review(OptimizationRunORM.id, MenuReviewRecordORM.run_id))
        return list(self.session.execute(stmt).scalars().all())

    @staticmethod
    def _has_approved_review(resource_id, review_resource_id):
        return (
            select(MenuReviewRecordORM.id)
            .where(review_resource_id == resource_id, MenuReviewRecordORM.status == "APPROVED")
            .exists()
        )

    def load_dataset_bundle(
        self, dataset_id: UUID, kitchen_id: Optional[UUID] = None
    ) -> Tuple[
        Dict[str, Ingredient],
        Dict[str, str],  # code -> ingredient UUID str
        Dict[str, IngredientPrice],
        Dict[str, StockItem],
        List[RecipeVariant],
    ]:
        self.get_dataset_orm(dataset_id, kitchen_id=kitchen_id)

        ing_stmt = (
            select(IngredientORM)
            .options(selectinload(IngredientORM.nutrients))
            .where(IngredientORM.dataset_version_id == str(dataset_id))
            .order_by(IngredientORM.code)
        )
        ing_rows = list(self.session.execute(ing_stmt).scalars().all())

        ingredients_by_code: Dict[str, Ingredient] = {}
        ing_id_by_code: Dict[str, str] = {}
        code_by_ing_id: Dict[str, str] = {}
        for row in ing_rows:
            nut = row.nutrients
            ingredients_by_code[row.code] = Ingredient(
                id=UUID(row.id),
                code=row.code,
                name=row.name,
                category=row.category,
                edible_fraction=row.edible_fraction,
                allergens=list(row.allergens_json or []),
                nutrients=IngredientNutrients(
                    energy_kcal_100g=nut.energy_kcal_100g if nut else None,
                    protein_g_100g=nut.protein_g_100g if nut else None,
                    fat_g_100g=nut.fat_g_100g if nut else None,
                    carb_g_100g=nut.carb_g_100g if nut else None,
                    fiber_g_100g=nut.fiber_g_100g if nut else None,
                    iron_mg_100g=nut.iron_mg_100g if nut else None,
                ),
                source_type=SourceTypeEnum(row.source_type),
                source_ref=row.source_ref,
                review_status=ReviewStatusEnum(row.review_status),
            )
            ing_id_by_code[row.code] = row.id
            code_by_ing_id[row.id] = row.code

        price_stmt = select(IngredientPriceORM).where(
            IngredientPriceORM.dataset_version_id == str(dataset_id)
        )
        prices_by_code: Dict[str, IngredientPrice] = {}
        for pr in self.session.execute(price_stmt).scalars().all():
            code = code_by_ing_id[pr.ingredient_id]
            prices_by_code[code] = IngredientPrice(
                id=UUID(pr.id),
                ingredient_code=code,
                price_idr_per_g=pr.price_idr_per_g,
                original_value=pr.original_value,
                original_unit=pr.original_unit,
                region=pr.region,
                observed_at=pr.observed_at,
                source_type=SourceTypeEnum(pr.source_type),
                dataset_version_id=UUID(pr.dataset_version_id),
            )

        stock_stmt = select(DatasetStockSnapshotORM).where(
            DatasetStockSnapshotORM.dataset_version_id == str(dataset_id)
        )
        stock_by_code: Dict[str, StockItem] = {}
        for st_row in self.session.execute(stock_stmt).scalars().all():
            code = code_by_ing_id[st_row.ingredient_id]
            stock_by_code[code] = StockItem(
                ingredient_code=code,
                stock_raw_g=st_row.stock_raw_g,
            )

        rec_stmt = (
            select(RecipeVariantORM)
            .options(selectinload(RecipeVariantORM.ingredients))
            .where(RecipeVariantORM.dataset_version_id == str(dataset_id))
            .order_by(RecipeVariantORM.code)
        )
        recipes: List[RecipeVariant] = []
        for r_row in self.session.execute(rec_stmt).scalars().all():
            recipes.append(
                RecipeVariant(
                    id=UUID(r_row.id),
                    code=r_row.code,
                    name=r_row.name,
                    slot=SlotEnum(r_row.slot),
                    family=r_row.family,
                    review_status=ReviewStatusEnum(r_row.review_status),
                    reviewer=r_row.reviewer,
                    reviewed_at=r_row.reviewed_at,
                    active=r_row.active,
                    allergen_tags=list(r_row.allergen_tags_json or []),
                    ingredients=[
                        RecipeIngredient(
                            ingredient_code=code_by_ing_id[ri.ingredient_id],
                            raw_g_per_serving=ri.raw_g_per_serving,
                            retention_factor=ri.retention_factor,
                        )
                        for ri in r_row.ingredients
                    ],
                )
            )

        return ingredients_by_code, ing_id_by_code, prices_by_code, stock_by_code, recipes

    def get_target(self, target_id: UUID) -> NutritionTargetProfile:
        stmt = (
            select(NutritionTargetORM)
            .options(selectinload(NutritionTargetORM.limits))
            .where(NutritionTargetORM.id == str(target_id))
        )
        row = self.session.execute(stmt).scalar_one_or_none()
        if row is None:
            raise ResourceNotFoundError(f"Nutrition target '{target_id}' not found")
        return NutritionTargetProfile(
            id=UUID(row.id),
            cohort=row.cohort,
            meal_type=row.meal_type,
            source_ref=row.source_ref,
            version=row.version,
            review_status=ReviewStatusEnum(row.review_status),
            limits=[
                NutritionTargetLimit(
                    nutrient_key=lim.nutrient_key,
                    min_per_serving=lim.min_per_serving,
                    max_per_serving=lim.max_per_serving,
                    unit=lim.unit,
                )
                for lim in sorted(row.limits, key=lambda x: x.nutrient_key)
            ],
        )

    def _scenario_orm_to_schema(self, row: ScenarioORM) -> Scenario:
        ing_rows = self.session.execute(
            select(IngredientORM.id, IngredientORM.code).where(
                IngredientORM.dataset_version_id == row.dataset_version_id
            )
        ).all()
        code_by_id = {r[0]: r[1] for r in ing_rows}

        price_overrides = {
            code_by_id[po.ingredient_id]: po.price_idr_per_g
            for po in row.price_overrides
            if po.ingredient_id in code_by_id
        }
        stock_overrides = {
            code_by_id[so.ingredient_id]: so.stock_raw_g
            for so in row.stock_overrides
            if so.ingredient_id in code_by_id
        }

        return Scenario(
            id=UUID(row.id),
            name=row.name,
            parent_scenario_id=UUID(row.parent_scenario_id) if row.parent_scenario_id else None,
            dataset_version_id=UUID(row.dataset_version_id),
            nutrition_target_id=UUID(row.target_id),
            meal_type=row.meal_type,
            servings_per_day=row.servings_per_day,
            days=row.days,
            budget_idr_per_serving=row.budget_idr_per_serving,
            max_repeat_per_family=row.max_repeat_per_family,
            excluded_allergens=list(row.excluded_allergens_json or []),
            price_overrides_idr_per_g=price_overrides,
            stock_overrides_raw_g=stock_overrides,
            source_label=SourceTypeEnum(row.source_label),
            production_date=row.production_date,
            locked=row.locked,
            created_at=row.created_at,
        )

    def get_scenario(
        self, scenario_id: UUID, kitchen_id: Optional[UUID] = None, *, approved_only: bool = False
    ) -> Scenario:
        stmt = (
            select(ScenarioORM)
            .options(
                selectinload(ScenarioORM.price_overrides),
                selectinload(ScenarioORM.stock_overrides),
            )
            .where(ScenarioORM.id == str(scenario_id))
        )
        if kitchen_id is not None:
            stmt = stmt.where(
                ScenarioORM.kitchen_id == str(kitchen_id),
                ScenarioORM.dataset_version_id.in_(self.visible_dataset_ids(kitchen_id)),
            )
        if approved_only:
            stmt = stmt.where(self._has_approved_review(ScenarioORM.id, MenuReviewRecordORM.scenario_id))
        row = self.session.execute(stmt).scalar_one_or_none()
        if row is None:
            raise ResourceNotFoundError(f"Scenario '{scenario_id}' not found")
        return self._scenario_orm_to_schema(row)

    def create_scenario(
        self, req: ScenarioCreateRequest, kitchen_id: Optional[UUID] = None
    ) -> Scenario:
        dataset_id = req.dataset_version_id or self.get_active_dataset_id(kitchen_id)
        target_id = req.nutrition_target_id or self.get_default_target_id()

        self.get_dataset_orm(dataset_id, kitchen_id=kitchen_id)
        if self.session.get(NutritionTargetORM, str(target_id)) is None:
            raise ResourceNotFoundError(f"Nutrition target '{target_id}' not found")

        sc_id = uuid4()
        row = ScenarioORM(
            id=str(sc_id),
            kitchen_id=str(kitchen_id) if kitchen_id else None,
            name=req.name,
            parent_scenario_id=None,
            dataset_version_id=str(dataset_id),
            target_id=str(target_id),
            meal_type=req.meal_type,
            servings_per_day=req.servings_per_day,
            budget_idr_per_serving=req.budget_idr_per_serving,
            days=req.days,
            max_repeat_per_family=req.max_repeat_per_family,
            excluded_allergens_json=list(req.excluded_allergens),
            source_label=req.source_label.value,
            production_date=req.production_date,
            locked=False,
            created_at=datetime.now(timezone.utc),
        )
        self.session.add(row)
        self.session.commit()
        return self.get_scenario(sc_id, kitchen_id=kitchen_id)

    def clone_scenario(
        self,
        scenario_id: UUID,
        req: Optional[ScenarioCloneRequest] = None,
        kitchen_id: Optional[UUID] = None,
    ) -> Scenario:
        stmt = (
            select(ScenarioORM)
            .options(
                selectinload(ScenarioORM.price_overrides),
                selectinload(ScenarioORM.stock_overrides),
            )
            .where(ScenarioORM.id == str(scenario_id))
        )
        if kitchen_id is not None:
            stmt = stmt.where(
                ScenarioORM.kitchen_id == str(kitchen_id),
                ScenarioORM.dataset_version_id.in_(self.visible_dataset_ids(kitchen_id)),
            )
        base = self.session.execute(stmt).scalar_one_or_none()
        if base is None:
            raise ResourceNotFoundError(f"Scenario '{scenario_id}' not found")

        new_id = uuid4()
        new_name = req.name if req and req.name else f"{base.name} (Clone)"
        cloned = ScenarioORM(
            id=str(new_id),
            kitchen_id=base.kitchen_id or (str(kitchen_id) if kitchen_id else None),
            name=new_name,
            parent_scenario_id=base.id,
            dataset_version_id=base.dataset_version_id,
            target_id=base.target_id,
            meal_type=base.meal_type,
            servings_per_day=base.servings_per_day,
            budget_idr_per_serving=base.budget_idr_per_serving,
            days=base.days,
            max_repeat_per_family=base.max_repeat_per_family,
            excluded_allergens_json=list(base.excluded_allergens_json or []),
            source_label=base.source_label,
            production_date=base.production_date,
            locked=False,
            created_at=datetime.now(timezone.utc),
        )
        self.session.add(cloned)
        self.session.flush()
        for po in base.price_overrides:
            self.session.add(
                ScenarioPriceOverrideORM(
                    scenario_id=str(new_id),
                    ingredient_id=po.ingredient_id,
                    price_idr_per_g=po.price_idr_per_g,
                )
            )
        for so in base.stock_overrides:
            self.session.add(
                ScenarioStockOverrideORM(
                    scenario_id=str(new_id),
                    ingredient_id=so.ingredient_id,
                    stock_raw_g=so.stock_raw_g,
                )
            )
        self.session.commit()
        return self.get_scenario(new_id, kitchen_id=kitchen_id)

    def apply_price_overrides(
        self,
        scenario_id: UUID,
        req: PriceOverridesRequest,
        kitchen_id: Optional[UUID] = None,
    ) -> Scenario:
        row = self.session.get(ScenarioORM, str(scenario_id))
        if row is None or (kitchen_id is not None and row.kitchen_id != str(kitchen_id)):
            raise ResourceNotFoundError(f"Scenario '{scenario_id}' not found")
        self.get_dataset_orm(UUID(row.dataset_version_id), kitchen_id=kitchen_id)
        if row.locked:
            raise ScenarioConflictError(
                f"Scenario '{scenario_id}' is locked after optimization; clone it to create a what-if scenario"
            )

        ing_rows = self.session.execute(
            select(IngredientORM.code, IngredientORM.id).where(
                IngredientORM.dataset_version_id == row.dataset_version_id
            )
        ).all()
        ing_id_by_code = {r[0]: r[1] for r in ing_rows}

        # Validate all overrides first so failure leaves DB untouched (atomic)
        validated: List[Tuple[str, float]] = []
        for entry in req.overrides:
            if entry.ingredient_code not in ing_id_by_code:
                raise DataValidationError(f"Unknown ingredient_code '{entry.ingredient_code}'")
            idr_per_g = convert_price_to_idr_per_g(
                entry.price_value, entry.unit, entry.density_g_per_ml
            )
            validated.append((ing_id_by_code[entry.ingredient_code], idr_per_g))

        try:
            for ing_id, idr_per_g in validated:
                existing = self.session.get(
                    ScenarioPriceOverrideORM, (str(scenario_id), ing_id)
                )
                if existing is None:
                    self.session.add(
                        ScenarioPriceOverrideORM(
                            scenario_id=str(scenario_id),
                            ingredient_id=ing_id,
                            price_idr_per_g=idr_per_g,
                        )
                    )
                else:
                    existing.price_idr_per_g = idr_per_g
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

        return self.get_scenario(scenario_id, kitchen_id=kitchen_id)

    def apply_stock_overrides(
        self,
        scenario_id: UUID,
        req: StockOverridesRequest,
        kitchen_id: Optional[UUID] = None,
    ) -> Scenario:
        row = self.session.get(ScenarioORM, str(scenario_id))
        if row is None or (kitchen_id is not None and row.kitchen_id != str(kitchen_id)):
            raise ResourceNotFoundError(f"Scenario '{scenario_id}' not found")
        self.get_dataset_orm(UUID(row.dataset_version_id), kitchen_id=kitchen_id)
        if row.locked:
            raise ScenarioConflictError(
                f"Scenario '{scenario_id}' is locked after optimization; clone it to create a what-if scenario"
            )

        ing_rows = self.session.execute(
            select(IngredientORM.code, IngredientORM.id).where(
                IngredientORM.dataset_version_id == row.dataset_version_id
            )
        ).all()
        ing_id_by_code = {r[0]: r[1] for r in ing_rows}

        validated: List[Tuple[str, float]] = []
        avail_by_code = {}
        if row.kitchen_id:
            avail = compute_usable_inventory(
                self.session,
                kitchen_id=UUID(row.kitchen_id),
                dataset_version_id=UUID(row.dataset_version_id),
                production_date=row.production_date,
            )
            avail_by_code = {item.ingredient_code: item for item in avail.items}

        for entry in req.overrides:
            if entry.ingredient_code not in ing_id_by_code:
                raise DataValidationError(f"Unknown ingredient_code '{entry.ingredient_code}'")
            avail_item = avail_by_code.get(entry.ingredient_code)
            if avail_item is not None and (
                avail_item.safety_held_raw_g > 0 or avail_item.rejected_disposed_raw_g > 0
            ):
                max_clean_g = avail_item.usable_raw_g if avail_item.usable_raw_g is not None else 0.0
                if entry.stock_raw_g > max_clean_g + 1e-6:
                    raise ScenarioConflictError(
                        f"Bahan '{avail_item.ingredient_name}' ({entry.ingredient_code}) memiliki lot berstatus tahan keamanan (SAFETY HOLD). "
                        f"Stok bersih siap pakai saat ini {max_clean_g / 1000.0:.2f} kg dan tidak dapat dinaikkan secara manual."
                    )
            validated.append((ing_id_by_code[entry.ingredient_code], entry.stock_raw_g))

        try:
            for ing_id, stock_g in validated:
                existing = self.session.get(
                    ScenarioStockOverrideORM, (str(scenario_id), ing_id)
                )
                if existing is None:
                    self.session.add(
                        ScenarioStockOverrideORM(
                            scenario_id=str(scenario_id),
                            ingredient_id=ing_id,
                            stock_raw_g=stock_g,
                        )
                    )
                else:
                    existing.stock_raw_g = stock_g
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

        return self.get_scenario(scenario_id, kitchen_id=kitchen_id)

    def _build_canonical_snapshot(
        self,
        scenario: Scenario,
        target: NutritionTargetProfile,
        ingredients_by_code: Dict[str, Ingredient],
        effective_prices: Dict[str, float],
        effective_stock: Dict[str, float],
        recipes: List[RecipeVariant],
        availability: Optional[InventoryAvailabilitySummary] = None,
    ) -> dict:
        snapshot = {
            "model_version": MODEL_VERSION,
            "dataset_version_id": str(scenario.dataset_version_id),
            "production_date": (
                scenario.production_date.isoformat() if scenario.production_date else None
            ),
            "nutrition_target": {
                "id": str(target.id),
                "cohort": target.cohort,
                "meal_type": target.meal_type,
                "version": target.version,
                "source_ref": target.source_ref,
                "limits": [
                    {
                        "nutrient_key": lim.nutrient_key,
                        "min_per_serving": lim.min_per_serving,
                        "max_per_serving": lim.max_per_serving,
                        "unit": lim.unit,
                    }
                    for lim in sorted(target.limits, key=lambda x: x.nutrient_key)
                ],
            },
            "scenario_params": {
                "meal_type": scenario.meal_type,
                "servings_per_day": scenario.servings_per_day,
                "days": scenario.days,
                "budget_idr_per_serving": scenario.budget_idr_per_serving,
                "max_repeat_per_family": scenario.max_repeat_per_family,
                "excluded_allergens": sorted(
                    {a.strip().lower() for a in scenario.excluded_allergens if a.strip()}
                ),
                "source_label": scenario.source_label.value,
            },
            "prices_idr_per_g": dict(sorted(effective_prices.items())),
            "stock_raw_g": dict(sorted(effective_stock.items())),
            "ingredients": [
                {
                    "code": ing.code,
                    "edible_fraction": ing.edible_fraction,
                    "allergens": sorted({a.strip().lower() for a in ing.allergens if a.strip()}),
                    "nutrients": ing.nutrients.model_dump(),
                }
                for ing in sorted(ingredients_by_code.values(), key=lambda x: x.code)
            ],
            "recipes": [
                {
                    "code": r.code,
                    "slot": r.slot.value,
                    "family": r.family,
                    "active": r.active,
                    "review_status": r.review_status.value,
                    "allergen_tags": sorted(
                        {a.strip().lower() for a in r.allergen_tags if a.strip()}
                    ),
                    "ingredients": [
                        {
                            "ingredient_code": ri.ingredient_code,
                            "raw_g_per_serving": ri.raw_g_per_serving,
                            "retention_factor": ri.retention_factor,
                        }
                        for ri in sorted(r.ingredients, key=lambda x: x.ingredient_code)
                    ],
                }
                for r in sorted(recipes, key=lambda x: x.code)
            ],
        }
        if availability is not None and availability.uses_batch_ledger:
            snapshot["inventory_availability"] = [
                {
                    "ingredient_code": item.ingredient_code,
                    "recorded_raw_g": item.recorded_raw_g,
                    "usable_raw_g": item.usable_raw_g,
                    "reserved_raw_g": item.reserved_raw_g,
                    "unavailable_raw_g": item.unavailable_raw_g,
                    "incoming_raw_g": item.incoming_raw_g,
                    "data_quality_status": item.data_quality_status,
                    "data_classification": item.data_classification,
                    "source_name": item.source_name,
                }
                for item in sorted(availability.items, key=lambda x: x.ingredient_code)
            ]
        return snapshot

    def run_optimization(
        self,
        scenario_id: UUID,
        time_limit_seconds: float = 10.0,
        forced_raw_result: Optional[RawSolveResult] = None,
        kitchen_id: Optional[UUID] = None,
    ) -> OptimizationRunResponse:
        scenario = self.get_scenario(scenario_id, kitchen_id=kitchen_id)
        sc_orm = self.session.get(ScenarioORM, str(scenario_id))
        effective_kitchen_id = kitchen_id or (
            UUID(sc_orm.kitchen_id) if sc_orm and sc_orm.kitchen_id else None
        )
        ingredients_by_code, ing_id_by_code, base_prices, base_stock, recipes = (
            self.load_dataset_bundle(scenario.dataset_version_id, kitchen_id=kitchen_id)
        )
        recipes_by_id = {r.id: r for r in recipes}
        target = self.get_target(scenario.nutrition_target_id)
        limits_by_key = {lim.nutrient_key: lim for lim in target.limits}

        effective_prices = {code: p.price_idr_per_g for code, p in base_prices.items()}
        effective_prices.update(scenario.price_overrides_idr_per_g)

        availability: Optional[InventoryAvailabilitySummary] = None
        effective_stock: Dict[str, float] = {}
        inv_warnings: List[str] = []
        if effective_kitchen_id is not None:
            availability = compute_usable_inventory(
                self.session,
                kitchen_id=effective_kitchen_id,
                dataset_version_id=scenario.dataset_version_id,
                production_date=scenario.production_date,
            )
            for item in availability.items:
                if item.ingredient_code in scenario.stock_overrides_raw_g:
                    override_val = scenario.stock_overrides_raw_g[item.ingredient_code]
                    if item.safety_held_raw_g > 0 or item.rejected_disposed_raw_g > 0:
                        max_clean_g = item.usable_raw_g if item.usable_raw_g is not None else 0.0
                        if override_val > max_clean_g + 1e-6:
                            raise ScenarioConflictError(
                                f"Optimasi diblokir: bahan '{item.ingredient_name}' ({item.ingredient_code}) sedang ditahan keamanan (SAFETY HOLD). "
                                f"Override stok ({override_val / 1000.0:.2f} kg) melebihi sisa lot bersih ({max_clean_g / 1000.0:.2f} kg)."
                            )
                    effective_stock[item.ingredient_code] = override_val
                elif item.usable_raw_g is not None:
                    effective_stock[item.ingredient_code] = item.usable_raw_g
                    if item.warnings:
                        inv_warnings.append(item.availability_explanation)
                else:
                    inv_warnings.append(item.availability_explanation)
        else:
            effective_stock = {code: s.stock_raw_g for code, s in base_stock.items()}
            effective_stock.update(scenario.stock_overrides_raw_g)

        all_features = precompute_all_recipes(
            recipes, ingredients_by_code, effective_prices, target.limits
        )
        features_by_id = {f.recipe_id: f for f in all_features}

        try:
            built = build_recipe_milp(
                scenario=scenario,
                recipes=recipes,
                features_by_id=features_by_id,
                target=target,
                stock_raw_g=effective_stock,
                ingredients_by_code=ingredients_by_code,
            )
        except ValueError as exc:
            raise DataValidationError(str(exc)) from exc

        input_snapshot = self._build_canonical_snapshot(
            scenario=scenario,
            target=target,
            ingredients_by_code=ingredients_by_code,
            effective_prices=effective_prices,
            effective_stock=effective_stock,
            recipes=recipes,
            availability=availability,
        )
        input_sha256 = compute_snapshot_sha256(input_snapshot)
        price_snapshot_id = f"snap-{input_sha256[:12]}"

        ds_orm = self.session.get(DatasetVersionORM, str(scenario.dataset_version_id))
        if ds_orm and not ds_orm.is_synthetic:
            warnings = [
                "DATA_PILOT_NO_CLINICAL_SIGNOFF: Menggunakan data inventaris terunggah dapur; tetap memerlukan validasi ahli gizi sebelum klaim kepatuhan BGN."
            ]
        else:
            warnings = [
                "SIMULATION_ONLY: Nilai nutrisi, harga, dan stok adalah data sintetis (DEMO_ONLY) untuk demonstrasi dan belum divalidasi ahli gizi."
            ]
        if inv_warnings:
            warnings.extend(inv_warnings[:6])

        raw_result = (
            forced_raw_result
            if forced_raw_result is not None
            else solve_built_model(built, time_limit_seconds=time_limit_seconds)
        )

        # Build OptimizationRunResponse object
        run_id = uuid4()
        created_at = datetime.now(timezone.utc)
        total_servings = scenario.days * scenario.servings_per_day
        common_meta = dict(
            run_id=run_id,
            scenario_id=scenario.id,
            dataset_version_id=scenario.dataset_version_id,
            price_snapshot_id=price_snapshot_id,
            simulation_only=True,
            days_count=scenario.days,
            servings_per_day=scenario.servings_per_day,
            total_servings=total_servings,
            total_menu_slots=scenario.days * len(SlotEnum),
            best_bound=raw_result.best_bound,
            gap_abs=raw_result.gap_abs,
            gap_rel=raw_result.gap_rel,
            solver_name=raw_result.solver_name,
            solver_version=raw_result.solver_version,
            raw_solver_status=raw_result.raw_solver_status,
            solver_seconds=raw_result.solver_seconds,
            input_sha256=input_sha256,
            model_version=MODEL_VERSION,
            input_snapshot=input_snapshot,
            created_at=created_at,
        )

        run_resp: OptimizationRunResponse
        if raw_result.solver_status == SolverStatusEnum.ERROR:
            run_resp = OptimizationRunResponse(
                **common_meta,
                solver_status=SolverStatusEnum.ERROR,
                validation_passed=False,
                objective_total_idr=None,
                cost_per_serving_average_idr=None,
                days=[],
                constraint_audit=ConstraintAudit(all_hard_constraints_pass=False),
                warnings=warnings + [f"Solver error: {raw_result.error_message or 'unknown error'}"],
            )
        elif raw_result.solver_status == SolverStatusEnum.INFEASIBLE:
            try:
                diag_solver = create_cbc_solver(time_limit_seconds=min(time_limit_seconds, 5.0))
                diagnostics = diagnose_infeasibility(
                    scenario,
                    recipes,
                    features_by_id,
                    target,
                    effective_stock,
                    diag_solver,
                    ingredients_by_code=ingredients_by_code,
                )
            except Exception:
                diagnostics = [
                    DiagnosticHint(
                        family="combined",
                        message="Tidak dapat menentukan bottleneck secara terpisah; periksa anggaran, stok, dan target gizi.",
                    )
                ]
            run_resp = OptimizationRunResponse(
                **common_meta,
                solver_status=SolverStatusEnum.INFEASIBLE,
                validation_passed=False,
                objective_total_idr=None,
                cost_per_serving_average_idr=None,
                days=[],
                constraint_audit=ConstraintAudit(all_hard_constraints_pass=False),
                constraint_diagnostics=diagnostics,
                warnings=warnings
                + [
                    "Tidak ada menu yang memenuhi semua batasan. Jangan gunakan alternatif relaksasi sebagai rekomendasi valid."
                ],
            )
        elif not raw_result.has_incumbent and raw_result.raw_x_values is None:
            run_resp = OptimizationRunResponse(
                **common_meta,
                solver_status=raw_result.solver_status,
                validation_passed=False,
                objective_total_idr=None,
                cost_per_serving_average_idr=None,
                days=[],
                constraint_audit=ConstraintAudit(all_hard_constraints_pass=False),
                warnings=warnings
                + ["Solver tidak menghasilkan solusi integer lengkap yang dapat diverifikasi."],
            )
        else:
            audit = verify_assignments(
                scenario=scenario,
                assignments_by_day=raw_result.assignments_by_day,
                recipes_by_id=recipes_by_id,
                ingredients_by_code=ingredients_by_code,
                effective_prices_idr_per_g=effective_prices,
                target=target,
                stock_raw_g=effective_stock,
                raw_x_values=raw_result.raw_x_values,
                reported_objective=raw_result.reported_objective,
            )
            if not audit.all_hard_constraints_pass:
                run_resp = OptimizationRunResponse(
                    **common_meta,
                    solver_status=raw_result.solver_status,
                    validation_passed=False,
                    objective_total_idr=None,
                    cost_per_serving_average_idr=None,
                    days=[],
                    constraint_audit=audit,
                    warnings=warnings
                    + [
                        "Solusi ditolak oleh independent validator karena melanggar hard constraint."
                    ],
                )
            else:
                day_plans: List[DayPlan] = []
                used_by_ingredient: Dict[str, float] = {}
                total_cost_idr = 0.0

                for d in range(1, scenario.days + 1):
                    slot_map = raw_result.assignments_by_day[d]
                    names_map: Dict[SlotEnum, str] = {}
                    day_cost_per_serving = 0.0
                    day_nutrients: Dict[str, float] = {lim.nutrient_key: 0.0 for lim in target.limits}

                    for slot, rid in slot_map.items():
                        feat = features_by_id[rid]
                        names_map[slot] = feat.recipe_name
                        day_cost_per_serving += feat.cost_idr_per_serving
                        for k in day_nutrients:
                            day_nutrients[k] += feat.nutrients_per_serving[k]
                        for ing_code, raw_g in feat.raw_grams_by_ingredient.items():
                            used_by_ingredient[ing_code] = (
                                used_by_ingredient.get(ing_code, 0.0)
                                + raw_g * scenario.servings_per_day
                            )

                    total_cost_idr += day_cost_per_serving * scenario.servings_per_day
                    day_plans.append(
                        DayPlan(
                            day_index=d,
                            recipes_by_slot=slot_map,
                            recipe_names_by_slot=names_map,
                            daily_cost_idr_per_serving=round(day_cost_per_serving, 2),
                            nutrients_per_serving={k: round(v, 3) for k, v in day_nutrients.items()},
                        )
                    )

                material_usage = [
                    MaterialUsage(
                        ingredient_code=code,
                        ingredient_name=ingredients_by_code[code].name,
                        used_raw_g=round(used_g, 2),
                        available_raw_g=round(effective_stock.get(code, 0.0), 2),
                    )
                    for code, used_g in sorted(used_by_ingredient.items())
                ]
                avg_cost = total_cost_idr / (scenario.days * scenario.servings_per_day)
                avg_daily_cost = total_cost_idr / max(1, scenario.days)
                solved_meta = {
                    **common_meta,
                    "total_menu_slots": sum(len(d.recipes_by_slot) for d in day_plans),
                }

                run_resp = OptimizationRunResponse(
                    **solved_meta,
                    solver_status=raw_result.solver_status,
                    validation_passed=True,
                    objective_total_idr=round(total_cost_idr, 2),
                    cost_per_serving_average_idr=round(avg_cost, 2),
                    cost_per_day_average_idr=round(avg_daily_cost, 2),
                    days=day_plans,
                    material_usage=material_usage,
                    constraint_audit=audit,
                    warnings=warnings,
                )

        # Persist scenario lock + run + assignments + metrics + material usage atomically
        try:
            sc_row = self.session.get(ScenarioORM, str(scenario_id))
            assert sc_row is not None
            sc_row.locked = True

            run_row = OptimizationRunORM(
                id=str(run_resp.run_id),
                scenario_id=str(run_resp.scenario_id),
                dataset_version_id=str(run_resp.dataset_version_id),
                price_snapshot_id=run_resp.price_snapshot_id,
                solver_status=run_resp.solver_status.value,
                validation_passed=run_resp.validation_passed,
                simulation_only=run_resp.simulation_only,
                objective_total_idr=run_resp.objective_total_idr,
                cost_per_serving_average_idr=run_resp.cost_per_serving_average_idr,
                best_bound=run_resp.best_bound,
                gap_abs=run_resp.gap_abs,
                gap_rel=run_resp.gap_rel,
                solver_name=run_resp.solver_name,
                solver_version=run_resp.solver_version,
                raw_solver_status=run_resp.raw_solver_status,
                solver_seconds=run_resp.solver_seconds,
                model_version=run_resp.model_version,
                input_sha256=run_resp.input_sha256,
                input_snapshot_json=run_resp.input_snapshot,
                constraint_audit_json=run_resp.constraint_audit.model_dump(mode="json"),
                constraint_diagnostics_json=[
                    d.model_dump(mode="json") for d in run_resp.constraint_diagnostics
                ],
                warnings_json=list(run_resp.warnings),
                created_at=run_resp.created_at,
            )
            self.session.add(run_row)
            self.session.flush()

            for day in run_resp.days:
                for slot, rid in day.recipes_by_slot.items():
                    self.session.add(
                        RunAssignmentORM(
                            run_id=str(run_resp.run_id),
                            day_index=day.day_index,
                            slot=slot.value,
                            recipe_id=str(rid),
                            recipe_name=day.recipe_names_by_slot[slot],
                            daily_cost_idr_per_serving=day.daily_cost_idr_per_serving,
                        )
                    )
                for nkey, nval in day.nutrients_per_serving.items():
                    lim = limits_by_key.get(nkey)
                    self.session.add(
                        RunMetricORM(
                            run_id=str(run_resp.run_id),
                            day_index=day.day_index,
                            nutrient_key=nkey,
                            actual_value=nval,
                            min_value=lim.min_per_serving if lim else None,
                            max_value=lim.max_per_serving if lim else None,
                            unit=lim.unit if lim else "",
                        )
                    )

            for mu in run_resp.material_usage:
                self.session.add(
                    RunMaterialUsageORM(
                        run_id=str(run_resp.run_id),
                        ingredient_id=ing_id_by_code[mu.ingredient_code],
                        ingredient_code=mu.ingredient_code,
                        ingredient_name=mu.ingredient_name,
                        used_raw_g=mu.used_raw_g,
                        available_raw_g=mu.available_raw_g,
                    )
                )

            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

        return self.get_run(run_resp.run_id, kitchen_id=kitchen_id)

    def get_run(
        self, run_id: UUID, kitchen_id: Optional[UUID] = None, *, approved_only: bool = False
    ) -> OptimizationRunResponse:
        stmt = (
            select(OptimizationRunORM)
            .options(
                selectinload(OptimizationRunORM.assignments),
                selectinload(OptimizationRunORM.metrics),
                selectinload(OptimizationRunORM.material_usage),
            )
            .where(OptimizationRunORM.id == str(run_id))
        )
        if kitchen_id is not None:
            stmt = stmt.join(ScenarioORM, OptimizationRunORM.scenario_id == ScenarioORM.id).where(
                ScenarioORM.kitchen_id == str(kitchen_id),
                OptimizationRunORM.dataset_version_id.in_(self.visible_dataset_ids(kitchen_id)),
            )
        if approved_only:
            stmt = stmt.where(self._has_approved_review(OptimizationRunORM.id, MenuReviewRecordORM.run_id))
        row = self.session.execute(stmt).scalar_one_or_none()
        if row is None:
            raise ResourceNotFoundError(f"Run '{run_id}' not found")

        days_map: Dict[int, dict] = {}
        for assign in sorted(row.assignments, key=lambda a: (a.day_index, a.slot)):
            bucket = days_map.setdefault(
                assign.day_index,
                {
                    "recipes_by_slot": {},
                    "recipe_names_by_slot": {},
                    "daily_cost_idr_per_serving": assign.daily_cost_idr_per_serving,
                    "nutrients_per_serving": {},
                },
            )
            slot_enum = SlotEnum(assign.slot)
            bucket["recipes_by_slot"][slot_enum] = UUID(assign.recipe_id)
            bucket["recipe_names_by_slot"][slot_enum] = assign.recipe_name

        for metric in row.metrics:
            if metric.day_index in days_map:
                days_map[metric.day_index]["nutrients_per_serving"][metric.nutrient_key] = (
                    metric.actual_value
                )

        days = [
            DayPlan(
                day_index=d_idx,
                recipes_by_slot=bucket["recipes_by_slot"],
                recipe_names_by_slot=bucket["recipe_names_by_slot"],
                daily_cost_idr_per_serving=bucket["daily_cost_idr_per_serving"],
                nutrients_per_serving=dict(sorted(bucket["nutrients_per_serving"].items())),
            )
            for d_idx, bucket in sorted(days_map.items())
        ]

        material_usage = [
            MaterialUsage(
                ingredient_code=m.ingredient_code,
                ingredient_name=m.ingredient_name,
                used_raw_g=m.used_raw_g,
                available_raw_g=m.available_raw_g,
            )
            for m in sorted(row.material_usage, key=lambda x: x.ingredient_code)
        ]

        sc_row = self.session.get(ScenarioORM, row.scenario_id)
        snap_params = (row.input_snapshot_json or {}).get("scenario_parameters", {})
        days_count = sc_row.days if sc_row is not None else (snap_params.get("days") or len(days))
        servings_per_day = (
            sc_row.servings_per_day
            if sc_row is not None
            else snap_params.get("servings_per_day")
        )
        total_servings = (
            days_count * servings_per_day
            if days_count is not None and servings_per_day is not None
            else None
        )
        total_menu_slots = (
            sum(len(d.recipes_by_slot) for d in days)
            if days
            else (days_count * len(SlotEnum) if days_count is not None else None)
        )
        cost_per_day_avg = (
            round(float(row.objective_total_idr) / max(1, int(days_count)), 2)
            if row.objective_total_idr is not None and days_count
            else None
        )

        return OptimizationRunResponse(
            run_id=UUID(row.id),
            scenario_id=UUID(row.scenario_id),
            dataset_version_id=UUID(row.dataset_version_id),
            price_snapshot_id=row.price_snapshot_id,
            solver_status=SolverStatusEnum(row.solver_status),
            validation_passed=row.validation_passed,
            simulation_only=row.simulation_only,
            days_count=days_count,
            servings_per_day=servings_per_day,
            total_servings=total_servings,
            total_menu_slots=total_menu_slots,
            objective_total_idr=row.objective_total_idr,
            cost_per_serving_average_idr=row.cost_per_serving_average_idr,
            cost_per_day_average_idr=cost_per_day_avg,
            best_bound=row.best_bound,
            gap_abs=row.gap_abs,
            gap_rel=row.gap_rel,
            solver_name=row.solver_name,
            solver_version=row.solver_version,
            raw_solver_status=row.raw_solver_status,
            solver_seconds=row.solver_seconds,
            input_sha256=row.input_sha256,
            model_version=row.model_version,
            input_snapshot=dict(row.input_snapshot_json or {}),
            days=days,
            material_usage=material_usage,
            constraint_audit=ConstraintAudit.model_validate(row.constraint_audit_json),
            constraint_diagnostics=[
                DiagnosticHint.model_validate(d) for d in (row.constraint_diagnostics_json or [])
            ],
            warnings=list(row.warnings_json or []),
            created_at=row.created_at,
        )
