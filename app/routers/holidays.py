from fastapi import APIRouter, Depends, HTTPException
from pymongo.errors import DuplicateKeyError

from app.core.database import get_db
from app.core.deps import get_current_user, require_admin
from app.schemas import HolidayIn
from app.utils import now_utc, oid, serialize

router = APIRouter(prefix="/holidays", tags=["holidays"])


@router.get("")
async def list_holidays(year: int | None = None, user: dict = Depends(get_current_user)):
    filt = {"date": {"$gte": f"{year}-01-01", "$lte": f"{year}-12-31"}} if year else {}
    return serialize(await get_db().holidays.find(filt).sort("date", 1).to_list(500))


@router.post("", status_code=201)
async def create_holiday(data: HolidayIn, admin: dict = Depends(require_admin)):
    doc = {**data.model_dump(), "created_at": now_utc()}
    try:
        await get_db().holidays.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(409, "A holiday already exists on this date")
    return serialize(doc)


@router.put("/{holiday_id}")
async def update_holiday(holiday_id: str, data: HolidayIn, admin: dict = Depends(require_admin)):
    _id = oid(holiday_id, "holiday id")
    try:
        res = await get_db().holidays.update_one({"_id": _id}, {"$set": data.model_dump()})
    except DuplicateKeyError:
        raise HTTPException(409, "A holiday already exists on this date")
    if not res.matched_count:
        raise HTTPException(404, "Holiday not found")
    return serialize(await get_db().holidays.find_one({"_id": _id}))


@router.delete("/{holiday_id}")
async def delete_holiday(holiday_id: str, admin: dict = Depends(require_admin)):
    res = await get_db().holidays.delete_one({"_id": oid(holiday_id, "holiday id")})
    if not res.deleted_count:
        raise HTTPException(404, "Holiday not found")
    return {"message": "Holiday deleted"}
