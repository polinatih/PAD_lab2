from contextlib import asynccontextmanager

from fastapi import FastAPI

from common.app import create_service_app
from common.db import Base, Database
from common.logging import setup_logging
from common.messaging import EventBus

from .api import bootstrap_admin, internal, router
from .config import Settings

DESCRIPTION = """
**Auth Service** — регистрация, вход и выпуск JWT-токенов, профиль, роли.

Роли: `customer` (клиент), `restaurant` (владелец ресторана), `courier` (курьер), `admin`.

Хранилище: PostgreSQL `auth_db` (таблица `users`).
Публикует событие `user.registered`.
"""


def build_app(settings: Settings | None = None, bus=None) -> FastAPI:
    settings = settings or Settings()
    setup_logging(settings.service_name, settings.log_level)
    db = Database(settings.database_url)
    bus = bus or EventBus(settings.rabbitmq_url, settings.events_exchange, settings.service_name)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await db.create_schema(Base)
        await bootstrap_admin(app)
        await bus.start()
        yield
        await bus.close()
        await db.close()

    app = create_service_app(
        title="Auth Service", description=DESCRIPTION, service_name=settings.service_name, docs_slug="auth",
        lifespan=lifespan, checks={"database": db.ping, "rabbitmq": bus.is_connected},
    )
    app.state.settings, app.state.db, app.state.bus = settings, db, bus
    app.include_router(router)
    app.include_router(internal)
    return app


app = build_app()
