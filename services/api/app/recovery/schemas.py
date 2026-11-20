from __future__ import annotations

from datetime import datetime
from enum import Enum
import math
from typing import Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.domain.models.schemas import (
    DiagnosticHint,
    OptimizationRunResponse,
    SlotEnum,
    SolverStatusEnum,
)


class DisruptionTypeEnum(str, Enum):
    PRICE_CHANGE = "PRICE_CHANGE"
    STOCK_SHORTAGE = "STOCK_SHORTAGE"
    SUPPLIER_DELAY = "SUPPLIER_DELAY"
    PARTIAL_DELIVERY = "PARTIAL_DELIVERY"
    INGREDIENT_UNAVAILABLE = "INGREDIENT_UNAVAILABLE"
    SERVING_COUNT_CHANGE = "SERVING_COUNT_CHANGE"
    SAFETY_HOLD = "SAFETY_HOLD"


class RecoveryModeEnum(str, Enum):
    MIN_DISRUPTION = "MIN_DISRUPTION"
    MIN_COST = "MIN_COST"


class RecoveryStatusEnum(str, Enum):
    ANALYZED = "ANALYZED"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REVISION_REQUIRED = "REVISION_REQUIRED"
    INFEASIBLE = "INFEASIBLE"


class PriceDisruptionInput(BaseModel):
    ingredient_code: str = Field(min_length=1, max_length=64)
    new_price_idr_per_kg: float = Field(gt=0.0)

    @field_validator("ingredient_code")
    @classmethod
    def clean_code(cls, v: str) -> str:
        text = v.strip()
        if not text:
            raise ValueError("ingredient_code cannot be empty")
        return text

    @field_validator("new_price_idr_per_kg")
    @classmethod
    def validate_finite_price(cls, v: float) -> float:
        if not math.isfinite(v) or v <= 0:
            raise ValueError("Harga harus berupa angka positif yang valid (> 0 Rp/kg).")
        return float(v)


class StockDisruptionInput(BaseModel):
    ingredient_code: str = Field(min_length=1, max_length=64)
    new_usable_kg: Optional[float] = Field(default=None, ge=0.0)
    expected_delivery_kg: Optional[float] = Field(default=None, ge=0.0)
    received_delivery_kg: Optional[float] = Field(default=None, ge=0.0)
    unavailable: bool = False
    delivery_status: Optional[str] = Field(default=None, max_length=32)
    reason: Optional[str] = Field(default=None, max_length=255)

    @field_validator("ingredient_code")
    @classmethod
    def clean_code(cls, v: str) -> str:
        text = v.strip()
        if not text:
            raise ValueError("ingredient_code cannot be empty")
        return text

    @field_validator("new_usable_kg", "expected_delivery_kg", "received_delivery_kg")
    @classmethod
    def validate_finite_nonneg(cls, v: Optional[float]) -> Optional[float]:
        if v is None:
            return None
        if not math.isfinite(v) or v < 0:
            raise ValueError("Stok/pengiriman harus berupa bilangan nonnegatif yang valid.")
        return float(v)


class DisruptionConditionRequest(BaseModel):
    baseline_run_id: Optional[UUID] = None
    baseline_menu_review_id: Optional[UUID] = None
    incident_id: Optional[UUID] = None
    title: Optional[str] = Field(default=None, max_length=255)
    disruption_summary: Optional[str] = Field(default=None, max_length=1000)
    disruption_types: List[DisruptionTypeEnum] = Field(default_factory=list)
    production_date: Optional[datetime] = None
    use_latest_verified_inventory: bool = True
    new_servings_per_day: Optional[int] = Field(default=None, ge=1, le=500000)
    new_budget_idr_per_serving: Optional[float] = Field(default=None, gt=0.0)
    price_changes: List[PriceDisruptionInput] = Field(default_factory=list)
    stock_changes: List[StockDisruptionInput] = Field(default_factory=list)
    time_limit_seconds: float = Field(default=10.0, gt=0.1, le=60.0)

    @field_validator("new_budget_idr_per_serving")
    @classmethod
    def validate_budget_finite(cls, v: Optional[float]) -> Optional[float]:
        if v is None:
            return None
        if not math.isfinite(v) or v <= 0:
            raise ValueError("Anggaran per porsi harus bernilai positif dan finite.")
        return float(v)


class AffectedIngredientItem(BaseModel):
    ingredient_code: str
    ingredient_name: str
    baseline_required_kg: float
    previous_usable_kg: Optional[float] = None
    current_usable_kg: Optional[float] = None
    shortfall_kg: float = 0.0
    previous_price_idr_per_kg: float
    current_price_idr_per_kg: float
    price_delta_pct: Optional[float] = None
    delivery_status: str = "NONE"
    incoming_kg: float = 0.0
    data_quality_status: str = "UNKNOWN"
    causes: List[str] = Field(default_factory=list)


class AffectedSlotItem(BaseModel):
    day_index: int
    slot: SlotEnum
    original_recipe_id: UUID
    original_recipe_name: str
    affected_ingredients: List[str] = Field(default_factory=list)
    reasons: List[str] = Field(default_factory=list)


