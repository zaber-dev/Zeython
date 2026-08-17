"""Common HTTP security response headers -- opt-in, since sensible defaults
for some of these (a Content-Security-Policy above all) are genuinely
application-specific: a wrong default here doesn't fail loudly, it just
silently breaks a legitimate asset/script your own pages load. Register
:class:`SecurityHeadersServiceProvider` explicitly once you've decided
what belongs in your own policy, rather than getting one imposed on you.
"""

from __future__ import annotations

from typing import Any

from starlette.datastructures import MutableHeaders

from zeython.providers import ServiceProvider


class SecurityHeadersMiddleware:
    """Pure ASGI middleware that adds security response headers to every response.

    - ``X-Content-Type-Options: nosniff`` -- stops a browser from
      second-guessing a response's declared ``Content-Type`` (the classic
      case: an uploaded file served back and "sniffed" as HTML, letting it
      execute as a page instead of staying inert).
    - ``X-Frame-Options`` -- ``DENY`` by default, so this app can't be
      framed by another site (clickjacking).
    - ``Referrer-Policy`` -- ``strict-origin-when-cross-origin`` by
      default: full URL on same-origin navigation, origin-only cross-origin,
      nothing on a downgrade to plain HTTP.
    - ``Content-Security-Policy`` -- unset by default. There's no universal
      safe default: a policy that's too strict breaks your own inline
      scripts or CDN-loaded assets (this framework's own Swagger UI and
      dev-mode Tailwind both load from a CDN -- see docs/security-headers.md),
      and one that's too loose isn't worth sending. Pass your own.
    - ``Strict-Transport-Security`` (HSTS) -- off by default. Turning it on
      before every path to this app is actually served over HTTPS can lock
      users out of a plain-HTTP fallback for as long as ``max_age`` says;
      only enable it once you mean it.
    """

    def __init__(
        self,
        app: Any,
        *,
        content_security_policy: str | None = None,
        frame_options: str | None = "DENY",
        content_type_options: bool = True,
        referrer_policy: str | None = "strict-origin-when-cross-origin",
        hsts: bool = False,
        hsts_max_age: int = 60 * 60 * 24 * 365,
    ) -> None:
        self.app = app
        self.content_security_policy = content_security_policy
        self.frame_options = frame_options
        self.content_type_options = content_type_options
        self.referrer_policy = referrer_policy
        self.hsts = hsts
        self.hsts_max_age = hsts_max_age

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: dict) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                if self.content_type_options:
                    headers.append("X-Content-Type-Options", "nosniff")
                if self.frame_options:
                    headers.append("X-Frame-Options", self.frame_options)
                if self.referrer_policy:
                    headers.append("Referrer-Policy", self.referrer_policy)
                if self.content_security_policy:
                    headers.append("Content-Security-Policy", self.content_security_policy)
                if self.hsts:
                    headers.append("Strict-Transport-Security", f"max-age={self.hsts_max_age}; includeSubDomains")
            await send(message)

        await self.app(scope, receive, send_with_headers)


class SecurityHeadersServiceProvider(ServiceProvider):
    """Registers :class:`SecurityHeadersMiddleware`, configured entirely via ``.env``.

    Not registered by default -- see the module docstring. Add it explicitly::

        app.register(SecurityHeadersServiceProvider)

    - ``SECURITY_HEADERS_CSP`` -- your ``Content-Security-Policy`` value.
      Unset by default; no header is sent until you provide one.
    - ``SECURITY_HEADERS_FRAME_OPTIONS`` -- default ``DENY``.
    - ``SECURITY_HEADERS_CONTENT_TYPE_OPTIONS`` -- default ``true``.
    - ``SECURITY_HEADERS_REFERRER_POLICY`` -- default ``strict-origin-when-cross-origin``.
    - ``SECURITY_HEADERS_HSTS`` -- default ``false``.
    - ``SECURITY_HEADERS_HSTS_MAX_AGE`` -- default ``31536000`` (1 year).
    """

    def boot(self) -> None:
        self.app.add_middleware(
            SecurityHeadersMiddleware,
            content_security_policy=self.config.get("security_headers.csp"),
            frame_options=self.config.get("security_headers.frame_options", "DENY"),
            content_type_options=bool(self.config.get("security_headers.content_type_options", True)),
            referrer_policy=self.config.get("security_headers.referrer_policy", "strict-origin-when-cross-origin"),
            hsts=bool(self.config.get("security_headers.hsts", False)),
            hsts_max_age=int(self.config.get("security_headers.hsts_max_age", 60 * 60 * 24 * 365)),
        )


__all__ = ["SecurityHeadersMiddleware", "SecurityHeadersServiceProvider"]
