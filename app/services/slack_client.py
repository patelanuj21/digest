import logging

import httpx

logger = logging.getLogger(__name__)

SLACK_POST_MESSAGE_URL = "https://slack.com/api/chat.postMessage"


class SlackAPIError(Exception):
    def __init__(self, message: str):
        super().__init__(message)


async def post_message(access_token: str, channel: str, text: str) -> str:
    """Post a message to Slack. Returns message_ts on success."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            SLACK_POST_MESSAGE_URL,
            json={"channel": channel, "text": text},
            headers={"Authorization": f"Bearer {access_token}"},
        )

    if resp.status_code != 200:
        logger.error("Slack API HTTP error: status=%s", resp.status_code)
        raise SlackAPIError(f"Slack API returned HTTP {resp.status_code}")

    data = resp.json()
    if not data.get("ok"):
        error = data.get("error", "unknown_error")
        logger.error("Slack API error: %s", error)
        raise SlackAPIError(f"Slack error: {error}")

    return data.get("ts", "")
