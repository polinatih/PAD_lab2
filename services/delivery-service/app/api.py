import logging
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from common.auth import CurrentUser, current_user
from common.deps import get_session
from common.errors import AppError, Conflict, Forbidden, NotFound

from .models import Courier, Delivery
from .outbox import add_event

logger = logging.getLogger("deliveries")
router = APIRouter(prefix="/api/deliveries", tags=["deliveries"])

ACTIVE = ("assigned", "picked_up")
STATUS_LABELS = {"searching": "Ищем курьера", "assigned": "Курьер едет в ресторан",
                 "picked_up": "Курьер везёт заказ", "delivered": "Доставлен"}


def now() -> datetime:
    return datetime.now(timezone.utc)


class DeliveryOut(BaseModel):
    id: str
    order_id: str
    order_number: str
    customer_name: str
    customer_phone: str | None
    restaurant_name: str
    restaurant_address: str
    delivery_address: str
    comment: str
    order_total: float
    courier_fee: float
    status: str
    status_label: str
    courier_id: str | None
    courier_name: str | None
    courier_phone: str | None
    created_at: datetime
    assigned_at: datetime | None
    picked_up_at: datetime | None
    delivered_at: datetime | None


def out(d: Delivery) -> DeliveryOut:
    data = {k: getattr(d, k) for k in DeliveryOut.model_fields if k != "status_label"}
    return DeliveryOut(**data, status_label=STATUS_LABELS.get(d.status, d.status))


class OnlineIn(BaseModel):
    is_online: bool


def _courier_only(user: CurrentUser) -> None:
    if user.role != "courier":
        raise Forbidden("Раздел доступен только курьерам")


async def _courier(session: AsyncSession, user_id: str) -> Courier:
    courier = await session.get(Courier, user_id)
    if courier is None:
        courier = Courier(user_id=user_id, is_online=False)
        session.add(courier)
        try:
            await session.flush()
        except IntegrityError:
            await session.rollback()
            courier = await session.get(Courier, user_id)
    return courier


def _event(d: Delivery) -> dict:
    return {"delivery_id": d.id, "order_id": d.order_id, "order_number": d.order_number,
            "customer_id": d.customer_id, "courier_id": d.courier_id, "courier_name": d.courier_name,
            "courier_phone": d.courier_phone, "restaurant_name": d.restaurant_name, "status": d.status}


# ---------- статус курьера ----------

@router.get("/couriers/me", summary="Мой статус и статистика за сегодня")
async def my_status(user: CurrentUser = Depends(current_user), session: AsyncSession = Depends(get_session)):
    _courier_only(user)
    courier = await _courier(session, user.id)
    await session.commit()
    start = now().replace(hour=0, minute=0, second=0, microsecond=0)
    rows = (await session.scalars(select(Delivery).where(Delivery.courier_id == user.id,
                                                         Delivery.status == "delivered"))).all()
    today = [d for d in rows if d.delivered_at and (d.delivered_at.replace(tzinfo=timezone.utc)
                                                    if d.delivered_at.tzinfo is None else d.delivered_at) >= start]
    return {"is_online": courier.is_online, "delivered_today": len(today),
            "earned_today": float(sum((d.courier_fee for d in today), Decimal("0"))), "delivered_total": len(rows)}


@router.put("/couriers/me", summary="Выйти на линию или уйти с линии")
async def set_online(body: OnlineIn, user: CurrentUser = Depends(current_user), session: AsyncSession = Depends(get_session)):
    _courier_only(user)
    courier = await _courier(session, user.id)
    if not body.is_online:
        active = await session.scalar(select(func.count()).select_from(Delivery).where(
            Delivery.courier_id == user.id, Delivery.status.in_(ACTIVE)))
        if active:
            raise Conflict("Сначала завершите текущую доставку", code="active_delivery")
    courier.is_online = body.is_online
    await session.commit()
    logger.info("Courier online" if body.is_online else "Courier offline", extra={"courier_id": user.id})
    return {"is_online": courier.is_online}


# ---------- доставки ----------

@router.get("/available", response_model=list[DeliveryOut], summary="Заказы, которые ждут курьера")
async def available(user: CurrentUser = Depends(current_user), session: AsyncSession = Depends(get_session)):
    _courier_only(user)
    rows = (await session.scalars(select(Delivery).where(Delivery.status == "searching")
                                  .order_by(Delivery.created_at))).all()
    return [out(d) for d in rows]


