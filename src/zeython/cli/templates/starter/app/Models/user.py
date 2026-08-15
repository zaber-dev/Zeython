from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from zeython import Model


class User(Model):
    __tablename__ = "users"

    name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
