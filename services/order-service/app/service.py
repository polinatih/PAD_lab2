"""Бизнес-логика заказов: смена статуса с записью в историю и событием в outbox."""

import logging
from datetime import datetime, timezone

from .models import Order, StatusChange
from .outbox import add_event
from .states import LABELS, ensure_transition

logger = logging.getLogger("orders")


def event_payload(order: Order, **extra) -> dict:
    return {
        "order_id": order.id, "number": order.number, "status": order.status,
        "customer_id": order.customer_id, "restaurant_id": order.restaurant_id,
        "restaurant_owner_id": order.restaurant_owner_id, "restaurant_name": order.restaurant_name,
        "total": float(order.total), **extra,
    }


def change_status(session, order: Order, new_status: str, *, note: str | None = None,
                  event: str | None = None, extra: dict | None = None) -> None:
    """Проверяет переход, меняет статус, пишет историю и (если нужно) событие — всё в одной транзакции."""
    ensure_transition(order.status, new_status)
    old = order.status
    order.status = new_status
    order.updated_at = datetime.now(timezone.utc)
    order.history.append(StatusChange(status=new_status, note=note))
    if event:
        add_event(session, event, event_payload(order, previous_status=old, **(extra or {})))
    logger.info(f"Order {order.number}: {LABELS[old]} -> {LABELS[new_status]}",
                extra={"order_id": order.id, "from": old, "to": new_status})
