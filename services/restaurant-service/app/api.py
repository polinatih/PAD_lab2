import logging
from decimal import ROUND_HALF_UP, Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from common.auth import CurrentUser, current_user, internal_only
from common.deps import get_session
from common.errors import AppError, BadRequest, Forbidden, NotFound

from .models import MenuItem, Restaurant
from .schemas import (CUISINES, MenuItemIn, MenuItemOut, MenuItemPatch, QuoteIn, QuoteLineOut, QuoteOut,
                      RestaurantDetail, RestaurantIn, RestaurantOut, RestaurantPatch)

logger = logging.getLogger("restaurants")
router = APIRouter(prefix="/api/restaurants", tags=["restaurants"])
internal = APIRouter(prefix="/internal", tags=["internal"], dependencies=[Depends(internal_only)])

MONEY_FIELDS = {"delivery_fee", "min_order", "price"}


def money(value: float | Decimal) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _apply(obj, data: dict) -> None:
    for field, value in data.items():
        setattr(obj, field, money(value) if field in MONEY_FIELDS and value is not None else value)


async def _restaurant(session: AsyncSession, restaurant_id: str) -> Restaurant:
    rest = await session.get(Restaurant, restaurant_id)
    if rest is None:
        raise NotFound("Ресторан не найден")
    return rest


async def _owned(session: AsyncSession, user: CurrentUser, restaurant_id: str) -> Restaurant:
    rest = await _restaurant(session, restaurant_id)
    if not (user.is_admin or rest.owner_id == user.id):
        raise Forbidden("Управлять рестораном может только его владелец")
    return rest


async def _menu(session: AsyncSession, restaurant_id: str, only_available: bool = False) -> list[MenuItem]:
    q = select(MenuItem).where(MenuItem.restaurant_id == restaurant_id)
    if only_available:
        q = q.where(MenuItem.is_available.is_(True))
    return (await session.scalars(q.order_by(MenuItem.category, MenuItem.name))).all()


# ---------- каталог (доступен всем, без входа) ----------

@router.get("", response_model=list[RestaurantOut], summary="Каталог ресторанов")
async def list_restaurants(q: str | None = Query(None, max_length=100, description="поиск по названию и описанию"),
                           cuisine: str | None = Query(None, max_length=40),
                           open_only: bool = False,
                           session: AsyncSession = Depends(get_session)):
    stmt = select(Restaurant)
    if q:
        pattern = f"%{q.strip()}%"
        stmt = stmt.where(or_(Restaurant.name.ilike(pattern), Restaurant.description.ilike(pattern)))
    if cuisine:
        stmt = stmt.where(Restaurant.cuisine == cuisine)
    if open_only:
        stmt = stmt.where(Restaurant.is_open.is_(True))
    stmt = stmt.order_by(Restaurant.is_open.desc(), Restaurant.rating_avg.desc(), Restaurant.name)
    return (await session.scalars(stmt)).all()


@router.get("/cuisines", summary="Кухни, которые есть в каталоге")
async def cuisines(session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(select(Restaurant.cuisine, func.count()).group_by(Restaurant.cuisine))).all()
    present = {c: n for c, n in rows}
    return {"present": [{"cuisine": c, "restaurants": n} for c, n in sorted(present.items())], "suggested": CUISINES}


@router.get("/mine", response_model=list[RestaurantOut], summary="Мои рестораны (владелец)")
async def my_restaurants(user: CurrentUser = Depends(current_user), session: AsyncSession = Depends(get_session)):
    return (await session.scalars(select(Restaurant).where(Restaurant.owner_id == user.id)
                                  .order_by(Restaurant.created_at))).all()


@router.get("/{restaurant_id}", response_model=RestaurantDetail, summary="Ресторан и его меню")
async def get_restaurant(restaurant_id: str, session: AsyncSession = Depends(get_session)):
    rest = await _restaurant(session, restaurant_id)
    menu = await _menu(session, restaurant_id)
    return RestaurantDetail(**RestaurantOut.model_validate(rest).model_dump(),
                            menu=[MenuItemOut.model_validate(m) for m in menu])


# ---------- управление рестораном (владелец или администратор) ----------

@router.post("", response_model=RestaurantOut, status_code=201, summary="Открыть ресторан (роль restaurant)")
async def create_restaurant(body: RestaurantIn, user: CurrentUser = Depends(current_user),
                            session: AsyncSession = Depends(get_session)):
    if user.role not in ("restaurant", "admin"):
        raise Forbidden("Создавать рестораны могут только пользователи с ролью «Ресторан»")
    rest = Restaurant(owner_id=user.id)
    _apply(rest, body.model_dump())
    session.add(rest)
    await session.commit()
    logger.info("Restaurant created", extra={"restaurant_id": rest.id, "owner_id": user.id})
    return rest


