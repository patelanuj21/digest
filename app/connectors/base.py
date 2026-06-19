from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass
class OAuthConfig:
    client_id: str
    client_secret: str
    base_url: str


@dataclass
class TokenData:
    access_token: str
    refresh_token: str | None
    token_type: str
    scope: str | None
    expires_at: datetime | None


class Connector(ABC):
    provider: str
    auth_url: str
    token_url: str
    scopes: list[str]

    def __init__(self, oauth_config: OAuthConfig):
        self.oauth_config = oauth_config

    @property
    def redirect_uri(self) -> str:
        return f"{self.oauth_config.base_url}/oauth/{self.provider}/callback"

    @abstractmethod
    def get_authorize_url(self, state: str, code_challenge: str) -> str: ...

    @abstractmethod
    async def exchange_code(self, code: str, code_verifier: str) -> TokenData: ...
