from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.dependencies import AuthContext, record_audit_event
from app.auth.schemas import RoleEnum
from app.custodian.lookup import ensure_utc, resolve_active_custodian, utcnow as _utcnow
from app.custodian.schemas import (
    AssignCustodianRequest,
    CustodianAssignmentResponse,
    CustodianStatusEnum,
    EligibleCustodianCandidate,
    KitchenStockCustodianStatusResponse,
    RevokeCustodianRequest,
)
from app.db.models import (
    KitchenMembershipORM,
    KitchenStockCustodianAssignmentORM,
    UserORM,
)


def expire_stale_assignments_for_kitchen(
    session: Session,
    kitchen_id: str | UUID,
    *,
    now: Optional[datetime] = None,
) -> Optional[KitchenStockCustodianAssignmentORM]:
    """Return currently effective ACTIVE assignment after expiring any timed-out row."""
    curr = now or _utcnow()
    active_rows = list(
        session.execute(
            select(KitchenStockCustodianAssignmentORM).where(
                KitchenStockCustodianAssignmentORM.kitchen_id == str(kitchen_id),
                KitchenStockCustodianAssignmentORM.status == CustodianStatusEnum.ACTIVE.value,
            )
        )
        .scalars()
        .all()
    )
    still_active: Optional[KitchenStockCustodianAssignmentORM] = None
    for row in active_rows:
        until = ensure_utc(row.effective_until)
        if until is not None and until <= curr:
            row.status = CustodianStatusEnum.EXPIRED.value
            row.active_kitchen_key = None
            row.updated_at = curr
            continue
        still_active = row
    return still_active


def get_active_stock_custodian_row(
    session: Session,
    kitchen_id: str | UUID,
    *,
    now: Optional[datetime] = None,
) -> Optional[KitchenStockCustodianAssignmentORM]:
    """Read the currently valid active stock custodian assignment for a kitchen."""
    resolved = resolve_active_custodian(session, kitchen_id, now=now)
    return resolved[0] if resolved is not None else None


def _build_assignment_response(
    row: KitchenStockCustodianAssignmentORM,
    users_by_id: Dict[str, UserORM],
) -> CustodianAssignmentResponse:
    cust_user = users_by_id.get(row.custodian_user_id)
    assigner = users_by_id.get(row.assigned_by_user_id) if row.assigned_by_user_id else None
    return CustodianAssignmentResponse(
        id=UUID(row.id),
        kitchen_id=UUID(row.kitchen_id),
        custodian_user_id=UUID(row.custodian_user_id),
        custodian_username=cust_user.username if cust_user else "unknown",
        custodian_full_name=cust_user.full_name if cust_user else "Pengguna tidak dikenal",
        assigned_by_user_id=UUID(row.assigned_by_user_id) if row.assigned_by_user_id else None,
        assigned_by_name=assigner.full_name if assigner else None,
        status=CustodianStatusEnum(row.status),
        effective_from=row.effective_from,
        effective_until=row.effective_until,
        revoked_at=row.revoked_at,
        revoked_by_user_id=UUID(row.revoked_by_user_id) if row.revoked_by_user_id else None,
        notes=row.notes,
        created_at=row.created_at,
    )


def get_kitchen_custodian_status(
    session: Session,
    auth: AuthContext,
) -> KitchenStockCustodianStatusResponse:
    active_row = get_active_stock_custodian_row(session, auth.kitchen_id)
    rows = list(
        session.execute(
            select(KitchenStockCustodianAssignmentORM)
            .where(KitchenStockCustodianAssignmentORM.kitchen_id == str(auth.kitchen_id))
            .order_by(KitchenStockCustodianAssignmentORM.created_at.desc())
            .limit(20)
        )
        .scalars()
        .all()
    )

    candidate_users = list(
        session.execute(
            select(UserORM)
            .join(KitchenMembershipORM, KitchenMembershipORM.user_id == UserORM.id)
            .where(
                KitchenMembershipORM.kitchen_id == str(auth.kitchen_id),
                KitchenMembershipORM.role == RoleEnum.QC_OFFICER.value,
                UserORM.is_active.is_(True),
            )
            .order_by(UserORM.full_name.asc())
        )
        .scalars()
        .all()
    )

    user_ids = {r.custodian_user_id for r in rows}
    for r in rows:
        if r.assigned_by_user_id:
            user_ids.add(r.assigned_by_user_id)
    users_by_id: Dict[str, UserORM] = {u.id: u for u in candidate_users}
    missing_ids = user_ids - set(users_by_id.keys())
    if missing_ids:
        for u in session.execute(select(UserORM).where(UserORM.id.in_(missing_ids))).scalars().all():
            users_by_id[u.id] = u

    active_custodian_user_id = active_row.custodian_user_id if active_row else None
    is_manager = auth.role == RoleEnum.KITCHEN_MANAGER

    return KitchenStockCustodianStatusResponse(
        kitchen_id=auth.kitchen_id,
        kitchen_code=auth.kitchen_code,
        kitchen_name=auth.kitchen_name,
        active_assignment=_build_assignment_response(active_row, users_by_id) if active_row else None,
        eligible_qc_candidates=(
            [
                EligibleCustodianCandidate(
                    user_id=UUID(u.id),
                    username=u.username,
                    full_name=u.full_name,
                    email=u.email,
                    is_active_custodian=(u.id == active_custodian_user_id),
                )
                for u in candidate_users
            ]
            if is_manager
            else []
        ),
        history=(
            [_build_assignment_response(r, users_by_id) for r in rows] if is_manager else []
        ),
    )


