import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from common.db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    """Учётная запись. Роль определяет, что пользователь может делать в системе:
    customer — заказывает еду, restaurant — управляет рестораном и готовит заказы,
    courier — доставляет заказы, admin — администрирует систему."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default="customer")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
