from contextlib import asynccontextmanager

from fastapi import FastAPI

from common.app import create_service_app
from common.db import Base, Database
from common.logging import setup_logging
from common.messaging import EventBus

from .api import internal, router
from .config import Settings

DESCRIPTION = """
**Restaurant Service** — рестораны и их меню.

* Каталог ресторанов и меню доступен без входа.
* Владелец (роль `restaurant`) открывает ресторан, ведёт меню, меняет цены и наличие блюд, открывает и закрывает приём заказов.
* Для order-service есть внутренний `POST /internal/restaurants/{id}/quote`: проверяет блюда и считает стоимость.
  Цены всегда берутся из этого сервиса, а не от клиента.

Хранилище: PostgreSQL `restaurant_db` (`restaurants`, `menu_items`).
"""


def build_app(settings: Settings | None = None, bus=None) -> FastAPI:
    settings = settings or Settings()
    setup_logging(settings.service_name, settings.log_level)
    db = Database(settings.database_url)
    bus = bus or EventBus(settings.rabbitmq_url, settings.events_exchange, settings.service_name)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await db.create_schema(Base)
        await bus.start()
        yield
        await bus.close()
        await db.close()

    app = create_service_app(
        title="Restaurant Service", description=DESCRIPTION, service_name=settings.service_name,
        docs_slug="restaurants", lifespan=lifespan, checks={"database": db.ping, "rabbitmq": bus.is_connected},
    )
    app.state.settings, app.state.db, app.state.bus = settings, db, bus
    app.include_router(router)
    app.include_router(internal)
    return app


app = build_app()
