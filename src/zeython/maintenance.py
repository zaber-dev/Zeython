"""Maintenance mode: take the whole app offline for a deploy or a risky
migration without stopping the process. `zeython down` writes a flag file
this middleware checks on every request; `zeython up` removes it. Mirrors
Laravel's `artisan down`/`up` closely, including the bypass-secret
mechanism for checking the site while it's "down" for everyone else.
"""

from __future__ import annotations

import json
import secrets
import time
from pathlib import Path
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse

from zeython.providers import ServiceProvider

DEFAULT_STORE_PATH = "storage/framework/down.json"
BYPASS_COOKIE_NAME = "zeython_maintenance_bypass"


def maintenance_store_path(base_path: Path, configured: str | None) -> Path:
    """Resolve the flag-file path, relative to ``base_path`` unless already absolute."""
    path = Path(configured or DEFAULT_STORE_PATH)
    return path if path.is_absolute() else base_path / path


def enable_maintenance_mode(
    store_path: Path,
    *,
    message: str | None = None,
    retry: int | None = None,
    allowed_ips: list[str] | None = None,
    secret: str | None = None,
) -> str:
    """Write the maintenance flag file. Returns the bypass secret in effect
    (either the one passed in, or a freshly generated one)."""
    secret = secret or secrets.token_urlsafe(16)
    payload: dict[str, Any] = {
        "message": message or "Be right back.",
        "retry": retry,
        "allowed_ips": allowed_ips or [],
        "secret": secret,
        "since": time.time(),
    }
    store_path.parent.mkdir(parents=True, exist_ok=True)
    store_path.write_text(json.dumps(payload))
    return secret


def disable_maintenance_mode(store_path: Path) -> bool:
    """Remove the maintenance flag file. Returns ``False`` if it wasn't there."""
    if not store_path.exists():
        return False
    store_path.unlink()
    return True


class MaintenanceModeMiddleware:
    """Pure ASGI middleware: while the flag file is present, every request
    gets a ``503`` -- except one from an allowed IP, or one carrying a
    valid bypass (a cookie set by visiting ``/<secret>`` once).

    Reads the flag file fresh on every request rather than caching its
    contents in memory: `zeython up` removing the file must take effect on
    the very next request, not after a process restart, and the read
    itself is cheap -- a single ``Path.exists()`` call is the entire cost
    once the app isn't down.

    The bypass cookie is a bearer credential -- holding it skips
    maintenance mode entirely for as long as the cookie lives -- so
    ``secure`` should be set once the app is served over HTTPS (matches
    :class:`~zeython.csrf.CsrfMiddleware`/the session cookie's own
    ``secure=`` convention); left ``False`` by default only because a
    plain local ``http://`` dev server can't set a ``Secure`` cookie at
    all.
    """

    def __init__(self, app: Any, *, store_path: Path, secure: bool = False) -> None:
        self.app = app
        self.store_path = store_path
        self.secure = secure

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http" or not self.store_path.exists():
            await self.app(scope, receive, send)
            return

        try:
            payload = json.loads(self.store_path.read_text())
        except (OSError, json.JSONDecodeError):
            # A flag file mid-write or corrupted -- fail open rather than
            # locking every visitor out over a transient read.
            await self.app(scope, receive, send)
            return

        secret = payload.get("secret")
        request = Request(scope, receive)

        if secret and request.url.path == f"/{secret}":
            response = RedirectResponse("/")
            response.set_cookie(
                BYPASS_COOKIE_NAME, secret, httponly=True, samesite="lax", secure=self.secure
            )
            await response(scope, receive, send)
            return

        bypass_cookie = request.cookies.get(BYPASS_COOKIE_NAME)
        if secret and bypass_cookie and secrets.compare_digest(bypass_cookie, secret):
            await self.app(scope, receive, send)
            return

        client = scope.get("client")
        client_host = client[0] if client else None
        if client_host and client_host in (payload.get("allowed_ips") or []):
            await self.app(scope, receive, send)
            return

        headers = {}
        retry = payload.get("retry")
        if retry:
            headers["Retry-After"] = str(retry)
        body = {"message": payload.get("message") or "Be right back.", "status": 503}
        unavailable = JSONResponse(body, status_code=503, headers=headers)
        await unavailable(scope, receive, send)


class MaintenanceModeServiceProvider(ServiceProvider):
    """Registers :class:`MaintenanceModeMiddleware`.

    Safe to always register, the same reasoning
    :class:`~zeython.request_id.RequestIdServiceProvider` relies on: with
    no flag file present (the default), every request pays one
    ``Path.exists()`` call and nothing else changes. `zeython down`
    creates that file; `zeython up` removes it -- no process restart
    needed either way, since the middleware reads it fresh every time.

    Register this **last**, after every other provider that adds
    middleware (`DatabaseServiceProvider` included) -- the most recently
    registered middleware wraps outermost, and maintenance mode needs to
    intercept a request before anything else runs, including opening a
    database session. That matters most exactly when this feature is
    useful: a migration in progress, a database that's briefly down.

    - ``MAINTENANCE_STORE_PATH`` -- default ``storage/framework/down.json``,
      relative to the project root.
    - ``MAINTENANCE_SECURE_COOKIE`` -- default ``false``; set ``true`` once
      you're serving over HTTPS, the same convention
      ``SESSION_HTTPS_ONLY``/``session.https_only`` uses for the session
      cookie (see :class:`~zeython.auth.AuthServiceProvider`) -- set this
      independently since maintenance mode works without auth registered
      at all.
    """

    def boot(self) -> None:
        store_path = maintenance_store_path(
            self.app.base_path, self.config.get("maintenance.store_path")
        )
        secure = bool(self.config.get("maintenance.secure_cookie", False))
        self.app.add_middleware(MaintenanceModeMiddleware, store_path=store_path, secure=secure)


__all__ = [
    "BYPASS_COOKIE_NAME",
    "DEFAULT_STORE_PATH",
    "MaintenanceModeMiddleware",
    "MaintenanceModeServiceProvider",
    "disable_maintenance_mode",
    "enable_maintenance_mode",
    "maintenance_store_path",
]
