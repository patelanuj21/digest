import os
from functools import lru_cache
from cryptography.fernet import Fernet


class Settings:
    def __init__(self):
        self.app_secret_key: str = os.environ.get("APP_SECRET_KEY", "")
        self.database_url: str = os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///./data/app.db")
        self.app_env: str = os.environ.get("APP_ENV", "development")

        self._fernet_key: bytes | None = None

    def validate(self) -> None:
        if not self.app_secret_key:
            raise RuntimeError("APP_SECRET_KEY environment variable is not set")
        try:
            Fernet(self.app_secret_key.encode())
        except Exception:
            raise RuntimeError(
                "APP_SECRET_KEY is not a valid Fernet key. "
                "Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
            )

    @property
    def fernet_key(self) -> bytes:
        if self._fernet_key is None:
            self._fernet_key = self.app_secret_key.encode()
        return self._fernet_key


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
