from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from threading import BoundedSemaphore
from typing import List
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.auth.dependencies import (
    AuthContext,
    SESSION_COOKIE_NAME,
    get_current_auth,
    get_db_session,
    record_audit_event,
    require_roles,
)
from app.auth.schemas import (
    AuditEventResponse,
    AuthUserResponse,
    KitchenMembershipInfo,
    LoginRequest,
    RoleEnum,
    StockCustodianSummary,
    SwitchKitchenRequest,
)
from app.auth.rate_limit import RateLimiter
from app.auth.security import (
    generate_csrf_token,
    generate_session_token,
    hash_password,
    hash_session_token,
    verify_password,
)
from app.custodian.lookup import resolve_active_custodian
from app.db.models import AuditEventORM, AuthSessionORM, UserORM

router = APIRouter(prefix="/auth", tags=["auth"])

SESSION_TTL_HOURS = 12
LOGIN_LIMIT_DETAIL = "Terlalu banyak percobaan masuk. Tunggu sebentar sebelum mencoba lagi."
INVALID_LOGIN_DETAIL = "Nama pengguna atau kata sandi tidak valid."
_login_peer_limit = RateLimiter(120, 60)
_login_account_limit = RateLimiter(12, 60)
_password_check_slots = BoundedSemaphore(4)
_dummy_login_hash = hash_password(generate_session_token())


def _cookie_secure_flag() -> bool:
    return (
        os.getenv("GIZIOPTIMA_ENV", "").strip().lower() == "production"
        or os.getenv("GIZIOPTIMA_COOKIE_SECURE", "").strip().lower() in {"1", "true", "yes"}
    )


def _resolve_custodian_flags(
    session: Session,
    *,
    kitchen_id: UUID,
    user_id: UUID,
    role: RoleEnum,
) -> tuple[bool, StockCustodianSummary]:
    resolved = resolve_active_custodian(session, kitchen_id)
    summary = StockCustodianSummary(
        is_assigned=resolved is not None,
        custodian_user_id=UUID(resolved[1].id) if resolved else None,
        custodian_username=resolved[1].username if resolved else None,
        custodian_full_name=resolved[1].full_name if resolved else None,
        effective_until=resolved[0].effective_until if resolved else None,
    )
    is_custodian = bool(
        role == RoleEnum.QC_OFFICER
        and resolved is not None
        and resolved[0].custodian_user_id == str(user_id)
    )
    return is_custodian, summary


def _build_auth_response(auth: AuthContext) -> AuthUserResponse:
    return AuthUserResponse(
        user_id=auth.user_id,
        username=auth.username,
        email=auth.email,
        full_name=auth.full_name,
        active_kitchen_id=auth.kitchen_id,
        active_kitchen_code=auth.kitchen_code,
        active_kitchen_name=auth.kitchen_name,
        active_role=auth.role,
        csrf_token=auth.csrf_token,
        is_active_stock_custodian=auth.is_active_stock_custodian,
        stock_custodian=auth.stock_custodian,
        memberships=auth.memberships,
    )


