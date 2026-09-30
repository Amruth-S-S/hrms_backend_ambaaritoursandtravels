from fastapi import APIRouter, Depends

from app.core.deps import get_current_user, require_admin
from app.schemas import SettingsIn
from app.services.company import get_company_settings, save_company_settings
from app.utils import serialize

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("")
async def read_settings(user: dict = Depends(get_current_user)):
    return serialize(await get_company_settings())


@router.put("")
async def update_settings(data: SettingsIn, admin: dict = Depends(require_admin)):
    return serialize(await save_company_settings(data.model_dump()))
