import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Connection

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _workspace_name(conn: Connection | None) -> str | None:
    if not conn:
        return None
    try:
        return json.loads(conn.metadata_json or "{}").get("workspace_name")
    except Exception:
        return None


def _connected_at(conn: Connection | None) -> str | None:
    if not conn:
        return None
    return conn.created_at.strftime("%Y-%m-%d")


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def dashboard(request: Request, db: AsyncSession = Depends(get_db)):
    linear_conn = (await db.execute(
        select(Connection).where(Connection.provider == "linear", Connection.is_active)
    )).scalar_one_or_none()

    slack_conn = (await db.execute(
        select(Connection).where(Connection.provider == "slack", Connection.is_active)
    )).scalar_one_or_none()

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "active_page": "dashboard",
            "linear_connected": linear_conn is not None,
            "linear_name": _workspace_name(linear_conn),
            "linear_connected_at": _connected_at(linear_conn),
            "slack_connected": slack_conn is not None,
            "slack_name": _workspace_name(slack_conn),
            "slack_connected_at": _connected_at(slack_conn),
            "flash_success": request.query_params.get("flash"),
        },
    )
