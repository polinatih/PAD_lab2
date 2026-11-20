"""Фабрика FastAPI-приложения: одинаковая "обвязка" для всех сервисов."""

from contextlib import AbstractAsyncContextManager
from typing import Callable

from fastapi import FastAPI

from .errors import install_exception_handlers
from .health import Check, make_health_router
from .middleware import RequestContextMiddleware


def create_service_app(
    *,
    title: str,
    description: str,
    service_name: str,
    docs_slug: str,
    lifespan: Callable[[FastAPI], AbstractAsyncContextManager] | None,
    checks: dict[str, Check],
    version: str = "1.0.0",
) -> FastAPI:
    # Swagger UI каждого сервиса доступен по /docs/<slug>/ — и напрямую, и через gateway
    app = FastAPI(
        title=title,
        description=description,
        version=version,
        lifespan=lifespan,
        docs_url=f"/docs/{docs_slug}/",
        openapi_url=f"/docs/{docs_slug}/openapi.json",
        redoc_url=None,
    )
    app.add_middleware(RequestContextMiddleware)
    install_exception_handlers(app)
    app.include_router(make_health_router(service_name, checks))
    return app
