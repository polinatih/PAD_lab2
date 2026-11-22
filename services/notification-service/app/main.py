from contextlib import asynccontextmanager

from fastapi import FastAPI

from common.app import create_service_app
from common.db import Base, Database
from common.logging import setup_logging
from common.messaging import EventBus

from .api import make_handler, router
from .config import Settings
from .templates import TEMPLATES

DESCRIPTION = """
**Notification Service** — уведомления клиентам, ресторанам и курьерам.

Ни один сервис не вызывает его напрямую: он только **слушает события** RabbitMQ
(`order.*`, `payment.refunded`, `delivery.*`, `review.created`, `user.registered`)
и превращает их в уведомления для нужных людей. Если сервис недоступен, события ждут в его очереди.

Хранилище: PostgreSQL `notification_db` (`notifications`).
"""


def build_app(settings: Settings | None = None, bus=None) -> FastAPI:
    settings = settings or Settings()
    setup_logging(settings.service_name, settings.log_level)
    db = Database(settings.database_url)
    bus = bus or EventBus(settings.rabbitmq_url, settings.events_exchange, settings.service_name)
    bus.subscribe(list(TEMPLATES), make_handler(db))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await db.create_schema(Base)
        await bus.start()
        yield
        await bus.close()
        await db.close()

    app = create_service_app(
        title="Notification Service", description=DESCRIPTION, service_name=settings.service_name,
        docs_slug="notifications", lifespan=lifespan, checks={"database": db.ping, "rabbitmq": bus.is_connected},
    )
    app.state.settings, app.state.db, app.state.bus = settings, db, bus
    app.include_router(router)
    return app


app = build_app()
