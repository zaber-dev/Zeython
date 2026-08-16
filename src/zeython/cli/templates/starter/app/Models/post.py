from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from zeython import Model, max_length, required

from app.Models.user import User


class Post(Model):
    __tablename__ = "posts"
    __rules__ = {
        "title": [required(), max_length(255)],
        "body": [required()],
    }

    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))

    # Touching this directly (post.author) without eager-loading raises
    # MissingGreenlet in an async session -- always fetch with
    # `include=("author",)` instead. See docs/relationships.md.
    author: Mapped[User] = relationship(back_populates="posts")
