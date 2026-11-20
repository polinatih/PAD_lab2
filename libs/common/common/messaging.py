"""Асинхронное взаимодействие через RabbitMQ.

Схема:
  * один topic-exchange `food.events`; routing key = тип события (`order.created`, ...);
  * у каждого сервиса-потребителя своя durable-очередь (`payment-service.events`),
    привязанная к нужным ему routing key — сервисы не мешают друг другу;
  * сообщения persistent, подтверждаются (ack) только после успешной обработки;
  * при ошибке сообщение один раз возвращается в очередь (повтор), при повторной ошибке
    уходит в dead-letter очередь `<queue>.dlq`, чтобы не потерять его и не зациклиться.

Формат сообщения (envelope):
  {"event_id": "...", "event_type": "order.created", "occurred_at": "...",
   "source": "order-service", "request_id": "...", "data": {...}}
"""

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

import aio_pika
from aio_pika.abc import AbstractIncomingMessage, AbstractRobustConnection

from .errors import ServiceUnavailable
from .logging import request_id_var

logger = logging.getLogger("events")
Handler = Callable[[dict], Awaitable[None]]


@dataclass
class Subscription:
    queue: str
    routing_keys: list[str]
    handler: Handler


def make_envelope(event_type: str, data: dict, source: str) -> dict:
    return {
        "event_id": uuid.uuid4().hex,
        "event_type": event_type,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "request_id": request_id_var.get(),
        "data": data,
    }


class EventBus:
    def __init__(self, url: str, exchange: str, service_name: str, prefetch: int = 10):
        self.url = url
        self.exchange_name = exchange
        self.service_name = service_name
        self.prefetch = prefetch
        self._subs: list[Subscription] = []
        self._conn: AbstractRobustConnection | None = None
        self._exchange: aio_pika.abc.AbstractExchange | None = None
        self._task: asyncio.Task | None = None
        self._connected = asyncio.Event()

    def subscribe(self, routing_keys: list[str], handler: Handler, queue: str | None = None) -> None:
        """Регистрирует обработчик. Вызывать до start()."""
        self._subs.append(Subscription(queue or f"{self.service_name}.events", routing_keys, handler))

    async def start(self) -> None:
        """Подключение в фоне: сервис стартует, даже если RabbitMQ ещё не поднялся."""
        self._task = asyncio.create_task(self._connect_loop())

    async def _connect_loop(self) -> None:
        delay = 1.0
        while True:
            try:
                await self._connect()
                logger.info("Connected to RabbitMQ", extra={"exchange": self.exchange_name})
                return
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"RabbitMQ not available ({exc!r}), retry in {delay:.0f}s")
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30)

    async def _connect(self) -> None:
        self._conn = await aio_pika.connect_robust(self.url, client_properties={"connection_name": self.service_name})
        channel = await self._conn.channel()
        await channel.set_qos(prefetch_count=self.prefetch)
        self._exchange = await channel.declare_exchange(self.exchange_name, aio_pika.ExchangeType.TOPIC, durable=True)
        dlx = await channel.declare_exchange(f"{self.exchange_name}.dlx", aio_pika.ExchangeType.DIRECT, durable=True)

        # Одна очередь может обслуживать несколько обработчиков (разные routing keys)
        by_queue: dict[str, list[Subscription]] = {}
        for sub in self._subs:
            by_queue.setdefault(sub.queue, []).append(sub)

        for queue_name, subs in by_queue.items():
            dlq = await channel.declare_queue(f"{queue_name}.dlq", durable=True)
            await dlq.bind(dlx, routing_key=queue_name)
            queue = await channel.declare_queue(
                queue_name,
                durable=True,
                arguments={"x-dead-letter-exchange": dlx.name, "x-dead-letter-routing-key": queue_name},
            )
            routes: dict[str, Handler] = {}
            for sub in subs:
                for key in sub.routing_keys:
                    await queue.bind(self._exchange, routing_key=key)
                    routes[key] = sub.handler
            await queue.consume(self._make_consumer(queue_name, routes))
            logger.info(f"Consuming {queue_name}", extra={"routing_keys": list(routes)})
        self._connected.set()

    def _make_consumer(self, queue_name: str, routes: dict[str, Handler]):
        async def on_message(message: AbstractIncomingMessage) -> None:
            try:
                envelope = json.loads(message.body)
            except json.JSONDecodeError:
                logger.error("Malformed message, sending to DLQ", extra={"queue": queue_name})
                await message.reject(requeue=False)
                return
            token = request_id_var.set(envelope.get("request_id") or envelope.get("event_id", "-"))
            event_type = envelope.get("event_type", message.routing_key)
            try:
                handler = routes.get(event_type) or routes.get(message.routing_key)
                if handler is None:
                    logger.warning(f"No handler for {event_type}, ack and skip")
                    await message.ack()
                    return
                await handler(envelope)
                await message.ack()
                logger.info(f"Event {event_type} processed", extra={"event_id": envelope.get("event_id")})
            except Exception as exc:  # noqa: BLE001
                if not message.redelivered:
                    logger.warning(f"Event {event_type} failed ({exc!r}), will retry once")
                    await message.nack(requeue=True)
                else:
                    logger.error(f"Event {event_type} failed again, moved to DLQ", exc_info=exc)
                    await message.reject(requeue=False)
            finally:
                request_id_var.reset(token)

        return on_message

    async def publish(self, event_type: str, data: dict[str, Any]) -> dict:
        if self._exchange is None or not self._connected.is_set():
            raise ServiceUnavailable("Брокер сообщений недоступен", code="broker_unavailable")
        envelope = make_envelope(event_type, data, self.service_name)
        message = aio_pika.Message(
            body=json.dumps(envelope, ensure_ascii=False, default=str).encode(),
            content_type="application/json",
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            message_id=envelope["event_id"],
            type=event_type,
        )
        await self._exchange.publish(message, routing_key=event_type)
        logger.info(f"Event {event_type} published", extra={"event_id": envelope["event_id"]})
        return envelope

    async def is_connected(self) -> bool:
        # connected сбрасывается robust-соединением на время переподключения к брокеру
        return (self._connected.is_set() and self._conn is not None and not self._conn.is_closed
                and self._conn.connected.is_set())

    async def close(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
        if self._conn:
            await self._conn.close()


class InMemoryEventBus:
    """Заглушка для unit-тестов: запоминает опубликованные события и может вызвать обработчики."""

    def __init__(self, service_name: str = "test"):
        self.service_name = service_name
        self.published: list[dict] = []
        self.handlers: dict[str, Handler] = {}

    def subscribe(self, routing_keys: list[str], handler: Handler, queue: str | None = None) -> None:
        for key in routing_keys:
            self.handlers[key] = handler

    async def start(self) -> None: ...

    async def close(self) -> None: ...

    async def is_connected(self) -> bool:
        return True

    async def publish(self, event_type: str, data: dict) -> dict:
        envelope = make_envelope(event_type, data, self.service_name)
        self.published.append(envelope)
        return envelope

    async def deliver(self, event_type: str, data: dict) -> None:
        """Имитирует получение события из брокера."""
        await self.handlers[event_type](make_envelope(event_type, data, "test"))

    def types(self) -> list[str]:
        return [e["event_type"] for e in self.published]
