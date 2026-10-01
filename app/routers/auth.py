from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import close_session, get_current_user
from app.core.security import create_access_token, hash_password, verify_password
from app.schemas import ChangePasswordIn, LoginIn, ProfileUpdateIn
from app.services.users import public_user
from app.utils import now_utc, serialize, today_str

router = APIRouter(prefix="/auth", tags=["auth"])


def _client_ip(request: Request) -> str | None:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None


@router.post("/login")
async def login(data: LoginIn, request: Request):
    db = get_db()
    user = await db.users.find_one({"email": data.email.lower().strip()})
    if not user or not verify_password(data.password, user.get("password_hash", "")):
        raise HTTPException(401, "Invalid email or password")
    if user.get("status") != "active":
        raise HTTPException(403, "Your account is inactive. Contact your administrator.")

    now = now_utc()
    # Close sessions that went idle without an explicit logout (browser closed, token lost)
    idle_cutoff = now - timedelta(minutes=settings.SESSION_IDLE_MINUTES)
    async for s in db.sessions.find({"user_id": user["_id"], "active": True,
                                     "last_seen": {"$lt": idle_cutoff}}):
        await close_session(s["_id"], "auto_closed")

    res = await db.sessions.insert_one({
        "user_id": user["_id"],
        "date": today_str(),
        "login_at": now,
        "last_seen": now,
        "logout_at": None,
        "active": True,
        "ip": _client_ip(request),
        "user_agent": (request.headers.get("user-agent") or "")[:300],
    })
    await db.users.update_one({"_id": user["_id"]}, {"$set": {"last_login_at": now}})
    token = create_access_token(str(user["_id"]), user["role"], str(res.inserted_id))
    body = await public_user(user)
    body["session"] = {"id": str(res.inserted_id), "login_at": now.isoformat()}
    return {"access_token": token, "token_type": "bearer", "user": body}


@router.post("/logout")
async def logout(reason: str = "manual", user: dict = Depends(get_current_user)):
    reason = reason if reason in ("manual", "idle") else "manual"
    now = now_utc()
    await close_session(user["_session"]["_id"], reason, at=now)
    return {"message": "Logged out", "logout_at": now.isoformat()}


@router.get("/me")
async def me(user: dict = Depends(get_current_user)):
    body = await public_user(user)
    body["session"] = {"id": str(user["_session"]["_id"]),
                       "login_at": serialize(user["_session"]["login_at"])}
    return body


@router.put("/me")
async def update_me(data: ProfileUpdateIn, user: dict = Depends(get_current_user)):
    # Employees' contact details are managed by an administrator (Employees page) and are read-only to them.
    if user.get("role") != "admin":
        raise HTTPException(403, "Contact details can only be changed by an administrator")
    updates = data.model_dump(exclude_unset=True)
    if updates:
        updates["updated_at"] = now_utc()
        await get_db().users.update_one({"_id": user["_id"]}, {"$set": updates})
    return await public_user(await get_db().users.find_one({"_id": user["_id"]}))


@router.post("/change-password")
async def change_password(data: ChangePasswordIn, user: dict = Depends(get_current_user)):
    if not verify_password(data.current_password, user["password_hash"]):
        raise HTTPException(400, "Current password is incorrect")
    await get_db().users.update_one(
        {"_id": user["_id"]},
        {"$set": {"password_hash": hash_password(data.new_password), "updated_at": now_utc()}},
    )
    return {"message": "Password changed"}
