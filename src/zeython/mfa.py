"""Time-based one-time password (TOTP) two-factor authentication.

RFC 6238 TOTP layered on top of the existing session-auth login flow
(:mod:`zeython.auth`): a user enrolls a secret, confirms it with a live
code from their authenticator app to turn MFA on (issuing one-time
recovery codes for when they lose that device), and from then on a
password check alone isn't enough -- login is gated behind a second
step. No new dependency: HMAC-SHA1 and base32 are both in the standard
library, so this needs nothing beyond what's already imported for
password hashing.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from starlette.requests import Request

from zeython.auth import AuthManager, login
from zeython.exceptions import ValidationException
from zeython.hashing import hash_password, verify_password

if TYPE_CHECKING:
    from zeython.db import Model

_PENDING_SESSION_KEY = "mfa_pending_user_id"
_DIGITS = 6
_PERIOD = 30
_RECOVERY_CODE_COUNT = 8


class MfaEnrollable:
    """Mixin adding TOTP two-factor auth to a user model.

    Declare the columns yourself, the same convention
    :class:`~zeython.auth.Authenticatable` uses for ``password_hash``::

        class User(Model, Authenticatable, MfaEnrollable):
            __tablename__ = "users"
            __hidden__ = ("password_hash", "mfa_secret", "mfa_recovery_codes")

            mfa_secret: Mapped[str | None] = mapped_column(String(64), nullable=True)
            mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
            mfa_recovery_codes: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)

    ``mfa_secret`` and ``mfa_recovery_codes`` belong in ``__hidden__`` --
    they're as sensitive as ``password_hash`` and must never round-trip
    through ``to_dict()``.
    """

    mfa_secret: Any
    mfa_enabled: Any
    mfa_recovery_codes: Any


@dataclass(frozen=True)
class Enrollment:
    """The result of :func:`enroll` -- both forms an authenticator app
    accepts: ``uri`` for a QR code (rendered client-side; this module has
    no image dependency), ``secret`` for manual entry as a fallback.
    """

    secret: str
    uri: str


def generate_secret() -> str:
    """A fresh random base32 TOTP secret, 160 bits -- RFC 4226's recommended
    minimum key length, twice what a bare 80-bit secret would give an
    attacker brute-forcing offline.
    """
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii")


def provisioning_uri(secret: str, *, account_name: str, issuer: str) -> str:
    """The ``otpauth://totp/...`` URI an authenticator app scans as a QR
    code (e.g. via a client-side JS QR library) or accepts pasted directly.
    """
    label = quote(f"{issuer}:{account_name}")
    return f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer)}&digits={_DIGITS}&period={_PERIOD}"


def _hotp(secret: str, counter: int) -> str:
    padded = secret.upper()
    padded += "=" * (-len(padded) % 8)
    key = base64.b32decode(padded)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()  # noqa: S324
    offset = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF) % (10**_DIGITS)
    return str(code).zfill(_DIGITS)


def verify_totp(secret: str, code: str, *, valid_window: int = 1) -> bool:
    """``True`` if ``code`` matches ``secret`` for the current 30s step, or
    up to ``valid_window`` steps either side (tolerating ordinary clock
    drift between server and the authenticator app -- the default of 1
    accepts a ±30s window).
    """
    if not code or not code.isdigit() or len(code) != _DIGITS:
        return False
    counter = int(time.time() // _PERIOD)
    return any(
        hmac.compare_digest(_hotp(secret, counter + offset), code)
        for offset in range(-valid_window, valid_window + 1)
    )


def _generate_recovery_codes(count: int = _RECOVERY_CODE_COUNT) -> list[str]:
    return [f"{secrets.token_hex(4)}-{secrets.token_hex(4)}" for _ in range(count)]


async def enroll(user: Any, *, account_name: str, issuer: str = "Zeython") -> Enrollment:
    """Start enrollment: generates a new secret and stores it on ``user`` --
    not yet enabled, :func:`confirm` must verify a live code first. Calling
    this again before confirming replaces the pending secret, so an
    abandoned enrollment can't be confirmed later with a stale one.
    """
    secret = generate_secret()
    user.mfa_secret = secret
    await user.save()
    return Enrollment(secret=secret, uri=provisioning_uri(secret, account_name=account_name, issuer=issuer))


async def confirm(user: Any, code: str) -> list[str]:
    """Verify ``code`` against the pending secret from :func:`enroll`,
    turning MFA on and issuing recovery codes -- returned here in
    plaintext, the only time they're ever visible; only their hash is
    stored, the same way a password is. Raises :class:`ValidationException`
    if there's no enrollment in progress or the code doesn't verify.
    """
    if not user.mfa_secret:
        raise ValidationException({"code": ["No MFA enrollment in progress."]})
    if not verify_totp(user.mfa_secret, code):
        raise ValidationException({"code": ["Invalid code."]})

    codes = _generate_recovery_codes()
    user.mfa_enabled = True
    user.mfa_recovery_codes = [hash_password(c) for c in codes]
    await user.save()
    return codes


async def disable(user: Any) -> None:
    """Turn MFA off and forget the secret and recovery codes."""
    user.mfa_secret = None
    user.mfa_enabled = False
    user.mfa_recovery_codes = None
    await user.save()


async def verify_and_consume(user: Any, code: str) -> bool:
    """``True`` if ``code`` is a valid live TOTP code, or an unused recovery
    code. A matching recovery code is consumed -- removed from storage --
    on success, since each is one-time use; a spent code never verifies
    again.
    """
    if not user.mfa_enabled or not user.mfa_secret:
        return False
    if verify_totp(user.mfa_secret, code):
        return True

    for hashed in user.mfa_recovery_codes or []:
        if verify_password(code, hashed):
            user.mfa_recovery_codes = [h for h in user.mfa_recovery_codes if h != hashed]
            await user.save()
            return True
    return False


def start_challenge(request: Request, user: Model) -> None:
    """Mark ``user`` as having passed the password check but still needing
    their second factor -- call this from a login handler instead of
    :func:`zeython.auth.login` whenever ``user.mfa_enabled`` is true::

        user = await manager.attempt(email, password)
        if user is None:
            raise UnauthorizedException("Invalid email or password.")
        if user.mfa_enabled:
            start_challenge(request, user)
            return JSONResponse({"mfa_required": True})
        auth_login(request, user)

    The user is *not* authenticated yet -- :func:`~zeython.auth.current_user`
    still returns ``None`` -- until :func:`complete_challenge` succeeds.
    """
    request.session[_PENDING_SESSION_KEY] = user.id


def pending_user_id(request: Request) -> int | None:
    """The id of the user awaiting their second factor, or ``None`` if
    there's no challenge in progress for this session.
    """
    return request.session.get(_PENDING_SESSION_KEY)


async def complete_challenge(request: Request, code: str) -> Model | None:
    """Verify ``code`` for the user :func:`start_challenge` left pending
    and, on success, complete login (equivalent to calling
    :func:`zeython.auth.login` directly) and return that user. Returns
    ``None`` if there's no pending challenge or ``code`` doesn't verify --
    the pending state is left in place on failure so the caller can retry,
    subject to their own :func:`~zeython.rate_limit.throttle`.
    """
    user_id = pending_user_id(request)
    if user_id is None:
        return None

    manager: AuthManager = request.app.state.container.make(AuthManager)
    user = await manager.user_model.find(user_id)
    if user is None or not await verify_and_consume(user, code):
        return None

    request.session.pop(_PENDING_SESSION_KEY, None)
    login(request, user)
    return user


__all__ = [
    "Enrollment",
    "MfaEnrollable",
    "complete_challenge",
    "confirm",
    "disable",
    "enroll",
    "generate_secret",
    "pending_user_id",
    "provisioning_uri",
    "start_challenge",
    "verify_and_consume",
    "verify_totp",
]
