from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from gridfs.errors import NoFile

from app.core.database import get_fs
from app.core.deps import get_current_user_flexible

router = APIRouter(prefix="/files", tags=["files"])


@router.get("/{file_id}")
async def get_file(file_id: str, user: dict = Depends(get_current_user_flexible)):
    if not ObjectId.is_valid(file_id):
        raise HTTPException(404, "File not found")
    try:
        stream = await get_fs().open_download_stream(ObjectId(file_id))
    except NoFile:
        raise HTTPException(404, "File not found")
    meta = stream.metadata or {}
    if user["role"] != "admin" and meta.get("user_id") != str(user["_id"]):
        raise HTTPException(403, "You cannot view this file")
    data = await stream.read()
    return Response(content=data, media_type=meta.get("content_type", "image/jpeg"),
                    headers={"Cache-Control": "private, max-age=86400"})
