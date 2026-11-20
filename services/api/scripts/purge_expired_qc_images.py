"""Remove expired QC photo files while retaining inspection and audit references."""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from app.db.models import QCImageORM  # noqa: E402
from app.db.session import get_database_url  # noqa: E402
from app.vision.image_security import ImageSecurityError, image_expiry, qc_storage_path  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Delete the expired binaries. Default is a dry run.")
    args = parser.parse_args()
    database_url = make_url(get_database_url())
    if database_url.get_backend_name() == "sqlite" and not Path(database_url.database or "").is_file():
        parser.error("The configured SQLite database file was not found.")

    db = create_engine(database_url)
    now = datetime.now(timezone.utc)
    eligible = deleted = errors = 0
    try:
        with Session(db) as session:
            query = select(QCImageORM.storage_key, QCImageORM.created_at, QCImageORM.retention_days).where(
                QCImageORM.created_at <= now - timedelta(days=1)
            )
            for key, created_at, retention_days in session.execute(query).yield_per(1000):
                if image_expiry(created_at, retention_days) > now:
                    continue
                try:
                    path = qc_storage_path(key)
                    if path.is_file():
                        eligible += 1
                        if args.apply:
                            path.unlink(missing_ok=True)
                            deleted += 1
                except (ImageSecurityError, OSError):
                    errors += 1
    finally:
        db.dispose()

    print(f"mode={'apply' if args.apply else 'dry-run'} eligible={eligible} deleted={deleted} errors={errors}")
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
