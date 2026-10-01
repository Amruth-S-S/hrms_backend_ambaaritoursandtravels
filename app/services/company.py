"""Company-wide settings, employee code counter and first-run seeding."""
from pymongo import ReturnDocument

from app.core.config import settings
from app.core.database import get_db
from app.core.security import hash_password
from app.utils import now_utc

DEFAULT_SETTINGS = {
    "company_name": "My Company",
    "office_start": "09:30",
    "office_end": "18:30",
    "grace_minutes": 15,
    "half_day_hours": 4,
    "full_day_hours": 8,
    "working_days": [0, 1, 2, 3, 4],  # Mon-Fri (0 = Monday)
    "office_lat": None,
    "office_lng": None,
    "office_radius_m": 200,
    "enforce_geofence": False,
    "require_selfie": True,
    "leave_quota": {"casual": 12, "sick": 8, "earned": 15},
    "late_cut_start": None,  # "YYYY-MM-DD": only late arrivals from this date are cut from salary
}


async def get_company_settings() -> dict:
    doc = await get_db().settings.find_one({"_id": "global"}) or {}
    merged = {**DEFAULT_SETTINGS, **{k: v for k, v in doc.items() if k != "_id"}}
    merged["leave_quota"] = {**DEFAULT_SETTINGS["leave_quota"], **(doc.get("leave_quota") or {})}
    return merged


async def save_company_settings(data: dict) -> dict:
    await get_db().settings.update_one(
        {"_id": "global"}, {"$set": {**data, "updated_at": now_utc()}}, upsert=True
    )
    return await get_company_settings()


async def next_employee_code() -> str:
    db = get_db()
    while True:
        r = await db.counters.find_one_and_update(
            {"_id": "employee"}, {"$inc": {"seq": 1}},
            upsert=True, return_document=ReturnDocument.AFTER,
        )
        code = f"EMP{r['seq']:04d}"
        if not await db.users.find_one({"employee_code": code}, {"_id": 1}):
            return code


async def seed() -> None:
    db = get_db()
    if not await db.settings.find_one({"_id": "global"}):
        await db.settings.insert_one({"_id": "global", **DEFAULT_SETTINGS})
    if await db.users.count_documents({"role": "admin"}) == 0:
        await db.users.insert_one({
            "name": settings.ADMIN_NAME,
            "email": settings.ADMIN_EMAIL.lower().strip(),
            "password_hash": hash_password(settings.ADMIN_PASSWORD),
            "role": "admin",
            "status": "active",
            "employee_code": "ADM0001",
            "designation": "Administrator",
            "salary": 0,
            "created_at": now_utc(),
        })
        print(f"[HRMS] Admin account created: {settings.ADMIN_EMAIL}")