@router.post("/login", response_model=AuthUserResponse)
def api_login(
    req: LoginRequest,
    request: Request,
    response: Response,
    session: Session = Depends(get_db_session),
) -> AuthUserResponse:
    identifier = req.username.strip().lower()
    peer = request.client.host if request.client else "unknown"
    attempt_key = (peer, identifier)
    _login_peer_limit.check(peer, detail=LOGIN_LIMIT_DETAIL)
    _login_account_limit.check(attempt_key, detail=LOGIN_LIMIT_DETAIL)
    stmt = select(UserORM).where((UserORM.username == identifier) | (UserORM.email == identifier))
    user = session.execute(stmt).scalar_one_or_none()
    digest = user.password_hash if user is not None and user.is_active else _dummy_login_hash
    if not _password_check_slots.acquire(blocking=False):
        raise HTTPException(status_code=429, detail=LOGIN_LIMIT_DETAIL, headers={"Retry-After": "1"})
    try:
        valid_password = verify_password(digest, req.password)
    finally:
        _password_check_slots.release()
    if user is None or not user.is_active or not valid_password:
        raise HTTPException(status_code=401, detail=INVALID_LOGIN_DETAIL)

    # Serialize session issuance with admin updates and recheck the verified credentials.
    current_credentials = session.execute(
        update(UserORM)
        .where(UserORM.id == user.id, UserORM.password_hash == digest, UserORM.is_active.is_(True))
        .values(password_hash=digest)
    )
    if current_credentials.rowcount != 1:
        raise HTTPException(status_code=401, detail=INVALID_LOGIN_DETAIL)

    active_memberships: List[KitchenMembershipInfo] = []
    for m in user.memberships:
        if m.kitchen is None or not m.kitchen.active:
            continue
        active_memberships.append(
            KitchenMembershipInfo(
                kitchen_id=UUID(m.kitchen_id),
                kitchen_code=m.kitchen.code,
                kitchen_name=m.kitchen.name,
                kitchen_region=m.kitchen.region,
                role=RoleEnum(m.role),
                is_default=m.is_default,
            )
        )

    if not active_memberships:
        raise HTTPException(
            status_code=403,
            detail="Akun belum terdaftar pada dapur aktif mana pun.",
        )

    chosen: KitchenMembershipInfo | None = None
    if req.kitchen_id is not None:
        chosen = next((m for m in active_memberships if m.kitchen_id == req.kitchen_id), None)
        if chosen is None:
            raise HTTPException(
                status_code=403,
                detail="Pengguna tidak memiliki keanggotaan pada dapur yang dipilih.",
            )
    else:
        chosen = next((m for m in active_memberships if m.is_default), active_memberships[0])

    raw_token = generate_session_token()
    csrf_token = generate_csrf_token()
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(hours=SESSION_TTL_HOURS)

    sess_orm = AuthSessionORM(
        id=str(uuid4()),
        user_id=user.id,
        active_kitchen_id=str(chosen.kitchen_id),
        token_hash=hash_session_token(raw_token),
        csrf_token=csrf_token,
        expires_at=expires_at,
        revoked_at=None,
        created_at=now,
    )
    session.add(sess_orm)
    record_audit_event(
        session,
        action="auth.login",
        entity_type="auth_session",
        entity_id=sess_orm.id,
        kitchen_id=chosen.kitchen_id,
        actor_user_id=UUID(user.id),
        actor_role=chosen.role.value,
        metadata={"username": user.username},
    )
    session.commit()
    _login_account_limit.reset(attempt_key)

    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=raw_token,
        httponly=True,
        secure=_cookie_secure_flag(),
        samesite="lax",
        max_age=SESSION_TTL_HOURS * 3600,
        path="/",
    )

    is_custodian, custodian_summary = _resolve_custodian_flags(
        session,
        kitchen_id=chosen.kitchen_id,
        user_id=UUID(user.id),
        role=chosen.role,
    )

    return AuthUserResponse(
        user_id=UUID(user.id),
        username=user.username,
        email=user.email,
        full_name=user.full_name,
        active_kitchen_id=chosen.kitchen_id,
        active_kitchen_code=chosen.kitchen_code,
        active_kitchen_name=chosen.kitchen_name,
        active_role=chosen.role,
        csrf_token=csrf_token,
        is_active_stock_custodian=is_custodian,
        stock_custodian=custodian_summary,
        memberships=active_memberships,
    )


@router.post("/logout")
def api_logout(
    response: Response,
    auth: AuthContext = Depends(get_current_auth),
    session: Session = Depends(get_db_session),
) -> dict:
    sess_orm = session.get(AuthSessionORM, str(auth.session_id))
    if sess_orm is not None:
        sess_orm.revoked_at = datetime.now(timezone.utc)
        record_audit_event(
            session,
            action="auth.logout",
            entity_type="auth_session",
            entity_id=sess_orm.id,
            kitchen_id=auth.kitchen_id,
            actor_user_id=auth.user_id,
            actor_role=auth.role.value,
        )
        session.commit()

    response.delete_cookie(
        key=SESSION_COOKIE_NAME, path="/", secure=_cookie_secure_flag(), httponly=True, samesite="lax"
    )
    return {"status": "logged_out"}


