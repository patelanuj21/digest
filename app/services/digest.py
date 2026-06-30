import json
import logging
from dataclasses import dataclass
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


# Workflow-state types whose issues are dropped before building the digest, so
# counts reflect active work (Live/Churned accounts are not the manager's focus).
EXCLUDED_STATE_TYPES = {"completed", "canceled"}

# Display order for priority buckets in the per-engineer overview.
PRIORITY_ORDER = ["Urgent", "High", "Medium", "Low", "No priority"]


@dataclass
class DigestParams:
    team_key: str
    slack_channel: str
    limit: int = 20
    include_unassigned: bool = True
    include_assignment_summary: bool = True


@dataclass
class DigestResult:
    team_key: str
    slack_channel: str
    issues_pulled: int
    unassigned_count: int
    assignment_summary: dict
    slack_posted: bool
    message_ts: str | None
    started_at: datetime
    completed_at: datetime


def build_assignment_summary(issues: list[LinearIssue]) -> dict[str, dict]:
    """Per-engineer account counts, broken down by priority label."""
    summary: dict[str, dict] = {}
    for issue in issues:
        entry = summary.setdefault(issue.assignee_name, {"total": 0, "by_priority": {}})
        entry["total"] += 1
        label = issue.priority_label
        entry["by_priority"][label] = entry["by_priority"].get(label, 0) + 1
    return summary


def format_digest_message(
    team_key: str,
    unassigned: list[LinearIssue],
    summary: dict[str, dict],
    include_unassigned: bool,
    include_assignment_summary: bool,
) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [f"📋 Linear Digest — {team_key}", now, ""]

    if include_unassigned:
        if unassigned:
            lines.append(f"🚨 Unassigned Accounts ({len(unassigned)})")
            lines.append("")
            for issue in unassigned:
                lines.append(f"• {issue.identifier} — {issue.title} | {issue.state_name}")
                lines.append(f"  {issue.url}")
            lines.append("")
        else:
            lines.append("✅ All accounts have an owner")
            lines.append("")

    if include_assignment_summary and summary:
        lines.append("👥 Assignments by Engineer")
        ranked = sorted(summary.items(), key=lambda kv: (-kv[1]["total"], kv[0]))
        for name, entry in ranked:
            plural = "s" if entry["total"] != 1 else ""
            lines.append(f"• {name} — {entry['total']} account{plural}")
            buckets = entry["by_priority"]
            ordered = [f"{label} {buckets[label]}" for label in PRIORITY_ORDER if label in buckets]
            if ordered:
                lines.append("    " + " · ".join(ordered))

    return "\n".join(lines).rstrip()


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
    active = [i for i in issues if i.state_type not in EXCLUDED_STATE_TYPES]
    unassigned = [i for i in active if i.assignee_name is None]
    assigned = [i for i in active if i.assignee_name is not None]
    summary = build_assignment_summary(assigned) if params.include_assignment_summary else {}

    message = format_digest_message(
        team_key=params.team_key,
        unassigned=unassigned,
        summary=summary,
        include_unassigned=params.include_unassigned,
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
        unassigned_count=len(unassigned),
        assignment_summary=summary,
        slack_posted=True,
        message_ts=message_ts,
        started_at=started_at,
        completed_at=datetime.now(timezone.utc),
    )
