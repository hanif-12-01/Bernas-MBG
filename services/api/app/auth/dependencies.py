from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.auth.schemas import KitchenMembershipInfo, RoleEnum
from app.auth.security import constant_time_equals, hash_session_token
from app.db.models import AuditEventORM, AuthSessionORM, KitchenMembershipORM, UserORM
from app.db.session import db_manager

SESSION_COOKIE_NAME = "gizioptima_session"
CSRF_HEADER_NAME = "X-CSRF-Token"
MUTATING_HTTP_METHODS = {"POST", "PATCH", "PUT", "DELETE"}


@dataclass(frozen=True)
class AuthContext:
    session_id: UUID
    user_id: UUID
    username: str
    email: str
    full_name: str
    kitchen_id: UUID
    kitchen_code: str
    kitchen_name: str
    role: RoleEnum
    csrf_token: str
    memberships: List[KitchenMembershipInfo]


def get_db_session():
    yield from db_manager.get_session()


def _extract_session_token(request: Request) -> tuple[Optional[str], bool]:
    """Return (raw_token, from_cookie)."""
    cookie_token = request.cookies.get(SESSION_COOKIE_NAME)
    if cookie_token:
        return cookie_token, True
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[len("Bearer ") :].strip()
        if token:
            return token, False
    return None, False


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def get_current_auth(
    request: Request,
    session: Session = Depends(get_db_session),
) -> AuthContext:
    raw_token, from_cookie = _extract_session_token(request)
    if not raw_token:
        raise HTTPException(
            status_code=401,
            detail="Autentikasi diperlukan. Silakan masuk terlebih dahulu.",
        )

    token_hash = hash_session_token(raw_token)
    stmt = (
        select(AuthSessionORM)
        .options(
            selectinload(AuthSessionORM.user)
            .selectinload(UserORM.memberships)
            .selectinload(KitchenMembershipORM.kitchen)
        )
        .where(AuthSessionORM.token_hash == token_hash)
    )
    auth_session = session.execute(stmt).scalar_one_or_none()
    now = datetime.now(timezone.utc)

    if (
        auth_session is None
        or auth_session.revoked_at is not None
        or _ensure_utc(auth_session.expires_at) <= now
    ):
        raise HTTPException(
            status_code=401,
            detail="Sesi tidak valid atau telah berakhir. Silakan masuk kembali.",
        )

    user = auth_session.user
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=401,
            detail="Akun pengguna tidak aktif.",
        )

    # Enforce CSRF verification on mutating requests authenticated via browser cookie
    if from_cookie and request.method.upper() in MUTATING_HTTP_METHODS:
        csrf_header = request.headers.get(CSRF_HEADER_NAME, "")
        if not csrf_header or not constant_time_equals(csrf_header, auth_session.csrf_token):
            raise HTTPException(
                status_code=403,
                detail="Token CSRF tidak valid atau tidak ditemukan.",
            )

    memberships: List[KitchenMembershipInfo] = []
    active_membership: Optional[KitchenMembershipInfo] = None
    for m in user.memberships:
        if m.kitchen is None or not m.kitchen.active:
            continue
        info = KitchenMembershipInfo(
            kitchen_id=UUID(m.kitchen_id),
            kitchen_code=m.kitchen.code,
            kitchen_name=m.kitchen.name,
            kitchen_region=m.kitchen.region,
            role=RoleEnum(m.role),
            is_default=m.is_default,
        )
        memberships.append(info)
        if m.kitchen_id == auth_session.active_kitchen_id:
            active_membership = info

    if active_membership is None:
        raise HTTPException(
            status_code=403,
            detail="Pengguna tidak memiliki keanggotaan aktif pada dapur yang dipilih.",
        )

    return AuthContext(
        session_id=UUID(auth_session.id),
        user_id=UUID(user.id),
        username=user.username,
        email=user.email,
        full_name=user.full_name,
        kitchen_id=active_membership.kitchen_id,
        kitchen_code=active_membership.kitchen_code,
        kitchen_name=active_membership.kitchen_name,
        role=active_membership.role,
        csrf_token=auth_session.csrf_token,
        memberships=memberships,
    )


def require_roles(*allowed_roles: RoleEnum):
    allowed_set = set(allowed_roles)

    def _checker(auth: AuthContext = Depends(get_current_auth)) -> AuthContext:
        if auth.role not in allowed_set:
            raise HTTPException(
                status_code=403,
                detail=(
                    f"Akses ditolak. Peran '{auth.role.value}' tidak memiliki izin untuk aksi ini."
                ),
            )
        return auth

    return _checker


def record_audit_event(
    session: Session,
    *,
    action: str,
    entity_type: str,
    entity_id: str,
    kitchen_id: Optional[UUID] = None,
    actor_user_id: Optional[UUID] = None,
    actor_role: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> AuditEventORM:
    event = AuditEventORM(
        id=str(uuid4()),
        kitchen_id=str(kitchen_id) if kitchen_id else None,
        actor_user_id=str(actor_user_id) if actor_user_id else None,
        actor_role=actor_role,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id),
        metadata_json=metadata or {},
        created_at=datetime.now(timezone.utc),
    )
    session.add(event)
    return event
