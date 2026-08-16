from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from zeython import Authenticatable, Model, email, required


class User(Model, Authenticatable):
    __tablename__ = "users"
    __hidden__ = ("password_hash",)
    __rules__ = {
        "name": [required()],
        "email": [required(), email()],
    }

    name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))

    # See app/Models/post.py and docs/relationships.md -- plain SQLAlchemy
    # relationship(), no framework wrapper needed to define it. Loading it
    # safely (Post.all(include=("author",))) is where Zeython adds value.
    posts: Mapped[list["Post"]] = relationship(back_populates="author")  # noqa: F821
