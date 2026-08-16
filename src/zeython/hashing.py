"""Password hashing: PBKDF2-HMAC-SHA256, no C-extension dependency required.

PBKDF2 was chosen over bcrypt/argon2 deliberately: it needs no third-party
crypto library (stdlib `hashlib` only), which keeps the framework installable
everywhere pip and a C compiler don't necessarily agree, while still meeting
OWASP's current guidance for PBKDF2-HMAC-SHA256 iteration counts.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os

_ALGORITHM = "pbkdf2_sha256"
_DEFAULT_ITERATIONS = 600_000  # OWASP (2023) minimum recommendation for PBKDF2-HMAC-SHA256
_SALT_BYTES = 16


def hash_password(password: str, *, iterations: int = _DEFAULT_ITERATIONS) -> str:
    """Hash ``password`` for storage.

    Returns a self-describing string: ``pbkdf2_sha256$<iterations>$<salt>$<hash>``
    (salt and hash base64-encoded), so the iteration count can be raised later
    without invalidating hashes already in the database.
    """
    if not password:
        raise ValueError("password must not be empty")

    salt = os.urandom(_SALT_BYTES)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return "$".join(
        [
            _ALGORITHM,
            str(iterations),
            base64.b64encode(salt).decode("ascii"),
            base64.b64encode(derived).decode("ascii"),
        ]
    )


def verify_password(password: str, hashed: str) -> bool:
    """Constant-time check of ``password`` against a hash from :func:`hash_password`."""
    if not password or not hashed:
        return False

    parts = hashed.split("$")
    if len(parts) != 4:
        return False
    algorithm, iterations_raw, salt_b64, hash_b64 = parts

    if algorithm != _ALGORITHM:
        return False

    try:
        iterations = int(iterations_raw)
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
    except (ValueError, TypeError):
        return False

    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(derived, expected)


__all__ = ["hash_password", "verify_password"]
