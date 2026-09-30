from bson import ObjectId

from app.core.database import get_db
from app.utils import serialize


async def department_map() -> dict:
    return {d["_id"]: d["name"] async for d in get_db().departments.find({}, {"name": 1})}


async def user_map(ids) -> dict:
    ids = list({i for i in ids if isinstance(i, ObjectId)})
    if not ids:
        return {}
    cur = get_db().users.find({"_id": {"$in": ids}},
                              {"name": 1, "email": 1, "employee_code": 1, "designation": 1, "department_id": 1})
    return {u["_id"]: u async for u in cur}


async def public_users(users: list[dict]) -> list[dict]:
    depts = await department_map()
    out = []
    for u in users:
        d = serialize(u)
        d["department_name"] = depts.get(u.get("department_id"))
        out.append(d)
    return out


async def public_user(user: dict) -> dict:
    return (await public_users([user]))[0]


def employee_brief(u: dict | None) -> dict:
    if not u:
        return {"name": "Deleted user", "employee_code": None, "email": None}
    return {"name": u.get("name"), "employee_code": u.get("employee_code"),
            "email": u.get("email"), "designation": u.get("designation")}
