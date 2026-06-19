import logging
from urllib.parse import urlencode

import httpx

from app.connectors.base import Connector, TokenData

logger = logging.getLogger(__name__)


class SlackConnector(Connector):
    provider = "slack"
    auth_url = "https://slack.com/oauth/v2/authorize"
    token_url = "https://slack.com/api/oauth.v2.access"
    scopes = ["chat:write", "channels:read"]

    def get_authorize_url(self, state: str, code_challenge: str) -> str:
        params = {
            "client_id": self.oauth_config.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": ",".join(self.scopes),
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        return f"{self.auth_url}?{urlencode(params)}"

    async def exchange_code(self, code: str, code_verifier: str) -> TokenData:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                self.token_url,
                data={
                    "code": code,
                    "redirect_uri": self.redirect_uri,
                    "client_id": self.oauth_config.client_id,
                    "client_secret": self.oauth_config.client_secret,
                    "code_verifier": code_verifier,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        if resp.status_code != 200:
            logger.error("Slack token exchange failed: status=%s", resp.status_code)
            raise ValueError(f"Slack token exchange failed (HTTP {resp.status_code})")

        data = resp.json()
        if not data.get("ok"):
            error = data.get("error", "unknown_error")
            logger.error("Slack token exchange error: %s", error)
            raise ValueError(f"Slack OAuth error: {error}")

        # Slack returns bot token under access_token at the top level
        return TokenData(
            access_token=data["access_token"],
            refresh_token=None,  # Slack bot tokens don't expire or refresh
            token_type="bot",
            scope=data.get("scope"),
            expires_at=None,
        )

