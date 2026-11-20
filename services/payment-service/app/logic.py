"""Платежи в saga «заказ»:

    order.created ──► создаём платёж (pending), ждём оплату от клиента
    клиент платит ──► payment.succeeded ──► order-service: заказ PAID
    3 отказа банка или истекло время ──► payment.failed ──► order-service: заказ CANCELLED (компенсация)
    order.cancelled (заказ был оплачен) ──► возврат денег ──► payment.refunded
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .models import Payment, Transaction
from .outbox import add_event

logger = logging.getLogger("payments")


def now() -> datetime:
    return datetime.now(timezone.utc)


def aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)  # SQLite не хранит таймзону


def payload(p: Payment, **extra) -> dict:
    return {"payment_id": p.id, "order_id": p.order_id, "order_number": p.order_number, "customer_id": p.customer_id,
            "restaurant_name": p.restaurant_name, "amount": float(p.amount), "status": p.status,
            "card_last4": p.card_last4, **extra}


def fail(session, p: Payment, reason: str, status: str = "failed") -> None:
    p.status, p.failure_reason = status, reason
    add_event(session, "payment.failed", payload(p, reason=reason))
    logger.info(f"Payment {status}: {reason}", extra={"order_id": p.order_id})


class PaymentHandlers:
    def __init__(self, db, outbox, settings):
        self.db, self.outbox, self.settings = db, outbox, settings
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def on_order_created(self, envelope: dict) -> None:
        d = envelope["data"]
        async with self.db.sessionmaker() as session:
            if await session.scalar(select(Payment).where(Payment.order_id == d["order_id"])):
                return  # повторная доставка события
            session.add(Payment(order_id=d["order_id"], order_number=d.get("number", ""), customer_id=d["customer_id"],
                                restaurant_name=d.get("restaurant_name", ""), amount=Decimal(str(d["total"])),
                                expires_at=now() + timedelta(minutes=self.settings.payment_timeout_minutes)))
            try:
                await session.commit()
                logger.info("Payment awaiting", extra={"order_id": d["order_id"], "amount": d["total"]})
            except IntegrityError:
                await session.rollback()

    async def on_order_cancelled(self, envelope: dict) -> None:
        d = envelope["data"]
        async with self.db.sessionmaker() as session:
            p = await session.scalar(select(Payment).where(Payment.order_id == d["order_id"]))
            if p is None:
                return
            if p.status == "pending":  # заказ отменили до оплаты — платёж больше не нужен
                p.status, p.failure_reason = "cancelled", "Заказ отменён"
            elif p.status == "succeeded":  # компенсация: возвращаем деньги
                p.status, p.refunded_at = "refunded", now()
                p.transactions.append(Transaction(kind="refund", status="approved", amount=p.amount,
                                                  card_last4=p.card_last4, message=d.get("reason") or "Заказ отменён"))
                add_event(session, "payment.refunded", payload(p, reason=d.get("reason")))
                logger.info("Payment refunded", extra={"order_id": p.order_id, "amount": float(p.amount)})
            else:
                return
            await session.commit()
        self.outbox.kick()

    async def expire_overdue(self) -> int:
        """Неоплаченные вовремя платежи → payment.failed → заказ отменяется."""
        async with self.db.sessionmaker() as session:
            pending = (await session.scalars(select(Payment).where(Payment.status == "pending"))).all()
            overdue = [p for p in pending if aware(p.expires_at) <= now()]
            for p in overdue:
                fail(session, p, "Время на оплату истекло", status="expired")
            await session.commit()
        if overdue:
            self.outbox.kick()
        return len(overdue)

    async def start(self) -> None:
        async def loop():
            while not self._stop.is_set():
                try:
                    await self.expire_overdue()
                except Exception as exc:  # noqa: BLE001
                    logger.warning(f"Expiry check failed: {exc!r}")
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=self.settings.expiry_check_seconds)
                except asyncio.TimeoutError:
                    pass
        self._task = asyncio.create_task(loop())

    async def stop(self) -> None:
        """Мягкая остановка: не обрываем проверку на середине работы с БД."""
        self._stop.set()
        if self._task:
            await asyncio.wait_for(self._task, timeout=5)
