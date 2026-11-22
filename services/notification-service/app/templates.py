"""Какое событие кому и что сообщает.

Каждая функция получает данные события и возвращает список уведомлений:
(получатель, уровень, заголовок, текст, ссылка в интерфейсе).
"""

from dataclasses import dataclass


@dataclass
class Message:
    user_id: str
    level: str
    title: str
    body: str
    link: str | None = None


def _money(value) -> str:
    n = float(value or 0)
    return f"{n:.0f} лей" if n.is_integer() else f"{n:.2f} лей"


def _order_link(d: dict) -> str:
    return f"#/orders/{d['order_id']}"


def user_registered(d):
    return [Message(d["user_id"], "info", "Добро пожаловать в «Ложку»!",
                    {"customer": "Выберите ресторан и закажите первое блюдо.",
                     "restaurant": "Откройте свой ресторан и соберите меню в разделе «Мои рестораны».",
                     "courier": "Выйдите на линию, и вам начнут приходить заказы."}.get(d.get("role"), ""))]


def order_created(d):
    return [Message(d["customer_id"], "info", f"Заказ № {d['number']} оформлен",
                    f"{d['restaurant_name']}, {_money(d['total'])}. Осталось оплатить.", _order_link(d))]


def order_paid(d):
    return [
        Message(d["customer_id"], "success", f"Заказ № {d['number']} оплачен", "Ресторан получил заказ.", _order_link(d)),
        Message(d["restaurant_owner_id"], "warning", f"Новый заказ № {d['number']}",
                f"{d['restaurant_name']}, {_money(d['total'])}. Примите его в работу.", "#/kitchen"),
    ]


def order_accepted(d):
    return [Message(d["customer_id"], "info", f"Ресторан готовит заказ № {d['number']}",
                    f"{d['restaurant_name']} уже начал готовить.", _order_link(d))]


def order_ready(d):
    return [Message(d["customer_id"], "info", f"Заказ № {d['number']} готов", "Ищем курьера.", _order_link(d))]


def order_cancelled(d):
    reason = d.get("reason") or "Заказ отменён"
    refund = " Деньги вернутся на карту." if d.get("refund") else ""
    messages = [Message(d["customer_id"], "error", f"Заказ № {d['number']} отменён", f"{reason}.{refund}", _order_link(d))]
    if d.get("previous_status") not in (None, "pending_payment") and d.get("cancelled_by") != "ресторан":
        messages.append(Message(d["restaurant_owner_id"], "error", f"Заказ № {d['number']} отменён", reason, "#/kitchen"))
    return messages


def order_delivered(d):
    return [Message(d["customer_id"], "success", f"Заказ № {d['number']} доставлен",
                    "Приятного аппетита! Оцените ресторан, это поможет другим.", _order_link(d))]


def payment_refunded(d):
    card = f" •• {d['card_last4']}" if d.get("card_last4") else ""
    return [Message(d["customer_id"], "info", f"Возврат {_money(d['amount'])}",
                    f"Деньги за заказ № {d['order_number']} вернутся на карту{card} в течение нескольких дней.",
                    f"#/orders/{d['order_id']}")]


def delivery_assigned(d):
    phone = f", {d['courier_phone']}" if d.get("courier_phone") else ""
    return [Message(d["customer_id"], "info", "Курьер назначен",
                    f"{d.get('courier_name') or 'Курьер'}{phone} едет в ресторан за заказом № {d['order_number']}.",
                    f"#/orders/{d['order_id']}")]


def delivery_picked_up(d):
    return [Message(d["customer_id"], "info", "Курьер в пути",
                    f"Заказ № {d['order_number']} уже едет к вам.", f"#/orders/{d['order_id']}")]


def delivery_delivered(d):
    if not d.get("courier_id"):
        return []
    return [Message(d["courier_id"], "success", f"Доставка № {d['order_number']} завершена",
                    f"Заработок: {_money(d.get('courier_fee'))}.", "#/courier/history")]


def review_created(d):
    stars = "★" * int(d["rating"])
    return [Message(d["restaurant_owner_id"], "info", f"Новый отзыв: {stars}",
                    f"{d['restaurant_name']}: {d.get('comment') or 'без комментария'}", "#/my")]


TEMPLATES = {
    "user.registered": user_registered,
    "order.created": order_created,
    "order.paid": order_paid,
    "order.accepted": order_accepted,
    "order.ready": order_ready,
    "order.cancelled": order_cancelled,
    "order.delivered": order_delivered,
    "payment.refunded": payment_refunded,
    "delivery.assigned": delivery_assigned,
    "delivery.picked_up": delivery_picked_up,
    "delivery.delivered": delivery_delivered,
    "review.created": review_created,
}
