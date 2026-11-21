from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Tuple
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.schemas import RoleEnum
from app.db.models import (
    KitchenMembershipORM,
    KitchenStockCustodianAssignmentORM,
    UserORM,
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def resolve_active_custodian(
    session: Session,
    kitchen_id: str | UUID,
    *,
    now: Optional[datetime] = None,
) -> Optional[Tuple[KitchenStockCustodianAssignmentORM, UserORM]]:
    """Read active stock custodian assignment and verify active QC_OFFICER membership without side effects."""
    curr = now or utcnow()
    row = session.execute(
        select(KitchenStockCustodianAssignmentORM).where(
            KitchenStockCustodianAssignmentORM.active_kitchen_key == str(kitchen_id),
            KitchenStockCustodianAssignmentORM.status == "ACTIVE",
        )
    ).scalar_one_or_none()
    if row is None:
        return None

    until = ensure_utc(row.effective_until)
    if until is not None and until <= curr:
        return None
    eff_from = ensure_utc(row.effective_from)
    if eff_from is not None and eff_from > curr:
        return None

    pair = session.execute(
        select(KitchenMembershipORM, UserORM)
        .join(UserORM, UserORM.id == KitchenMembershipORM.user_id)
        .where(
            KitchenMembershipORM.kitchen_id == str(kitchen_id),
            KitchenMembershipORM.user_id == row.custodian_user_id,
            KitchenMembershipORM.role == RoleEnum.QC_OFFICER.value,
            UserORM.is_active.is_(True),
        )
    ).first()
    if pair is None:
        return None
    return row, pair[1]
