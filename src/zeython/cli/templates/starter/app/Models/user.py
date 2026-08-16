from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from zeython import Model, email, required


class User(Model):
    __tablename__ = "users"
    __rules__ = {
        "name": [required()],
        "email": [required(), email()],
    }

    name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
