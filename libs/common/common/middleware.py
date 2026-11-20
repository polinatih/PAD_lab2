"""Middleware: Request ID + access-лог каждого HTTP-запроса."""

import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from .errors import error_body
from .logging import request_id_var

REQUEST_ID_HEADER = "X-Request-ID"
logger = logging.getLogger("http")


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Берём ID от gateway (или вызывающего сервиса), иначе генерируем новый
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        status = 500
        try:
            try:
                response = await call_next(request)
            except Exception as exc:  # непойманная ошибка: логируем со stack trace, клиенту — только код
                logger.error("Unhandled error", exc_info=exc, extra={"path": request.url.path})
                response = JSONResponse(status_code=500, content=error_body("internal_error", "Внутренняя ошибка сервиса"))
            status = response.status_code
            response.headers[REQUEST_ID_HEADER] = request_id
            return response
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 1)
            path = request.url.path
            if path not in ("/health", "/ready"):  # не засоряем лог проверками от docker/k8s
                logger.info(
                    f"{request.method} {path} -> {status}",
                    extra={"method": request.method, "path": path, "status": status, "duration_ms": duration_ms},
                )
            request_id_var.reset(token)
