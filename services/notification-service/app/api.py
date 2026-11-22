import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from common.auth import CurrentUser, current_user
from common.deps import get_session
from common.errors import NotFound

from .models import Notification
from .templates import TEMPLATES

logger = logging.getLogger("notifications")
router = APIRouter(prefix="/api/notifications", tags=["notifications"])


class NotificationOut(BaseModel):
    id: str
    kind: str
    level: str
    title: str
    body: str
    link: str | None
    is_read: bool
    created_at: datetime
    model_config = {"from_attributes": True}


@router.get("", response_model=list[NotificationOut], summary="Мои уведомления")
async def list_notifications(unread_only: bool = False, limit: int = Query(30, ge=1, le=200),
                             user: CurrentUser = Depends(current_user), session: AsyncSession = Depends(get_session)):
    q = select(Notification).where(Notification.user_id == user.id)
    if unread_only:
        q = q.where(Notification.is_read.is_(False))
    return (await session.scalars(q.order_by(Notification.created_at.desc()).limit(limit))).all()


@router.get("/unread-count", summary="Сколько непрочитанных")
async def unread_count(user: CurrentUser = Depends(current_user), session: AsyncSession = Depends(get_session)):
    n = await session.scalar(select(func.count()).select_from(Notification)
                             .where(Notification.user_id == user.id, Notification.is_read.is_(False)))
    return {"unread": n or 0}


@router.post("/read-all", summary="Отметить все прочитанными")
async def read_all(user: CurrentUser = Depends(current_user), session: AsyncSession = Depends(get_session)):
    res = await session.execute(update(Notification).where(Notification.user_id == user.id,
                                                           Notification.is_read.is_(False)).values(is_read=True))
    await session.commit()
    return {"updated": res.rowcount}


@router.post("/{notification_id}/read", response_model=NotificationOut, summary="Отметить прочитанным")
async def mark_read(notification_id: str, user: CurrentUser = Depends(current_user),
                    session: AsyncSession = Depends(get_session)):
    n = await session.get(Notification, notification_id)
    if n is None or n.user_id != user.id:
        raise NotFound("Уведомление не найдено")
    n.is_read = True
    await session.commit()
    return n


def make_handler(db):
    async def handle(envelope: dict) -> None:
        template = TEMPLATES.get(envelope["event_type"])
        if template is None:
            return
        messages = [m for m in template(envelope["data"]) if m.user_id]
        async with db.sessionmaker() as session:
            for m in messages:
                exists = await session.scalar(select(Notification.id).where(
                    Notification.event_id == envelope["event_id"], Notification.user_id == m.user_id))
                if exists:
                    continue  # повторная доставка события
                session.add(Notification(event_id=envelope["event_id"], user_id=m.user_id, kind=envelope["event_type"],
                                         level=m.level, title=m.title, body=m.body, link=m.link))
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
        if messages:
            logger.info(f"{len(messages)} notification(s) for {envelope['event_type']}")

    return handle
