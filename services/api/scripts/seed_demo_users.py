"""Explicit development-only CLI tool to seed demo kitchens and role accounts.

Usage:
    set GIZIOPTIMA_DEMO_PASSWORD=<your-dev-password>
    python scripts/seed_demo_users.py
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from app.auth.seed import seed_development_demo_accounts  # noqa: E402
from app.db.session import db_manager  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Seed local development demo kitchens and RBAC accounts (DEMO_ONLY)."
    )
    parser.add_argument(
        "--password",
        default=os.getenv("GIZIOPTIMA_DEMO_PASSWORD", ""),
        help="Password for local demo accounts (or set GIZIOPTIMA_DEMO_PASSWORD env var).",
    )
    args = parser.parse_args()
    if os.getenv("GIZIOPTIMA_ENV", "").strip().lower() == "production":
        print("ERROR: Demo accounts are disabled in production. Use manage_access.py.", file=sys.stderr)
        return 1

    if not args.password or len(args.password) < 8:
        print(
            "ERROR: Provide a password (>= 8 chars) via --password or GIZIOPTIMA_DEMO_PASSWORD.",
            file=sys.stderr,
        )
        return 1

    db_manager.ensure_initialized()
    assert db_manager.SessionLocal is not None
    with db_manager.SessionLocal() as session:
        seeded = seed_development_demo_accounts(session, demo_password=args.password)

    print("Seeded local development demo accounts (DEMO_ONLY):")
    for username, info in seeded.items():
        print(f"  - {username:18s} | role={info['role']:16s} | kitchen={info['kitchen_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
