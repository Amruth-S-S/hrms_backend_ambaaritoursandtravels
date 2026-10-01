from datetime import date

from fastapi import APIRouter, Depends, HTTPException

from app.core.database import get_db
from app.core.deps import get_current_user, require_admin
from app.schemas import LeaveDecisionIn, LeaveIn
from app.services.calendar import count_leave_days
from app.services.company import get_company_settings
from app.services.users import employee_brief, user_map
from app.utils import local_today, now_utc, oid, serialize

router = APIRouter(prefix="/leaves", tags=["leaves"])
LEAVE_TYPES = ("casual", "sick", "earned", "unpaid")


async def leave_balance(user: dict, company: dict, year: int | None = None) -> dict:
    year = year or local_today().year
    quota = {**company["leave_quota"], **(user.get("leave_quota") or {})}
    out = {t: {"quota": float(quota.get(t, 0)) if t != "unpaid" else None,
               "used": 0.0, "pending": 0.0, "remaining": None} for t in LEAVE_TYPES}
    cur = get_db().leaves.find({
        "user_id": user["_id"], "status": {"$in": ["approved", "pending"]},
        "start_date": {"$gte": f"{year}-01-01", "$lte": f"{year}-12-31"},
    })
    async for lv in cur:
        key = "used" if lv["status"] == "approved" else "pending"
        out[lv["leave_type"]][key] += lv.get("days", 0)
    for t, b in out.items():
        if b["quota"] is not None:
            b["remaining"] = round(b["quota"] - b["used"], 1)
    return out


async def _attach(leaves: list[dict]) -> list[dict]:
    users = await user_map(lv["user_id"] for lv in leaves)
    out = []
    for lv in leaves:
        d = serialize(lv)
        d["employee"] = employee_brief(users.get(lv["user_id"]))
        out.append(d)
    return out


@router.post("", status_code=201)
async def apply_leave(data: LeaveIn, user: dict = Depends(get_current_user)):
    db = get_db()
    company = await get_company_settings()
    start, end = date.fromisoformat(data.start_date), date.fromisoformat(data.end_date)
    days = await count_leave_days(start, end, data.half_day, company, user)
    if days == 0:
        raise HTTPException(400, "The selected dates are your week off, so no leave is needed")

    overlap = await db.leaves.find_one({
        "user_id": user["_id"], "status": {"$in": ["pending", "approved"]},
        "start_date": {"$lte": data.end_date}, "end_date": {"$gte": data.start_date},
    })
    if overlap:
        raise HTTPException(400, "You already have a leave request covering these dates")

    if data.leave_type != "unpaid":
        bal = (await leave_balance(user, company, start.year))[data.leave_type]
        available = bal["remaining"] - bal["pending"]
        if days > available:
            raise HTTPException(400, f"Not enough {data.leave_type} leave. Available: {available:g} day(s), "
                                     f"requested: {days:g}.")

    doc = {**data.model_dump(), "user_id": user["_id"], "days": days,
           "status": "pending", "applied_at": now_utc()}
    await db.leaves.insert_one(doc)
    return serialize(doc)


@router.get("/me")
async def my_leaves(user: dict = Depends(get_current_user)):
    leaves = await get_db().leaves.find({"user_id": user["_id"]}).sort("applied_at", -1).to_list(500)
    return serialize(leaves)


@router.get("/balance")
async def my_balance(user: dict = Depends(get_current_user)):
    return await leave_balance(user, await get_company_settings())


@router.delete("/{leave_id}")
async def cancel_leave(leave_id: str, user: dict = Depends(get_current_user)):
    db = get_db()
    lv = await db.leaves.find_one({"_id": oid(leave_id, "leave id"), "user_id": user["_id"]})
    if not lv:
        raise HTTPException(404, "Leave request not found")
    if lv["status"] != "pending":
        raise HTTPException(400, "Only pending requests can be cancelled")
    await db.leaves.update_one({"_id": lv["_id"]}, {"$set": {"status": "cancelled", "updated_at": now_utc()}})
    return {"message": "Leave request cancelled"}


# ---------------- admin
@router.get("")
async def all_leaves(status: str | None = None, user_id: str | None = None,
                     admin: dict = Depends(require_admin)):
    filt: dict = {}
    if status:
        filt["status"] = status
    if user_id:
        filt["user_id"] = oid(user_id, "user id")
    leaves = await get_db().leaves.find(filt).sort("applied_at", -1).to_list(2000)
    return await _attach(leaves)


@router.get("/balance/{user_id}")
async def user_balance(user_id: str, admin: dict = Depends(require_admin)):
    user = await get_db().users.find_one({"_id": oid(user_id, "user id")})
    if not user:
        raise HTTPException(404, "User not found")
    return await leave_balance(user, await get_company_settings())


@router.put("/{leave_id}/decision")
async def decide(leave_id: str, data: LeaveDecisionIn, admin: dict = Depends(require_admin)):
    db = get_db()
    lv = await db.leaves.find_one({"_id": oid(leave_id, "leave id")})
    if not lv:
        raise HTTPException(404, "Leave request not found")
    if lv["status"] not in ("pending", "approved"):
        raise HTTPException(400, f"This request is already {lv['status']}")
    await db.leaves.update_one({"_id": lv["_id"]}, {"$set": {
        "status": data.status, "remarks": data.remarks,
        "decided_by": admin["_id"], "decided_at": now_utc()}})
    return (await _attach([await db.leaves.find_one({"_id": lv["_id"]})]))[0]
