import logging
from decimal import Decimal

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from common.auth import CurrentUser, current_user, internal_only
from common.deps import get_session
from common.errors import AppError, BadRequest, Forbidden, NotFound

from . import states
from .models import Order, OrderItem, StatusChange
from .outbox import add_event
from .schemas import CancelIn, OrderIn, OrderOut
from .service import change_status, event_payload

logger = logging.getLogger("orders")
router = APIRouter(prefix="/api/orders", tags=["orders"])
internal = APIRouter(prefix="/internal", tags=["internal"], dependencies=[Depends(internal_only)])


def _can_view(user: CurrentUser, order: Order) -> bool:
    return (user.is_admin or order.customer_id == user.id or order.restaurant_owner_id == user.id
            or (order.courier_id is not None and order.courier_id == user.id))


async def _order(session: AsyncSession, order_id: str) -> Order:
    order = await session.get(Order, order_id)
    if order is None:
        raise NotFound("Заказ не найден")
    return order


async def _visible(session: AsyncSession, user: CurrentUser, order_id: str) -> Order:
    order = await _order(session, order_id)
    if not _can_view(user, order):
        raise NotFound("Заказ не найден")  # не раскрываем, что чужой заказ существует
    return order


async def _customer_profile(request: Request, user: CurrentUser) -> dict:
    """Имя и телефон клиента из auth-service. Если он недоступен, заказ всё равно оформляется."""
    try:
        return await request.app.state.auth.get(f"/internal/users/{user.id}", timeout=2.0)
    except AppError as exc:
        logger.warning(f"auth-service unavailable, ordering without profile: {exc.message}")
        return {"full_name": user.email, "phone": None}


@router.post("", response_model=OrderOut, status_code=201, summary="Оформить заказ")
async def create_order(body: OrderIn, request: Request, response: Response,
                       idempotency_key: str | None = Header(default=None, max_length=64),
                       user: CurrentUser = Depends(current_user), session: AsyncSession = Depends(get_session)):
    if user.role != "customer":
        raise Forbidden("Заказывать еду могут только клиенты")

    if idempotency_key:
        existing = await session.scalar(select(Order).where(Order.customer_id == user.id,
                                                            Order.idempotency_key == idempotency_key))
        if existing:
            response.status_code = 200
            return existing

    # 1. Синхронно: ресторан проверяет блюда и считает цену (цене из браузера не доверяем)
    quote = await request.app.state.restaurants.post(
        f"/internal/restaurants/{body.restaurant_id}/quote",
        json={"items": [line.model_dump() for line in body.items]},
    )
    # 2. Синхронно, но необязательно: контакты клиента для курьера
    profile = await _customer_profile(request, user)
    phone = body.phone or profile.get("phone")
    if not phone:
        raise BadRequest("Укажите телефон, чтобы курьер мог с вами связаться", code="phone_required")

    order = Order(
        customer_id=user.id, customer_name=profile.get("full_name") or user.email, customer_phone=phone,
        restaurant_id=quote["restaurant_id"], restaurant_owner_id=quote["owner_id"],
        restaurant_name=quote["restaurant_name"], restaurant_address=quote["restaurant_address"],
        delivery_address=body.delivery_address.strip(), comment=body.comment.strip(),
        subtotal=Decimal(str(quote["subtotal"])), delivery_fee=Decimal(str(quote["delivery_fee"])),
        total=Decimal(str(quote["total"])), prep_minutes=quote["prep_minutes"], idempotency_key=idempotency_key,
    )
    order.items = [OrderItem(position=i, menu_item_id=line["menu_item_id"], name=line["name"],
                             unit_price=Decimal(str(line["unit_price"])), quantity=line["quantity"],
                             line_total=Decimal(str(line["line_total"]))) for i, line in enumerate(quote["items"])]
    order.history = [StatusChange(status=states.PENDING_PAYMENT, note="Заказ оформлен")]
    session.add(order)
    await session.flush()
    # 3. Асинхронно: событие для payment-service и notification-service (через outbox)
    add_event(session, "order.created", event_payload(
        order, delivery_address=order.delivery_address, customer_name=order.customer_name,
        items=[{"name": i.name, "quantity": i.quantity} for i in order.items]))
    try:
        await session.commit()
    except IntegrityError:  # гонка двух запросов с одним Idempotency-Key
        await session.rollback()
        existing = await session.scalar(select(Order).where(Order.customer_id == user.id,
                                                            Order.idempotency_key == idempotency_key))
        if existing is None:
            raise
        response.status_code = 200
        return existing
    request.app.state.outbox.kick()
    logger.info("Order created", extra={"order_id": order.id, "total": float(order.total),
                                        "restaurant_id": order.restaurant_id})
    return await _order(session, order.id)


