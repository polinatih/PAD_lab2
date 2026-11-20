import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from common.logging import request_id_var

from .models import OutboxEvent

logger = logging.getLogger("outbox")


def add_event(session: AsyncSession, event_type: str, payload: dict) -> None:
    """Добавляет событие в outbox в рамках текущей транзакции (commit делает вызывающий код)."""
    session.add(OutboxEvent(event_type=event_type, payload=payload, request_id=request_id_var.get()))


class OutboxRelay:
    """Фоновая задача: читает неотправленные события из outbox и публикует их в RabbitMQ."""

    def __init__(self, db, bus, poll_seconds: float):
        self.db, self.bus, self.poll_seconds = db, bus, poll_seconds
        self._wake = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._stopping = False

    def kick(self) -> None:
        """Разбудить relay сразу после commit, не дожидаясь следующего опроса."""
        self._wake.set()

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        """Мягкая остановка: даём закончить текущую отправку, чтобы не оборвать работу с БД на середине."""
        self._stopping = True
        self._wake.set()
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=5)
            except asyncio.TimeoutError:
                self._task.cancel()

    async def _loop(self) -> None:
        while not self._stopping:
            try:
                await self.flush()
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"Outbox flush failed: {exc!r}")
            if self._stopping:
                break
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self.poll_seconds)
            except asyncio.TimeoutError:
                pass
            self._wake.clear()

    async def flush(self) -> int:
        if not await self.bus.is_connected():
            return 0
        sent = 0
        async with self.db.sessionmaker() as session:
            events = (await session.scalars(
                select(OutboxEvent).where(OutboxEvent.published_at.is_(None)).order_by(OutboxEvent.created_at).limit(100)
            )).all()
            for ev in events:
                token = request_id_var.set(ev.request_id)
                try:
                    await self.bus.publish(ev.event_type, ev.payload)
                    ev.published_at = datetime.now(timezone.utc)
                    sent += 1
                except Exception as exc:  # noqa: BLE001
                    ev.attempts += 1
                    logger.warning(f"Publish {ev.event_type} failed: {exc!r}")
                    break
                finally:
                    request_id_var.reset(token)
            await session.commit()
        return sent
