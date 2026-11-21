from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class OperationalPlanStatusEnum(str, Enum):
    ACTIVE = "ACTIVE"
    ON_HOLD = "ON_HOLD"
    SUPERSEDED = "SUPERSEDED"


class OperationalPlanStateEnum(str, Enum):
    NO_PLAN = "NO_PLAN"
    DRAFT = "DRAFT"
    APPROVED_NOT_ACTIVE = "APPROVED_NOT_ACTIVE"
    ACTIVE = "ACTIVE"
    ACTIVE_ON_HOLD = "ACTIVE_ON_HOLD"
    SUPERSEDED = "SUPERSEDED"
    HISTORICAL = "HISTORICAL"


class ProductionScopeInfo(BaseModel):
    kitchen_id: UUID
    production_date: date
    horizon_days: int
    service_dates: List[date] = Field(default_factory=list)
    meal_type: str
    target_cohort: str
    batch_label: str
    scope_key: str
    scope_label: str


class OperationalPlanAssignmentResponse(BaseModel):
    id: UUID
    kitchen_id: UUID
    dataset_version_id: UUID
    menu_review_id: UUID
    run_id: UUID
    scenario_id: UUID
    plan_title: str
    scenario_name: str
    review_version_number: int
    historical_review_status: str
    operational_status: OperationalPlanStatusEnum
    production_date: date
    horizon_days: int
    service_dates: List[date] = Field(default_factory=list)
    period_start_date: Optional[date] = None
    period_end_date: Optional[date] = None
    derived_period_phase: Optional[str] = None  # IN_PROGRESS | UPCOMING | COMPLETED (derived from dates)
    meal_type: str
    target_cohort: str
    batch_label: str
    scope_key: str
    scope_label: str
    supersedes_assignment_id: Optional[UUID] = None
    hold_incident_id: Optional[UUID] = None
    hold_reason: Optional[str] = None
    held_at: Optional[datetime] = None
    activated_by_user_id: Optional[UUID] = None
    activated_by_name: Optional[str] = None
    activated_at: datetime
    superseded_at: Optional[datetime] = None
    inventory_snapshot_sha256: Optional[str] = None
    is_stale_inventory: bool = False
    is_ready_for_execution: bool = True
    servings_per_day: int
    total_servings: int
    total_menu_slots: int
    total_cost_idr: Optional[float] = None
    cost_per_serving_idr: Optional[float] = None
    cost_per_day_average_idr: Optional[float] = None
    simulation_only: bool = True


class EffectiveOperationalPlanResponse(BaseModel):
    kitchen_id: UUID
    state: OperationalPlanStateEnum
    is_ready_for_execution: bool
    status_message: str
    queried_service_date: Optional[date] = None
    matched_day_index: Optional[int] = None
    active_plan: Optional[OperationalPlanAssignmentResponse] = None
    held_plan: Optional[OperationalPlanAssignmentResponse] = None
    approved_pending_activation: List[UUID] = Field(default_factory=list)
    superseded_plans_count: int = 0
    draft_plans_count: int = 0
    historical_approved_count: int = 0


class ActivateReplacementPlanRequest(BaseModel):
    menu_review_id: UUID
    batch_label: Optional[str] = Field(default=None, max_length=64)
    expected_active_assignment_id: Optional[UUID] = None
    notes: Optional[str] = Field(default=None, max_length=1000)
    idempotency_key: Optional[str] = Field(default=None, max_length=128)