@router.patch("/{restaurant_id}", response_model=RestaurantOut, summary="Изменить ресторан, открыть или закрыть")
async def update_restaurant(restaurant_id: str, body: RestaurantPatch, user: CurrentUser = Depends(current_user),
                            session: AsyncSession = Depends(get_session)):
    rest = await _owned(session, user, restaurant_id)
    _apply(rest, body.model_dump(exclude_unset=True))
    await session.commit()
    logger.info("Restaurant updated", extra={"restaurant_id": rest.id, "is_open": rest.is_open})
    return rest


@router.post("/{restaurant_id}/menu", response_model=MenuItemOut, status_code=201, summary="Добавить блюдо")
async def add_menu_item(restaurant_id: str, body: MenuItemIn, user: CurrentUser = Depends(current_user),
                        session: AsyncSession = Depends(get_session)):
    await _owned(session, user, restaurant_id)
    item = MenuItem(restaurant_id=restaurant_id)
    _apply(item, body.model_dump())
    session.add(item)
    await session.commit()
    return item


async def _owned_item(session, user, restaurant_id: str, item_id: str) -> MenuItem:
    await _owned(session, user, restaurant_id)
    item = await session.get(MenuItem, item_id)
    if item is None or item.restaurant_id != restaurant_id:
        raise NotFound("Блюдо не найдено")
    return item


@router.patch("/{restaurant_id}/menu/{item_id}", response_model=MenuItemOut, summary="Изменить блюдо (цена, наличие)")
async def update_menu_item(restaurant_id: str, item_id: str, body: MenuItemPatch,
                           user: CurrentUser = Depends(current_user), session: AsyncSession = Depends(get_session)):
    item = await _owned_item(session, user, restaurant_id, item_id)
    _apply(item, body.model_dump(exclude_unset=True))
    await session.commit()
    return item


@router.delete("/{restaurant_id}/menu/{item_id}", status_code=204, summary="Удалить блюдо")
async def delete_menu_item(restaurant_id: str, item_id: str, user: CurrentUser = Depends(current_user),
                           session: AsyncSession = Depends(get_session)):
    item = await _owned_item(session, user, restaurant_id, item_id)
    await session.delete(item)
    await session.commit()


# ---------- внутренний API (вызывается order-service при оформлении заказа) ----------

@internal.get("/restaurants/{restaurant_id}", response_model=RestaurantOut, summary="Данные ресторана")
async def internal_restaurant(restaurant_id: str, session: AsyncSession = Depends(get_session)):
    return await _restaurant(session, restaurant_id)


@internal.post("/restaurants/{restaurant_id}/quote", response_model=QuoteOut,
               summary="Проверить блюда и посчитать стоимость заказа")
async def quote(restaurant_id: str, body: QuoteIn, session: AsyncSession = Depends(get_session)):
    """Цены считает ресторан, а не клиент: order-service не доверяет ценам из браузера."""
    rest = await _restaurant(session, restaurant_id)
    if not rest.is_open:
        raise AppError("Ресторан сейчас закрыт и не принимает заказы", code="restaurant_closed", status_code=409)

    menu = {m.id: m for m in await _menu(session, restaurant_id)}
    quantities: dict[str, int] = {}
    for line in body.items:  # одинаковые позиции складываем
        quantities[line.menu_item_id] = quantities.get(line.menu_item_id, 0) + line.quantity

    lines, problems = [], []
    for item_id, qty in quantities.items():
        item = menu.get(item_id)
        if item is None:
            problems.append({"menu_item_id": item_id, "message": "Блюда нет в меню этого ресторана"})
        elif not item.is_available:
            problems.append({"menu_item_id": item_id, "message": f"«{item.name}» сейчас недоступно"})
        else:
            lines.append(QuoteLineOut(menu_item_id=item.id, name=item.name, unit_price=float(item.price),
                                      quantity=qty, line_total=float(money(item.price * qty))))
    if problems:
        raise AppError("Некоторые блюда нельзя заказать", code="items_unavailable", status_code=409, details=problems)

    subtotal = money(sum(Decimal(str(line.line_total)) for line in lines))
    if subtotal < rest.min_order:
        raise BadRequest(f"Минимальная сумма заказа в этом ресторане — {rest.min_order} лей", code="below_min_order")
    total = money(subtotal + rest.delivery_fee)
    return QuoteOut(restaurant_id=rest.id, restaurant_name=rest.name, restaurant_address=rest.address,
                    owner_id=rest.owner_id, prep_minutes=rest.prep_minutes, items=lines, subtotal=float(subtotal),
                    delivery_fee=float(rest.delivery_fee), total=float(total))
