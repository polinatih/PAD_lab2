"""Структурированное JSON-логирование.

Каждая строка лога — JSON-объект с полями timestamp, service, level, request_id, message
(+ дополнительные поля, переданные через extra={...}).
request_id берётся из contextvar, который выставляет middleware для HTTP-запросов
и consumer для сообщений из RabbitMQ — так один запрос можно проследить через все сервисы.
"""

import json
import logging
import sys
from contextvars import ContextVar
from datetime import datetime, timezone

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

_RESERVED = set(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def __init__(self, service_name: str):
        super().__init__()
        self.service_name = service_name

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(timespec="milliseconds"),
            "service": self.service_name,
            "level": record.levelname,
            "request_id": request_id_var.get(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Всё, что передано через extra={...}, добавляем в JSON
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def setup_logging(service_name: str, level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(service_name))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    # uvicorn пишет свои access-логи в другом формате — их заменяет наш middleware
    for name in ("uvicorn", "uvicorn.error"):
        logging.getLogger(name).handlers = [handler]
        logging.getLogger(name).propagate = False
    logging.getLogger("uvicorn.access").disabled = True
    for noisy in ("aiormq", "aio_pika", "httpx", "httpcore", "sqlalchemy.engine"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
