"""CSRF protection for cookie-authenticated requests.

A browser attaches cookies to a request automatically, even one triggered
by a completely different site -- that's exactly what session-cookie auth
(:mod:`zeython.auth`) relies on, and exactly what makes it forgeable
without protection: a malicious page can trigger a ``POST`` to this app
and the victim's session cookie rides along, no user interaction beyond
"visited a page" required.

This uses the double-submit-cookie pattern: a random token is set as a
*readable* (non-``HttpOnly``) cookie, and any unsafe request (``POST``,
``PUT``, ``PATCH``, ``DELETE``) must also send that same value back in a
header. A cross-site attacker's page can trigger the cookie to be sent,
but can't *read* its value (the same-origin policy blocks that) to also
set the matching header -- so a forged request is missing the header, or
has the wrong value, and gets rejected. See docs/csrf.md.
"""

from __future__ import annotations

import secrets
from typing import Any

from starlette.datastructures import MutableHeaders
from starlette.requests import Request

from zeython.exceptions import ForbiddenException, http_exception_handler

DEFAULT_COOKIE_NAME = "csrf_token"
DEFAULT_HEADER_NAME = "x-csrf-token"
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})


def csrf_token(request: Request) -> str | None:
    """The current request's CSRF token, if :class:`CsrfMiddleware` is installed.

    Useful for embedding in a server-rendered form as a hidden field, for
    apps that submit real HTML forms instead of driving everything through
    ``fetch``/XHR (which can just read the cookie directly instead).
    """
    return request.scope.get("csrf_token")


class CsrfMiddleware:
    """Pure ASGI middleware implementing the double-submit-cookie check.

    A request is exempt if:

    - its method is safe (``GET``/``HEAD``/``OPTIONS``/``TRACE`` never
      change state, so there's nothing to forge),
    - it carries an ``Authorization`` header -- a bearer token isn't
      attached to cross-site requests automatically the way a cookie is,
      so it isn't vulnerable to this in the first place (see
      :mod:`zeython.api_auth`), or
    - ``protect_if_cookie_present`` is set and this request doesn't carry
      that cookie -- CSRF only matters when there's an existing
      cookie-authenticated session to forge an action *within*; a request
      with no session cookie at all (a token-issuing endpoint like
      ``/api/token``, or the very first request from a brand new client)
      has nothing ambient for a forged cross-site request to ride on.
      :class:`~zeython.auth.AuthServiceProvider` sets this to its own
      session cookie's name; leave unset for blanket protection of every
      unsafe request regardless of cookies.

    Every other response gets a fresh ``csrf_token`` cookie if one isn't
    already present; every other *request* must send that same value back
    via the ``X-CSRF-Token`` header (client-configurable name).
    """

    def __init__(
        self,
        app: Any,
        *,
        cookie_name: str = DEFAULT_COOKIE_NAME,
        header_name: str = DEFAULT_HEADER_NAME,
        secure: bool = False,
        protect_if_cookie_present: str | None = None,
    ) -> None:
        self.app = app
        self.cookie_name = cookie_name
        self.header_name = header_name.lower()
        self.secure = secure
        self.protect_if_cookie_present = protect_if_cookie_present

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)
        existing_token = request.cookies.get(self.cookie_name)
        token = existing_token or secrets.token_urlsafe(32)
        scope["csrf_token"] = token
        needs_cookie = existing_token != token

        guarded = self.protect_if_cookie_present is None or self.protect_if_cookie_present in request.cookies
        if guarded and request.method not in _SAFE_METHODS and "authorization" not in request.headers:
            header_token = request.headers.get(self.header_name)
            if not existing_token or not header_token or not secrets.compare_digest(existing_token, header_token):
                # Reusing http_exception_handler, not `raise`: Starlette only
                # dispatches its `exception_handlers` mapping for exceptions
                # raised from *inside* routing (ExceptionMiddleware), not
                # from user middleware added via add_middleware(), which
                # sits *outside* that layer -- an uncaught raise here would
                # propagate straight past it as an unhandled 500 instead of
                # a clean, consistent 403.
                exc = ForbiddenException(
                    f"CSRF token missing or invalid. Send it back via the {self.header_name} header."
                )
                response = await http_exception_handler(request, exc)
                if needs_cookie:
                    response.set_cookie(self.cookie_name, token, samesite="lax", secure=self.secure, httponly=False)
                await response(scope, receive, send)
                return

        if not needs_cookie:
            await self.app(scope, receive, send)
            return

        async def send_with_cookie(message: dict) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                cookie = f"{self.cookie_name}={token}; Path=/; SameSite=lax"
                if self.secure:
                    cookie += "; Secure"
                headers.append("set-cookie", cookie)
            await send(message)

        await self.app(scope, receive, send_with_cookie)


__all__ = ["CsrfMiddleware", "csrf_token", "DEFAULT_COOKIE_NAME", "DEFAULT_HEADER_NAME"]
