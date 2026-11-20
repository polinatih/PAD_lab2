"""Health-check endpoints.

GET /health — liveness: процесс жив и отвечает (зависимости не проверяются).
GET /ready  — readiness: сервис готов принимать трафик (БД, брокер и т.д. доступны).
В лабораторной №3 они станут livenessProbe и readinessProbe в Kubernetes.
"""

import asyncio
import logging
from typing import Awaitable, Callable

from fastapi import APIRouter
from fastapi.responses import JSONResponse

Check = Callable[[], Awaitable[bool]]
logger = logging.getLogger("health")


def make_health_router(service_name: str, checks: dict[str, Check]) -> APIRouter:
    router = APIRouter(tags=["health"])

    @router.get("/health", summary="Liveness probe")
    async def health():
        return {"status": "ok", "service": service_name}

    @router.get("/ready", summary="Readiness probe (проверяет зависимости)")
    async def ready():
        results: dict[str, str] = {}
        for name, check in checks.items():
            try:
                ok = await asyncio.wait_for(check(), timeout=3)
            except Exception as exc:  # noqa: BLE001 — любая ошибка = зависимость не готова
                logger.warning(f"Readiness check '{name}' failed: {exc}")
                ok = False
            results[name] = "ok" if ok else "fail"
        all_ok = all(v == "ok" for v in results.values())
        return JSONResponse(
            status_code=200 if all_ok else 503,
            content={"status": "ready" if all_ok else "not_ready", "service": service_name, "checks": results},
        )

    return router
