from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone, tzinfo
from typing import Optional
from zoneinfo import ZoneInfo

try:
    JAKARTA_TZ: tzinfo = ZoneInfo("Asia/Jakarta")
except Exception:
    # Fallback on minimal Windows Python environments without tzdata package
    JAKARTA_TZ = timezone(timedelta(hours=7), name="WIB")

_BULAN_ID = (
    "Januari",
    "Februari",
    "Maret",
    "April",
    "Mei",
    "Juni",
    "Juli",
    "Agustus",
    "September",
    "Oktober",
    "November",
    "Desember",
)


def jakarta_now() -> datetime:
    return datetime.now(JAKARTA_TZ)


def jakarta_today() -> date:
    return jakarta_now().date()


def date_only_to_jakarta_production_dt(d: date, *, hour: int = 8, minute: int = 0) -> datetime:
    """Convert an operational date in Asia/Jakarta (default 08:00 WIB) to UTC datetime."""
    local_dt = datetime.combine(d, time(hour=hour, minute=minute, second=0), tzinfo=JAKARTA_TZ)
    return local_dt.astimezone(timezone.utc)


def date_only_to_jakarta_eod_utc(d: date) -> datetime:
    """Convert an expiry date-only string to end-of-day Asia/Jakarta (23:59:59 WIB) in UTC."""
    local_dt = datetime.combine(d, time(hour=23, minute=59, second=59), tzinfo=JAKARTA_TZ)
    return local_dt.astimezone(timezone.utc)


def parse_production_date_jakarta(raw: Optional[str | date | datetime]) -> datetime:
    """Interpret None -> today 08:00 WIB, YYYY-MM-DD -> 08:00 WIB that day, full ISO -> preserve & convert to UTC."""
    if raw is None:
        return date_only_to_jakarta_production_dt(jakarta_today())
    if isinstance(raw, datetime):
        if raw.tzinfo is None:
            return raw.replace(tzinfo=JAKARTA_TZ).astimezone(timezone.utc)
        return raw.astimezone(timezone.utc)
    if isinstance(raw, date):
        return date_only_to_jakarta_production_dt(raw)

    text = str(raw).strip()
    if not text:
        return date_only_to_jakarta_production_dt(jakarta_today())
    if len(text) == 10:
        d = date.fromisoformat(text)
        return date_only_to_jakarta_production_dt(d)
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=JAKARTA_TZ)
    return dt.astimezone(timezone.utc)


def parse_expiry_date_jakarta(raw: Optional[str | date | datetime]) -> Optional[datetime]:
    """Interpret YYYY-MM-DD expiry as 23:59:59 WIB converted to UTC."""
    if raw is None:
        return None
    if isinstance(raw, datetime):
        if raw.tzinfo is None:
            return raw.replace(tzinfo=JAKARTA_TZ).astimezone(timezone.utc)
        return raw.astimezone(timezone.utc)
    if isinstance(raw, date):
        return date_only_to_jakarta_eod_utc(raw)

    text = str(raw).strip()
    if not text:
        return None
    if len(text) == 10:
        return date_only_to_jakarta_eod_utc(date.fromisoformat(text))
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=JAKARTA_TZ)
    return dt.astimezone(timezone.utc)


def to_jakarta_date(dt: datetime) -> date:
    utc_dt = dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
    return utc_dt.astimezone(JAKARTA_TZ).date()


def format_jakarta_date_id(dt: Optional[datetime | date]) -> str:
    if dt is None:
        return "Belum dicatat"
    d = to_jakarta_date(dt) if isinstance(dt, datetime) else dt
    return f"{d.day} {_BULAN_ID[d.month - 1]} {d.year}"
