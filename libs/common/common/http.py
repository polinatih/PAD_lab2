"""HTTP-клиент для синхронных вызовов между сервисами.

* Таймаут на каждый запрос.
* Повторы (retry) с экспоненциальной паузой только для сетевых ошибок/таймаутов и 502/503/504.
* Пробрасывает X-Request-ID и X-Internal-Key.
* Переводит ошибки соседа в понятные AppError: 404 -> NotFound, timeout -> 504, недоступен -> 503.
"""

import asyncio
import logging
from typing import Any

import httpx

from .errors import AppError, BadGateway, GatewayTimeout, NotFound, ServiceUnavailable
from .logging import request_id_var

logger = logging.getLogger("http.client")
RETRY_STATUSES = {502, 503, 504}


class ServiceClient:
    def __init__(self, name: str, base_url: str, *, internal_key: str, timeout: float = 5.0, retries: int = 2,
                 transport: httpx.AsyncBaseTransport | None = None):
        self.name = name
        self.retries = retries
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=httpx.Timeout(timeout),
            headers={"X-Internal-Key": internal_key},
            transport=transport,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def request(self, method: str, path: str, *, timeout: float | None = None, **kwargs) -> Any:
        headers = kwargs.pop("headers", {}) | {"X-Request-ID": request_id_var.get()}
        if timeout is not None:
            kwargs["timeout"] = timeout
        last_exc: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                resp = await self._client.request(method, path, headers=headers, **kwargs)
                if resp.status_code in RETRY_STATUSES and attempt < self.retries:
                    raise httpx.HTTPStatusError("retryable", request=resp.request, response=resp)
                return self._handle(resp)
            except httpx.TimeoutException as exc:
                last_exc = exc
                logger.warning(f"Timeout calling {self.name} {method} {path} (attempt {attempt + 1})")
            except httpx.TransportError as exc:
                last_exc = exc
                logger.warning(f"{self.name} unreachable: {exc!r} (attempt {attempt + 1})")
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                logger.warning(f"{self.name} returned {exc.response.status_code} (attempt {attempt + 1})")
            if attempt < self.retries:
                await asyncio.sleep(0.2 * 2**attempt)

        if isinstance(last_exc, httpx.TimeoutException):
            raise GatewayTimeout(f"Сервис {self.name} не ответил вовремя")
        if isinstance(last_exc, httpx.HTTPStatusError):
            return self._handle(last_exc.response)
        raise ServiceUnavailable(f"Сервис {self.name} недоступен")

    def _handle(self, resp: httpx.Response) -> Any:
        if resp.status_code == 204:
            return None
        if resp.is_success:
            return resp.json()
        message = _extract_message(resp)
        if resp.status_code == 404:
            raise NotFound(message)
        if 400 <= resp.status_code < 500:
            # Ошибку клиента от соседа пробрасываем с тем же кодом
            raise AppError(message, status_code=resp.status_code, code="upstream_rejected")
        raise BadGateway(f"Сервис {self.name} вернул ошибку {resp.status_code}")

    async def get(self, path: str, **kw):
        return await self.request("GET", path, **kw)

    async def post(self, path: str, **kw):
        return await self.request("POST", path, **kw)


def _extract_message(resp: httpx.Response) -> str:
    try:
        return resp.json()["error"]["message"]
    except Exception:  # noqa: BLE001
        return resp.text[:200] or f"HTTP {resp.status_code}"
