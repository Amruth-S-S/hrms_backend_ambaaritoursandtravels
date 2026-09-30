import math
import re
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from bson import ObjectId
from fastapi import HTTPException

from app.core.config import settings

TZ = ZoneInfo(settings.TIMEZONE)
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def to_local(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(TZ)


def local_now() -> datetime:
    return datetime.now(TZ)


def local_today() -> date:
    return local_now().date()


def today_str() -> str:
    return local_today().isoformat()


def minutes_between(a: datetime, b: datetime) -> int:
    return max(0, int((b - a).total_seconds() // 60))


def local_datetime(day: str, hhmm: str) -> datetime:
    """Timezone-aware datetime from a local date (YYYY-MM-DD) and time (HH:MM)."""
    d = date.fromisoformat(day)
    h, m = (int(x) for x in hhmm.split(":"))
    return datetime(d.year, d.month, d.day, h, m, tzinfo=TZ)


def validate_date(value: str, name: str = "date") -> str:
    if not value or not DATE_RE.match(value):
        raise HTTPException(400, f"{name} must be in YYYY-MM-DD format")
    try:
        date.fromisoformat(value)
    except ValueError:
        raise HTTPException(400, f"{name} is not a valid date")
    return value


def month_bounds(month: str) -> tuple[date, date]:
    if not MONTH_RE.match(month or ""):
        raise HTTPException(400, "Month must be in YYYY-MM format")
    y, m = (int(x) for x in month.split("-"))
    start = date(y, m, 1)
    end = (date(y + 1, 1, 1) if m == 12 else date(y, m + 1, 1)) - timedelta(days=1)
    return start, end


def daterange(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def oid(value: str, name: str = "id") -> ObjectId:
    if not value or not ObjectId.is_valid(value):
        raise HTTPException(400, f"Invalid {name}")
    return ObjectId(value)


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def serialize(obj):
    """Convert Mongo documents into JSON-safe dicts (ObjectId -> str, _id -> id)."""
    if isinstance(obj, list):
        return [serialize(o) for o in obj]
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k == "password_hash" or (k.startswith("_") and k != "_id"):
                continue
            out["id" if k == "_id" else k] = serialize(v)
        return out
    if isinstance(obj, ObjectId):
        return str(obj)
    if isinstance(obj, datetime):
        if obj.tzinfo is None:
            obj = obj.replace(tzinfo=timezone.utc)
        return obj.isoformat()
    if isinstance(obj, date):
        return obj.isoformat()
    return obj