@router.get("", response_model=list[OrderOut], summary="Мои заказы")
async def list_orders(status: str | None = Query(None, description="один или несколько статусов через запятую"),
                      active: bool = Query(False, description="только незавершённые"),
                      restaurant_id: str | None = None, limit: int = Query(50, ge=1, le=200),
                      user: CurrentUser = Depends(current_user), session: AsyncSession = Depends(get_session)):
    q = select(Order)
    if user.role == "customer":
        q = q.where(Order.customer_id == user.id)
    elif user.role == "restaurant":
        q = q.where(Order.restaurant_owner_id == user.id)
    elif user.role == "courier":
        q = q.where(Order.courier_id == user.id)
    if restaurant_id:
        q = q.where(Order.restaurant_id == restaurant_id)
    if status:
        q = q.where(Order.status.in_([s.strip() for s in status.split(",") if s.strip()]))
    if active:
        q = q.where(Order.status.not_in(states.FINAL))
    return (await session.scalars(q.order_by(Order.created_at.desc()).limit(limit))).all()


@router.get("/{order_id}", response_model=OrderOut, summary="Заказ: состав и история статусов")
async def get_order(order_id: str, user: CurrentUser = Depends(current_user), session: AsyncSession = Depends(get_session)):
    return await _visible(session, user, order_id)


@router.post("/{order_id}/cancel", response_model=OrderOut, summary="Отменить заказ")
async def cancel_order(order_id: str, request: Request, body: CancelIn | None = None,
                       user: CurrentUser = Depends(current_user), session: AsyncSession = Depends(get_session)):
    order = await _visible(session, user, order_id)
    reason = (body.reason.strip() if body else "") or None
    if user.is_admin:
        allowed, who = order.status not in states.FINAL, "администратор"
    elif order.customer_id == user.id:
        allowed, who = order.status in states.CUSTOMER_CANCELLABLE, "клиент"
    elif order.restaurant_owner_id == user.id:
        allowed, who = order.status in states.RESTAURANT_CANCELLABLE, "ресторан"
    else:
        raise Forbidden("Отменить заказ может клиент, ресторан или администратор")
    if not allowed:
        raise AppError(f"Заказ в статусе «{states.LABELS[order.status]}» уже нельзя отменить",
                       code="cannot_cancel", status_code=409)

    was_paid = order.status != states.PENDING_PAYMENT
    order.cancel_reason = reason or f"Отменён: {who}"
    # order.cancelled: payment-service вернёт деньги, если заказ был оплачен
    change_status(session, order, states.CANCELLED, note=order.cancel_reason, event="order.cancelled",
                  extra={"cancelled_by": who, "reason": order.cancel_reason, "refund": was_paid})
    await session.commit()
    request.app.state.outbox.kick()
    return await _order(session, order.id)


@internal.get("/orders/{order_id}", response_model=OrderOut, summary="Заказ (для других сервисов)")
async def internal_order(order_id: str, session: AsyncSession = Depends(get_session)):
    return await _order(session, order_id)
