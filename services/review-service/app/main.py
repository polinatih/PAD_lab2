import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.exc import IntegrityError

from common.app import create_service_app
from common.db import Base, Database
from common.errors import AppError
from common.http import ServiceClient
from common.logging import setup_logging
from common.messaging import EventBus

from .api import router
from .config import Settings
from .models import DeliveredOrder
from .outbox import OutboxRelay

logger = logging.getLogger("reviews")

DESCRIPTION = """
**Review Service** — отзывы и рейтинги ресторанов.

* слушает `order.delivered` → запоминает, что клиент может оценить этот заказ;
* клиент ставит оценку 1–5 и пишет комментарий (один отзыв на заказ) → `review.created`
  (restaurant-service пересчитывает рейтинг в каталоге, notification-service сообщает ресторану);
* владелец ресторана может ответить на отзыв.

При старте сверяется с order-service: доставленные заказы, пропущенные пока сервис не работал, тоже можно оценить.
Хранилище: PostgreSQL `review_db` (`reviews`, `delivered_orders`, `outbox`).
"""


async def remember_delivered(db, d: dict) -> bool:
    async with db.sessionmaker() as session:
        if await session.get(DeliveredOrder, d["order_id"]):
            return False
        session.add(DeliveredOrder(order_id=d["order_id"], order_number=d.get("number", ""),
                                   customer_id=d["customer_id"], restaurant_id=d["restaurant_id"],
                                   restaurant_owner_id=d["restaurant_owner_id"],
                                   restaurant_name=d.get("restaurant_name", ""), customer_name=d.get("customer_name") or ""))
        try:
            await session.commit()
            return True
        except IntegrityError:
            await session.rollback()
            return False


async def reconcile(db, orders_client) -> None:
    for _ in range(10):
        try:
            delivered = await orders_client.get("/internal/orders", params={"status": "delivered", "limit": 1000})
            break
        except AppError as exc:
            logger.warning(f"Reconcile: order-service unavailable ({exc.message}), retry")
            await asyncio.sleep(3)
    else:
        return
    added = 0
    for o in delivered:
        added += await remember_delivered(db, {"order_id": o["id"], "number": o["number"], "customer_id": o["customer_id"],
                                               "restaurant_id": o["restaurant_id"], "restaurant_owner_id": o["restaurant_owner_id"],
                                               "restaurant_name": o["restaurant_name"], "customer_name": o["customer_name"]})
    if added:
        logger.info(f"Reconcile: {added} delivered orders added")


def build_app(settings: Settings | None = None, bus=None, orders_client=None) -> FastAPI:
    settings = settings or Settings()
    setup_logging(settings.service_name, settings.log_level)
    db = Database(settings.database_url)
    bus = bus or EventBus(settings.rabbitmq_url, settings.events_exchange, settings.service_name)
    orders = orders_client or ServiceClient("order-service", settings.order_service_url,
                                            internal_key=settings.internal_api_key, timeout=settings.http_timeout, retries=1)
    outbox = OutboxRelay(db, bus, settings.outbox_poll_seconds)

    async def on_order_delivered(envelope: dict) -> None:
        await remember_delivered(db, envelope["data"])

    bus.subscribe(["order.delivered"], on_order_delivered)

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
        await orders.close()
        await db.close()

    app = create_service_app(
        title="Review Service", description=DESCRIPTION, service_name=settings.service_name, docs_slug="reviews",
        lifespan=lifespan, checks={"database": db.ping, "rabbitmq": bus.is_connected},
    )
    app.state.settings, app.state.db, app.state.bus, app.state.outbox = settings, db, bus, outbox
    app.include_router(router)
    return app


app = build_app()
