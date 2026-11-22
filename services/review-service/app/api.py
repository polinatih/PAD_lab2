import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from common.auth import CurrentUser, current_user
from common.deps import get_session
from common.errors import Conflict, Forbidden, NotFound

from .models import DeliveredOrder, Review
from .outbox import add_event

logger = logging.getLogger("reviews")
router = APIRouter(prefix="/api/reviews", tags=["reviews"])


class ReviewIn(BaseModel):
    order_id: str = Field(min_length=1, max_length=32)
    rating: int = Field(ge=1, le=5)
    comment: str = Field(default="", max_length=1000)


class ReplyIn(BaseModel):
    text: str = Field(min_length=2, max_length=1000)


class ReviewOut(BaseModel):
    id: str
    order_id: str
    restaurant_id: str
    restaurant_name: str
    author: str
    rating: int
    comment: str
    reply: str | None
    replied_at: datetime | None
    created_at: datetime


def short_name(full_name: str) -> str:
    """«Мария Ионеску» → «Мария И.»: в публичных отзывах не показываем полную фамилию."""
    parts = (full_name or "").split()
    if not parts or "@" in parts[0]:
        return "Клиент"
    return parts[0] + (f" {parts[1][0]}." if len(parts) > 1 else "")


def out(r: Review) -> ReviewOut:
    return ReviewOut(id=r.id, order_id=r.order_id, restaurant_id=r.restaurant_id, restaurant_name=r.restaurant_name,
                     author=short_name(r.customer_name), rating=r.rating, comment=r.comment, reply=r.reply,
                     replied_at=r.replied_at, created_at=r.created_at)


async def restaurant_stats(session: AsyncSession, restaurant_id: str) -> dict:
    rows = (await session.execute(select(Review.rating, func.count()).where(Review.restaurant_id == restaurant_id)
                                  .group_by(Review.rating))).all()
    dist = {str(star): 0 for star in range(1, 6)}
    for rating, n in rows:
        dist[str(rating)] = n
    count = sum(dist.values())
    avg = round(sum(int(k) * v for k, v in dist.items()) / count, 2) if count else 0.0
    return {"rating_avg": avg, "rating_count": count, "distribution": dist}


@router.get("/restaurant/{restaurant_id}", summary="Отзывы о ресторане (публично)")
async def restaurant_reviews(restaurant_id: str, limit: int = Query(20, ge=1, le=100),
                             session: AsyncSession = Depends(get_session)):
    items = (await session.scalars(select(Review).where(Review.restaurant_id == restaurant_id)
                                   .order_by(Review.created_at.desc()).limit(limit))).all()
    return {"stats": await restaurant_stats(session, restaurant_id), "items": [out(r) for r in items]}


@router.get("/order/{order_id}", summary="Можно ли оценить заказ и отзыв на него")
async def order_review(order_id: str, user: CurrentUser = Depends(current_user), session: AsyncSession = Depends(get_session)):
    delivered = await session.get(DeliveredOrder, order_id)
    if delivered is None or delivered.customer_id != user.id:
        return {"can_review": False, "review": None}
    review = await session.scalar(select(Review).where(Review.order_id == order_id))
    return {"can_review": review is None, "review": out(review) if review else None}


@router.post("", response_model=ReviewOut, status_code=201, summary="Оставить отзыв на доставленный заказ")
async def create_review(body: ReviewIn, request: Request, user: CurrentUser = Depends(current_user),
                        session: AsyncSession = Depends(get_session)):
    delivered = await session.get(DeliveredOrder, body.order_id)
    if delivered is None or delivered.customer_id != user.id:
        raise Forbidden("Оценить можно только свой доставленный заказ", code="not_delivered")
    if await session.scalar(select(Review.id).where(Review.order_id == body.order_id)):
        raise Conflict("Вы уже оценили этот заказ", code="already_reviewed")
    review = Review(order_id=delivered.order_id, restaurant_id=delivered.restaurant_id,
                    restaurant_name=delivered.restaurant_name, restaurant_owner_id=delivered.restaurant_owner_id,
                    customer_id=user.id, customer_name=delivered.customer_name, rating=body.rating,
                    comment=body.comment.strip())
    session.add(review)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise Conflict("Вы уже оценили этот заказ", code="already_reviewed")
    stats = await restaurant_stats(session, delivered.restaurant_id)
    # review.created: restaurant-service обновит рейтинг, notification-service сообщит ресторану
    add_event(session, "review.created", {
        "review_id": review.id, "restaurant_id": review.restaurant_id, "restaurant_name": review.restaurant_name,
        "restaurant_owner_id": review.restaurant_owner_id, "rating": review.rating, "comment": review.comment,
        "rating_avg": stats["rating_avg"], "rating_count": stats["rating_count"]})
    await session.commit()
    request.app.state.outbox.kick()
    logger.info("Review created", extra={"restaurant_id": review.restaurant_id, "rating": review.rating})
    return out(review)


@router.get("/owner", response_model=list[ReviewOut], summary="Отзывы о моих ресторанах (владелец)")
async def owner_reviews(restaurant_id: str | None = None, limit: int = Query(50, ge=1, le=200),
                        user: CurrentUser = Depends(current_user), session: AsyncSession = Depends(get_session)):
    q = select(Review)
    if not user.is_admin:
        q = q.where(Review.restaurant_owner_id == user.id)
    if restaurant_id:
        q = q.where(Review.restaurant_id == restaurant_id)
    return [out(r) for r in (await session.scalars(q.order_by(Review.created_at.desc()).limit(limit))).all()]


@router.post("/{review_id}/reply", response_model=ReviewOut, summary="Ответить на отзыв (ресторан)")
async def reply(review_id: str, body: ReplyIn, user: CurrentUser = Depends(current_user),
                session: AsyncSession = Depends(get_session)):
    review = await session.get(Review, review_id)
    if review is None:
        raise NotFound("Отзыв не найден")
    if not (user.is_admin or review.restaurant_owner_id == user.id):
        raise Forbidden("Отвечать на отзывы может только владелец ресторана")
    review.reply, review.replied_at = body.text.strip(), datetime.now(timezone.utc)
    await session.commit()
    return out(review)
