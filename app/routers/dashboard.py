import asyncio
from datetime import timedelta

from fastapi import APIRouter, Depends

from app.core.database import get_db
from app.core.deps import get_current_user, require_admin
from app.routers.leaves import leave_balance
from app.services.calendar import month_summary
from app.services.company import get_company_settings
from app.services.late_fine import salary_summary
from app.services.users import employee_brief, user_map
from app.utils import local_now, local_today, serialize, today_str

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/admin")
async def admin_dashboard(admin: dict = Depends(require_admin)):
    db = get_db()
    today = today_str()
    emp_filter = {"role": "employee", "status": "active"}
    total = await db.users.count_documents(emp_filter)
    inactive = await db.users.count_documents({"role": "employee", "status": "inactive"})

    today_recs = await db.attendance.find({"date": today, "check_in": {"$ne": None}}).to_list(None)
    checked_in = len(today_recs)
    late = sum(1 for r in today_recs if r.get("is_late"))
    checked_out = sum(1 for r in today_recs if r.get("check_out"))
    on_leave = await db.leaves.count_documents({"status": "approved", "start_date": {"$lte": today},
                                                "end_date": {"$gte": today}})
    pending_leaves = await db.leaves.count_documents({"status": "pending"})
    online = await db.sessions.count_documents({"active": True})

    trend = []
    for i in range(6, -1, -1):
        d = (local_today() - timedelta(days=i)).isoformat()
        n = await db.attendance.count_documents({"date": d, "check_in": {"$ne": None}})
        trend.append({"date": d, "present": n})

    recent = sorted(today_recs, key=lambda r: r["check_in"]["time"], reverse=True)[:8]
    users = await user_map(r["user_id"] for r in recent)
    recent_out = []
    for r in recent:
        d = serialize(r)
        d["employee"] = employee_brief(users.get(r["user_id"]))
        recent_out.append(d)

    upcoming = await db.holidays.find({"date": {"$gte": today}}).sort("date", 1).to_list(3)
    return {
        "salaries": await _salary_rows(),
        "date": today,
        "employees": {"active": total, "inactive": inactive},
        "today": {"checked_in": checked_in, "checked_out": checked_out, "late": late,
                  "on_leave": on_leave, "not_in": max(0, total - checked_in - on_leave)},
        "pending_leaves": pending_leaves,
        "online_now": online,
        "departments": await db.departments.count_documents({}),
        "trend": trend,
        "recent_checkins": recent_out,
        "upcoming_holidays": serialize(upcoming),
    }


async def _salary_rows() -> list[dict]:
    """This month's salary, late cut and amount to pay for every active employee."""
    company = await get_company_settings()
    month = local_now().strftime("%Y-%m")
    users = await get_db().users.find({"role": "employee", "status": "active"}).sort("name", 1).to_list(None)
    summaries = await asyncio.gather(*(month_summary(u, month, company) for u in users))
    rows = []
    for u, summary in zip(users, summaries):
        row = {"id": str(u["_id"]), **employee_brief(u)}
        row.update(salary_summary(u.get("salary"), summary))
        row["late_days"] = summary["late"]
        rows.append(row)
    return rows


@router.get("/employee")
async def employee_dashboard(user: dict = Depends(get_current_user)):
    db = get_db()
    company = await get_company_settings()
    today = today_str()
    month = local_now().strftime("%Y-%m")
    upcoming = await db.holidays.find({"date": {"$gte": today}}).sort("date", 1).to_list(4)
    news = await db.announcements.find().sort("created_at", -1).to_list(5)
    pending = await db.leaves.count_documents({"user_id": user["_id"], "status": "pending"})
    summary = await month_summary(user, month, company)
    return {
        "month_summary": summary,
        "salary": salary_summary(user.get("salary"), summary),
        "leave_balance": await leave_balance(user, company),
        "pending_leaves": pending,
        "upcoming_holidays": serialize(upcoming),
        "announcements": serialize(news),
        "company_name": company["company_name"],
    }
