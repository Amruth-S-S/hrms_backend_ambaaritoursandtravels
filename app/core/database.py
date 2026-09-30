from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorGridFSBucket

from app.core.config import settings


class _State:
    client = None
    db = None
    fs = None


state = _State()


async def connect() -> None:
    state.client = AsyncIOMotorClient(
        settings.MONGODB_URI, tz_aware=True, serverSelectionTimeoutMS=15000
    )
    state.db = state.client[settings.MONGODB_DB]
    state.fs = AsyncIOMotorGridFSBucket(state.db, bucket_name="selfies")
    await state.client.admin.command("ping")
    await _create_indexes()


async def close() -> None:
    if state.client:
        state.client.close()


def get_db():
    return state.db


def get_fs():
    return state.fs


async def _create_indexes() -> None:
    db = state.db
    await db.users.create_index("email", unique=True)
    await db.users.create_index("employee_code", unique=True, sparse=True)
    await db.attendance.create_index([("user_id", 1), ("date", 1)], unique=True)
    await db.attendance.create_index("date")
    await db.sessions.create_index([("user_id", 1), ("login_at", -1)])
    await db.sessions.create_index("date")
    await db.leaves.create_index([("user_id", 1), ("start_date", 1)])
    await db.leaves.create_index("status")
    await db.holidays.create_index("date", unique=True)
    await db.payroll.create_index([("user_id", 1), ("month", 1)], unique=True)
    await db.departments.create_index("name", unique=True)
