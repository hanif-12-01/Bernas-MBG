from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class IncidentCategoryEnum(str, Enum):
    SPOILAGE = "SPOILAGE"
    SUSPECTED_CONTAMINATION = "SUSPECTED_CONTAMINATION"
    DAMAGED_PACKAGING = "DAMAGED_PACKAGING"
    ABNORMAL_ODOR_APPEARANCE = "ABNORMAL_ODOR_APPEARANCE"
    SUPPLIER_RECALL = "SUPPLIER_RECALL"
    TEMPERATURE_EXCURSION = "TEMPERATURE_EXCURSION"
    UNKNOWN_CONDITION = "UNKNOWN_CONDITION"


class IncidentSeverityEnum(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class IncidentStatusEnum(str, Enum):
    REPORTED = "REPORTED"
    ON_HOLD = "ON_HOLD"
    UNDER_REVIEW = "UNDER_REVIEW"
    REJECTED = "REJECTED"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class IncidentAffectedLotInput(BaseModel):
    lot_id: Optional[UUID] = None
    lot_code: Optional[str] = Field(default=None, max_length=128)
    ingredient_code: Optional[str] = Field(default=None, max_length=64)
    reason_detail: Optional[str] = Field(default=None, max_length=500)


class IncidentCreateRequest(BaseModel):
    title: str = Field(min_length=3, max_length=255)
    category: IncidentCategoryEnum
    severity: IncidentSeverityEnum = IncidentSeverityEnum.HIGH
    notes: str = Field(min_length=5, max_length=2000)
    dataset_version_id: Optional[UUID] = None
    observed_at: Optional[datetime] = None
    supplier_name: Optional[str] = Field(default=None, max_length=255)
    delivery_ref: Optional[str] = Field(default=None, max_length=128)
    related_batch_code: Optional[str] = Field(default=None, max_length=64)
    ingredient_codes: List[str] = Field(default_factory=list)
    affected_lots: List[IncidentAffectedLotInput] = Field(default_factory=list)
    auto_hold_matching_lots: bool = True
    idempotency_key: Optional[str] = Field(default=None, max_length=128)


class IncidentStatusUpdateRequest(BaseModel):
    status: IncidentStatusEnum
    notes: str = Field(min_length=3, max_length=2000)
    dispose_held_lots: bool = False
    disposal_notes: Optional[str] = Field(default=None, max_length=500)


class IncidentReleaseHoldRequest(BaseModel):
    authority_reference: Optional[str] = Field(default=None, max_length=255)
    notes: Optional[str] = Field(default=None, max_length=1000)


class IncidentStartRecoveryRequest(BaseModel):
    baseline_menu_review_id: Optional[UUID] = None
    baseline_run_id: Optional[UUID] = None
    production_date: Optional[datetime] = None
    new_servings_per_day: Optional[int] = Field(default=None, ge=1, le=500000)
    new_budget_idr_per_serving: Optional[float] = Field(default=None, gt=0.0)
    title: Optional[str] = Field(default=None, max_length=255)
    time_limit_seconds: float = Field(default=10.0, gt=0.1, le=60.0)


class IncidentAffectedLotResponse(BaseModel):
    id: UUID
    incident_id: UUID
    lot_id: UUID
    lot_code: str
    ingredient_id: UUID
    ingredient_code: str
    ingredient_name: str
    lot_safety_status: str
    prior_lot_verification_status: str
    recorded_raw_g_snapshot: float
    usable_before_hold_raw_g: float
    usable_after_hold_raw_g: float
    clean_remaining_raw_g: float = 0.0
    reason_detail: Optional[str] = None
    updated_at: datetime


class ProductionExposureItem(BaseModel):
    exposure_status: str  # NO_RECORDED_PRODUCTION_EXPOSURE | POTENTIAL_PRODUCTION_EXPOSURE | EXPOSURE_UNKNOWN
    summary: str
    lot_id: Optional[UUID] = None
    lot_code: Optional[str] = None
    ingredient_code: Optional[str] = None
    ingredient_name: Optional[str] = None
    quantity_kg: Optional[float] = None
    meal_batch_code: Optional[str] = None
    run_id: Optional[UUID] = None
    day_index: Optional[int] = None
    recorded_at: Optional[datetime] = None


class AffectedPlanSlotReference(BaseModel):
    menu_review_id: Optional[UUID] = None
    run_id: UUID
    plan_title: str
    operational_status: Optional[str] = None
    day_index: int
    slot: str
    recipe_id: UUID
    recipe_name: str
    affected_ingredients: List[str] = Field(default_factory=list)


class IncidentActionResponse(BaseModel):
    id: UUID
    incident_id: UUID
    action_type: str
    actor_user_id: Optional[UUID] = None
    actor_name: Optional[str] = None
    actor_role: Optional[str] = None
    notes: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class IncidentImageInfo(BaseModel):
    id: UUID
    incident_id: UUID
    original_filename_sanitized: str
    mime_type: str
    size_bytes: int
    width_px: int
    height_px: int
    sha256: str
    exif_stripped: bool
    uploaded_by_user_id: UUID
    created_at: datetime
    expires_at: datetime
    image_url: str


class IncidentImpactSummaryResponse(BaseModel):
    incident_id: UUID
    affected_ingredient_codes: List[str] = Field(default_factory=list)
    affected_ingredient_names: List[str] = Field(default_factory=list)
    held_lots_count: int = 0
    total_held_kg: float = 0.0
    total_clean_remaining_kg: float = 0.0
    affected_plan_ids: List[UUID] = Field(default_factory=list)
    affected_slots: List[AffectedPlanSlotReference] = Field(default_factory=list)
    exposure_status: str
    production_exposures: List[ProductionExposureItem] = Field(default_factory=list)
    summary_message: str
    safety_notice: str = (
        "Peringatan Keamanan Pangan Operasional: Penahanan lot (SAFETY HOLD) mengecualikan bahan dari stok siap pakai "
        "dan memblokir penggunaan terencana hingga ada tindak lanjut otoritas berwenang (BPOM/Dinkes/ahli gizi tersertifikasi). "
        "Sistem ini BUKAN uji mikrobiologi, BUKAN validasi gizi klinis, dan BUKAN kepatuhan resmi BGN."
    )


class IngredientIncidentResponse(BaseModel):
    id: UUID
    kitchen_id: UUID
    dataset_version_id: UUID
    title: str
    category: IncidentCategoryEnum
    severity: IncidentSeverityEnum
    status: IncidentStatusEnum
    notes: Optional[str] = None
    supplier_name: Optional[str] = None
    delivery_ref: Optional[str] = None
    related_batch_code: Optional[str] = None
    observed_at: datetime
    reported_by_user_id: UUID
    reported_by_name: str
    reporter_role: str
    created_at: datetime
    updated_at: datetime
    affected_lots: List[IncidentAffectedLotResponse] = Field(default_factory=list)
    affected_ingredient_codes: List[str] = Field(default_factory=list)
    affected_ingredient_names: List[str] = Field(default_factory=list)
    total_held_kg: float = 0.0
    total_clean_remaining_kg: float = 0.0
    affected_plans: List[AffectedPlanSlotReference] = Field(default_factory=list)
    exposure_status: str
    production_exposures: List[ProductionExposureItem] = Field(default_factory=list)
    recovery_event_id: Optional[UUID] = None
    images: List[IncidentImageInfo] = Field(default_factory=list)
    actions: List[IncidentActionResponse] = Field(default_factory=list)
    safety_notice: str = (
        "STATUS TAHAN KEAMANAN (SAFETY HOLD): Lot yang ditahan tidak dapat dilepaskan secara sepihak di dalam aplikasi "
        "kecuali oleh otoritas/laboratorium berwenang di luar lingkup keputusan sistem ini. "
        "Bukan pengganti uji laboratorium atau kepatuhan resmi BGN."
    )
    simulation_only: bool = True
