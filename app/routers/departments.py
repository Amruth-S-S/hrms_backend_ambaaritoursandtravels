from fastapi import APIRouter, Depends, HTTPException
from pymongo.errors import DuplicateKeyError

from app.core.database import get_db
from app.core.deps import get_current_user, require_admin
from app.schemas import DepartmentIn
from app.utils import now_utc, oid, serialize

router = APIRouter(prefix="/departments", tags=["departments"])


@router.get("")
async def list_departments(user: dict = Depends(get_current_user)):
    db = get_db()
    counts = {r["_id"]: r["n"] async for r in db.users.aggregate(
        [{"$match": {"department_id": {"$ne": None}}},
         {"$group": {"_id": "$department_id", "n": {"$sum": 1}}}])}
    depts = await db.departments.find().sort("name", 1).to_list(500)
    out = serialize(depts)
    for d, raw in zip(out, depts):
        d["employee_count"] = counts.get(raw["_id"], 0)
    return out


@router.post("", status_code=201)
async def create_department(data: DepartmentIn, admin: dict = Depends(require_admin)):
    doc = {**data.model_dump(), "name": data.name.strip(), "created_at": now_utc()}
    try:
        await get_db().departments.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(409, "A department with this name already exists")
    return serialize(doc)


@router.put("/{dept_id}")
async def update_department(dept_id: str, data: DepartmentIn, admin: dict = Depends(require_admin)):
    _id = oid(dept_id, "department id")
    try:
        res = await get_db().departments.update_one(
            {"_id": _id}, {"$set": {**data.model_dump(), "name": data.name.strip()}})
    except DuplicateKeyError:
        raise HTTPException(409, "A department with this name already exists")
    if not res.matched_count:
        raise HTTPException(404, "Department not found")
    return serialize(await get_db().departments.find_one({"_id": _id}))


@router.delete("/{dept_id}")
async def delete_department(dept_id: str, admin: dict = Depends(require_admin)):
    db = get_db()
    _id = oid(dept_id, "department id")
    res = await db.departments.delete_one({"_id": _id})
    if not res.deleted_count:
        raise HTTPException(404, "Department not found")
    await db.users.update_many({"department_id": _id}, {"$set": {"department_id": None}})
    return {"message": "Department deleted"}
