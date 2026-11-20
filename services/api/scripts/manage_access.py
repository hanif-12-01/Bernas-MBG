"""Manage GiziOptima accounts using trusted server shell and database access."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from getpass import getpass, getuser
from pathlib import Path
import re
import sys
from uuid import UUID, uuid4

SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from sqlalchemy import select, update  # noqa: E402
from sqlalchemy.exc import IntegrityError  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.auth.dependencies import record_audit_event  # noqa: E402
from app.auth.schemas import RoleEnum  # noqa: E402
from app.auth.security import hash_password  # noqa: E402
from app.db.models import AuthSessionORM, KitchenMembershipORM, KitchenORM, UserORM  # noqa: E402
from app.db.session import db_manager  # noqa: E402


def _text(value: str, max_length: int, label: str) -> str:
    clean = value.strip()
    if not 1 <= len(clean) <= max_length:
        raise ValueError(f"{label} must be 1 to {max_length} characters.")
    return clean


def _read_password(from_stdin: bool) -> str:
    if from_stdin:
        password = sys.stdin.readline(258).rstrip("\r\n")
    else:
        if not sys.stdin.isatty():
            raise ValueError("Use a terminal prompt or supply a password from a trusted stdin source.")
        password = getpass("New password: ")
        if getpass("Confirm password: ") != password:
            raise ValueError("The password confirmation did not match.")
    if not 12 <= len(password) <= 256:
        raise ValueError("New passwords must be 12 to 256 characters.")
    return password


def _get_kitchen(session: Session, code: str) -> KitchenORM:
    kitchen = session.scalar(select(KitchenORM).where(KitchenORM.code == code.strip().upper()))
    if kitchen is None:
        raise ValueError("Kitchen code not found.")
    return kitchen


def _get_user(session: Session, username: str) -> UserORM:
    user = session.scalar(select(UserORM).where(UserORM.username == username.strip().lower()))
    if user is None:
        raise ValueError("Username not found.")
    # Serialize credential and membership changes with other administration and login writes.
    session.execute(update(UserORM).where(UserORM.id == user.id).values(is_active=UserORM.is_active))
    session.refresh(user)
    return user


def _audit(
    session: Session,
    action: str,
    entity_type: str,
    entity_id: str,
    kitchen_id: str | None,
    **metadata: str,
) -> None:
    record_audit_event(
        session,
        action=f"admin.{action}",
        entity_type=entity_type,
        entity_id=entity_id,
        kitchen_id=UUID(kitchen_id) if kitchen_id else None,
        metadata={"operator": getuser(), **metadata},
    )


def _revoke_sessions(session: Session, user: UserORM, kitchen_id: str | None = None) -> None:
    stmt = update(AuthSessionORM).where(
        AuthSessionORM.user_id == user.id,
        AuthSessionORM.revoked_at.is_(None),
    )
    if kitchen_id is not None:
        stmt = stmt.where(AuthSessionORM.active_kitchen_id == kitchen_id)
    session.execute(stmt.values(revoked_at=datetime.now(timezone.utc)))


def _set_membership(
    session: Session, user: UserORM, kitchen: KitchenORM, role: str, make_default: bool
) -> None:
    if not kitchen.active:
        raise ValueError("Cannot assign a membership to an inactive kitchen.")
    memberships = session.scalars(
        select(KitchenMembershipORM).where(KitchenMembershipORM.user_id == user.id)
    ).all()
    existing = next((row for row in memberships if row.kitchen_id == kitchen.id), None)
    use_default = make_default or not any(row.is_default and row.kitchen.active for row in memberships)
    if use_default:
        for row in memberships:
            row.is_default = row.kitchen_id == kitchen.id

    if existing is None:
        session.add(
            KitchenMembershipORM(
                id=str(uuid4()), user_id=user.id, kitchen_id=kitchen.id,
                role=role, is_default=use_default,
            )
        )
    elif existing.role != role:
        existing.role = role
        _revoke_sessions(session, user, kitchen.id)
    _audit(session, "membership_set", "user", user.id, kitchen.id, username=user.username, role=role)


def _remove_membership(session: Session, user: UserORM, kitchen: KitchenORM) -> None:
    membership = session.scalar(
        select(KitchenMembershipORM).where(
            KitchenMembershipORM.user_id == user.id,
            KitchenMembershipORM.kitchen_id == kitchen.id,
        )
    )
    if membership is None:
        raise ValueError("User has no membership for that kitchen.")
    if membership.is_default:
        new_default = session.scalar(
            select(KitchenMembershipORM)
            .join(KitchenORM)
            .where(
                KitchenMembershipORM.user_id == user.id,
                KitchenMembershipORM.kitchen_id != kitchen.id,
                KitchenORM.active.is_(True),
            )
            .order_by(KitchenORM.code)
            .limit(1)
        )
        if new_default is not None:
            new_default.is_default = True
    session.delete(membership)
    _revoke_sessions(session, user, kitchen.id)
    _audit(session, "membership_removed", "user", user.id, kitchen.id, username=user.username)


def _apply_command(session: Session, args: argparse.Namespace, digest: str | None) -> None:
    if args.command == "create-kitchen":
        code = args.code.strip().upper()
        if not re.fullmatch(r"[A-Z0-9][A-Z0-9_-]{1,63}", code):
            raise ValueError("Kitchen code must contain 2 to 64 letters, numbers, dashes or underscores.")
        kitchen = KitchenORM(
            id=str(uuid4()),
            code=code,
            name=_text(args.name, 255, "Kitchen name"),
            region=_text(args.region, 128, "Region"),
            active=True,
        )
        session.add(kitchen)
        session.flush()
        _audit(session, "kitchen_created", "kitchen", kitchen.id, kitchen.id, code=code)
        return

    if args.command == "create-user":
        username = args.username.strip().lower()
        email = args.email.strip().lower()
        if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{1,63}", username):
            raise ValueError("Username must contain 2 to 64 letters, numbers, dots, dashes or underscores.")
        if len(email) > 128 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
            raise ValueError("Provide a usable email address of at most 128 characters.")
        kitchen = _get_kitchen(session, args.kitchen)
        user = UserORM(
            id=str(uuid4()), username=username, email=email,
            full_name=_text(args.name, 150, "Full name"), password_hash=digest, is_active=True,
        )
        session.add(user)
        session.flush()
        _set_membership(session, user, kitchen, args.role, make_default=True)
        _audit(session, "user_created", "user", user.id, kitchen.id, username=username)
        return

    user = _get_user(session, args.username)
    if args.command == "set-membership":
        _set_membership(session, user, _get_kitchen(session, args.kitchen), args.role, args.default)
        return
    if args.command == "remove-membership":
        _remove_membership(session, user, _get_kitchen(session, args.kitchen))
        return

    action = {
        "reset-password": "password_reset",
        "disable-user": "user_disabled",
        "enable-user": "user_enabled",
    }[args.command]
    if args.command == "reset-password":
        user.password_hash = digest
    else:
        user.is_active = args.command == "enable-user"
    _revoke_sessions(session, user)
    for kitchen_id in [membership.kitchen_id for membership in user.memberships] or [None]:
        _audit(session, action, "user", user.id, kitchen_id, username=user.username)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    kitchen = commands.add_parser("create-kitchen", help="Create an active kitchen")
    kitchen.add_argument("--code", required=True)
    kitchen.add_argument("--name", required=True)
    kitchen.add_argument("--region", required=True)

    roles = [role.value for role in RoleEnum]
    create_user = commands.add_parser("create-user", help="Create an account with a kitchen and role")
    create_user.add_argument("username")
    create_user.add_argument("--email", required=True)
    create_user.add_argument("--name", required=True)
    create_user.add_argument("--kitchen", required=True, help="Kitchen code")
    create_user.add_argument("--role", required=True, choices=roles)
    create_user.add_argument("--password-stdin", action="store_true", help="Read one password from stdin")

    membership = commands.add_parser("set-membership", help="Grant a kitchen membership or change its role")
    membership.add_argument("username")
    membership.add_argument("--kitchen", required=True, help="Kitchen code")
    membership.add_argument("--role", required=True, choices=roles)
    membership.add_argument("--default", action="store_true", help="Make this the user's default kitchen")
    remove = commands.add_parser("remove-membership", help="Revoke a user's access to a kitchen")
    remove.add_argument("username")
    remove.add_argument("--kitchen", required=True, help="Kitchen code")

    reset = commands.add_parser("reset-password", help="Set a new password and revoke all sessions")
    reset.add_argument("username")
    reset.add_argument("--password-stdin", action="store_true", help="Read one password from stdin")
    for command in ("disable-user", "enable-user"):
        commands.add_parser(command).add_argument("username")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        digest = None
        if args.command in {"create-user", "reset-password"}:
            digest = hash_password(_read_password(args.password_stdin))
        db_manager.ensure_initialized()
        assert db_manager.SessionLocal is not None
        with db_manager.SessionLocal.begin() as session:
            _apply_command(session, args, digest)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except IntegrityError:
        print("Error: a duplicate identifier or conflicting database state prevented the change.", file=sys.stderr)
        return 2
    print(f"Applied {args.command}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
