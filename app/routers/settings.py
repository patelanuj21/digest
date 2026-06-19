import logging
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.crypto import encrypt
from app.database import get_db
from app.models import AppSettings

logger = logging.getLogger(__name__)
router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


async def load_settings(db: AsyncSession) -> AppSettings | None:
    result = await db.execute(select(AppSettings).where(AppSettings.id == 1))
    return result.scalar_one_or_none()


def masked_settings(row: AppSettings | None) -> dict[str, Any]:
    if row is None:
        return {
            "base_url": None,
            "linear_client_id": None,
            "linear_client_secret_configured": False,
            "slack_client_id": None,
            "slack_client_secret_configured": False,
        }
    return {
        "base_url": row.base_url,
        "linear_client_id": row.linear_client_id,
        "linear_client_secret_configured": bool(row.linear_client_secret_enc),
        "slack_client_id": row.slack_client_id,
        "slack_client_secret_configured": bool(row.slack_client_secret_enc),
    }


@router.get("/settings", response_class=HTMLResponse, include_in_schema=False)
async def settings_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    row = await load_settings(db)
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "active_page": "settings",
            "settings": masked_settings(row),
            "errors": {},
            "flash_success": request.query_params.get("flash"),
        },
    )


class SettingsPayload(BaseModel):
    base_url: str | None = None
    linear_client_id: str | None = None
    linear_client_secret: str | None = None
    slack_client_id: str | None = None
    slack_client_secret: str | None = None


@router.post("/api/settings")
async def save_settings(
    payload: SettingsPayload,
    db: AsyncSession = Depends(get_db),
):
    # Validate base_url
    base_url = (payload.base_url or "").strip().rstrip("/")
    if base_url:
        is_localhost = "localhost" in base_url or "127.0.0.1" in base_url
        if not (base_url.startswith("https://") or (is_localhost and base_url.startswith("http://"))):
            return JSONResponse({"error": "Base URL must start with https:// (or http:// for localhost)"}, status_code=400)

    fernet_key = get_settings().fernet_key
    row = await load_settings(db)

    if row is None:
        row = AppSettings(id=1)
        db.add(row)

    row.base_url = base_url or None
    row.linear_client_id = (payload.linear_client_id or "").strip() or None

    if payload.linear_client_secret:
        row.linear_client_secret_enc = encrypt(payload.linear_client_secret, fernet_key)

    row.slack_client_id = (payload.slack_client_id or "").strip() or None

    if payload.slack_client_secret:
        row.slack_client_secret_enc = encrypt(payload.slack_client_secret, fernet_key)

    await db.commit()
    logger.info("Settings saved")
    return {"success": True}


@router.get("/api/settings")
async def get_settings_api(db: AsyncSession = Depends(get_db)):
    row = await load_settings(db)
    return masked_settings(row)