@router.get("/mine", response_model=list[DeliveryOut], summary="Мои доставки")
async def mine(active: bool = Query(False), limit: int = Query(50, ge=1, le=200),
               user: CurrentUser = Depends(current_user), session: AsyncSession = Depends(get_session)):
    _courier_only(user)
    q = select(Delivery).where(Delivery.courier_id == user.id)
    if active:
        q = q.where(Delivery.status.in_(ACTIVE))
    rows = (await session.scalars(q.order_by(Delivery.created_at.desc()).limit(limit))).all()
    return [out(d) for d in rows]


@router.get("/order/{order_id}", response_model=DeliveryOut, summary="Доставка по заказу")
async def by_order(order_id: str, user: CurrentUser = Depends(current_user), session: AsyncSession = Depends(get_session)):
    d = await session.scalar(select(Delivery).where(Delivery.order_id == order_id))
    if d is None or not (user.is_admin or user.id in (d.customer_id, d.courier_id)):
        raise NotFound("Доставка не найдена")
    return out(d)


async def _courier_contacts(request: Request, user: CurrentUser) -> dict:
    """Имя и телефон курьера — синхронно из auth-service; если он недоступен, берём то, что есть в токене."""
    try:
        return await request.app.state.auth.get(f"/internal/users/{user.id}", timeout=2.0)
    except AppError as exc:
        logger.warning(f"auth-service unavailable: {exc.message}")
        return {"full_name": user.email, "phone": None}


@router.post("/{delivery_id}/claim", response_model=DeliveryOut, summary="Взять заказ")
async def claim(delivery_id: str, request: Request, user: CurrentUser = Depends(current_user),
                session: AsyncSession = Depends(get_session)):
    _courier_only(user)
    courier = await _courier(session, user.id)
    if not courier.is_online:
        raise Conflict("Выйдите на линию, чтобы брать заказы", code="courier_offline")
    active = await session.scalar(select(func.count()).select_from(Delivery).where(
        Delivery.courier_id == user.id, Delivery.status.in_(ACTIVE)))
    if active >= request.app.state.settings.max_active_per_courier:
        raise Conflict("Сначала доставьте текущий заказ", code="too_many_active")

    contacts = await _courier_contacts(request, user)
    # Атомарно: заказ получит только один курьер, даже если двое нажали «Взять» одновременно
    result = await session.execute(
        update(Delivery).where(Delivery.id == delivery_id, Delivery.status == "searching")
        .values(status="assigned", courier_id=user.id, courier_name=contacts.get("full_name") or user.email,
                courier_phone=contacts.get("phone"), assigned_at=now())
    )
    if result.rowcount == 0:
        await session.rollback()
        if await session.get(Delivery, delivery_id) is None:
            raise NotFound("Доставка не найдена")
        raise Conflict("Этот заказ уже взял другой курьер", code="already_taken")
    d = await session.get(Delivery, delivery_id)
    await session.refresh(d)
    add_event(session, "delivery.assigned", _event(d))
    await session.commit()
    request.app.state.outbox.kick()
    logger.info("Delivery claimed", extra={"order_id": d.order_id, "courier_id": user.id})
    return out(d)


async def _my_delivery(session, user: CurrentUser, delivery_id: str) -> Delivery:
    _courier_only(user)
    d = await session.get(Delivery, delivery_id)
    if d is None or d.courier_id != user.id:
        raise NotFound("Доставка не найдена")
    return d


@router.post("/{delivery_id}/pickup", response_model=DeliveryOut, summary="Забрал заказ в ресторане")
async def pickup(delivery_id: str, request: Request, user: CurrentUser = Depends(current_user),
                 session: AsyncSession = Depends(get_session)):
    d = await _my_delivery(session, user, delivery_id)
    if d.status != "assigned":
        raise Conflict("Заказ уже забран или доставлен", code="invalid_delivery_status")
    d.status, d.picked_up_at = "picked_up", now()
    add_event(session, "delivery.picked_up", _event(d))
    await session.commit()
    request.app.state.outbox.kick()
    return out(d)


@router.post("/{delivery_id}/deliver", response_model=DeliveryOut, summary="Доставил заказ клиенту")
async def deliver(delivery_id: str, request: Request, user: CurrentUser = Depends(current_user),
                  session: AsyncSession = Depends(get_session)):
    d = await _my_delivery(session, user, delivery_id)
    if d.status != "picked_up":
        raise Conflict("Сначала заберите заказ в ресторане", code="invalid_delivery_status")
    d.status, d.delivered_at = "delivered", now()
    add_event(session, "delivery.delivered", _event(d) | {"courier_fee": float(d.courier_fee)})
    await session.commit()
    request.app.state.outbox.kick()
    logger.info("Delivery completed", extra={"order_id": d.order_id, "courier_id": user.id})
    return out(d)
