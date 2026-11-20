"""FastAPI-зависимости, достающие ресурсы сервиса из app.state."""

from typing import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.db.sessionmaker() as session:
        yield session


def get_bus(request: Request):
    return request.app.state.bus


def get_settings(request: Request):
    return request.app.state.settings
