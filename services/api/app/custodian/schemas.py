from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class CustodianStatusEnum(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class AssignCustodianRequest(BaseModel):
    custodian_user_id: UUID
    effective_until: Optional[datetime] = None
    notes: Optional[str] = Field(default=None, max_length=1000)


class RevokeCustodianRequest(BaseModel):
    notes: Optional[str] = Field(default=None, max_length=1000)


class EligibleCustodianCandidate(BaseModel):
    user_id: UUID
    username: str
    full_name: str
    email: str
    is_active_custodian: bool = False


class CustodianAssignmentResponse(BaseModel):
    id: UUID
    kitchen_id: UUID
    custodian_user_id: UUID
    custodian_username: str
    custodian_full_name: str
    assigned_by_user_id: Optional[UUID] = None
    assigned_by_name: Optional[str] = None
    status: CustodianStatusEnum
    effective_from: datetime
    effective_until: Optional[datetime] = None
    revoked_at: Optional[datetime] = None
    revoked_by_user_id: Optional[UUID] = None
    notes: Optional[str] = None
    created_at: datetime


class KitchenStockCustodianStatusResponse(BaseModel):
    kitchen_id: UUID
    kitchen_code: str
    kitchen_name: str
    active_assignment: Optional[CustodianAssignmentResponse] = None
    eligible_qc_candidates: List[EligibleCustodianCandidate] = Field(default_factory=list)
    history: List[CustodianAssignmentResponse] = Field(default_factory=list)
