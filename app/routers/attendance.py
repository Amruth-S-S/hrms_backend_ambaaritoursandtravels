import csv
import io
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from pymongo.errors import DuplicateKeyError

from app.core.config import settings
from app.core.database import get_db, get_fs
from app.core.deps import get_current_user, require_admin
from app.schemas import AttendanceMarkIn
from app.services.calendar import is_working_day, month_summary
from app.services.company import get_company_settings
from app.services.geo import build_location
from app.services.users import employee_brief, user_map
from app.utils import (local_datetime, local_now, local_today, minutes_between, month_bounds,
                       now_utc, oid, serialize, to_local, today_str, validate_date)

router = APIRouter(prefix="/attendance", tags=["attendance"])

ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}


# ---------------------------------------------------------------- helpers
async def _read_selfie(file: UploadFile | None, required: bool) -> tuple[bytes, str] | None:
    if file is None or not file.filename:
        if required:
            raise HTTPException(400, "A selfie is required to mark attendance")
        return None
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(400, "Selfie must be a JPEG, PNG or WEBP image")
    data = await file.read()
    if not data:
        raise HTTPException(400, "Selfie file is empty")
    if len(data) > settings.MAX_SELFIE_MB * 1024 * 1024:
        raise HTTPException(400, f"Selfie must be smaller than {settings.MAX_SELFIE_MB} MB")
    return data, file.content_type


async def _store_selfie(selfie, user_id, kind: str):
    if not selfie:
        return None
    data, ctype = selfie
    return await get_fs().upload_from_stream(
        f"{user_id}_{kind}_{int(now_utc().timestamp())}",
        data,
        metadata={"user_id": str(user_id), "content_type": ctype, "kind": kind},
    )


def _validate_coords(lat: float, lng: float):
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        raise HTTPException(400, "Invalid location coordinates")


def _geofence_guard(loc: dict, company: dict):
    if company.get("enforce_geofence") and loc["within_geofence"] is False:
        raise HTTPException(
            400,
            f"You are {loc['distance_from_office_m']} m from the office. "
            f"Attendance is allowed within {company['office_radius_m']} m.",
        )


def _status_for(work_minutes: int, company: dict) -> str:
    if work_minutes >= company["full_day_hours"] * 60:
        return "present"
    if work_minutes >= company["half_day_hours"] * 60:
        return "half_day"
    return "absent"


def _late_minutes(check_in_local, shift_start: str, grace: int) -> int:
    start = check_in_local.replace(hour=int(shift_start[:2]), minute=int(shift_start[3:]),
                                   second=0, microsecond=0)
    late = minutes_between(start, check_in_local)
    return late if late > grace else 0


async def _attach_users(records: list[dict]) -> list[dict]:
    users = await user_map(r["user_id"] for r in records)
    out = []
    for r in records:
        d = serialize(r)
        d["employee"] = employee_brief(users.get(r["user_id"]))
        out.append(d)
    return out


def _client_ip(request: Request):
    fwd = request.headers.get("x-forwarded-for")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else None)


# ---------------------------------------------------------------- employee actions
@router.post("/check-in")
async def check_in(
    request: Request,
    latitude: float = Form(...),
    longitude: float = Form(...),
    accuracy: Optional[float] = Form(None),
    note: Optional[str] = Form(None),
    selfie: Optional[UploadFile] = File(None),
    user: dict = Depends(get_current_user),
):
    db = get_db()
    company = await get_company_settings()
    _validate_coords(latitude, longitude)
    today = today_str()

    existing = await db.attendance.find_one({"user_id": user["_id"], "date": today})
    if existing and existing.get("check_in"):
        raise HTTPException(400, "You have already checked in today")

    photo = await _read_selfie(selfie, company["require_selfie"])
    loc = await build_location(latitude, longitude, accuracy, company)
    _geofence_guard(loc, company)

    now = now_utc()
    shift_start = user.get("shift_start") or company["office_start"]
    late = _late_minutes(to_local(now), shift_start, company["grace_minutes"])
    selfie_id = await _store_selfie(photo, user["_id"], "check_in")

    check_in_block = {"time": now, **loc, "selfie_id": selfie_id,
                      "note": (note or "")[:300] or None, "ip": _client_ip(request)}
    if existing:  # a record created by admin (e.g. marked absent) -> fill it in
        await db.attendance.update_one({"_id": existing["_id"]}, {"$set": {
            "check_in": check_in_block, "status": "present", "is_late": late > 0,
            "late_minutes": late, "updated_at": now}})
        doc = await db.attendance.find_one({"_id": existing["_id"]})
    else:
        doc = {"user_id": user["_id"], "date": today, "check_in": check_in_block,
               "check_out": None, "status": "present", "is_late": late > 0,
               "late_minutes": late, "work_minutes": 0, "overtime_minutes": 0,
               "source": "self", "created_at": now}
        try:
            await db.attendance.insert_one(doc)
        except DuplicateKeyError:
            raise HTTPException(400, "You have already checked in today")
    return serialize(doc)


