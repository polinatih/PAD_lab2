import logging

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from common.auth import CurrentUser, admin_user, create_access_token, current_user, internal_only
from common.deps import get_bus, get_session, get_settings
from common.errors import AppError, Conflict, NotFound, Unauthorized

from .models import User
from .schemas import LoginIn, ProfileUpdateIn, RegisterIn, RoleIn, TokenOut, UserOut
from .security import hash_password, verify_password

logger = logging.getLogger("auth")
router = APIRouter(prefix="/api/auth", tags=["auth"])
internal = APIRouter(prefix="/internal", tags=["internal"], dependencies=[Depends(internal_only)])


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED, summary="Регистрация")
async def register(body: RegisterIn, session: AsyncSession = Depends(get_session), settings=Depends(get_settings),
                   bus=Depends(get_bus)):
    email = body.email.lower()
    if await session.scalar(select(User).where(User.email == email)):
        raise Conflict("Пользователь с таким email уже существует", code="email_taken")
    user = User(email=email, full_name=body.full_name.strip(), phone=body.phone, role=body.role,
                password_hash=hash_password(body.password, settings.password_iterations))
    session.add(user)
    try:
        await session.commit()
    except IntegrityError:  # гонка: два одновременных запроса с одним email
        await session.rollback()
        raise Conflict("Пользователь с таким email уже существует", code="email_taken")
    logger.info("User registered", extra={"user_id": user.id, "role": user.role})

    # Событие для notification-service (приветственное уведомление).
    # Регистрация не должна падать, если брокер временно недоступен.
    try:
        await bus.publish("user.registered", {"user_id": user.id, "email": user.email,
                                              "full_name": user.full_name, "role": user.role})
    except AppError as exc:
        logger.warning(f"user.registered not published: {exc.message}")
    return user


@router.post("/login", response_model=TokenOut, summary="Вход, получение JWT")
async def login(body: LoginIn, session: AsyncSession = Depends(get_session), settings=Depends(get_settings)):
    user = await session.scalar(select(User).where(User.email == body.email.lower()))
    if user is None or not verify_password(body.password, user.password_hash):
        # Одинаковое сообщение, чтобы перебором нельзя было узнать, какие email зарегистрированы
        raise Unauthorized("Неверный email или пароль", code="invalid_credentials")
    token = create_access_token(
        user_id=user.id, email=user.email, role=user.role,
        secret=settings.jwt_secret, algorithm=settings.jwt_algorithm, ttl_minutes=settings.access_token_ttl_minutes,
    )
    logger.info("User logged in", extra={"user_id": user.id})
    return TokenOut(access_token=token, expires_in=settings.access_token_ttl_minutes * 60,
                    user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut, summary="Мой профиль")
async def me(user: CurrentUser = Depends(current_user), session: AsyncSession = Depends(get_session)):
    db_user = await session.get(User, user.id)
    if db_user is None:
        raise NotFound("Пользователь не найден")
    return db_user


@router.patch("/me", response_model=UserOut, summary="Изменить имя или телефон")
async def update_me(body: ProfileUpdateIn, user: CurrentUser = Depends(current_user),
                    session: AsyncSession = Depends(get_session)):
    db_user = await session.get(User, user.id)
    if db_user is None:
        raise NotFound("Пользователь не найден")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(db_user, field, value)
    await session.commit()
    return db_user


@router.get("/users", response_model=list[UserOut], summary="Список пользователей (admin)")
async def list_users(role: str | None = Query(None), _: CurrentUser = Depends(admin_user),
                     session: AsyncSession = Depends(get_session)):
    q = select(User).order_by(User.created_at)
    if role:
        q = q.where(User.role == role)
    return (await session.scalars(q)).all()


@router.patch("/users/{user_id}/role", response_model=UserOut, summary="Изменить роль (admin)")
async def change_role(user_id: str, body: RoleIn, admin: CurrentUser = Depends(admin_user),
                      session: AsyncSession = Depends(get_session)):
    user = await session.get(User, user_id)
    if user is None:
        raise NotFound("Пользователь не найден")
    user.role = body.role
    await session.commit()
    logger.info("Role changed", extra={"user_id": user_id, "role": body.role, "by": admin.id})
    return user


@internal.get("/users/{user_id}", response_model=UserOut, summary="Данные пользователя (для других сервисов)")
async def internal_user(user_id: str, session: AsyncSession = Depends(get_session)):
    user = await session.get(User, user_id)
    if user is None:
        raise NotFound("Пользователь не найден")
    return user


async def bootstrap_admin(app) -> None:
    """Создаёт администратора при первом запуске."""
    settings = app.state.settings
    async with app.state.db.sessionmaker() as session:
        email = settings.admin_email.lower()
        if await session.scalar(select(User).where(User.email == email)):
            return
        session.add(User(email=email, full_name="Администратор", role="admin",
                         password_hash=hash_password(settings.admin_password, settings.password_iterations)))
        try:
            await session.commit()
            logger.info("Admin user created", extra={"email": email})
        except IntegrityError:  # другой экземпляр сервиса успел первым
            await session.rollback()
