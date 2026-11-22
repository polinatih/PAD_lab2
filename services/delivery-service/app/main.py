import asyncio
import logging
from contextlib import asynccontextmanager
from decimal import Decimal

from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from common.app import create_service_app
from common.db import Base, Database
from common.errors import AppError
from common.http import ServiceClient
from common.logging import setup_logging
from common.messaging import EventBus

from .api import router
from .config import Settings
from .models import Delivery
from .outbox import OutboxRelay

logger = logging.getLogger("deliveries")

DESCRIPTION = """
**Delivery Service** — курьеры и доставка заказов.

* слушает `order.ready` → создаёт доставку со статусом «ищем курьера»;
* курьер выходит на линию и берёт заказ (атомарно: один заказ — один курьер) → `delivery.assigned`;
* «забрал в ресторане» → `delivery.picked_up`, «доставил» → `delivery.delivered`.

Синхронно (REST) берёт имя и телефон курьера из auth-service, чтобы клиент мог ему позвонить.
При старте сверяется с order-service (`/internal/orders?status=ready`): если событие `order.ready`
было пропущено, пока сервис не работал, доставка всё равно появится.
Хранилище: PostgreSQL `delivery_db` (`deliveries`, `couriers`, `outbox`).
"""


def make_order_ready_handler(db):
    async def on_order_ready(envelope: dict) -> None:
        await create_delivery(db, envelope["data"])

    return on_order_ready


async def create_delivery(db, d: dict) -> bool:
    async with db.sessionmaker() as session:
        if await session.scalar(select(Delivery).where(Delivery.order_id == d["order_id"])):
            return False  # повторная доставка события
        session.add(Delivery(
            order_id=d["order_id"], order_number=d.get("number", ""), customer_id=d["customer_id"],
            customer_name=d.get("customer_name") or "", customer_phone=d.get("customer_phone"),
            restaurant_name=d.get("restaurant_name", ""), restaurant_address=d.get("restaurant_address", ""),
            delivery_address=d.get("delivery_address", ""), comment=d.get("comment") or "",
            order_total=Decimal(str(d.get("total", 0))), courier_fee=Decimal(str(d.get("delivery_fee", 0))),
        ))
        try:
            await session.commit()
            logger.info("Looking for a courier", extra={"order_id": d["order_id"]})
            return True
        except IntegrityError:
            await session.rollback()
            return False


async def reconcile(db, orders_client) -> None:
    """Сверка при старте: заказы, которые ждут курьера, но о которых мы не знаем
    (например, событие order.ready ушло, пока delivery-service не работал), добавляем в список доставок."""
    for attempt in range(10):
        try:
            ready = await orders_client.get("/internal/orders", params={"status": "ready"})
            break
        except AppError as exc:
            logger.warning(f"Reconcile: order-service unavailable ({exc.message}), retry")
            await asyncio.sleep(3)
    else:
        return
    added = 0
    for o in ready:
        added += await create_delivery(db, {
            "order_id": o["id"], "number": o["number"], "customer_id": o["customer_id"],
            "customer_name": o["customer_name"], "customer_phone": o["customer_phone"],
            "restaurant_name": o["restaurant_name"], "restaurant_address": o["restaurant_address"],
            "delivery_address": o["delivery_address"], "comment": o["comment"], "total": o["total"],
            "delivery_fee": o["delivery_fee"]})
    if added:
        logger.info(f"Reconcile: {added} ready orders added", extra={"added": added})


def build_app(settings: Settings | None = None, bus=None, auth_client=None, orders_client=None) -> FastAPI:
    settings = settings or Settings()
    setup_logging(settings.service_name, settings.log_level)
    db = Database(settings.database_url)
    bus = bus or EventBus(settings.rabbitmq_url, settings.events_exchange, settings.service_name)
    auth = auth_client or ServiceClient("auth-service", settings.auth_service_url,
                                        internal_key=settings.internal_api_key, timeout=settings.http_timeout, retries=0)
    orders = orders_client or ServiceClient("order-service", settings.order_service_url,
                                            internal_key=settings.internal_api_key, timeout=settings.http_timeout, retries=1)
    outbox = OutboxRelay(db, bus, settings.outbox_poll_seconds)
    bus.subscribe(["order.ready"], make_order_ready_handler(db))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await db.create_schema(Base)
        await bus.start()
        await outbox.start()
        sync = asyncio.create_task(reconcile(db, orders))
        yield
        sync.cancel()
        await outbox.stop()
        await bus.close()
        await auth.close()
        await orders.close()
        await db.close()

    app = create_service_app(
        title="Delivery Service", description=DESCRIPTION, service_name=settings.service_name,
        docs_slug="deliveries", lifespan=lifespan, checks={"database": db.ping, "rabbitmq": bus.is_connected},
    )
    app.state.settings, app.state.db, app.state.bus = settings, db, bus
    app.state.outbox, app.state.auth = outbox, auth
    app.include_router(router)
    return app


app = build_app()
