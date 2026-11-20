import asyncio
import json
import logging

import httpx
import pytest

from common.errors import AppError, BadGateway, GatewayTimeout, NotFound, ServiceUnavailable
from common.http import ServiceClient
from common.logging import JsonFormatter, request_id_var


def test_json_log_contains_required_fields():
    token = request_id_var.set("req-123")
    record = logging.LogRecord("x", logging.INFO, __file__, 1, "Order created", None, None)
    record.order_id = 42
    line = json.loads(JsonFormatter("order-service").format(record))
    request_id_var.reset(token)
    assert {"timestamp", "service", "level", "request_id", "message"} <= set(line)
    assert line["service"] == "order-service" and line["request_id"] == "req-123" and line["order_id"] == 42


def _client(handler, retries=1):
    return ServiceClient("neighbor", "http://n", internal_key="k", retries=retries, transport=httpx.MockTransport(handler))


@pytest.mark.parametrize("handler, exc", [
    (lambda r: httpx.Response(404, json={"error": {"message": "нет"}}), NotFound),
    (lambda r: httpx.Response(500), BadGateway),
    (lambda r: httpx.Response(503), BadGateway),
])
def test_status_mapping(handler, exc):
    with pytest.raises(exc):
        asyncio.run(_client(handler).get("/x"))


def test_timeout_and_unreachable():
    def slow(r):
        raise httpx.ReadTimeout("slow")

    def down(r):
        raise httpx.ConnectError("refused")

    with pytest.raises(GatewayTimeout):
        asyncio.run(_client(slow).get("/x"))
    with pytest.raises(ServiceUnavailable):
        asyncio.run(_client(down).get("/x"))


def test_retry_then_success_and_headers():
    calls = []

    def flaky(r):
        calls.append(r)
        return httpx.Response(503) if len(calls) == 1 else httpx.Response(200, json={"ok": True})

    token = request_id_var.set("rid-1")
    assert asyncio.run(_client(flaky).get("/x")) == {"ok": True}
    request_id_var.reset(token)
    assert len(calls) == 2
    assert calls[0].headers["X-Request-ID"] == "rid-1" and calls[0].headers["X-Internal-Key"] == "k"


def test_client_error_is_propagated():
    with pytest.raises(AppError) as e:
        asyncio.run(_client(lambda r: httpx.Response(409, json={"error": {"message": "conflict"}})).get("/x"))
    assert e.value.status_code == 409 and e.value.message == "conflict"
