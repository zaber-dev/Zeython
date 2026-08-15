"""Environment-driven configuration for Zeython applications."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import dotenv_values

_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}


def _coerce(value: str) -> Any:
    lowered = value.lower()
    if lowered in _TRUE_VALUES:
        return True
    if lowered in _FALSE_VALUES:
        return False
    if value.isdigit():
        return int(value)
    try:
        return float(value)
    except ValueError:
        return value


class Config:
    """Layered configuration backed by the environment and ``.env`` files.

    Values resolve in this order (highest priority first): real process
    environment variables, then the loaded ``.env`` file, then explicit
    defaults passed to :meth:`get`.
    """

    def __init__(self, values: dict[str, Any], base_path: Path) -> None:
        self._values = values
        self.base_path = base_path

    @classmethod
    def load(cls, base_path: str | Path | None = None, env_file: str = ".env") -> Config:
        base = Path(base_path) if base_path is not None else Path.cwd()
        env_path = base / env_file

        values: dict[str, Any] = {}
        if env_path.exists():
            for key, raw in dotenv_values(env_path).items():
                if raw is not None:
                    values[key] = _coerce(raw)

        for key, raw in os.environ.items():
            values[key] = _coerce(raw)

        return cls(values, base)

    def get(self, key: str, default: Any = None) -> Any:
        """Dot-path lookup, e.g. ``config.get("database.url")`` reads ``DATABASE_URL``."""
        env_key = key.replace(".", "_").upper()
        return self._values.get(env_key, default)

    def __getitem__(self, key: str) -> Any:
        value = self.get(key)
        if value is None:
            raise KeyError(key)
        return value

    def set(self, key: str, value: Any) -> None:
        self._values[key.replace(".", "_").upper()] = value

    # -- Well-known settings, typed for convenience -------------------------------

    @property
    def app_name(self) -> str:
        return self.get("app.name", "Zeython App")

    @property
    def environment(self) -> str:
        return self.get("app.env", "development")

    @property
    def debug(self) -> bool:
        return bool(self.get("app.debug", self.environment != "production"))

    @property
    def host(self) -> str:
        return self.get("app.host", "127.0.0.1")

    @property
    def port(self) -> int:
        return int(self.get("app.port", 8000))

    @property
    def database_url(self) -> str:
        return self.get("database.url", "sqlite+aiosqlite:///./database.db")

    @property
    def secret_key(self) -> str:
        key = self.get("app.secret_key")
        if not key:
            raise RuntimeError(
                "APP_SECRET_KEY is not set. Add it to your .env file before running in production."
            )
        return key

    def is_testing(self) -> bool:
        return self.environment == "testing"

    def is_production(self) -> bool:
        return self.environment == "production"