@router.post("/check-out")
async def check_out(
    request: Request,
    latitude: float = Form(...),
    longitude: float = Form(...),
    accuracy: Optional[float] = Form(None),
    note: Optional[str] = Form(None),
    selfie: Optional[UploadFile] = File(None),
    user: dict = Depends(get_current_user),
):
    db = get_db()
    company = await get_company_settings()
    _validate_coords(latitude, longitude)

    rec = await db.attendance.find_one({"user_id": user["_id"], "date": today_str()})
    if not rec or not rec.get("check_in"):
        raise HTTPException(400, "You have not checked in today")
    if rec.get("check_out"):
        raise HTTPException(400, "You have already checked out today")

    photo = await _read_selfie(selfie, company["require_selfie"])
    loc = await build_location(latitude, longitude, accuracy, company)
    _geofence_guard(loc, company)

    now = now_utc()
    work = minutes_between(rec["check_in"]["time"], now)
    shift_end = user.get("shift_end") or company["office_end"]
    local = to_local(now)
    end_dt = local.replace(hour=int(shift_end[:2]), minute=int(shift_end[3:]), second=0, microsecond=0)
    selfie_id = await _store_selfie(photo, user["_id"], "check_out")

    updates = {
        "check_out": {"time": now, **loc, "selfie_id": selfie_id,
                      "note": (note or "")[:300] or None, "ip": _client_ip(request)},
        "work_minutes": work,
        "overtime_minutes": max(0, work - int(company["full_day_hours"] * 60)),
        "early_leave": local < end_dt,
        "status": _status_for(work, company),
        "updated_at": now,
    }
    await db.attendance.update_one({"_id": rec["_id"]}, {"$set": updates})
    return serialize({**rec, **updates})


@router.get("/today")
async def my_today(user: dict = Depends(get_current_user)):
    company = await get_company_settings()
    rec = await get_db().attendance.find_one({"user_id": user["_id"], "date": today_str()})
    return {
        "date": today_str(),
        "server_time": now_utc().isoformat(),
        "record": serialize(rec) if rec else None,
        "rules": {
            "office_start": user.get("shift_start") or company["office_start"],
            "office_end": user.get("shift_end") or company["office_end"],
            "grace_minutes": company["grace_minutes"],
            "require_selfie": company["require_selfie"],
            "enforce_geofence": company["enforce_geofence"],
            "office_radius_m": company["office_radius_m"],
            "has_office_location": company["office_lat"] is not None,
            "is_working_day": is_working_day(local_today(), company, user),
        },
    }


@router.get("/me")
async def my_attendance(month: str | None = None, user: dict = Depends(get_current_user)):
    month = month or local_now().strftime("%Y-%m")
    start, end = month_bounds(month)
    records = await get_db().attendance.find({
        "user_id": user["_id"], "date": {"$gte": start.isoformat(), "$lte": end.isoformat()},
    }).sort("date", -1).to_list(None)
    company = await get_company_settings()
    return {"records": serialize(records), "summary": await month_summary(user, month, company)}


# ---------------------------------------------------------------- admin
@router.get("")
async def list_attendance(date_: str | None = Query(None, alias="date"),
                          from_date: str | None = None, to_date: str | None = None,
                          user_id: str | None = None, status: str | None = None,
                          admin: dict = Depends(require_admin)):
    filt: dict = {}
    if date_:
        filt["date"] = validate_date(date_)
    elif from_date or to_date:
        filt["date"] = {}
        if from_date:
            filt["date"]["$gte"] = validate_date(from_date, "from_date")
        if to_date:
            filt["date"]["$lte"] = validate_date(to_date, "to_date")
    else:
        filt["date"] = today_str()
    if user_id:
        filt["user_id"] = oid(user_id, "user id")
    if status:
        filt["status"] = status
    records = await get_db().attendance.find(filt).sort([("date", -1), ("check_in.time", 1)]).to_list(5000)
    return await _attach_users(records)


@router.get("/report")
async def monthly_report(month: str | None = None, admin: dict = Depends(require_admin)):
    month = month or local_now().strftime("%Y-%m")
    month_bounds(month)
    company = await get_company_settings()
    users = await get_db().users.find({"role": "employee", "status": "active"}).sort("name", 1).to_list(None)
    rows = []
    for u in users:
        s = await month_summary(u, month, company)
        rows.append({"user_id": str(u["_id"]), **employee_brief(u), **s})
    return {"month": month, "rows": rows}


