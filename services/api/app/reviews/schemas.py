from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class MenuReviewStatusEnum(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REVISION_REQUIRED = "REVISION_REQUIRED"


class MenuReviewCreateRequest(BaseModel):
    run_id: UUID
    title: Optional[str] = Field(default=None, max_length=255)
    planner_notes: Optional[str] = Field(default=None, max_length=2000)


class MenuReviewSubmitRequest(BaseModel):
    planner_notes: Optional[str] = Field(default=None, max_length=2000)


class MenuReviewDecisionEnum(str, Enum):
    APPROVED = "APPROVED"
    REVISION_REQUIRED = "REVISION_REQUIRED"


class MenuReviewDecisionRequest(BaseModel):
    decision: MenuReviewDecisionEnum
    reviewer_notes: Optional[str] = Field(default=None, max_length=2000)


class MenuReviewResponse(BaseModel):
    id: UUID
    kitchen_id: UUID
    scenario_id: UUID
    scenario_name: str
    run_id: UUID
    dataset_version_id: UUID
    version_number: int
    status: MenuReviewStatusEnum
    title: str
    planner_notes: Optional[str] = None
    reviewer_notes: Optional[str] = None
    created_by_user_id: UUID
    created_by_name: str
    submitted_by_user_id: Optional[UUID] = None
    submitted_by_name: Optional[str] = None
    reviewed_by_user_id: Optional[UUID] = None
    reviewed_by_name: Optional[str] = None
    submitted_at: Optional[datetime] = None
    reviewed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    cost_per_serving_average_idr: Optional[float] = None
    objective_total_idr: Optional[float] = None
    days_count: int
    servings_per_day: Optional[int] = None
    total_servings: Optional[int] = None
    cost_per_day_average_idr: Optional[float] = None
    simulation_only: bool = True
    recovery_event_id: Optional[UUID] = None
    inventory_snapshot_sha256: Optional[str] = None
    is_stale_inventory: bool = False
    recovery_selected_mode: Optional[str] = None
    recovery_changed_slots_count: Optional[int] = None
    operational_status: Optional[str] = None
    operational_assignment_id: Optional[UUID] = None
    production_scope_label: Optional[str] = None
    hold_incident_id: Optional[UUID] = None
    hold_reason: Optional[str] = None
    approval_scope_notice: str = (
        "Peninjauan ini bersifat persetujuan operasional internal dapur, "
        "bukan validasi gizi profesional oleh ahli gizi atau kepatuhan resmi BGN."
    )
