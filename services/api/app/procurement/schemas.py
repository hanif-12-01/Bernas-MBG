from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class EvidenceStatusEnum(str, Enum):
    NO_EVIDENCE = "NO_EVIDENCE"
    RECEIPT_UPLOADED = "RECEIPT_UPLOADED"
    GOODS_RECEIVED = "GOODS_RECEIVED"
    VERIFIED_MATCH = "VERIFIED_MATCH"
    DISCREPANCY_FLAGGED = "DISCREPANCY_FLAGGED"


class PurchaseEvidenceReviewDecisionEnum(str, Enum):
    VERIFIED_MATCH = "VERIFIED_MATCH"
    DISCREPANCY_FLAGGED = "DISCREPANCY_FLAGGED"


class GoodsConditionEnum(str, Enum):
    GOOD = "GOOD"
    DAMAGED = "DAMAGED"
    QUARANTINED = "QUARANTINED"
    REJECTED = "REJECTED"


class PurchaseDocumentLineInput(BaseModel):
    ingredient_code: Optional[str] = Field(default=None, max_length=64)
    item_name: str = Field(min_length=1, max_length=255)
    quantity: float = Field(gt=0.0)
    unit: str = Field(default="kg", min_length=1, max_length=32)
    unit_price_idr: Optional[float] = Field(default=None, ge=0.0)
    line_total_idr: Optional[float] = Field(default=None, ge=0.0)
    lot_code_hint: Optional[str] = Field(default=None, max_length=128)
    expiry_date_hint: Optional[date] = None


class PurchaseDocumentCreateRequest(BaseModel):
    dataset_version_id: Optional[UUID] = None
    linked_run_id: Optional[UUID] = None
    linked_recovery_event_id: Optional[UUID] = None
    supplier_name: str = Field(min_length=2, max_length=255)
    supplier_contact: Optional[str] = Field(default=None, max_length=255)
    invoice_number: Optional[str] = Field(default=None, max_length=128)
    purchase_date: Optional[date] = None
    total_amount_idr: Optional[float] = Field(default=None, ge=0.0)
    notes: Optional[str] = Field(default=None, max_length=2000)
    lines: List[PurchaseDocumentLineInput] = Field(default_factory=list)


class PurchaseDocumentReviewRequest(BaseModel):
    decision: PurchaseEvidenceReviewDecisionEnum
    notes: Optional[str] = Field(default=None, max_length=1000)


class PurchaseDocumentLineResponse(BaseModel):
    id: UUID
    ingredient_id: Optional[UUID] = None
    ingredient_code: Optional[str] = None
    item_name: str
    quantity_raw_g: float
    unit_label: str
    unit_price_idr: Optional[float] = None
    line_total_idr: Optional[float] = None
    lot_code_hint: Optional[str] = None
    expiry_date_hint: Optional[date] = None


class PurchaseDocumentResponse(BaseModel):
    id: UUID
    kitchen_id: UUID
    dataset_version_id: UUID
    linked_run_id: Optional[UUID] = None
    linked_recovery_event_id: Optional[UUID] = None
    supplier_name: str
    supplier_contact: Optional[str] = None
    invoice_number: Optional[str] = None
    purchase_date: date
    total_amount_idr: Optional[float] = None
    evidence_status: EvidenceStatusEnum
    has_evidence_file: bool = False
    document_mime_type: Optional[str] = None
    document_sha256: Optional[str] = None
    document_size_bytes: Optional[int] = None
    document_original_filename: Optional[str] = None
    exif_stripped: Optional[bool] = None
    evidence_url: Optional[str] = None
    recorded_by_user_id: Optional[UUID] = None
    recorded_by_name: Optional[str] = None
    reviewed_by_user_id: Optional[UUID] = None
    reviewed_by_name: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    notes: Optional[str] = None
    lines: List[PurchaseDocumentLineResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class GoodsReceiptCreateRequest(BaseModel):
    dataset_version_id: Optional[UUID] = None
    purchase_document_id: Optional[UUID] = None
    ingredient_code: str = Field(min_length=1, max_length=64)
    lot_code: Optional[str] = Field(default=None, max_length=128)
    received_quantity: float = Field(gt=0.0)
    unit: str = Field(default="kg", min_length=1, max_length=32)
    expiry_date: Optional[date] = None
    supplier_name: Optional[str] = Field(default=None, max_length=255)
    condition_status: GoodsConditionEnum = GoodsConditionEnum.GOOD
    notes: Optional[str] = Field(default=None, max_length=1000)
    idempotency_key: Optional[str] = Field(default=None, max_length=128)


class GoodsReceiptResponse(BaseModel):
    id: UUID
    kitchen_id: UUID
    purchase_document_id: Optional[UUID] = None
    dataset_version_id: UUID
    ingredient_id: Optional[UUID] = None
    ingredient_code: str
    ingredient_name: str
    lot_id: Optional[UUID] = None
    lot_code: str
    received_raw_g: float
    expiry_date: Optional[date] = None
    supplier_name: Optional[str] = None
    condition_status: GoodsConditionEnum
    lot_verification_status: str
    lot_safety_hold_status: str
    usable_added_raw_g: float
    received_by_user_id: Optional[UUID] = None
    received_by_name: Optional[str] = None
    received_at: datetime
    notes: Optional[str] = None
    created_at: datetime
