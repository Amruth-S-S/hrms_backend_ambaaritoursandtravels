import re

from fastapi import APIRouter, Depends, HTTPException
from pymongo.errors import DuplicateKeyError

from app.core.database import get_db
from app.core.deps import close_session, require_admin
from app.core.security import hash_password
from app.schemas import UserCreate, UserUpdate
from app.services.company import next_employee_code
from app.services.users import public_user, public_users
from app.utils import now_utc, oid

router = APIRouter(prefix="/users", tags=["users"])


async def _check_department(dept_id):
    if dept_id is None:
        return None
    _id = oid(dept_id, "department")
    if not await get_db().departments.find_one({"_id": _id}):
        raise HTTPException(400, "Department not found")
    return _id


@router.get("")
async def list_users(q: str | None = None, department_id: str | None = None,
                     status: str | None = None, role: str | None = None,
                     admin: dict = Depends(require_admin)):
    filt: dict = {}
    if q:
        rx = {"$regex": re.escape(q.strip()), "$options": "i"}
        filt["$or"] = [{"name": rx}, {"email": rx}, {"employee_code": rx}, {"designation": rx}]
    if department_id:
        filt["department_id"] = oid(department_id, "department")
    if status in ("active", "inactive"):
        filt["status"] = status
    if role in ("admin", "employee"):
        filt["role"] = role
    users = await get_db().users.find(filt).sort("created_at", -1).to_list(2000)
    return await public_users(users)


@router.post("", status_code=201)
async def create_user(data: UserCreate, admin: dict = Depends(require_admin)):
    db = get_db()
    email = data.email.lower().strip()
    if await db.users.find_one({"email": email}):
        raise HTTPException(409, "A user with this email already exists")
    code = (data.employee_code or "").strip().upper() or await next_employee_code()
    if await db.users.find_one({"employee_code": code}):
        raise HTTPException(409, f"Employee code {code} is already in use")

    doc = data.model_dump(exclude={"password", "email", "employee_code"})
    doc.update({
        "email": email,
        "employee_code": code,
        "department_id": await _check_department(data.department_id),
        "password_hash": hash_password(data.password),
        "created_at": now_utc(),
        "created_by": admin["_id"],
    })
    try:
        await db.users.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(409, "Email or employee code already exists")
    return await public_user(doc)


@router.get("/{user_id}")
async def get_user(user_id: str, admin: dict = Depends(require_admin)):
    user = await get_db().users.find_one({"_id": oid(user_id, "user id")})
    if not user:
        raise HTTPException(404, "User not found")
    return await public_user(user)


@router.put("/{user_id}")
async def update_user(user_id: str, data: UserUpdate, admin: dict = Depends(require_admin)):
    db = get_db()
    _id = oid(user_id, "user id")
    user = await db.users.find_one({"_id": _id})
    if not user:
        raise HTTPException(404, "User not found")

    updates = data.model_dump(exclude_unset=True)
    if _id == admin["_id"]:
        if updates.get("status") == "inactive":
            raise HTTPException(400, "You cannot deactivate your own account")
        if updates.get("role") == "employee":
            raise HTTPException(400, "You cannot remove your own admin role")

    if "email" in updates and updates["email"]:
        updates["email"] = updates["email"].lower().strip()
        if await db.users.find_one({"email": updates["email"], "_id": {"$ne": _id}}):
            raise HTTPException(409, "A user with this email already exists")
    if updates.get("employee_code"):
        updates["employee_code"] = updates["employee_code"].strip().upper()
        if await db.users.find_one({"employee_code": updates["employee_code"], "_id": {"$ne": _id}}):
            raise HTTPException(409, "Employee code already in use")
    elif "employee_code" in updates:
        updates.pop("employee_code")  # never blank out an existing code
    if "department_id" in updates:
        updates["department_id"] = await _check_department(updates["department_id"])
    password = updates.pop("password", None)
    if password:
        updates["password_hash"] = hash_password(password)
    for key in ("name", "email", "role", "status", "salary"):
        if key in updates and updates[key] is None:
            updates.pop(key)

    updates["updated_at"] = now_utc()
    await db.users.update_one({"_id": _id}, {"$set": updates})

    # Deactivated or password reset -> end their open sessions
    # (but never the session making this request, e.g. an admin changing their own password)
    if updates.get("status") == "inactive" or password:
        async for s in db.sessions.find({"user_id": _id, "active": True,
                                         "_id": {"$ne": admin["_session"]["_id"]}}):
            await close_session(s["_id"], "ended_by_admin", at=now_utc())
    return await public_user(await db.users.find_one({"_id": _id}))


@router.delete("/{user_id}")
async def delete_user(user_id: str, admin: dict = Depends(require_admin)):
    db = get_db()
    _id = oid(user_id, "user id")
    if _id == admin["_id"]:
        raise HTTPException(400, "You cannot delete your own account")
    res = await db.users.delete_one({"_id": _id})
    if not res.deleted_count:
        raise HTTPException(404, "User not found")
    await db.sessions.update_many({"user_id": _id, "active": True},
                                  {"$set": {"active": False, "logout_at": now_utc(),
                                            "logout_reason": "ended_by_admin"}})
    return {"message": "User deleted"}
