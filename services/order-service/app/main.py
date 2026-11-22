from contextlib import asynccontextmanager

from fastapi import FastAPI

from common.app import create_service_app
from common.db import Base, Database
from common.http import ServiceClient
from common.logging import setup_logging
from common.messaging import EventBus

from .api import internal, router
from .config import Settings
from .events import OrderEventHandlers
from .outbox import OutboxRelay

DESCRIPTION = """
**Order Service** — оформление заказов и их жизненный цикл (конечный автомат статусов).

При оформлении заказа:
1. **синхронно (REST)** спрашивает restaurant-service: есть ли блюда и сколько стоит заказ (`/internal/restaurants/{id}/quote`);
2. **синхронно, но необязательно** берёт имя и телефон клиента из auth-service (если он недоступен, заказ всё равно оформляется);
3. **асинхронно** публикует `order.created` через transactional outbox.

Saga «заказ»: слушает `payment.succeeded` (→ `paid`) и `payment.failed` (→ `cancelled`, компенсация).
Ресторан принимает заказ (`/accept` → `cooking`, событие `order.accepted`) и отмечает готовность
(`/ready` → `ready`, событие `order.ready` для delivery-service).
Доставка: `delivery.assigned` → `courier_assigned`, `delivery.picked_up` → `in_delivery`,
`delivery.delivered` → `delivered` (событие `order.delivered`).

Статусы: `pending_payment → paid → cooking → ready → courier_assigned → in_delivery → delivered`, отмена: `cancelled`.

Хранилище: PostgreSQL `order_db` (`orders`, `order_items`, `order_status_history`, `outbox`).
"""


def build_app(settings: Settings | None = None, bus=None, restaurants_client=None, auth_client=None) -> FastAPI:
    settings = settings or Settings()
    setup_logging(settings.service_name, settings.log_level)
    db = Database(settings.database_url)
    bus = bus or EventBus(settings.rabbitmq_url, settings.events_exchange, settings.service_name)
    restaurants = restaurants_client or ServiceClient(
        "restaurant-service", settings.restaurant_service_url, internal_key=settings.internal_api_key,
        timeout=settings.http_timeout, retries=settings.http_retries)
    auth = auth_client or ServiceClient(
        "auth-service", settings.auth_service_url, internal_key=settings.internal_api_key,
        timeout=settings.http_timeout, retries=0)
    outbox = OutboxRelay(db, bus, settings.outbox_poll_seconds)
    handlers = OrderEventHandlers(db, outbox)
    bus.subscribe(["payment.succeeded"], handlers.on_payment_succeeded)
    bus.subscribe(["payment.failed"], handlers.on_payment_failed)
    bus.subscribe(["delivery.assigned"], handlers.on_delivery_assigned)
    bus.subscribe(["delivery.picked_up"], handlers.on_delivery_picked_up)
    bus.subscribe(["delivery.delivered"], handlers.on_delivery_delivered)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await db.create_schema(Base)
        await bus.start()
        await outbox.start()
        yield
        await outbox.stop()
        await bus.close()
        await restaurants.close()
        await auth.close()
        await db.close()

    app = create_service_app(
        title="Order Service", description=DESCRIPTION, service_name=settings.service_name, docs_slug="orders",
        lifespan=lifespan, checks={"database": db.ping, "rabbitmq": bus.is_connected},
    )
    app.state.settings, app.state.db, app.state.bus, app.state.outbox = settings, db, bus, outbox
    app.state.restaurants, app.state.auth = restaurants, auth
    app.include_router(router)
    app.include_router(internal)
    return app


app = build_app()
