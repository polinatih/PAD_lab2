"""Обработчики событий других сервисов: продвигают заказ по статусам.

Повторная или запоздавшая доставка события не ломает заказ: если переход уже невозможен
(например, оплата пришла для отменённого заказа), событие пропускается с записью в лог.
"""

import logging

from . import states
from .models import Order
from .service import change_status

logger = logging.getLogger("orders.events")


class OrderEventHandlers:
    def __init__(self, db, outbox):
        self.db, self.outbox = db, outbox

    async def _advance(self, order_id: str, new_status: str, *, note: str | None = None, event: str | None = None,
                       extra: dict | None = None, update=None) -> None:
        async with self.db.sessionmaker() as session:
            order = await session.get(Order, order_id)
            if order is None:
                logger.warning("Event for unknown order", extra={"order_id": order_id})
                return
            if order.status == new_status or not states.can_transition(order.status, new_status):
                logger.info(f"Skip {order.status} -> {new_status}", extra={"order_id": order_id})
                return
            if update:
                update(order)
            change_status(session, order, new_status, note=note, event=event, extra=extra)
            await session.commit()
        if event:
            self.outbox.kick()

    async def on_payment_succeeded(self, envelope: dict) -> None:
        d = envelope["data"]
        card = f"{d.get('card_brand') or 'картой'} •• {d['card_last4']}" if d.get("card_last4") else "картой"
        # order.paid — ресторан получает новый заказ (через notification-service)
        await self._advance(d["order_id"], states.PAID, note=f"Оплачено: {card}", event="order.paid")

    async def on_payment_failed(self, envelope: dict) -> None:
        d = envelope["data"]
        reason = d.get("reason") or "Оплата не прошла"

        def set_reason(order: Order) -> None:
            order.cancel_reason = reason

        # Компенсация в saga: оплата не прошла — заказ отменяется. Деньги не списаны, возвращать нечего.
        await self._advance(d["order_id"], states.CANCELLED, note=reason, event="order.cancelled",
                            extra={"cancelled_by": "система", "reason": reason, "refund": False}, update=set_reason)

    async def on_delivery_assigned(self, envelope: dict) -> None:
        d = envelope["data"]

        def set_courier(order: Order) -> None:
            order.courier_id, order.courier_name, order.courier_phone = d["courier_id"], d.get("courier_name"), d.get("courier_phone")

        await self._advance(d["order_id"], states.COURIER_ASSIGNED, note=f"Курьер: {d.get('courier_name') or 'назначен'}",
                            update=set_courier)

    async def on_delivery_picked_up(self, envelope: dict) -> None:
        await self._advance(envelope["data"]["order_id"], states.IN_DELIVERY, note="Курьер забрал заказ")

    async def on_delivery_delivered(self, envelope: dict) -> None:
        # order.delivered: после этого клиент может оставить отзыв (review-service, этап 7)
        await self._advance(envelope["data"]["order_id"], states.DELIVERED, note="Заказ доставлен",
                            event="order.delivered")
