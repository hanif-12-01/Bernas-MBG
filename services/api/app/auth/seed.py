from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.auth.schemas import RoleEnum
from app.auth.security import hash_password
from app.data.incident_fixture import seed_incident_demo_dataset
from app.data.inventory_quality_fixture import seed_inventory_quality_demo_dataset
from app.data.recovery_fixture import seed_recovery_demo_dataset
from app.db.models import KitchenMembershipORM, KitchenORM, ScenarioORM, UserORM
from app.inventory.service import seed_dataset_sources_if_empty

# Deterministic UUIDs for local development & automated test kitchens
DEMO_KITCHEN_A_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1")
DEMO_KITCHEN_B_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2")


def ensure_default_kitchen_and_migrate_legacy(session: Session) -> KitchenORM:
    """Ensure the primary local kitchen exists and non-destructively attach legacy NULL-kitchen scenarios."""
    kitchen_a = session.get(KitchenORM, str(DEMO_KITCHEN_A_ID))
    if kitchen_a is None:
        kitchen_a = KitchenORM(
            id=str(DEMO_KITCHEN_A_ID),
            code="SPPG-SIM-A",
            name="Dapur SPPG Simulasi A (DEMO_ONLY)",
            region="DKI Jakarta (Simulasi)",
            active=True,
            created_at=datetime.now(timezone.utc),
        )
        session.add(kitchen_a)
        session.flush()

    # Non-destructive migration for pre-Sprint-3A scenarios without kitchen_id
    session.execute(
        update(ScenarioORM)
        .where(ScenarioORM.kitchen_id.is_(None))
        .values(kitchen_id=str(DEMO_KITCHEN_A_ID))
    )
    session.commit()
    return kitchen_a


def seed_development_demo_accounts(
    session: Session,
    *,
    demo_password: str,
    include_second_kitchen: bool = True,
) -> dict[str, dict[str, str]]:
    """Explicitly seed local development demo accounts using Argon2id password hashing.

    Must ONLY be invoked via CLI setup script (`scripts/seed_demo_users.py`),
    explicit environment configuration, or automated test fixtures — never silently hardcoded
    into frontend bundles or production deployments.
    """
    if not demo_password or len(demo_password) < 8:
        raise ValueError("demo_password must be at least 8 characters")

    kitchen_a = ensure_default_kitchen_and_migrate_legacy(session)

    kitchen_b: Optional[KitchenORM] = None
    if include_second_kitchen:
        kitchen_b = session.get(KitchenORM, str(DEMO_KITCHEN_B_ID))
        if kitchen_b is None:
            kitchen_b = KitchenORM(
                id=str(DEMO_KITCHEN_B_ID),
                code="SPPG-SIM-B",
                name="Dapur SPPG Simulasi B (DEMO_ONLY)",
                region="Jawa Barat (Simulasi)",
                active=True,
                created_at=datetime.now(timezone.utc),
            )
            session.add(kitchen_b)
            session.flush()

    account_specs = [
        ("kepala_dapur", "kepala.a@simulasi.gizioptima.local", "Budi Santoso (Kepala Dapur A)", kitchen_a.id, RoleEnum.KITCHEN_MANAGER),
        ("perencana_menu", "perencana.a@simulasi.gizioptima.local", "Siti Rahma (Perencana Menu A)", kitchen_a.id, RoleEnum.MENU_PLANNER),
        ("petugas_qc", "qc.a@simulasi.gizioptima.local", "Dina Lestari (Petugas QC A)", kitchen_a.id, RoleEnum.QC_OFFICER),
    ]
    if include_second_kitchen and kitchen_b is not None:
        account_specs.extend(
            [
                ("kepala_dapur_b", "kepala.b@simulasi.gizioptima.local", "Hendra Wijaya (Kepala Dapur B)", kitchen_b.id, RoleEnum.KITCHEN_MANAGER),
                ("perencana_menu_b", "perencana.b@simulasi.gizioptima.local", "Rina Kusuma (Perencana Menu B)", kitchen_b.id, RoleEnum.MENU_PLANNER),
                ("petugas_qc_b", "qc.b@simulasi.gizioptima.local", "Fajar Pratama (Petugas QC B)", kitchen_b.id, RoleEnum.QC_OFFICER),
            ]
        )

    seeded: dict[str, dict[str, str]] = {}
    pw_hash = hash_password(demo_password)

    for username, email, full_name, kitchen_id, role in account_specs:
        user = session.execute(
            select(UserORM).where(UserORM.username == username)
        ).scalar_one_or_none()
        if user is None:
            user = UserORM(
                id=str(uuid4()),
                username=username,
                email=email,
                full_name=full_name,
                password_hash=pw_hash,
                is_active=True,
                created_at=datetime.now(timezone.utc),
            )
            session.add(user)
            session.flush()

        membership = session.execute(
            select(KitchenMembershipORM).where(
                KitchenMembershipORM.user_id == user.id,
                KitchenMembershipORM.kitchen_id == kitchen_id,
            )
        ).scalar_one_or_none()
        if membership is None:
            session.add(
                KitchenMembershipORM(
                    id=str(uuid4()),
                    user_id=user.id,
                    kitchen_id=kitchen_id,
                    role=role.value,
                    is_default=True,
                    created_at=datetime.now(timezone.utc),
                )
            )
        seeded[username] = {
            "user_id": user.id,
            "kitchen_id": kitchen_id,
            "role": role.value,
            "full_name": full_name,
        }

    seed_dataset_sources_if_empty(session)
    seed_inventory_quality_demo_dataset(session, kitchen_id=UUID(kitchen_a.id))
    seed_recovery_demo_dataset(session, kitchen_id=UUID(kitchen_a.id))
    seed_incident_demo_dataset(session, kitchen_id=UUID(kitchen_a.id))
    session.commit()
    return seeded
