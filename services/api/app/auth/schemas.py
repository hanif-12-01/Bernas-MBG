from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class RoleEnum(str, Enum):
    KITCHEN_MANAGER = "KITCHEN_MANAGER"
    MENU_PLANNER = "MENU_PLANNER"
    QC_OFFICER = "QC_OFFICER"
    NUTRITIONIST = "NUTRITIONIST"


class LoginRequest(BaseModel):
    username: str = Field(min_length=2, max_length=128)
    password: str = Field(min_length=1, max_length=256)
    kitchen_id: Optional[UUID] = None


class KitchenMembershipInfo(BaseModel):
    kitchen_id: UUID
    kitchen_code: str
    kitchen_name: str
    kitchen_region: str
    role: RoleEnum
    is_default: bool


class AuthUserResponse(BaseModel):
    user_id: UUID
    username: str
    email: str
    full_name: str
    active_kitchen_id: UUID
    active_kitchen_code: str
    active_kitchen_name: str
    active_role: RoleEnum
    csrf_token: str
    memberships: List[KitchenMembershipInfo]


class SwitchKitchenRequest(BaseModel):
    kitchen_id: UUID


class AuditEventResponse(BaseModel):
    id: UUID
    kitchen_id: Optional[UUID] = None
    actor_user_id: Optional[UUID] = None
    actor_username: Optional[str] = None
    actor_full_name: Optional[str] = None
    actor_role: Optional[str] = None
    action: str
    entity_type: str
    entity_id: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
