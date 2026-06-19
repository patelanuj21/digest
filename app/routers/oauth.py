import json
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.connectors.base import OAuthConfig
from app.connectors.linear import LinearConnector
from app.connectors.slack import SlackConnector
from app.crypto import encrypt
from app.database import get_db
from app.models import AppSettings, Connection, OAuthState
from app.pkce import generate_code_challenge, generate_code_verifier

logger = logging.getLogger(__name__)
router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

PROVIDERS = {"linear", "slack"}


async def _load_app_settings(db: AsyncSession) -> AppSettings | None:
    result = await db.execute(select(AppSettings).where(AppSettings.id == 1))
    return result.scalar_one_or_none()


def _build_connector(provider: str, settings_row: AppSettings, fernet_key: bytes):
    from app.crypto import decrypt
    if provider == "linear":
        secret = decrypt(settings_row.linear_client_secret_enc, fernet_key)
        config = OAuthConfig(
            client_id=settings_row.linear_client_id,
            client_secret=secret,
            base_url=settings_row.base_url,
        )
        return LinearConnector(config)
    else:
        secret = decrypt(settings_row.slack_client_secret_enc, fernet_key)
        config = OAuthConfig(
            client_id=settings_row.slack_client_id,
            client_secret=secret,
            base_url=settings_row.base_url,
        )
        return SlackConnector(config)


def _provider_configured(provider: str, row: AppSettings) -> bool:
    if provider == "linear":
        return bool(row.linear_client_id and row.linear_client_secret_enc and row.base_url)
    return bool(row.slack_client_id and row.slack_client_secret_enc and row.base_url)


@router.get("/oauth/{provider}/authorize", include_in_schema=False)
async def oauth_authorize(provider: str, request: Request, db: AsyncSession = Depends(get_db)):
    if provider not in PROVIDERS:
        return RedirectResponse("/?flash=Unknown+provider", status_code=302)

    settings_row = await _load_app_settings(db)
    if not settings_row or not _provider_configured(provider, settings_row):
        return RedirectResponse(
            f"/settings?flash=Configure+{provider.capitalize()}+credentials+before+connecting",
            status_code=302,
        )

    state = secrets.token_urlsafe(32)
    code_verifier = generate_code_verifier()
    code_challenge = generate_code_challenge(code_verifier)

    oauth_state = OAuthState(
        id=str(uuid.uuid4()),
        state=state,
        provider=provider,
        code_verifier=code_verifier,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
    )
    db.add(oauth_state)
    await db.commit()

    connector = _build_connector(provider, settings_row, get_settings().fernet_key)
    authorize_url = connector.get_authorize_url(state, code_challenge)
    return RedirectResponse(authorize_url, status_code=302)


@router.get("/oauth/{provider}/callback", include_in_schema=False)
async def oauth_callback(provider: str, request: Request, db: AsyncSession = Depends(get_db)):
    if provider not in PROVIDERS:
        return RedirectResponse("/?flash=Unknown+provider", status_code=302)

    # Surface provider errors immediately
    error = request.query_params.get("error")
    if error:
        desc = request.query_params.get("error_description", error)
        logger.warning("OAuth provider error for %s: %s", provider, error)
        return templates.TemplateResponse(
            request, "oauth_error.html",
            {"provider": provider, "error": desc},
            status_code=400,
        )

    code = request.query_params.get("code")
    state = request.query_params.get("state")
    if not code or not state:
        return templates.TemplateResponse(
            request, "oauth_error.html",
            {"provider": provider, "error": "Missing code or state parameter."},
            status_code=400,
        )

    # Verify state — CSRF protection
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(OAuthState).where(OAuthState.state == state, OAuthState.provider == provider)
    )
    oauth_state = result.scalar_one_or_none()

    if not oauth_state:
        return templates.TemplateResponse(
            request, "oauth_error.html",
            {"provider": provider, "error": "OAuth state not found. The link may have expired — please try connecting again."},
            status_code=400,
        )

    if oauth_state.expires_at.replace(tzinfo=timezone.utc) < now:
        await db.delete(oauth_state)
        await db.commit()
        return templates.TemplateResponse(
            request, "oauth_error.html",
            {"provider": provider, "error": "OAuth session expired (10-minute limit). Please try connecting again."},
            status_code=400,
        )

    # Capture verifier before deleting — single use
    code_verifier = oauth_state.code_verifier
    await db.delete(oauth_state)
    await db.commit()

    # Exchange code for tokens
    settings_row = await _load_app_settings(db)
    fernet_key = get_settings().fernet_key
    connector = _build_connector(provider, settings_row, fernet_key)

    try:
        token_data = await connector.exchange_code(code, code_verifier)
    except Exception as exc:
        logger.error("Token exchange failed for %s: %s", provider, type(exc).__name__)
        return templates.TemplateResponse(
            request, "oauth_error.html",
            {"provider": provider, "error": f"Token exchange failed: {exc}"},
            status_code=400,
        )

    # Fetch workspace metadata
    workspace_info = {}
    try:
        if provider == "linear":
            workspace_info = await connector.get_workspace_info(token_data.access_token)
        else:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    "https://slack.com/api/auth.test",
                    headers={"Authorization": f"Bearer {token_data.access_token}"},
                )
            if resp.status_code == 200 and resp.json().get("ok"):
                d = resp.json()
                workspace_info = {
                    "workspace_name": d.get("team"),
                    "workspace_id": d.get("team_id"),
                    "authed_user_id": d.get("user_id"),
                }
    except Exception:
        pass  # workspace info is cosmetic — don't fail the connection over it

    workspace_name = workspace_info.get("workspace_name", provider.capitalize())
    display_name = f"{provider.capitalize()} ({workspace_name})"

    # Build encrypted credentials blob
    creds = {
        "access_token": token_data.access_token,
        "refresh_token": token_data.refresh_token,
        "token_type": token_data.token_type,
        "scope": token_data.scope,
    }
    credentials_enc = encrypt(json.dumps(creds), fernet_key)

    # Deactivate existing active connections for this provider
    existing = await db.execute(
        select(Connection).where(Connection.provider == provider, Connection.is_active)
    )
    for conn in existing.scalars().all():
        conn.is_active = False

    # Insert new active connection
    new_conn = Connection(
        id=str(uuid.uuid4()),
        provider=provider,
        display_name=display_name,
        credentials_enc=credentials_enc,
        metadata_json=json.dumps(workspace_info),
        is_active=True,
    )
    db.add(new_conn)
    await db.commit()

    logger.info("Connected %s workspace=%s", provider, workspace_name)
    return RedirectResponse(f"/?flash={provider.capitalize()}+connected+successfully", status_code=302)
