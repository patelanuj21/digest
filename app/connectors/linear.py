import logging
from urllib.parse import urlencode

import httpx

from app.connectors.base import Connector, TokenData

logger = logging.getLogger(__name__)

LINEAR_API_URL = "https://api.linear.app/graphql"


class LinearConnector(Connector):
    provider = "linear"
    auth_url = "https://linear.app/oauth/authorize"
    token_url = "https://api.linear.app/oauth/token"
    scopes = ["read"]

    def get_authorize_url(self, state: str, code_challenge: str) -> str:
        params = {
            "client_id": self.oauth_config.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
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
                    "grant_type": "authorization_code",
                    "code_verifier": code_verifier,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        if resp.status_code != 200:
            logger.error("Linear token exchange failed: status=%s", resp.status_code)
            raise ValueError(f"Linear token exchange failed (HTTP {resp.status_code})")
        data = resp.json()
        return TokenData(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            token_type=data.get("token_type", "Bearer"),
            scope=data.get("scope"),
            expires_at=None,
        )

    async def get_workspace_info(self, access_token: str) -> dict:
        query = "{ organization { name id urlKey } viewer { id name } }"
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                LINEAR_API_URL,
                json={"query": query},
                headers={"Authorization": f"Bearer {access_token}"},
            )
        if resp.status_code != 200:
            return {}
        data = resp.json().get("data", {})
        org = data.get("organization", {})
        viewer = data.get("viewer", {})
        return {
            "workspace_name": org.get("name"),
            "workspace_id": org.get("id"),
            "authed_user_id": viewer.get("id"),
        }
