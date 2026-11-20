import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from common.auth import CurrentUser, admin_user, current_user
from common.deps import get_session
from common.errors import AppError, NotFound

from .gateway import charge, validate_card
from .logic import add_event, aware, fail, now, payload
from .models import Payment, Transaction

logger = logging.getLogger("payments")
router = APIRouter(prefix="/api/payments", tags=["payments"])

STATUS_LABELS = {"pending": "Ожидает оплаты", "succeeded": "Оплачен", "failed": "Не прошёл",
                 "expired": "Время истекло", "refunded": "Деньги возвращены", "cancelled": "Отменён"}


class CardIn(BaseModel):
    card_number: str = Field(min_length=12, max_length=23, examples=["4242 4242 4242 4242"])
    exp_month: int = Field(ge=1, le=12)
    exp_year: int = Field(ge=0, le=2100, description="две или четыре цифры")
    cvc: str = Field(min_length=3, max_length=4)
    holder: str = Field(default="", max_length=100)


class TransactionOut(BaseModel):
    kind: str
    status: str
    amount: float
    card_last4: str | None
    message: str
    created_at: datetime
    model_config = {"from_attributes": True}


class PaymentOut(BaseModel):
    id: str
    order_id: str
    order_number: str
    customer_id: str
    restaurant_name: str
    amount: float
    status: str
    status_label: str
    attempts: int
    attempts_left: int
    card_brand: str | None
    card_last4: str | None
    failure_reason: str | None
    expires_at: datetime
    created_at: datetime
    paid_at: datetime | None
    refunded_at: datetime | None
    transactions: list[TransactionOut]


def out(p: Payment, max_attempts: int) -> PaymentOut:
    return PaymentOut(**{k: getattr(p, k) for k in PaymentOut.model_fields if hasattr(p, k) and k != "transactions"},
                      status_label=STATUS_LABELS.get(p.status, p.status),
                      attempts_left=max(0, max_attempts - p.attempts) if p.status == "pending" else 0,
                      transactions=[TransactionOut.model_validate(t) for t in p.transactions])


async def _payment(session, user: CurrentUser, order_id: str) -> Payment:
    p = await session.scalar(select(Payment).where(Payment.order_id == order_id))
    if p is None or not (user.is_admin or p.customer_id == user.id):
        # Платёж создаётся асинхронно по событию order.created — обычно через доли секунды после заказа
        raise NotFound("Платёж для этого заказа ещё не готов", code="payment_not_ready")
    return p


@router.get("/order/{order_id}", response_model=PaymentOut, summary="Платёж по заказу")
async def get_payment(order_id: str, request: Request, user: CurrentUser = Depends(current_user),
                      session: AsyncSession = Depends(get_session)):
    return out(await _payment(session, user, order_id), request.app.state.settings.max_attempts)


@router.post("/order/{order_id}/pay", response_model=PaymentOut, summary="Оплатить заказ картой")
async def pay(order_id: str, body: CardIn, request: Request, user: CurrentUser = Depends(current_user),
              session: AsyncSession = Depends(get_session)):
    settings = request.app.state.settings
    p = await _payment(session, user, order_id)
    if p.status != "pending":
        raise AppError(f"Платёж уже в статусе «{STATUS_LABELS[p.status]}»", code="payment_closed", status_code=409)
    if aware(p.expires_at) <= now():
        fail(session, p, "Время на оплату истекло", status="expired")
        await session.commit()
        request.app.state.outbox.kick()
        raise AppError("Время на оплату истекло, заказ отменён", code="payment_expired", status_code=409)

    number = "".join(ch for ch in body.card_number if ch.isdigit())
    errors = validate_card(number, body.exp_month, body.exp_year, body.cvc)
    if errors:
        raise AppError("Проверьте данные карты", code="invalid_card", status_code=422, details=errors)

    result = charge(number)
    p.attempts += 1
    p.card_brand, p.card_last4 = result.brand, result.last4
    p.transactions.append(Transaction(kind="charge", status="approved" if result.approved else "declined",
                                      amount=p.amount, card_last4=result.last4, message=result.message))
    if result.approved:
        p.status, p.paid_at, p.failure_reason = "succeeded", now(), None
        add_event(session, "payment.succeeded", payload(p, card_brand=result.brand))
        logger.info("Payment succeeded", extra={"order_id": order_id, "amount": float(p.amount)})
    elif p.attempts >= settings.max_attempts:
        fail(session, p, f"{result.message}. Попытки оплаты закончились")
    else:
        p.failure_reason = result.message
        logger.info("Payment declined", extra={"order_id": order_id, "attempt": p.attempts})
    await session.commit()
    request.app.state.outbox.kick()

    if not result.approved and p.status == "pending":
        left = settings.max_attempts - p.attempts
        raise AppError(f"{result.message}. Осталось попыток: {left}", code="card_declined", status_code=402,
                       details={"attempts_left": left})
    if p.status == "failed":
        raise AppError(p.failure_reason, code="payment_failed", status_code=402)
    return out(p, settings.max_attempts)


@router.get("", response_model=list[PaymentOut], summary="Все платежи (admin)")
async def list_payments(request: Request, status: str | None = None, limit: int = Query(100, ge=1, le=500),
                        _: CurrentUser = Depends(admin_user),
                        session: AsyncSession = Depends(get_session)):
    q = select(Payment).order_by(Payment.created_at.desc()).limit(limit)
    if status:
        q = q.where(Payment.status == status)
    return [out(p, request.app.state.settings.max_attempts) for p in (await session.scalars(q)).all()]
