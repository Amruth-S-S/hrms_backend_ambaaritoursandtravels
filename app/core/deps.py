import jwt
from bson import ObjectId
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.database import get_db
from app.core.security import decode_token
from app.utils import minutes_between, now_utc

bearer = HTTPBearer(auto_error=False)


def _unauthorized(msg: str = "Not authenticated"):
    return HTTPException(status.HTTP_401_UNAUTHORIZED, msg, headers={"WWW-Authenticate": "Bearer"})


async def close_session(session_id, reason: str, at=None):
    """Mark a session as ended. If `at` is None, use its last activity time."""
    db = get_db()
    if isinstance(session_id, str):
        if not ObjectId.is_valid(session_id):
            return
        session_id = ObjectId(session_id)
    s = await db.sessions.find_one({"_id": session_id, "active": True})
    if not s:
        return
    end = at or s.get("last_seen") or s["login_at"]
    await db.sessions.update_one(
        {"_id": s["_id"]},
        {"$set": {"active": False, "logout_at": end, "logout_reason": reason,
                  "duration_minutes": minutes_between(s["login_at"], end)}},
    )


async def _resolve_user(token):
    if not token:
        raise _unauthorized()
    try:
        payload = decode_token(token)
    except jwt.ExpiredSignatureError:
        try:
            await close_session(decode_token(token, verify_exp=False).get("sid", ""), "expired")
        except jwt.PyJWTError:
            pass
        raise _unauthorized("Session expired. Please log in again.")
    except jwt.PyJWTError:
        raise _unauthorized("Invalid token")

    db = get_db()
    sid, sub = payload.get("sid", ""), payload.get("sub", "")
    if not ObjectId.is_valid(sid) or not ObjectId.is_valid(sub):
        raise _unauthorized("Invalid token")

    session = await db.sessions.find_one({"_id": ObjectId(sid)})
    if not session or not session.get("active"):
        raise _unauthorized("Your session has ended. Please log in again.")

    user = await db.users.find_one({"_id": ObjectId(sub)})
    if not user or user.get("status") != "active":
        raise _unauthorized("Account not found or inactive")

    now = now_utc()
    last_seen = session.get("last_seen") or session["login_at"]
    if (now - last_seen).total_seconds() > 60:
        await db.sessions.update_one({"_id": session["_id"]}, {"$set": {"last_seen": now}})

    user["_session"] = session
    return user


async def get_current_user(creds: HTTPAuthorizationCredentials | None = Depends(bearer)) -> dict:
    return await _resolve_user(creds.credentials if creds else None)


async def get_current_user_flexible(
    request: Request, creds: HTTPAuthorizationCredentials | None = Depends(bearer)
) -> dict:
    """Accepts a bearer header or ?token= (used for <img src> selfie URLs)."""
    token = creds.credentials if creds else request.query_params.get("token")
    return await _resolve_user(token)


async def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin access required")
    return user
