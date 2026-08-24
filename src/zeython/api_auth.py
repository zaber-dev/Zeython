"""API token authentication: stateless bearer tokens for clients that can't
use cookies -- a mobile app, a separate SPA, a server-to-server caller.

Deliberately a separate code path from :mod:`zeython.auth`'s cookie
sessions, not a mode bolted onto the same functions -- a bearer token and a
session cookie are verified differently, travel in different places (an
``Authorization`` header vs. a cookie jar), and a handler should be
unambiguous about which one it expects.

Tokens are signed with ``itsdangerous`` (already a framework dependency,
used by Starlette's own session cookie signing) rather than a JWT library or
a database-backed token table -- no new dependency, and no migration
required to get started. The trade-off that buys: a token can't be revoked
before it expires. There's no server-side record of it to delete. If your
app needs "log this device out remotely," implement a real
:class:`TokenManager` yourself against a token table you can delete rows
from -- this one is the zero-setup default, not the only correct design.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from itsdangerous import BadSignature, URLSafeTimedSerializer
from starlette.requests import Request

from zeython.exceptions import UnauthorizedException
from zeython.providers import ServiceProvider

if TYPE_CHECKING:
    from zeython.application import Application
    from zeython.db import Model

_SALT = "zeython-api-token"


class TokenManager:
    """Issues and verifies bearer tokens for a chosen user model."""

    def __init__(self, user_model: type[Model], *, secret_key: str, expires_in: int) -> None:
        self.user_model = user_model
        self.expires_in = expires_in
        self._serializer = URLSafeTimedSerializer(secret_key, salt=_SALT)

    def issue(self, user: Model) -> str:
        """A signed token encoding ``user.id``.

        Signed, not encrypted: ``itsdangerous`` protects against
        *tampering* (a client can't forge or edit a valid token without
        the secret key) but not against *reading* -- the payload is only
        base64-encoded, trivially decodable by anyone holding the token,
        the client it was issued to included. Fine for ``user_id`` alone;
        don't extend this to encode anything that shouldn't be readable
        by whoever holds the token.
        """
        return self._serializer.dumps({"user_id": user.id})

    async def verify(self, token: str) -> Model | None:
        """The user the token was issued for, or ``None`` if it's missing, tampered, or expired."""
        try:
            data = self._serializer.loads(token, max_age=self.expires_in)
        except BadSignature:
            return None
        user_id = data.get("user_id") if isinstance(data, dict) else None
        if user_id is None:
            return None
        return await self.user_model.find(user_id)


def _bearer_token(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer "):
        return None
    return header[len("Bearer ") :].strip() or None


async def current_api_user(request: Request) -> Model | None:
    """The user identified by this request's ``Authorization: Bearer <token>`` header, or ``None``."""
    token = _bearer_token(request)
    if token is None:
        return None
    manager: TokenManager = request.app.state.container.make(TokenManager)
    return await manager.verify(token)


async def require_api_auth(request: Request) -> Model:
    """Return the token-authenticated user, or raise ``UnauthorizedException`` (401).

    Call this at the top of any handler meant for bearer-token clients, the
    same way :func:`~zeython.auth.require_auth` guards cookie-session ones::

        async def me(self, request):
            user = await require_api_auth(request)
    """
    user = await current_api_user(request)
    if user is None:
        raise UnauthorizedException("A valid API token is required.")
    return user


class ApiAuthServiceProvider(ServiceProvider):
    """Binds a :class:`TokenManager` into the container.

    Reuses ``APP_SECRET_KEY`` (the same key session cookies are signed
    with) -- rotating it invalidates every issued token, same as it already
    invalidates every session. ``.env``: ``API_TOKEN_EXPIRES_IN`` (seconds,
    default 30 days).
    """

    def __init__(self, app: Application, user_model: type[Model]) -> None:
        super().__init__(app)
        self.user_model = user_model

    def register(self) -> None:
        manager = TokenManager(
            self.user_model,
            secret_key=self.config.secret_key,
            expires_in=int(self.config.get("api.token_expires_in", 60 * 60 * 24 * 30)),
        )
        self.container.singleton(TokenManager, lambda: manager)


__all__ = ["TokenManager", "current_api_user", "require_api_auth", "ApiAuthServiceProvider"]
