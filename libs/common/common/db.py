"""Работа с БД через SQLAlchemy (async).

Каждый сервис подключается только к СВОЕЙ базе (DATABASE_URL у каждого свой).
Таблицы создаются при старте (create_all) — для учебного проекта этого достаточно,
в продакшене здесь были бы миграции Alembic.
"""

import asyncio
import logging
from typing import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

logger = logging.getLogger("db")


class Base(DeclarativeBase):
    pass


class Database:
    def __init__(self, url: str):
        kwargs = {"pool_pre_ping": True}
        if not url.startswith("sqlite"):
            kwargs |= {"pool_size": 5, "max_overflow": 5, "pool_timeout": 5}
        self.engine: AsyncEngine = create_async_engine(url, **kwargs)
        self.sessionmaker = async_sessionmaker(self.engine, expire_on_commit=False)

    async def create_schema(self, base: type[DeclarativeBase], attempts: int = 30) -> None:
        """Ждём, пока БД поднимется (в docker-compose она может стартовать позже), и создаём таблицы."""
        for attempt in range(1, attempts + 1):
            try:
                async with self.engine.begin() as conn:
                    await conn.run_sync(base.metadata.create_all)
                logger.info("Database schema ready")
                return
            except Exception as exc:  # noqa: BLE001
                if attempt == attempts:
                    raise
                logger.warning(f"Database not ready ({exc.__class__.__name__}), attempt {attempt}/{attempts}")
                await asyncio.sleep(2)

    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self.sessionmaker() as session:
            yield session

    async def ping(self) -> bool:
        async with self.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True

    async def close(self) -> None:
        await self.engine.dispose()
