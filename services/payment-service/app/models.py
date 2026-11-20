import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from common.db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _id() -> str:
    return uuid.uuid4().hex


class Payment(Base):
    """Платёж по заказу. Статусы: pending → succeeded → refunded, или pending → failed / expired."""

    __tablename__ = "payments"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    order_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    order_number: Mapped[str] = mapped_column(String(16), default="")
    customer_id: Mapped[str] = mapped_column(String(32), index=True)
    restaurant_name: Mapped[str] = mapped_column(String(120), default="")
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    card_brand: Mapped[str | None] = mapped_column(String(16), nullable=True)
    card_last4: Mapped[str | None] = mapped_column(String(4), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    refunded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    transactions: Mapped[list["Transaction"]] = relationship(back_populates="payment", lazy="selectin",
                                                             order_by="Transaction.created_at", cascade="all, delete-orphan")


class Transaction(Base):
    """Каждая попытка списания и каждый возврат — отдельная запись (журнал для разбора спорных случаев)."""

    __tablename__ = "transactions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    payment_id: Mapped[str] = mapped_column(ForeignKey("payments.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))      # charge | refund
    status: Mapped[str] = mapped_column(String(16))    # approved | declined
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    card_last4: Mapped[str | None] = mapped_column(String(4), nullable=True)
    message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    payment: Mapped[Payment] = relationship(back_populates="transactions")


class OutboxEvent(Base):
    __tablename__ = "outbox"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    event_type: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)
    request_id: Mapped[str] = mapped_column(String(64), default="-")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
