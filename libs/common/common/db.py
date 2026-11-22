"""Работа с БД через SQLAlchemy (async).

Каждый сервис подключается только к СВОЕЙ базе (DATABASE_URL у каждого свой).
Таблицы создаются при старте (create_all) — для учебного проекта этого достаточно,
в продакшене здесь были бы миграции Alembic.
"""

import asyncio
import logging
from typing import AsyncIterator

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

logger = logging.getLogger("db")


class Base(DeclarativeBase):
    pass


def _add_missing_columns(conn, metadata) -> None:
    """Простейшая «миграция»: если в модели появилась новая колонка, а таблица уже существует
    (база создана на прошлом этапе), добавляем колонку через ALTER TABLE. Новые колонки делаем nullable.
    Для учебного проекта этого достаточно; в продакшене здесь были бы миграции Alembic."""
    insp = inspect(conn)
    existing_tables = set(insp.get_table_names())
    for table in metadata.sorted_tables:
        if table.name not in existing_tables:
            continue
        present = {c["name"] for c in insp.get_columns(table.name)}
        for column in table.columns:
            if column.name in present:
                continue
            col_type = column.type.compile(dialect=conn.dialect)
            conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN {column.name} {col_type}'))
            logger.info(f"Column added: {table.name}.{column.name}")


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
                    await conn.run_sync(_add_missing_columns, base.metadata)
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
