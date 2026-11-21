from __future__ import annotations

import math
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator, model_validator


def _ensure_finite(value: Optional[float], field_name: str) -> Optional[float]:
    if value is not None and not math.isfinite(value):
        raise ValueError(f"{field_name} must be a finite number, got {value!r}")
    return value


class SlotEnum(str, Enum):
    STAPLE = "staple"
    PROTEIN = "protein"
    VEGETABLE = "vegetable"
    FRUIT = "fruit"


class ReviewStatusEnum(str, Enum):
    DRAFT = "draft"
    NEEDS_REVIEW = "needs_review"
    REVIEWED = "reviewed"
    REJECTED = "rejected"


class SolverStatusEnum(str, Enum):
    OPTIMAL = "OPTIMAL"
    FEASIBLE = "FEASIBLE"
    INFEASIBLE = "INFEASIBLE"
    TIME_LIMIT = "TIME_LIMIT"
    ERROR = "ERROR"


class SourceTypeEnum(str, Enum):
    OFFICIAL = "official"
    UPLOADED = "uploaded"
    RESEARCH = "research"
    SYNTHETIC = "synthetic"


class DatasetVersion(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    name: str
    source_type: SourceTypeEnum = SourceTypeEnum.SYNTHETIC
    source_url: Optional[str] = None
    is_synthetic: bool = True
    review_status: ReviewStatusEnum = ReviewStatusEnum.DRAFT
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class IngredientNutrients(BaseModel):
    energy_kcal_100g: Optional[float] = Field(default=None, ge=0)
    protein_g_100g: Optional[float] = Field(default=None, ge=0)
    fat_g_100g: Optional[float] = Field(default=None, ge=0)
    carb_g_100g: Optional[float] = Field(default=None, ge=0)
    fiber_g_100g: Optional[float] = Field(default=None, ge=0)
    iron_mg_100g: Optional[float] = Field(default=None, ge=0)

    @field_validator(
        "energy_kcal_100g",
        "protein_g_100g",
        "fat_g_100g",
        "carb_g_100g",
        "fiber_g_100g",
        "iron_mg_100g",
    )
    @classmethod
    def check_finite(cls, v: Optional[float]) -> Optional[float]:
        return _ensure_finite(v, "nutrient_100g")

    def get_nutrient(self, key: str) -> Optional[float]:
        mapping = {
            "energy_kcal": self.energy_kcal_100g,
            "protein_g": self.protein_g_100g,
            "fat_g": self.fat_g_100g,
            "carb_g": self.carb_g_100g,
            "fiber_g": self.fiber_g_100g,
            "iron_mg": self.iron_mg_100g,
        }
        if key not in mapping:
            raise ValueError(f"Unknown nutrient key: {key}")
        return mapping[key]


class Ingredient(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    code: str
    name: str
    category: str
    edible_fraction: float = Field(gt=0.0, le=1.0)
    allergens: List[str] = Field(default_factory=list)
    nutrients: IngredientNutrients
    source_type: SourceTypeEnum = SourceTypeEnum.SYNTHETIC
    source_ref: str = "DEMO_ONLY"
    review_status: ReviewStatusEnum = ReviewStatusEnum.DRAFT

    @field_validator("edible_fraction")
    @classmethod
    def check_edible_finite(cls, v: float) -> float:
        _ensure_finite(v, "edible_fraction")
        return v


class IngredientPrice(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    ingredient_code: str
    price_idr_per_g: float = Field(gt=0.0)
    original_value: float = Field(gt=0.0)
    original_unit: str
    region: str = "SIMULASI"
    observed_at: date
    source_type: SourceTypeEnum = SourceTypeEnum.SYNTHETIC
    dataset_version_id: UUID

    @field_validator("price_idr_per_g", "original_value")
    @classmethod
    def check_price_finite(cls, v: float) -> float:
        _ensure_finite(v, "price")
        return v


class StockItem(BaseModel):
    ingredient_code: str
    stock_raw_g: float = Field(ge=0.0)

    @field_validator("stock_raw_g")
    @classmethod
    def check_stock_finite(cls, v: float) -> float:
        _ensure_finite(v, "stock_raw_g")
        return v


class RecipeIngredient(BaseModel):
    ingredient_code: str
    raw_g_per_serving: float = Field(gt=0.0)
    retention_factor: float = Field(default=1.0, gt=0.0, le=1.0)

    @field_validator("raw_g_per_serving", "retention_factor")
    @classmethod
    def check_recipe_ing_finite(cls, v: float) -> float:
        _ensure_finite(v, "recipe_ingredient_value")
        return v


class RecipeVariant(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    code: str
    name: str
    slot: SlotEnum
    family: str
    review_status: ReviewStatusEnum = ReviewStatusEnum.DRAFT
    reviewer: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    active: bool = True
    allergen_tags: List[str] = Field(default_factory=list)
    ingredients: List[RecipeIngredient] = Field(min_length=1)


class NutritionTargetLimit(BaseModel):
    nutrient_key: str
    min_per_serving: Optional[float] = Field(default=None, ge=0.0)
    max_per_serving: Optional[float] = Field(default=None, ge=0.0)
    unit: str

    @field_validator("min_per_serving", "max_per_serving")
    @classmethod
    def check_limit_finite(cls, v: Optional[float]) -> Optional[float]:
        return _ensure_finite(v, "target_limit")

    @model_validator(mode="after")
    def check_bounds(self) -> "NutritionTargetLimit":
        if (
            self.min_per_serving is not None
            and self.max_per_serving is not None
            and self.min_per_serving > self.max_per_serving
        ):
            raise ValueError(
                f"min_per_serving ({self.min_per_serving}) cannot exceed max_per_serving ({self.max_per_serving}) for {self.nutrient_key}"
            )
        return self


class NutritionTargetProfile(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    cohort: str
    meal_type: str = "lunch"
    source_ref: str = "DEMO_ONLY"
    version: str = "0.1-synthetic"
    review_status: ReviewStatusEnum = ReviewStatusEnum.DRAFT
    limits: List[NutritionTargetLimit] = Field(min_length=1)

    @model_validator(mode="after")
    def check_unique_keys(self) -> "NutritionTargetProfile":
        keys = [lim.nutrient_key for lim in self.limits]
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate nutrient_key in NutritionTargetProfile.limits")
        return self


class ScenarioCreateRequest(BaseModel):
    name: str
    dataset_version_id: Optional[UUID] = None
    nutrition_target_id: Optional[UUID] = None
    meal_type: str = "lunch"
    servings_per_day: int = Field(default=100, ge=1, le=10000)
    days: int = Field(default=5, ge=1, le=14)
    budget_idr_per_serving: float = Field(default=12000.0, gt=0.0)
    max_repeat_per_family: int = Field(default=2, ge=1, le=14)
    excluded_allergens: List[str] = Field(default_factory=list)
    source_label: SourceTypeEnum = SourceTypeEnum.SYNTHETIC
    production_date: Optional[datetime] = None
    service_dates: Optional[List[date]] = None
    continuation_of_run_id: Optional[UUID] = None

    @field_validator("budget_idr_per_serving")
    @classmethod
    def check_budget_finite(cls, v: float) -> float:
        _ensure_finite(v, "budget_idr_per_serving")
        return v

    @model_validator(mode="after")
    def validate_service_dates(self) -> "ScenarioCreateRequest":
        if self.service_dates is not None:
            if not (1 <= len(self.service_dates) <= 14):
                raise ValueError("service_dates harus berisi antara 1 hingga 14 tanggal pelayanan.")
            if len(set(self.service_dates)) != len(self.service_dates):
                raise ValueError("service_dates tidak boleh mengandung tanggal duplikat.")
            sorted_dates = sorted(self.service_dates)
            self.service_dates = sorted_dates
            self.days = len(sorted_dates)
            if self.production_date is None:
                d0 = sorted_dates[0]
                self.production_date = datetime(d0.year, d0.month, d0.day, 8, 0, tzinfo=timezone.utc)
        return self


class ScenarioCloneRequest(BaseModel):
    name: Optional[str] = None


class PriceOverrideEntry(BaseModel):
    ingredient_code: str
    price_value: float
    unit: str = "IDR/kg"
    density_g_per_ml: Optional[float] = None


class PriceOverridesRequest(BaseModel):
    overrides: List[PriceOverrideEntry] = Field(min_length=1)


class StockOverrideEntry(BaseModel):
    ingredient_code: str
    stock_raw_g: float = Field(ge=0.0)

    @field_validator("stock_raw_g")
    @classmethod
    def check_stock_override_finite(cls, v: float) -> float:
        _ensure_finite(v, "stock_raw_g")
        return v


class StockOverridesRequest(BaseModel):
    overrides: List[StockOverrideEntry] = Field(min_length=1)


class OptimizeRequest(BaseModel):
    time_limit_seconds: float = Field(default=10.0, gt=0.0, le=60.0)


class Scenario(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    name: str
    parent_scenario_id: Optional[UUID] = None
    dataset_version_id: UUID
    nutrition_target_id: UUID
    meal_type: str = "lunch"
    servings_per_day: int = Field(default=100, ge=1, le=10000)
    days: int = Field(default=5, ge=1, le=14)
    budget_idr_per_serving: float = Field(gt=0.0)
    max_repeat_per_family: int = Field(default=2, ge=1, le=14)
    excluded_allergens: List[str] = Field(default_factory=list)
    price_overrides_idr_per_g: Dict[str, float] = Field(default_factory=dict)
    stock_overrides_raw_g: Dict[str, float] = Field(default_factory=dict)
    source_label: SourceTypeEnum = SourceTypeEnum.SYNTHETIC
    production_date: Optional[datetime] = None
    service_dates: List[date] = Field(default_factory=list)
    continuation_of_run_id: Optional[UUID] = None
    locked: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class RecipeFeatures(BaseModel):
    recipe_id: UUID
    recipe_code: str
    recipe_name: str
    slot: SlotEnum
    family: str
    cost_idr_per_serving: float
    nutrients_per_serving: Dict[str, float]
    raw_grams_by_ingredient: Dict[str, float]


class DayPlan(BaseModel):
    day_index: int
    service_date: Optional[date] = None
    recipes_by_slot: Dict[SlotEnum, UUID]
    recipe_names_by_slot: Dict[SlotEnum, str]
    daily_cost_idr_per_serving: float
    nutrients_per_serving: Dict[str, float]


class ConstraintViolation(BaseModel):
    constraint_family: str
    detail: str
    expected: Optional[float] = None
    actual: Optional[float] = None


class ConstraintAudit(BaseModel):
    all_hard_constraints_pass: bool
    tolerance: float = 1e-6
    violations: List[ConstraintViolation] = Field(default_factory=list)


class DiagnosticHint(BaseModel):
    family: str
    message: str


class MaterialUsage(BaseModel):
    ingredient_code: str
    ingredient_name: str
    used_raw_g: float
    available_raw_g: float


class OptimizationRunResponse(BaseModel):
    run_id: UUID = Field(default_factory=uuid4)
    scenario_id: UUID
    dataset_version_id: UUID
    price_snapshot_id: str
    solver_status: SolverStatusEnum
    validation_passed: bool
    simulation_only: bool = True
    objective_total_idr: Optional[float] = None
    cost_per_serving_average_idr: Optional[float] = None
    days_count: Optional[int] = None
    service_dates: List[date] = Field(default_factory=list)
    servings_per_day: Optional[int] = None
    total_servings: Optional[int] = None
    total_menu_slots: Optional[int] = None
    cost_per_day_average_idr: Optional[float] = None
    stock_confirmation_required: bool = False
    stock_confirmation_reason: Optional[str] = None
    history_context: Optional[Dict[str, Any]] = None
    best_bound: Optional[float] = None
    gap_abs: Optional[float] = None
    gap_rel: Optional[float] = None
    solver_name: Optional[str] = None
    solver_version: Optional[str] = None
    raw_solver_status: Optional[str] = None
    solver_seconds: float
    input_sha256: str
    model_version: str = "recipe-milp-v0.1"
    input_snapshot: Dict[str, Any] = Field(default_factory=dict)
    days: List[DayPlan] = Field(default_factory=list)
    material_usage: List[MaterialUsage] = Field(default_factory=list)
    constraint_audit: ConstraintAudit
    constraint_diagnostics: List[DiagnosticHint] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
