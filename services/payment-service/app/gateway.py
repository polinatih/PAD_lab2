"""Эмуляция платёжного шлюза (настоящий банк в учебном проекте не подключаем).

Проверки как у настоящего шлюза: алгоритм Луна, срок действия, CVC.
Тестовые карты (как у Stripe):
    4242 4242 4242 4242 — оплата проходит
    4000 0000 0000 0002 — отказ банка: недостаточно средств
    4000 0000 0000 0069 — отказ: срок действия карты истёк по данным банка
Номер карты никогда не сохраняется: в БД пишутся только платёжная система и последние 4 цифры.
"""

from dataclasses import dataclass
from datetime import date

DECLINES = {
    "4000000000000002": "Банк отклонил платёж: недостаточно средств",
    "4000000000000069": "Банк отклонил платёж: карта просрочена",
}


@dataclass
class ChargeResult:
    approved: bool
    message: str
    brand: str
    last4: str


def luhn_ok(number: str) -> bool:
    digits = [int(d) for d in number][::-1]
    total = sum(d if i % 2 == 0 else (d * 2 - 9 if d * 2 > 9 else d * 2) for i, d in enumerate(digits))
    return total % 10 == 0


def brand_of(number: str) -> str:
    if number.startswith("4"):
        return "Visa"
    if number[:2] in {"51", "52", "53", "54", "55"} or 2221 <= int(number[:4]) <= 2720:
        return "Mastercard"
    return "Карта"


def validate_card(number: str, exp_month: int, exp_year: int, cvc: str, today: date | None = None) -> list[dict]:
    """Ошибки в формате API: [{"field", "message"}]. Пустой список — карта корректна."""
    today = today or date.today()
    errors = []
    if not number.isdigit() or not 13 <= len(number) <= 19 or not luhn_ok(number):
        errors.append({"field": "card_number", "message": "Проверьте номер карты"})
    year = exp_year + 2000 if exp_year < 100 else exp_year
    if not 1 <= exp_month <= 12 or (year, exp_month) < (today.year, today.month):
        errors.append({"field": "expiry", "message": "Срок действия карты истёк или указан неверно"})
    if not cvc.isdigit() or len(cvc) not in (3, 4):
        errors.append({"field": "cvc", "message": "CVC — 3 цифры на обороте карты"})
    return errors


def charge(number: str) -> ChargeResult:
    decline = DECLINES.get(number)
    return ChargeResult(approved=decline is None, message=decline or "Оплата прошла", brand=brand_of(number),
                        last4=number[-4:])