@router.get("/export")
async def export_csv(month: str | None = None, admin: dict = Depends(require_admin)):
    month = month or local_now().strftime("%Y-%m")
    start, end = month_bounds(month)
    records = await get_db().attendance.find(
        {"date": {"$gte": start.isoformat(), "$lte": end.isoformat()}}
    ).sort([("date", 1)]).to_list(None)
    users = await user_map(r["user_id"] for r in records)

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Date", "Employee code", "Name", "Status", "Check in", "Check out", "Hours worked",
                "Late (min)", "Overtime (min)", "Check-in location", "Check-in lat", "Check-in lng",
                "Check-out location", "Remarks"])
    for r in records:
        u = users.get(r["user_id"]) or {}
        ci, co = r.get("check_in") or {}, r.get("check_out") or {}
        fmt = lambda b: to_local(b["time"]).strftime("%H:%M") if b.get("time") else ""
        w.writerow([r["date"], u.get("employee_code", ""), u.get("name", "Deleted user"), r.get("status"),
                    fmt(ci), fmt(co), round((r.get("work_minutes") or 0) / 60, 2),
                    r.get("late_minutes", 0), r.get("overtime_minutes", 0), ci.get("address") or "",
                    ci.get("latitude", ""), ci.get("longitude", ""), co.get("address") or "",
                    r.get("remarks") or ""])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="attendance-{month}.csv"'},
    )


@router.get("/user/{user_id}")
async def user_month(user_id: str, month: str | None = None, admin: dict = Depends(require_admin)):
    db = get_db()
    user = await db.users.find_one({"_id": oid(user_id, "user id")})
    if not user:
        raise HTTPException(404, "User not found")
    month = month or local_now().strftime("%Y-%m")
    start, end = month_bounds(month)
    records = await db.attendance.find({
        "user_id": user["_id"], "date": {"$gte": start.isoformat(), "$lte": end.isoformat()},
    }).sort("date", -1).to_list(None)
    company = await get_company_settings()
    return {"employee": employee_brief(user), "records": serialize(records),
            "summary": await month_summary(user, month, company)}


@router.post("/mark")
async def mark_attendance(data: AttendanceMarkIn, admin: dict = Depends(require_admin)):
    """Create or correct a day's attendance for an employee (forgot to check out, manual entry, etc.)."""
    db = get_db()
    uid = oid(data.user_id, "user id")
    user = await db.users.find_one({"_id": uid})
    if not user:
        raise HTTPException(404, "User not found")
    if date.fromisoformat(data.date) > local_today():
        raise HTTPException(400, "Cannot mark attendance for a future date")

    company = await get_company_settings()
    rec = await db.attendance.find_one({"user_id": uid, "date": data.date}) or {}
    now = now_utc()
    ci = dict(rec.get("check_in") or {})
    co = dict(rec.get("check_out") or {}) if rec.get("check_out") else None

    if data.check_in_time:
        ci["time"] = local_datetime(data.date, data.check_in_time)
        ci.setdefault("edited_by_admin", True)
    if data.check_out_time:
        co = co or {}
        co["time"] = local_datetime(data.date, data.check_out_time)
        co["edited_by_admin"] = True
    if ci.get("time") and co and co.get("time") and co["time"] <= ci["time"]:
        raise HTTPException(400, "Check-out time must be after check-in time")

    work = minutes_between(ci["time"], co["time"]) if ci.get("time") and co and co.get("time") else 0
    late = 0
    if ci.get("time"):
        late = _late_minutes(to_local(ci["time"]), user.get("shift_start") or company["office_start"],
                             company["grace_minutes"])
    doc = {
        "user_id": uid, "date": data.date, "status": data.status,
        "check_in": ci or None, "check_out": co,
        "work_minutes": work, "overtime_minutes": max(0, work - int(company["full_day_hours"] * 60)),
        "is_late": late > 0, "late_minutes": late, "remarks": data.remarks,
        "marked_by": admin["_id"], "updated_at": now,
    }
    await db.attendance.update_one({"user_id": uid, "date": data.date},
                                   {"$set": doc, "$setOnInsert": {"created_at": now, "source": "admin"}},
                                   upsert=True)
    saved = await db.attendance.find_one({"user_id": uid, "date": data.date})
    return (await _attach_users([saved]))[0]


@router.delete("/{record_id}")
async def delete_record(record_id: str, admin: dict = Depends(require_admin)):
    res = await get_db().attendance.delete_one({"_id": oid(record_id, "record id")})
    if not res.deleted_count:
        raise HTTPException(404, "Record not found")
    return {"message": "Attendance record deleted"}
