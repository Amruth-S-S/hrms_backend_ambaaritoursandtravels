from fastapi import APIRouter, Depends, HTTPException

from app.core.database import get_db
from app.core.deps import close_session, get_current_user, require_admin
from app.services.users import employee_brief, user_map
from app.utils import now_utc, oid, serialize, validate_date

router = APIRouter(prefix="/sessions", tags=["login sessions"])


def _clean(s: dict) -> dict:
    return serialize(s)


@router.get("/me")
async def my_sessions(limit: int = 30, user: dict = Depends(get_current_user)):
    docs = await get_db().sessions.find({"user_id": user["_id"]}).sort("login_at", -1).to_list(min(limit, 200))
    return [_clean(s) for s in docs]


@router.get("")
async def all_sessions(user_id: str | None = None, from_date: str | None = None,
                       to_date: str | None = None, active: bool | None = None,
                       admin: dict = Depends(require_admin)):
    filt: dict = {}
    if user_id:
        filt["user_id"] = oid(user_id, "user id")
    if from_date or to_date:
        filt["date"] = {}
        if from_date:
            filt["date"]["$gte"] = validate_date(from_date, "from_date")
        if to_date:
            filt["date"]["$lte"] = validate_date(to_date, "to_date")
    if active is not None:
        filt["active"] = active
    docs = await get_db().sessions.find(filt).sort("login_at", -1).to_list(1000)
    users = await user_map(s["user_id"] for s in docs)
    out = []
    for s in docs:
        d = _clean(s)
        d["employee"] = employee_brief(users.get(s["user_id"]))
        out.append(d)
    return out


@router.post("/{session_id}/end")
async def end_session(session_id: str, admin: dict = Depends(require_admin)):
    _id = oid(session_id, "session id")
    if _id == admin["_session"]["_id"]:
        raise HTTPException(400, "Use Log out to end your own session")
    s = await get_db().sessions.find_one({"_id": _id})
    if not s:
        raise HTTPException(404, "Session not found")
    await close_session(_id, "ended_by_admin", at=now_utc())
    return {"message": "Session ended"}
