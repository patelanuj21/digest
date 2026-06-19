import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crypto import decrypt
from app.models import Connection
from app.services.linear_client import LinearIssue, fetch_issues
from app.services.slack_client import post_message

logger = logging.getLogger(__name__)


class ConnectionNotFoundError(Exception):
    def __init__(self, provider: str):
        self.provider = provider
        super().__init__(f"No active {provider} connection")


@dataclass
class UntriagedDefinition:
    include_unassigned: bool = True
    include_no_priority: bool = True
    state_names: list[str] = field(default_factory=lambda: ["Triage", "Backlog"])


@dataclass
class DigestParams:
    team_key: str
    slack_channel: str
    limit: int = 20
    include_untriaged: bool = True
    include_assignment_summary: bool = True
    untriaged_definition: UntriagedDefinition = field(default_factory=UntriagedDefinition)


@dataclass
class DigestResult:
    team_key: str
    slack_channel: str
    issues_pulled: int
    untriaged_count: int
    assignment_summary: dict
    slack_posted: bool
    message_ts: str | None
    started_at: datetime
    completed_at: datetime


def is_untriaged(issue: LinearIssue, definition: UntriagedDefinition) -> bool:
    if definition.include_unassigned and issue.assignee_name is None:
        return True
    if definition.include_no_priority and issue.priority == 0:
        return True
    if issue.state_name in definition.state_names:
        return True
    return False


def build_assignment_summary(issues: list[LinearIssue]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for issue in issues:
        name = issue.assignee_name or "Unassigned"
        summary[name] = summary.get(name, 0) + 1
    return summary


def format_digest_message(
    team_key: str,
    issues: list[LinearIssue],
    untriaged: list[LinearIssue],
    summary: dict[str, int],
    include_untriaged: bool,
    include_assignment_summary: bool,
) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [f"📋 Linear Digest — {team_key}", now, ""]

    if not issues:
        lines.append("No issues found matching the current filter.")
        return "\n".join(lines)

    if include_untriaged:
        if untriaged:
            lines.append(f"⚠️ Untriaged Issues ({len(untriaged)})")
            lines.append("")
            for issue in untriaged:
                assignee = issue.assignee_name or "Unassigned"
                lines.append(f"• {issue.identifier} — {issue.title}")
                lines.append(f"  Assignee: {assignee} | Priority: {issue.priority_label} | State: {issue.state_name}")
                lines.append(f"  {issue.url}")
                lines.append("")
        else:
            lines.append("✅ No untriaged issues")
            lines.append("")

    if include_assignment_summary and summary:
        lines.append("👥 Assignment Summary")
        for name, count in sorted(summary.items()):
            plural = "s" if count != 1 else ""
            lines.append(f"• {name}: {count} open issue{plural}")

    return "\n".join(lines)


async def _load_connection(db: AsyncSession, provider: str, fernet_key: bytes) -> dict:
    result = await db.execute(
        select(Connection).where(Connection.provider == provider, Connection.is_active)
    )
    conn = result.scalar_one_or_none()
    if not conn:
        raise ConnectionNotFoundError(provider)
    creds = json.loads(decrypt(conn.credentials_enc, fernet_key))
    return creds


async def run_linear_slack_digest(
    params: DigestParams,
    db: AsyncSession,
    fernet_key: bytes,
) -> DigestResult:
    started_at = datetime.now(timezone.utc)

    linear_creds = await _load_connection(db, "linear", fernet_key)
    slack_creds = await _load_connection(db, "slack", fernet_key)

    issues = await fetch_issues(
        access_token=linear_creds["access_token"],
        team_key=params.team_key,
        limit=params.limit,
    )
    untriaged = [i for i in issues if is_untriaged(i, params.untriaged_definition)] if params.include_untriaged else []
    summary = build_assignment_summary(issues) if params.include_assignment_summary else {}

    message = format_digest_message(
        team_key=params.team_key,
        issues=issues,
        untriaged=untriaged,
        summary=summary,
        include_untriaged=params.include_untriaged,
        include_assignment_summary=params.include_assignment_summary,
    )

    message_ts = await post_message(
        access_token=slack_creds["access_token"],
        channel=params.slack_channel,
        text=message,
    )

    return DigestResult(
        team_key=params.team_key,
        slack_channel=params.slack_channel,
        issues_pulled=len(issues),
        untriaged_count=len(untriaged),
        assignment_summary=summary,
        slack_posted=True,
        message_ts=message_ts,
        started_at=started_at,
        completed_at=datetime.now(timezone.utc),
    )
