import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import JSON, Boolean, DateTime, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from common.db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _id() -> str:
    return uuid.uuid4().hex


class Delivery(Base):
    """Доставка заказа. Статусы: searching → assigned → picked_up → delivered."""

    __tablename__ = "deliveries"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    order_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    order_number: Mapped[str] = mapped_column(String(16), default="")
    customer_id: Mapped[str] = mapped_column(String(32), index=True)
    customer_name: Mapped[str] = mapped_column(String(255), default="")
    customer_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    restaurant_name: Mapped[str] = mapped_column(String(120))
    restaurant_address: Mapped[str] = mapped_column(String(255))
    delivery_address: Mapped[str] = mapped_column(String(255))
    comment: Mapped[str] = mapped_column(Text, default="")
    order_total: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0"))
    courier_fee: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0"))
    status: Mapped[str] = mapped_column(String(16), default="searching", index=True)
    courier_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    courier_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    courier_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    picked_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Courier(Base):
    """Состояние курьера в этом сервисе: на линии или нет. Учётная запись — в auth-service."""

    __tablename__ = "couriers"

    user_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    is_online: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class OutboxEvent(Base):
    __tablename__ = "outbox"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    event_type: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)
    request_id: Mapped[str] = mapped_column(String(64), default="-")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