class DisruptionImpactReport(BaseModel):
    baseline_run_id: UUID
    baseline_menu_review_id: Optional[UUID] = None
    baseline_title: str
    baseline_status: str
    dataset_version_id: UUID
    dataset_name: str
    production_date: datetime
    days: int
    baseline_servings_per_day: int
    servings_per_day: int
    baseline_budget_idr_per_serving: float
    budget_idr_per_serving: float
    inventory_snapshot_sha256: str
    is_disrupted: bool
    baseline_still_feasible_at_new_conditions: bool
    disruption_types: List[DisruptionTypeEnum] = Field(default_factory=list)
    affected_ingredients: List[AffectedIngredientItem] = Field(default_factory=list)
    affected_slots: List[AffectedSlotItem] = Field(default_factory=list)
    budget_violations: List[str] = Field(default_factory=list)
    stock_shortages: List[str] = Field(default_factory=list)
    nutrition_or_other_issues: List[str] = Field(default_factory=list)
    summary_message: str
    warnings: List[str] = Field(default_factory=list)


class SlotSwapDetail(BaseModel):
    day_index: int
    slot: SlotEnum
    original_recipe_id: UUID
    original_recipe_name: str
    new_recipe_id: UUID
    new_recipe_name: str
    reason: str


class CandidatePlanSummary(BaseModel):
    mode: RecoveryModeEnum
    scenario_id: Optional[UUID] = None
    run_id: Optional[UUID] = None
    solver_status: SolverStatusEnum
    validation_passed: bool
    changed_slots_count: int = 0
    unchanged_slots_count: int = 0
    total_slots_count: int = 0
    changed_slots: List[SlotSwapDetail] = Field(default_factory=list)
    total_cost_idr: Optional[float] = None
    cost_per_serving_idr: Optional[float] = None
    days_count: Optional[int] = None
    servings_per_day: Optional[int] = None
    total_servings: Optional[int] = None
    total_menu_slots: Optional[int] = None
    cost_per_day_average_idr: Optional[float] = None
    delta_vs_original_historical_idr: Optional[float] = None
    delta_vs_original_at_new_conditions_idr: Optional[float] = None
    delta_vs_min_disruption_idr: Optional[float] = None
    constraint_diagnostics: List[DiagnosticHint] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    run_detail: Optional[OptimizationRunResponse] = None


class CounterfactualBaselineSnapshot(BaseModel):
    label: str
    feasible: bool
    total_cost_idr: Optional[float] = None
    cost_per_serving_idr: Optional[float] = None
    days_count: Optional[int] = None
    servings_per_day: Optional[int] = None
    total_servings: Optional[int] = None
    cost_per_day_average_idr: Optional[float] = None
    notes: str
    budget_violations: List[str] = Field(default_factory=list)
    stock_shortages: List[str] = Field(default_factory=list)
    nutrition_or_other_issues: List[str] = Field(default_factory=list)


class FairComparisonBundle(BaseModel):
    original_historical: CounterfactualBaselineSnapshot
    original_under_new_conditions: CounterfactualBaselineSnapshot
    same_conditions_comparison_valid: bool
    historical_price_comparison_allowed: bool = False
    cost_savings_claimed_idr: Optional[float] = None
    comparison_notice: str
    min_disruption_vs_min_cost_identical: bool = False
    extra_slots_changed_for_min_cost: Optional[int] = None
    savings_by_choosing_min_cost_over_min_disruption_idr: Optional[float] = None


class ProcurementDeltaItem(BaseModel):
    ingredient_code: str
    ingredient_name: str
    baseline_required_kg: float
    required_kg: float
    delta_vs_baseline_required_kg: float
    usable_on_hand_kg: float
    incoming_kg: float
    delivery_status: str
    net_to_buy_kg: float
    unit_price_idr_per_kg: float
    estimated_net_purchase_cost_idr: float
    reason: str


class RecoveryEventResponse(BaseModel):
    id: UUID
    kitchen_id: UUID
    dataset_version_id: UUID
    baseline_menu_review_id: Optional[UUID] = None
    baseline_run_id: UUID
    baseline_scenario_id: UUID
    incident_id: Optional[UUID] = None
    title: str
    status: RecoveryStatusEnum
    disruption_types: List[DisruptionTypeEnum] = Field(default_factory=list)
    disruption_summary: str
    impact: DisruptionImpactReport
    min_disruption: CandidatePlanSummary
    min_cost: CandidatePlanSummary
    comparison: FairComparisonBundle
    procurement_delta_by_mode: Dict[str, List[ProcurementDeltaItem]] = Field(default_factory=dict)
    selected_mode: Optional[RecoveryModeEnum] = None
    selected_run_id: Optional[UUID] = None
    submitted_review_id: Optional[UUID] = None
    inventory_snapshot_sha256: str
    is_stale_inventory: bool = False
    simulation_only: bool = True
    created_at: datetime
    updated_at: datetime


class RecoverySubmitRequest(BaseModel):
    mode: RecoveryModeEnum
    title: Optional[str] = Field(default=None, min_length=3, max_length=255)
    planner_notes: Optional[str] = Field(default=None, max_length=2000)
    submit_for_review: bool = True
