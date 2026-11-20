from contextlib import asynccontextmanager

from fastapi import FastAPI

from common.app import create_service_app
from common.db import Base, Database
from common.logging import setup_logging
from common.messaging import EventBus

from .api import router
from .config import Settings
from .logic import PaymentHandlers
from .outbox import OutboxRelay

DESCRIPTION = """
**Payment Service** — оплата заказов (эмуляция платёжного шлюза) и возвраты.

Участник saga «заказ»:
* слушает `order.created` → создаёт платёж и ждёт оплату;
* клиент платит картой → `payment.succeeded`;
* 3 отказа банка или истекло время на оплату → `payment.failed` (order-service отменяет заказ);
* слушает `order.cancelled` → если заказ был оплачен, возвращает деньги → `payment.refunded`.

Тестовые карты: `4242 4242 4242 4242` — успех, `4000 0000 0000 0002` — отказ (недостаточно средств).

Хранилище: PostgreSQL `payment_db` (`payments`, `transactions`, `outbox`). Номера карт не хранятся.
"""


def build_app(settings: Settings | None = None, bus=None) -> FastAPI:
    settings = settings or Settings()
    setup_logging(settings.service_name, settings.log_level)
    db = Database(settings.database_url)
    bus = bus or EventBus(settings.rabbitmq_url, settings.events_exchange, settings.service_name)
    outbox = OutboxRelay(db, bus, settings.outbox_poll_seconds)
    handlers = PaymentHandlers(db, outbox, settings)
    bus.subscribe(["order.created"], handlers.on_order_created)
    bus.subscribe(["order.cancelled"], handlers.on_order_cancelled)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await db.create_schema(Base)
        await bus.start()
        await outbox.start()
        await handlers.start()
        yield
        await handlers.stop()
        await outbox.stop()
        await bus.close()
        await db.close()

    app = create_service_app(
        title="Payment Service", description=DESCRIPTION, service_name=settings.service_name, docs_slug="payments",
        lifespan=lifespan, checks={"database": db.ping, "rabbitmq": bus.is_connected},
    )
    app.state.settings, app.state.db, app.state.bus = settings, db, bus
    app.state.outbox, app.state.handlers = outbox, handlers
    app.include_router(router)
    return app


app = build_app()
