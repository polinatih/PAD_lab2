"""Единый формат ошибок и обработчики исключений.

Любая ошибка возвращается клиенту в виде:
    {"error": {"code": "not_found", "message": "...", "request_id": "...", "details": ...}}
Stack trace пользователю никогда не отдаётся — он пишется только в лог.
"""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from .logging import request_id_var

logger = logging.getLogger("errors")


class AppError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, *, code: str | None = None, details: Any = None, status_code: int | None = None):
        super().__init__(message)
        self.message = message
        self.details = details
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code


class BadRequest(AppError):
    status_code, code = 400, "bad_request"


class Unauthorized(AppError):
    status_code, code = 401, "unauthorized"


class Forbidden(AppError):
    status_code, code = 403, "forbidden"


class NotFound(AppError):
    status_code, code = 404, "not_found"


class Conflict(AppError):
    status_code, code = 409, "conflict"


class BadGateway(AppError):
    """Внешний сервис ответил ошибкой."""

    status_code, code = 502, "upstream_error"


class ServiceUnavailable(AppError):
    """Зависимость (БД, брокер, другой сервис) недоступна."""

    status_code, code = 503, "service_unavailable"


class GatewayTimeout(AppError):
    """Внешний сервис не ответил вовремя."""

    status_code, code = 504, "upstream_timeout"


def error_body(code: str, message: str, details: Any = None) -> dict:
    body = {"code": code, "message": message, "request_id": request_id_var.get()}
    if details is not None:
        body["details"] = details
    return {"error": body}


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError):
        level = logging.ERROR if exc.status_code >= 500 else logging.WARNING
        logger.log(level, exc.message, extra={"error_code": exc.code, "status": exc.status_code, "path": request.url.path})
        return JSONResponse(status_code=exc.status_code, content=error_body(exc.code, exc.message, exc.details))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError):
        details = [
            {"field": ".".join(str(p) for p in err["loc"] if p != "body"), "message": err["msg"]}
            for err in exc.errors()
        ]
        logger.warning("Validation failed", extra={"path": request.url.path, "errors": details})
        return JSONResponse(status_code=422, content=error_body("validation_error", "Некорректные входные данные", details))

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException):
        code = {404: "not_found", 405: "method_not_allowed", 401: "unauthorized", 403: "forbidden"}.get(exc.status_code, "http_error")
        return JSONResponse(status_code=exc.status_code, content=error_body(code, str(exc.detail)))

    @app.exception_handler(SQLAlchemyError)
    async def _db_error(request: Request, exc: SQLAlchemyError):
        logger.error("Database error", exc_info=exc, extra={"path": request.url.path})
        return JSONResponse(status_code=503, content=error_body("database_error", "Ошибка базы данных, попробуйте позже"))

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        logger.error("Unhandled error", exc_info=exc, extra={"path": request.url.path})
        return JSONResponse(status_code=500, content=error_body("internal_error", "Внутренняя ошибка сервиса"))
