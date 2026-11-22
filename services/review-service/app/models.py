import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from common.db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _id() -> str:
    return uuid.uuid4().hex


class DeliveredOrder(Base):
    """Доставленные заказы (из события order.delivered). Оставить отзыв можно только на такой заказ,
    поэтому review-service не нужно спрашивать order-service при каждом отзыве."""

    __tablename__ = "delivered_orders"

    order_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    order_number: Mapped[str] = mapped_column(String(16), default="")
    customer_id: Mapped[str] = mapped_column(String(32), index=True)
    restaurant_id: Mapped[str] = mapped_column(String(32), index=True)
    restaurant_owner_id: Mapped[str] = mapped_column(String(32), index=True)
    restaurant_name: Mapped[str] = mapped_column(String(120), default="")
    customer_name: Mapped[str] = mapped_column(String(255), default="")
    delivered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Review(Base):
    __tablename__ = "reviews"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    order_id: Mapped[str] = mapped_column(String(32), unique=True)  # один отзыв на заказ
    restaurant_id: Mapped[str] = mapped_column(String(32), index=True)
    restaurant_name: Mapped[str] = mapped_column(String(120), default="")
    restaurant_owner_id: Mapped[str] = mapped_column(String(32), index=True)
    customer_id: Mapped[str] = mapped_column(String(32), index=True)
    customer_name: Mapped[str] = mapped_column(String(255), default="")
    rating: Mapped[int] = mapped_column(Integer)
    comment: Mapped[str] = mapped_column(Text, default="")
    reply: Mapped[str | None] = mapped_column(Text, nullable=True)  # ответ ресторана
    replied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)


class OutboxEvent(Base):
    __tablename__ = "outbox"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    event_type: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)
    request_id: Mapped[str] = mapped_column(String(64), default="-")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