@router.get("/me", response_model=AuthUserResponse)
def api_me(auth: AuthContext = Depends(get_current_auth)) -> AuthUserResponse:
    return _build_auth_response(auth)


@router.post("/switch-kitchen", response_model=AuthUserResponse)
def api_switch_kitchen(
    req: SwitchKitchenRequest,
    auth: AuthContext = Depends(get_current_auth),
    session: Session = Depends(get_db_session),
) -> AuthUserResponse:
    target = next((m for m in auth.memberships if m.kitchen_id == req.kitchen_id), None)
    if target is None:
        raise HTTPException(
            status_code=403,
            detail="Anda tidak memiliki akses ke dapur yang dipilih.",
        )

    sess_orm = session.get(AuthSessionORM, str(auth.session_id))
    if sess_orm is None:
        raise HTTPException(status_code=401, detail="Sesi tidak ditemukan.")
    sess_orm.active_kitchen_id = str(target.kitchen_id)
    record_audit_event(
        session,
        action="auth.switch_kitchen",
        entity_type="kitchen",
        entity_id=str(target.kitchen_id),
        kitchen_id=target.kitchen_id,
        actor_user_id=auth.user_id,
        actor_role=target.role.value,
    )
    session.commit()

    is_custodian, custodian_summary = _resolve_custodian_flags(
        session,
        kitchen_id=target.kitchen_id,
        user_id=auth.user_id,
        role=target.role,
    )

    return AuthUserResponse(
        user_id=auth.user_id,
        username=auth.username,
        email=auth.email,
        full_name=auth.full_name,
        active_kitchen_id=target.kitchen_id,
        active_kitchen_code=target.kitchen_code,
        active_kitchen_name=target.kitchen_name,
        active_role=target.role,
        csrf_token=auth.csrf_token,
        is_active_stock_custodian=is_custodian,
        stock_custodian=custodian_summary,
        memberships=auth.memberships,
    )


@router.get("/audit-events", response_model=List[AuditEventResponse])
def api_list_audit_events(
    limit: int = 30,
    auth: AuthContext = Depends(
        require_roles(RoleEnum.KITCHEN_MANAGER, RoleEnum.MENU_PLANNER, RoleEnum.QC_OFFICER)
    ),
    session: Session = Depends(get_db_session),
) -> List[AuditEventResponse]:
    bounded = max(1, min(limit, 100))
    stmt = (
        select(AuditEventORM)
        .where(AuditEventORM.kitchen_id == str(auth.kitchen_id))
        .order_by(AuditEventORM.created_at.desc())
        .limit(bounded)
    )
    if auth.role == RoleEnum.QC_OFFICER:
        stmt = stmt.where(
            (AuditEventORM.actor_user_id == str(auth.user_id))
            | (AuditEventORM.entity_type == "qc_inspection")
        )
    elif auth.role == RoleEnum.MENU_PLANNER:
        stmt = stmt.where(
            AuditEventORM.entity_type.in_(["scenario", "optimization_run", "menu_review", "qc_inspection", "dataset"])
        )

    rows = list(session.execute(stmt).scalars().all())
    user_ids = {r.actor_user_id for r in rows if r.actor_user_id}
    users_by_id = {}
    if user_ids:
        for u in session.execute(select(UserORM).where(UserORM.id.in_(user_ids))).scalars().all():
            users_by_id[u.id] = u

    out: List[AuditEventResponse] = []
    for r in rows:
        u = users_by_id.get(r.actor_user_id) if r.actor_user_id else None
        out.append(
            AuditEventResponse(
                id=UUID(r.id),
                kitchen_id=UUID(r.kitchen_id) if r.kitchen_id else None,
                actor_user_id=UUID(r.actor_user_id) if r.actor_user_id else None,
                actor_username=u.username if u else None,
                actor_full_name=u.full_name if u else None,
                actor_role=r.actor_role,
                action=r.action,
                entity_type=r.entity_type,
                entity_id=r.entity_id,
                metadata=dict(r.metadata_json or {}),
                created_at=r.created_at,
            )
        )
    return out
