from datetime import timedelta

import bcrypt
import jwt

from app.core.config import settings
from app.utils import now_utc


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def create_access_token(user_id: str, role: str, session_id: str) -> str:
    payload = {
        "sub": user_id,
        "role": role,
        "sid": session_id,
        "exp": now_utc() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str, verify_exp: bool = True) -> dict:
    return jwt.decode(
        token,
        settings.JWT_SECRET,
        algorithms=[settings.JWT_ALGORITHM],
        options={"verify_exp": verify_exp},
    )
