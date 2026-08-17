"""Session-based authentication.

A deliberately small design: one signed cookie (Starlette's ``SessionMiddleware``,
keyed off ``APP_SECRET_KEY``) holding the authenticated user's ID, CSRF
protection (:mod:`zeython.csrf`) that comes with it automatically -- cookie
auth without it is forgeable from any other site the user's browser happens
to have open -- an :class:`AuthManager` that knows how to look up and verify
credentials against whichever model you designate as your user model, and a
handful of functions (`login`, `logout`, `current_user`, `require_auth`)
that operate on a request.

No server-side session store, no token issuance/rotation — that's a
deliberate scope boundary, not an oversight. Token-based auth (for an API
consumed by a separate frontend) is a reasonable future addition; it does not
belong in the same code path as cookie sessions.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from starlette.requests import Request

from zeython.exceptions import UnauthorizedException
from zeython.hashing import hash_password, verify_password
from zeython.providers import ServiceProvider

if TYPE_CHECKING:
    from zeython.application import Application
    from zeython.db import Model

_SESSION_KEY = "auth_user_id"


class Authenticatable:
    """Mixin adding password helpers to a user model.

    The concrete model declares its own password column — conventionally
    ``password_hash: Mapped[str] = mapped_column(String(255))`` — this mixin
    only adds behavior on top of it::

        class User(Model, Authenticatable):
            __tablename__ = "users"
            email: Mapped[str] = mapped_column(String(255), unique=True)
            password_hash: Mapped[str] = mapped_column(String(255))
    """

    password_hash: Any

    def set_password(self, raw_password: str) -> None:
        self.password_hash = hash_password(raw_password)

    def check_password(self, raw_password: str) -> bool:
        return verify_password(raw_password, self.password_hash)


class AuthManager:
    """Looks up and verifies users against a configured model and field names."""

    def __init__(
        self,
        user_model: type[Model],
        *,
        username_field: str = "email",
        password_field: str = "password_hash",
    ) -> None:
        self.user_model = user_model
        self.username_field = username_field
        self.password_field = password_field

    async def attempt(self, username: str, password: str) -> Model | None:
        """Verify credentials, returning the user on success or ``None`` on failure."""
        if not username or not password:
            return None

        filters: dict[str, Any] = {self.username_field: username}
        user = await self.user_model.first_where(**filters)
        if user is None:
            return None

        hashed = getattr(user, self.password_field, None)
        if not hashed or not verify_password(password, hashed):
            return None

        return user


def login(request: Request, user: Model) -> None:
    """Mark ``user`` as authenticated for the current session."""
    request.session[_SESSION_KEY] = user.id


def logout(request: Request) -> None:
    """Clear authentication from the current session."""
    request.session.pop(_SESSION_KEY, None)


async def current_user(request: Request) -> Model | None:
    """The authenticated user for this request, or ``None`` if not logged in."""
    user_id = request.session.get(_SESSION_KEY)
    if user_id is None:
        return None

    manager: AuthManager = request.app.state.container.make(AuthManager)
    return await manager.user_model.find(user_id)


async def require_auth(request: Request) -> Model:
    """Return the authenticated user, or raise ``UnauthorizedException``.

    Call this at the top of any handler that requires a logged-in user::

        async def show(self, request):
            user = await require_auth(request)
    """
    user = await current_user(request)
    if user is None:
        raise UnauthorizedException("Authentication required.")
    return user


class AuthServiceProvider(ServiceProvider):
    """Wires up session-backed authentication for a chosen user model.

    Adds Starlette's signed-cookie ``SessionMiddleware`` (keyed off
    ``APP_SECRET_KEY``, so that must be set), CSRF protection
    (:class:`~zeython.csrf.CsrfMiddleware` -- see docs/csrf.md), and binds
    an :class:`AuthManager` into the container::

        app.register(AuthServiceProvider(app, user_model=User))

    Configurable via ``.env``: ``SESSION_COOKIE_NAME``, ``SESSION_MAX_AGE``
    (seconds, default 14 days), ``SESSION_HTTPS_ONLY`` (default ``false``;
    set ``true`` once you're serving over HTTPS). ``CSRF_ENABLED`` (default
    ``true``), ``CSRF_COOKIE_NAME``, ``CSRF_HEADER_NAME`` configure the CSRF
    protection that comes with it -- turning it off is rarely the right
    call, since it's exactly what makes cookie-based auth safe to use from
    a browser.
    """

    def __init__(
        self,
        app: Application,
        user_model: type[Model],
        *,
        username_field: str = "email",
        password_field: str = "password_hash",
    ) -> None:
        super().__init__(app)
        self.user_model = user_model
        self.username_field = username_field
        self.password_field = password_field

    def register(self) -> None:
        manager = AuthManager(
            self.user_model,
            username_field=self.username_field,
            password_field=self.password_field,
        )
        self.container.singleton(AuthManager, lambda: manager)

    def boot(self) -> None:
        from starlette.middleware.sessions import SessionMiddleware

        https_only = bool(self.config.get("session.https_only", False))
        session_cookie_name = self.config.get("session.cookie_name", "zeython_session")
        self.app.add_middleware(
            SessionMiddleware,
            secret_key=self.config.secret_key,
            session_cookie=session_cookie_name,
            max_age=int(self.config.get("session.max_age", 60 * 60 * 24 * 14)),
            https_only=https_only,
        )

        if bool(self.config.get("csrf.enabled", True)):
            from zeython.csrf import DEFAULT_COOKIE_NAME, DEFAULT_HEADER_NAME, CsrfMiddleware

            self.app.add_middleware(
                CsrfMiddleware,
                cookie_name=self.config.get("csrf.cookie_name", DEFAULT_COOKIE_NAME),
                header_name=self.config.get("csrf.header_name", DEFAULT_HEADER_NAME),
                secure=https_only,
                protect_if_cookie_present=session_cookie_name,
            )


__all__ = [
    "Authenticatable",
    "AuthManager",
    "AuthServiceProvider",
    "login",
    "logout",
    "current_user",
    "require_auth",
    "hash_password",
    "verify_password",
]
