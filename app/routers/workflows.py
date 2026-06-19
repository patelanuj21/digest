import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.services.digest import (
    ConnectionNotFoundError,
    DigestParams,
    UntriagedDefinition,
    run_linear_slack_digest,
)
from app.services.linear_client import (
    InvalidTeamKeyError,
    LinearAPIError,
    LinearRateLimitError,
)
from app.services.slack_client import SlackAPIError

logger = logging.getLogger(__name__)
router = APIRouter()


class UntriagedDefinitionBody(BaseModel):
    include_unassigned: bool = True
    include_no_priority: bool = True
    state_names: list[str] = ["Triage", "Backlog"]


class WorkflowRequest(BaseModel):
    team_key: str
    slack_channel: str
    limit: int = 20
    include_untriaged: bool = True
    include_assignment_summary: bool = True
    untriaged_definition: UntriagedDefinitionBody = UntriagedDefinitionBody()


def _error_response(error_type: str, message: str, http_status: int) -> JSONResponse:
    return JSONResponse(
        status_code=http_status,
        content={
            "status": "failed",
            "error": {"type": error_type, "message": message},
        },
    )


@router.post("/api/workflows/linear-slack-digest")
async def trigger_workflow(
    body: WorkflowRequest,
    db: AsyncSession = Depends(get_db),
):
    started_at = datetime.now(timezone.utc)
    fernet_key = get_settings().fernet_key

    params = DigestParams(
        team_key=body.team_key,
        slack_channel=body.slack_channel,
        limit=body.limit,
        include_untriaged=body.include_untriaged,
        include_assignment_summary=body.include_assignment_summary,
        untriaged_definition=UntriagedDefinition(
            include_unassigned=body.untriaged_definition.include_unassigned,
            include_no_priority=body.untriaged_definition.include_no_priority,
            state_names=body.untriaged_definition.state_names,
        ),
    )

    try:
        result = await run_linear_slack_digest(params, db, fernet_key)
    except ConnectionNotFoundError as exc:
        msg = f"No active {exc.provider} connection. Connect {exc.provider.capitalize()} in the dashboard."
        return _error_response("connection_not_found", msg, 400)
    except InvalidTeamKeyError as exc:
        return _error_response("invalid_team_key", str(exc), 400)
    except LinearRateLimitError as exc:
        retry = f" Retry after {exc.retry_after} seconds." if exc.retry_after else ""
        return _error_response("linear_rate_limit", f"Linear rate limit hit.{retry}", 502)
    except LinearAPIError as exc:
        error_type = "linear_auth_error" if (exc.status_code or 0) == 401 else "linear_api_error"
        return _error_response(error_type, str(exc), 502)
    except SlackAPIError as exc:
        return _error_response("slack_api_error", str(exc), 502)
    except Exception as exc:
        logger.exception("Unexpected error in workflow: %s", type(exc).__name__)
        return _error_response("internal_error", "An unexpected error occurred", 500)

    return {
        "status": "success",
        "team_key": result.team_key,
        "slack_channel": result.slack_channel,
        "issues_pulled": result.issues_pulled,
        "untriaged_count": result.untriaged_count,
        "assignment_summary": result.assignment_summary,
        "slack_posted": result.slack_posted,
        "message_ts": result.message_ts,
        "started_at": started_at.isoformat(),
        "completed_at": result.completed_at.isoformat(),
    }
