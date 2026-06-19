import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import AppSettings, Connection

logger = logging.getLogger(__name__)
router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

PROVIDERS = {"linear", "slack"}


@router.get("/connect/{provider}", response_class=HTMLResponse, include_in_schema=False)
async def connect_page(provider: str, request: Request, db: AsyncSession = Depends(get_db)):
    if provider not in PROVIDERS:
        return RedirectResponse("/", status_code=302)

    conn_result = await db.execute(
        select(Connection).where(Connection.provider == provider, Connection.is_active)
    )
    connection = conn_result.scalar_one_or_none()

    settings_result = await db.execute(select(AppSettings).where(AppSettings.id == 1))
    settings_row = settings_result.scalar_one_or_none()
    configured = False
    if settings_row:
        if provider == "linear":
            configured = bool(settings_row.linear_client_id and settings_row.linear_client_secret_enc and settings_row.base_url)
        else:
            configured = bool(settings_row.slack_client_id and settings_row.slack_client_secret_enc and settings_row.base_url)

    return templates.TemplateResponse(
        request,
        "connect.html",
        {
            "active_page": "dashboard",
            "provider": provider,
            "provider_label": provider.capitalize(),
            "connection": connection,
            "configured": configured,
            "flash_success": request.query_params.get("flash"),
        },
    )


@router.get("/api/connections/{provider}")
async def get_connection(provider: str, db: AsyncSession = Depends(get_db)):
    if provider not in PROVIDERS:
        return {"error": "Unknown provider"}, 400
    result = await db.execute(
        select(Connection).where(Connection.provider == provider, Connection.is_active)
    )
    conn = result.scalar_one_or_none()
    if not conn:
        return {"provider": provider, "connected": False}
    return {
        "provider": provider,
        "connected": True,
        "display_name": conn.display_name,
        "connected_at": conn.created_at.isoformat(),
    }


@router.post("/api/connections/{provider}/disconnect", include_in_schema=False)
async def disconnect(provider: str, request: Request, db: AsyncSession = Depends(get_db)):
    """HTML form disconnect — deactivates and redirects to dashboard."""
    if provider not in PROVIDERS:
        return RedirectResponse("/", status_code=302)
    result = await db.execute(
        select(Connection).where(Connection.provider == provider, Connection.is_active)
    )
    conn = result.scalar_one_or_none()
    if conn:
        conn.is_active = False
        await db.commit()
        logger.info("Disconnected %s", provider)
    return RedirectResponse(f"/?flash={provider.capitalize()}+disconnected", status_code=302)


@router.delete("/api/connections/{provider}")
async def disconnect_api(provider: str, db: AsyncSession = Depends(get_db)):
    """JSON API disconnect — for external callers."""
    if provider not in PROVIDERS:
        return {"error": "Unknown provider"}
    result = await db.execute(
        select(Connection).where(Connection.provider == provider, Connection.is_active)
    )
    conn = result.scalar_one_or_none()
    if conn:
        conn.is_active = False
        await db.commit()
    return {"success": True}
