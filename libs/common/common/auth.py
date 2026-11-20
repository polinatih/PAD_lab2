"""Аутентификация и авторизация.

* Токены (JWT) выпускает только auth-service.
* Любой сервис проверяет подпись токена сам (общий секрет JWT_SECRET) — ему не нужно
  ходить в auth-service на каждый запрос.
* Роли: "user" и "admin". Зависимость `admin_user` — для admin-only endpoint'ов.
* Внутренние endpoint'ы (/internal/*) защищены ключом X-Internal-Key и не проброшены
  наружу через gateway.

Настройки берутся из request.app.state.settings (кладётся туда при создании приложения).
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .errors import Forbidden, Unauthorized

bearer_scheme = HTTPBearer(auto_error=False, description="JWT из POST /api/auth/login")


@dataclass
class CurrentUser:
    id: str
    email: str
    role: str

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def create_access_token(*, user_id: str, email: str, role: str, secret: str, algorithm: str, ttl_minutes: int) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "iat": now,
        "exp": now + timedelta(minutes=ttl_minutes),
        "iss": "auth-service",
    }
    return jwt.encode(payload, secret, algorithm=algorithm)


def decode_token(token: str, secret: str, algorithm: str) -> CurrentUser:
    try:
        payload = jwt.decode(token, secret, algorithms=[algorithm], issuer="auth-service")
    except jwt.ExpiredSignatureError:
        raise Unauthorized("Срок действия токена истёк", code="token_expired")
    except jwt.PyJWTError:
        raise Unauthorized("Недействительный токен", code="invalid_token")
    return CurrentUser(id=payload["sub"], email=payload.get("email", ""), role=payload.get("role", "user"))


async def current_user(request: Request, creds: HTTPAuthorizationCredentials | None = Depends(bearer_scheme)) -> CurrentUser:
    if creds is None:
        raise Unauthorized("Требуется заголовок Authorization: Bearer <token>")
    s = request.app.state.settings
    return decode_token(creds.credentials, s.jwt_secret, s.jwt_algorithm)


async def admin_user(user: CurrentUser = Depends(current_user)) -> CurrentUser:
    if not user.is_admin:
        raise Forbidden("Действие доступно только администратору")
    return user


async def internal_only(request: Request, x_internal_key: str | None = Header(default=None)) -> None:
    if x_internal_key != request.app.state.settings.internal_api_key:
        raise Forbidden("Внутренний endpoint: неверный X-Internal-Key", code="internal_only")
