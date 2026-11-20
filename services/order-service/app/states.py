"""Жизненный цикл заказа (конечный автомат).

    PENDING_PAYMENT ──payment.succeeded──► PAID ──ресторан принял──► COOKING ──ресторан: готово──► READY
          │                                  │                          │                            │
          │ payment.failed / клиент отменил  │ клиент или ресторан      │ ресторан отменил            │ delivery.assigned
          ▼                                  ▼ отменили                 ▼                            ▼
      CANCELLED ◄──────────────────────── CANCELLED ◄─────────────── CANCELLED              COURIER_ASSIGNED
                                                                                                     │ delivery.picked_up
                                                                                                     ▼
                                                                                   DELIVERED ◄── IN_DELIVERY
                                                                                          delivery.delivered

Каждый переход проверяется здесь: недопустимый переход (например, «доставлен» → «готовится»)
отклоняется с ошибкой 409, а повторное событие в то же состояние просто игнорируется.
"""

from common.errors import Conflict

PENDING_PAYMENT = "pending_payment"
PAID = "paid"
COOKING = "cooking"
READY = "ready"
COURIER_ASSIGNED = "courier_assigned"
IN_DELIVERY = "in_delivery"
DELIVERED = "delivered"
CANCELLED = "cancelled"

LABELS = {
    PENDING_PAYMENT: "Ожидает оплаты",
    PAID: "Оплачен",
    COOKING: "Готовится",
    READY: "Ждёт курьера",
    COURIER_ASSIGNED: "Курьер назначен",
    IN_DELIVERY: "Курьер в пути",
    DELIVERED: "Доставлен",
    CANCELLED: "Отменён",
}

TRANSITIONS: dict[str, set[str]] = {
    PENDING_PAYMENT: {PAID, CANCELLED},
    PAID: {COOKING, CANCELLED},
    COOKING: {READY, CANCELLED},
    READY: {COURIER_ASSIGNED},
    COURIER_ASSIGNED: {IN_DELIVERY},
    IN_DELIVERY: {DELIVERED},
    DELIVERED: set(),
    CANCELLED: set(),
}

FINAL = {DELIVERED, CANCELLED}
# До какого момента клиент может сам отменить заказ: пока ресторан не начал готовить
CUSTOMER_CANCELLABLE = {PENDING_PAYMENT, PAID}
# Ресторан может отказаться от заказа, пока он не передан курьеру
RESTAURANT_CANCELLABLE = {PAID, COOKING}


def can_transition(current: str, new: str) -> bool:
    return new in TRANSITIONS.get(current, set())


def ensure_transition(current: str, new: str) -> None:
    if not can_transition(current, new):
        raise Conflict(f"Нельзя перевести заказ из статуса «{LABELS[current]}» в «{LABELS[new]}»",
                       code="invalid_status_transition")
