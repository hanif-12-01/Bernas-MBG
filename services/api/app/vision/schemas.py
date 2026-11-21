from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class FoodCategoryEnum(str, Enum):
    STAPLE = "staple"
    PROTEIN = "protein"
    VEGETABLE = "vegetable"
    FRUIT = "fruit"
    OTHER = "other"


class ObservationStatusEnum(str, Enum):
    VISIBLE = "visible"
    UNCERTAIN = "uncertain"
    NOT_VISIBLE = "not_visible"
    NEEDS_REVIEW = "needs_review"


class ComparisonStatusEnum(str, Enum):
    VISUAL_MATCH = "visual_match"
    MISSING_EXPECTED = "missing_expected"
    UNCERTAIN = "uncertain"
    NEEDS_MANUAL_CHECK = "needs_manual_check"


class QCInspectionStatusEnum(str, Enum):
    CREATED = "CREATED"
    AI_ANALYZED = "AI_ANALYZED"
    HUMAN_REVIEWED = "HUMAN_REVIEWED"
    SUBMITTED = "SUBMITTED"
    REVIEWED = "REVIEWED"


class QCReviewOutcomeEnum(str, Enum):
    ACCEPTED_FOR_RECORD = "ACCEPTED_FOR_RECORD"
    REVISION_REQUIRED = "REVISION_REQUIRED"
    RETAKE_REQUIRED = "RETAKE_REQUIRED"


class ObservedComponent(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    category: FoodCategoryEnum
    possible_food_name: str = Field(min_length=1, max_length=160)
    observation_status: ObservationStatusEnum
    explanation: str = Field(min_length=1, max_length=500)


class VisionAnalysisOutput(BaseModel):
    """Strict structured output validated from any Vision provider (untrusted model output)."""

    model_config = ConfigDict(extra="forbid")

    observed_components: List[ObservedComponent] = Field(default_factory=list)
    uncertain_components: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(
        default_factory=lambda: [
            "Berat aktual, kandungan gizi, suhu, dan keamanan mikrobiologis makanan tidak dapat dipastikan dari foto."
        ]
    )


class ExpectedMenuSlot(BaseModel):
    slot: str
    recipe_id: str
    recipe_name: str
    ingredient_names: List[str] = Field(default_factory=list)


class ExpectedVsObservedFinding(BaseModel):
    slot: str
    expected_recipe_name: str
    status: ComparisonStatusEnum
    finding_label: str
    matched_observation: Optional[str] = None
    explanation: str


class QCInspectionCreateRequest(BaseModel):
    run_id: UUID
    menu_review_id: Optional[UUID] = None
    previous_inspection_id: Optional[UUID] = None
    day_index: int = Field(ge=1, le=14)
    service_date: Optional[date] = None
    meal_batch_code: Optional[str] = Field(default=None, max_length=64)
    qc_notes: Optional[str] = Field(default=None, max_length=2000)


class HumanCorrectedComponent(BaseModel):
    slot: str = Field(min_length=1, max_length=32)
    confirmed_status: ObservationStatusEnum
    observed_food_name: str = Field(min_length=1, max_length=160)
    officer_note: Optional[str] = Field(default=None, max_length=500)


class QCObservationsPatchRequest(BaseModel):
    corrected_components: List[HumanCorrectedComponent] = Field(min_length=1)
    ai_observation_id: Optional[UUID] = None
    notes: Optional[str] = Field(default=None, max_length=2000)
    request_retake: bool = False


class QCSubmitRequest(BaseModel):
    qc_notes: Optional[str] = Field(default=None, max_length=2000)


class QCManagerReviewRequest(BaseModel):
    outcome: QCReviewOutcomeEnum
    manager_notes: Optional[str] = Field(default=None, max_length=2000)


class QCImageInfo(BaseModel):
    id: UUID
    original_filename_sanitized: str
    mime_type: str
    size_bytes: int
    width_px: int
    height_px: int
    sha256: str
    exif_stripped: bool
    retention_days: int
    uploaded_by_user_id: UUID
    created_at: datetime
    expires_at: datetime
    image_url: str


class QCAIObservationInfo(BaseModel):
    id: UUID
    image_id: UUID
    provider_name: str
    provider_mode: str
    is_live_ai: bool
    model_identifier: str
    prompt_version: str
    validated_output: VisionAnalysisOutput
    comparison_findings: List[ExpectedVsObservedFinding]
    latency_ms: int
    created_at: datetime


class QCHumanReviewInfo(BaseModel):
    id: UUID
    ai_observation_id: Optional[UUID] = None
    reviewer_user_id: UUID
    reviewer_name: str
    corrected_components: List[HumanCorrectedComponent]
    notes: Optional[str] = None
    request_retake: bool
    created_at: datetime


class QCInspectionResponse(BaseModel):
    id: UUID
    kitchen_id: UUID
    menu_review_id: Optional[UUID] = None
    run_id: UUID
    scenario_name: str
    day_index: int
    service_date: Optional[date] = None
    status: QCInspectionStatusEnum
    review_outcome: Optional[QCReviewOutcomeEnum] = None
    plan_operational_status: Optional[str] = None
    plan_hold_reason: Optional[str] = None
    created_by_user_id: UUID
    created_by_name: str
    submitted_by_user_id: Optional[UUID] = None
    submitted_by_name: Optional[str] = None
    reviewed_by_user_id: Optional[UUID] = None
    reviewed_by_name: Optional[str] = None
    qc_notes: Optional[str] = None
    manager_notes: Optional[str] = None
    submitted_at: Optional[datetime] = None
    reviewed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    expected_menu: List[ExpectedMenuSlot]
    images: List[QCImageInfo]
    ai_observations: List[QCAIObservationInfo]
    human_reviews: List[QCHumanReviewInfo]
    food_safety_disclaimer: str = (
        "Pemeriksaan visual berbantuan AI ini hanya untuk pencocokan komponen menu secara visual "
        "dan dokumentasi operasional. Bukan sertifikasi keamanan pangan (SLHS/HACCP/halal), "
        "bukan pengukuran berat/suhu, dan tidak menyatakan makanan aman dikonsumsi."
    )
