import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

LINEAR_API_URL = "https://api.linear.app/graphql"

_QUERY = """
query Digest($teamKey: String!, $limit: Int!) {
  teams(filter: { key: { eq: $teamKey } }) {
    nodes { id name }
  }
  issues(
    first: $limit,
    filter: { team: { key: { eq: $teamKey } } }
    orderBy: updatedAt
  ) {
    nodes {
      identifier title url priority priorityLabel
      assignee { name }
      state { name type }
      createdAt updatedAt
    }
  }
}
"""


@dataclass
class LinearIssue:
    identifier: str
    title: str
    url: str
    priority: int
    priority_label: str
    assignee_name: str | None
    state_name: str
    state_type: str


class LinearAPIError(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        self.status_code = status_code
        super().__init__(message)


class LinearRateLimitError(LinearAPIError):
    def __init__(self, retry_after: int | None = None):
        self.retry_after = retry_after
        super().__init__("Linear rate limit exceeded", 429)


class InvalidTeamKeyError(Exception):
    def __init__(self, team_key: str):
        self.team_key = team_key
        super().__init__(f"No Linear team found with key '{team_key}'")


async def fetch_issues(access_token: str, team_key: str, limit: int) -> list[LinearIssue]:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            LINEAR_API_URL,
            json={"query": _QUERY, "variables": {"teamKey": team_key, "limit": limit}},
            headers={"Authorization": f"Bearer {access_token}"},
        )

    if resp.status_code == 429:
        retry_after = int(resp.headers.get("Retry-After", 0)) or None
        raise LinearRateLimitError(retry_after)
    if resp.status_code == 401:
        raise LinearAPIError("Linear API returned 401 Unauthorized", 401)
    if resp.status_code != 200:
        logger.error("Linear API error: status=%s", resp.status_code)
        raise LinearAPIError(f"Linear API returned HTTP {resp.status_code}", resp.status_code)

    body = resp.json()
    if "errors" in body:
        msg = body["errors"][0].get("message", "Unknown GraphQL error")
        logger.error("Linear GraphQL error: %s", msg)
        raise LinearAPIError(f"Linear GraphQL error: {msg}")

    data = body.get("data", {})
    if not data.get("teams", {}).get("nodes"):
        raise InvalidTeamKeyError(team_key)

    return [
        LinearIssue(
            identifier=i["identifier"],
            title=i["title"],
            url=i["url"],
            priority=i.get("priority", 0),
            priority_label=i.get("priorityLabel") or "No priority",
            assignee_name=i["assignee"]["name"] if i.get("assignee") else None,
            state_name=i["state"]["name"],
            state_type=i["state"].get("type", ""),
        )
        for i in data.get("issues", {}).get("nodes", [])
    ]
