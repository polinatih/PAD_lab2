import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from common.db import Base

from .states import PENDING_PAYMENT


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _id() -> str:
    return uuid.uuid4().hex


class Order(Base):
    __tablename__ = "orders"
    # Idempotency-Key: повторное нажатие «Оформить» не создаёт второй заказ
    __table_args__ = (UniqueConstraint("customer_id", "idempotency_key", name="uq_order_idempotency"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    customer_id: Mapped[str] = mapped_column(String(32), index=True)
    customer_name: Mapped[str] = mapped_column(String(255), default="")
    customer_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    restaurant_id: Mapped[str] = mapped_column(String(32), index=True)
    restaurant_owner_id: Mapped[str] = mapped_column(String(32), index=True)
    restaurant_name: Mapped[str] = mapped_column(String(120))
    restaurant_address: Mapped[str] = mapped_column(String(255))
    delivery_address: Mapped[str] = mapped_column(String(255))
    comment: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(24), default=PENDING_PAYMENT, index=True)
    cancel_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    delivery_fee: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    total: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    prep_minutes: Mapped[int] = mapped_column(Integer, default=25)
    courier_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    courier_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    courier_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    items: Mapped[list["OrderItem"]] = relationship(back_populates="order", cascade="all, delete-orphan",
                                                    lazy="selectin", order_by="OrderItem.position")
    history: Mapped[list["StatusChange"]] = relationship(back_populates="order", cascade="all, delete-orphan",
                                                         lazy="selectin", order_by="StatusChange.at")

    @property
    def number(self) -> str:
        return self.id[:6].upper()


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    menu_item_id: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(120))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    quantity: Mapped[int] = mapped_column(Integer)
    line_total: Mapped[Decimal] = mapped_column(Numeric(10, 2))

    order: Mapped[Order] = relationship(back_populates="items")


class StatusChange(Base):
    """История статусов: из неё интерфейс рисует шкалу отслеживания заказа."""

    __tablename__ = "order_status_history"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(24))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    order: Mapped[Order] = relationship(back_populates="history")


class OutboxEvent(Base):
    """Transactional outbox: событие пишется в той же транзакции, что и заказ, и не теряется,
    даже если RabbitMQ в этот момент недоступен."""

    __tablename__ = "outbox"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    event_type: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)
    request_id: Mapped[str] = mapped_column(String(64), default="-")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