def assign_stock_custodian(
    session: Session,
    auth: AuthContext,
    req: AssignCustodianRequest,
) -> KitchenStockCustodianStatusResponse:
    """Assign exactly one active QC Officer as stock custodian for the kitchen."""
    if auth.role != RoleEnum.KITCHEN_MANAGER:
        raise HTTPException(
            status_code=403,
            detail="Hanya Kepala Dapur (KITCHEN_MANAGER) yang dapat menunjuk Petugas QC Pengelola Stok.",
        )

    now = _utcnow()
    eff_until = ensure_utc(req.effective_until)
    if eff_until is not None and eff_until <= now:
        raise HTTPException(
            status_code=422,
            detail="Batas waktu penugasan (effective_until) harus berada di masa mendatang.",
        )

    target_user = session.get(UserORM, str(req.custodian_user_id))
    if target_user is None or not target_user.is_active:
        raise HTTPException(
            status_code=422,
            detail="Pengguna yang ditunjuk tidak ditemukan atau tidak aktif.",
        )

    target_membership = session.execute(
        select(KitchenMembershipORM).where(
            KitchenMembershipORM.kitchen_id == str(auth.kitchen_id),
            KitchenMembershipORM.user_id == target_user.id,
        )
    ).scalar_one_or_none()
    if target_membership is None:
        raise HTTPException(
            status_code=422,
            detail="Pengguna yang ditunjuk bukan anggota aktif pada dapur ini.",
        )
    if target_membership.role != RoleEnum.QC_OFFICER.value:
        raise HTTPException(
            status_code=422,
            detail=(
                "Hanya pengguna dengan peran QC_OFFICER (Petugas QC) pada dapur ini yang boleh ditunjuk sebagai Pengelola Stok."
            ),
        )

    prior_active = expire_stale_assignments_for_kitchen(session, auth.kitchen_id, now=now)
    remaining_active = list(
        session.execute(
            select(KitchenStockCustodianAssignmentORM).where(
                KitchenStockCustodianAssignmentORM.kitchen_id == str(auth.kitchen_id),
                KitchenStockCustodianAssignmentORM.status == CustodianStatusEnum.ACTIVE.value,
            )
        )
        .scalars()
        .all()
    )
    previous_custodian_id = (
        remaining_active[0].custodian_user_id
        if remaining_active
        else (prior_active.custodian_user_id if prior_active else None)
    )
    for row in remaining_active:
        row.status = CustodianStatusEnum.REVOKED.value
        row.active_kitchen_key = None
        row.revoked_at = now
        row.revoked_by_user_id = str(auth.user_id)
        row.updated_at = now
    session.flush()

    new_assignment = KitchenStockCustodianAssignmentORM(
        id=str(uuid4()),
        kitchen_id=str(auth.kitchen_id),
        custodian_user_id=target_user.id,
        assigned_by_user_id=str(auth.user_id),
        status=CustodianStatusEnum.ACTIVE.value,
        active_kitchen_key=str(auth.kitchen_id),
        effective_from=now,
        effective_until=eff_until,
        revoked_at=None,
        revoked_by_user_id=None,
        notes=req.notes.strip() if req.notes and req.notes.strip() else None,
        created_at=now,
        updated_at=now,
    )
    session.add(new_assignment)

    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="Konflik penugasan Pengelola Stok bersamaan. Silakan muat ulang dan coba kembali.",
        ) from exc

    record_audit_event(
        session,
        action="stock_custodian.assigned",
        entity_type="kitchen_stock_custodian",
        entity_id=new_assignment.id,
        kitchen_id=auth.kitchen_id,
        actor_user_id=auth.user_id,
        actor_role=auth.role.value,
        metadata={
            "custodian_user_id": target_user.id,
            "custodian_username": target_user.username,
            "previous_custodian_user_id": previous_custodian_id,
            "effective_until": eff_until.isoformat() if eff_until else None,
        },
    )
    session.commit()
    return get_kitchen_custodian_status(session, auth)


def revoke_stock_custodian(
    session: Session,
    auth: AuthContext,
    req: RevokeCustodianRequest,
) -> KitchenStockCustodianStatusResponse:
    if auth.role != RoleEnum.KITCHEN_MANAGER:
        raise HTTPException(
            status_code=403,
            detail="Hanya Kepala Dapur (KITCHEN_MANAGER) yang dapat mencabut penugasan Pengelola Stok.",
        )

    now = _utcnow()
    still_active = expire_stale_assignments_for_kitchen(session, auth.kitchen_id, now=now)
    active_rows = [still_active] if still_active is not None else []
    if not active_rows:
        session.commit()
        raise HTTPException(
            status_code=409,
            detail="Saat ini tidak ada Petugas QC Pengelola Stok aktif yang perlu dicabut.",
        )

    revoked_ids: List[str] = []
    for row in active_rows:
        row.status = CustodianStatusEnum.REVOKED.value
        row.active_kitchen_key = None
        row.revoked_at = now
        row.revoked_by_user_id = str(auth.user_id)
        if req.notes and req.notes.strip():
            row.notes = req.notes.strip()
        row.updated_at = now
        revoked_ids.append(row.id)

    record_audit_event(
        session,
        action="stock_custodian.revoked",
        entity_type="kitchen_stock_custodian",
        entity_id=revoked_ids[0],
        kitchen_id=auth.kitchen_id,
        actor_user_id=auth.user_id,
        actor_role=auth.role.value,
        metadata={
            "revoked_assignment_ids": revoked_ids,
            "notes": req.notes.strip() if req.notes and req.notes.strip() else None,
        },
    )
    session.commit()
    return get_kitchen_custodian_status(session, auth)
