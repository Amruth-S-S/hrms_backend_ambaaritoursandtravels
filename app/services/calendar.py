"""Working-day, leave and attendance-summary calculations shared by several routers."""
from datetime import date

from bson import ObjectId

from app.core.database import get_db
from app.services.late_fine import late_blocks
from app.utils import daterange, local_today, month_bounds


async def holiday_dates(start: date, end: date) -> dict[str, str]:
    cur = get_db().holidays.find({"date": {"$gte": start.isoformat(), "$lte": end.isoformat()}})
    return {h["date"]: h["name"] async for h in cur}


def is_working_day(d: date, company: dict, holidays: dict) -> bool:
    return d.weekday() in company["working_days"] and d.isoformat() not in holidays


async def count_leave_days(start: date, end: date, half_day: bool, company: dict) -> float:
    holidays = await holiday_dates(start, end)
    days = sum(1 for d in daterange(start, end) if is_working_day(d, company, holidays))
    if half_day and days:
        return 0.5
    return float(days)


async def approved_leave_map(user_id: ObjectId, start: date, end: date, company: dict) -> dict:
    """date string -> {'type': leave_type, 'half': bool} for approved leave on working days."""
    holidays = await holiday_dates(start, end)
    cur = get_db().leaves.find({
        "user_id": user_id, "status": "approved",
        "start_date": {"$lte": end.isoformat()}, "end_date": {"$gte": start.isoformat()},
    })
    out = {}
    async for lv in cur:
        ls, le = date.fromisoformat(lv["start_date"]), date.fromisoformat(lv["end_date"])
        for d in daterange(max(ls, start), min(le, end)):
            if is_working_day(d, company, holidays):
                out[d.isoformat()] = {"type": lv["leave_type"], "half": bool(lv.get("half_day"))}
    return out


async def month_summary(user: dict, month: str, company: dict) -> dict:
    """Attendance summary for one employee and month. Days before joining are ignored."""
    user_id = user["_id"]
    start, end = month_bounds(month)
    joined = user.get("date_of_joining")
    today = local_today()
    holidays = await holiday_dates(start, end)
    records = await get_db().attendance.find({
        "user_id": user_id, "date": {"$gte": start.isoformat(), "$lte": end.isoformat()},
    }).to_list(None)
    by_date = {r["date"]: r for r in records}
    leaves = await approved_leave_map(user_id, start, end, company)

    s = {"month": month, "working_days": 0, "present": 0, "half_day": 0, "absent": 0,
         "late": 0, "late_minutes": 0, "late_blocks": 0, "paid_leave": 0.0, "unpaid_leave": 0.0, "holidays": len(holidays),
         "work_minutes": 0, "overtime_minutes": 0}

    for d in daterange(start, end):
        ds = d.isoformat()
        rec = by_date.get(ds)
        if rec:
            s["work_minutes"] += rec.get("work_minutes", 0) or 0
            s["overtime_minutes"] += rec.get("overtime_minutes", 0) or 0
            if rec.get("is_late"):
                s["late"] += 1
                s["late_minutes"] += rec.get("late_minutes", 0) or 0
                s["late_blocks"] += late_blocks(rec.get("late_minutes", 0))
        if not is_working_day(d, company, holidays) or (joined and ds < joined):
            continue
        s["working_days"] += 1
        status = rec.get("status") if rec else None
        lv = leaves.get(ds)
        if lv:
            amount = 0.5 if lv["half"] else 1.0
            s["unpaid_leave" if lv["type"] == "unpaid" else "paid_leave"] += amount
            if lv["half"]:
                if status in ("present", "half_day"):
                    s["present"] += 0.5
                elif d < today:
                    s["absent"] += 0.5
            continue
        if status == "present":
            s["present"] += 1
        elif status == "half_day":
            s["half_day"] += 1
        elif status == "leave":
            s["paid_leave"] += 1
        elif status == "holiday":
            s["holidays"] += 1
        elif status == "absent" or (rec is None and d < today):
            # a past working day with no record counts as absent; today is not counted yet
            s["absent"] += 1
    return s
