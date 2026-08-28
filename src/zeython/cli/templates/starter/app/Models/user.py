from sqlalchemy import JSON, Boolean, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from zeython import Authenticatable, MfaEnrollable, Model, email, required


class User(Model, Authenticatable, MfaEnrollable):
    __tablename__ = "users"
    # mfa_secret/mfa_recovery_codes are as sensitive as password_hash --
    # see docs/mfa.md -- never let any of the three round-trip through
    # to_dict().
    __hidden__ = ("password_hash", "mfa_secret", "mfa_recovery_codes")
    __rules__ = {
        "name": [required()],
        "email": [required(), email()],
    }

    name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))

    # Two-factor auth (TOTP) -- see docs/mfa.md. mfa_secret is only set
    # while MFA is enabled or pending confirmation; mfa_enabled gates the
    # login-time second-factor challenge in AuthController.login.
    mfa_secret: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    mfa_recovery_codes: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)

    # See app/Models/post.py and docs/relationships.md -- plain SQLAlchemy
    # relationship(), no framework wrapper needed to define it. Loading it
    # safely (Post.all(include=("author",))) is where Zeython adds value.
    posts: Mapped[list["Post"]] = relationship(back_populates="author")  # noqa: F821

    async def saving(self) -> None:
        # Runs before every create *and* update (see docs/model-events.md).
        # Without this, "ada@example.com" and "Ada@Example.com" would pass
        # the unique constraint as two different rows.
        self.email = self.email.strip().lower()
