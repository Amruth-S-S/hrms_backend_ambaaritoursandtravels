from fastapi import APIRouter, Depends, HTTPException

from app.core.database import get_db
from app.core.deps import get_current_user, require_admin
from app.schemas import AnnouncementIn
from app.utils import now_utc, oid, serialize

router = APIRouter(prefix="/announcements", tags=["announcements"])


@router.get("")
async def list_announcements(limit: int = 50, user: dict = Depends(get_current_user)):
    limit = max(1, min(limit, 200))
    docs = await get_db().announcements.find().sort("created_at", -1).to_list(limit)
    return serialize(docs)


@router.post("", status_code=201)
async def create_announcement(data: AnnouncementIn, admin: dict = Depends(require_admin)):
    doc = {**data.model_dump(), "created_at": now_utc(), "author": admin["name"]}
    await get_db().announcements.insert_one(doc)
    return serialize(doc)


@router.delete("/{ann_id}")
async def delete_announcement(ann_id: str, admin: dict = Depends(require_admin)):
    res = await get_db().announcements.delete_one({"_id": oid(ann_id, "announcement id")})
    if not res.deleted_count:
        raise HTTPException(404, "Announcement not found")
    return {"message": "Announcement deleted"}
