from fastapi import APIRouter, Depends, HTTPException

from app.core.database import get_db
from app.core.deps import get_current_user, require_admin
from app.schemas import PayrollGenerateIn, PayrollUpdateIn
from app.services.calendar import month_summary
from app.services.company import get_company_settings
from app.services.late_fine import fine_per_block, late_deduction
from app.services.users import department_map, employee_brief, user_map
from app.utils import now_utc, oid, serialize

router = APIRouter(prefix="/payroll", tags=["payroll"])


def _net(p: dict) -> float:
    return round(p["gross"] - p["lop_deduction"] - p.get("late_deduction", 0)
                 - p.get("other_deductions", 0) + p.get("bonus", 0), 2)


async def _attach(slips: list[dict]) -> list[dict]:
    users = await user_map(p["user_id"] for p in slips)
    out = []
    for p in slips:
        d = serialize(p)
        d["employee"] = employee_brief(users.get(p["user_id"]))
        out.append(d)
    return out


@router.post("/generate")
async def generate(data: PayrollGenerateIn, admin: dict = Depends(require_admin)):
    db = get_db()
    company = await get_company_settings()
    depts = await department_map()
    users = await db.users.find({"role": "employee", "status": "active"}).to_list(None)
    generated = skipped = 0
    for u in users:
        existing = await db.payroll.find_one({"user_id": u["_id"], "month": data.month})
        if existing and existing.get("status") == "paid":
            skipped += 1
            continue
        s = await month_summary(u, data.month, company)
        gross = float(u.get("salary") or 0)
        wd = s["working_days"] or 1
        per_day = gross / wd
        lop_days = s["absent"] + 0.5 * s["half_day"] + s["unpaid_leave"]
        payable_days = max(0.0, s["working_days"] - lop_days)
        slip = {
            "user_id": u["_id"], "month": data.month,
            "employee_code": u.get("employee_code"), "name": u.get("name"),
            "designation": u.get("designation"), "department": depts.get(u.get("department_id")),
            "bank_account": u.get("bank_account"), "pan": u.get("pan"),
            "gross": round(gross, 2),
            "earnings": {"basic": round(gross * 0.5, 2), "hra": round(gross * 0.2, 2),
                         "special_allowance": round(gross * 0.3, 2)},
            "working_days": s["working_days"], "present_days": s["present"],
            "half_days": s["half_day"], "paid_leave_days": s["paid_leave"],
            "absent_days": s["absent"], "unpaid_leave_days": s["unpaid_leave"],
            "payable_days": payable_days, "lop_days": lop_days,
            "lop_deduction": round(per_day * lop_days, 2),
            "late_count": s["late"], "late_minutes": s["late_minutes"],
            "late_fine_per_5_min": fine_per_block(gross) if gross else 0,
            "late_deduction": round(late_deduction(gross, s["late_blocks"]), 2),
            "bonus": (existing or {}).get("bonus", 0),
            "other_deductions": (existing or {}).get("other_deductions", 0),
            "remarks": (existing or {}).get("remarks"),
            "status": "draft", "generated_at": now_utc(),
        }
        slip["net_pay"] = _net(slip)
        await db.payroll.update_one({"user_id": u["_id"], "month": data.month},
                                    {"$set": slip}, upsert=True)
        generated += 1
    return {"message": f"Generated {generated} payslip(s)" + (f", {skipped} already paid" if skipped else ""),
            "generated": generated, "skipped": skipped}


@router.get("")
async def list_payroll(month: str, admin: dict = Depends(require_admin)):
    slips = await get_db().payroll.find({"month": month}).sort("name", 1).to_list(None)
    return await _attach(slips)


@router.get("/me")
async def my_payslips(user: dict = Depends(get_current_user)):
    slips = await get_db().payroll.find({"user_id": user["_id"]}).sort("month", -1).to_list(120)
    return serialize(slips)


@router.put("/{slip_id}")
async def update_slip(slip_id: str, data: PayrollUpdateIn, admin: dict = Depends(require_admin)):
    db = get_db()
    slip = await db.payroll.find_one({"_id": oid(slip_id, "payslip id")})
    if not slip:
        raise HTTPException(404, "Payslip not found")
    updates = {k: v for k, v in data.model_dump(exclude_unset=True).items() if v is not None or k == "remarks"}
    slip.update(updates)
    updates["net_pay"] = _net(slip)
    if updates.get("status") == "paid":
        updates["paid_at"] = now_utc()
    await db.payroll.update_one({"_id": slip["_id"]}, {"$set": updates})
    return (await _attach([await db.payroll.find_one({"_id": slip["_id"]})]))[0]


@router.delete("/{slip_id}")
async def delete_slip(slip_id: str, admin: dict = Depends(require_admin)):
    res = await get_db().payroll.delete_one({"_id": oid(slip_id, "payslip id")})
    if not res.deleted_count:
        raise HTTPException(404, "Payslip not found")
    return {"message": "Payslip deleted"}
