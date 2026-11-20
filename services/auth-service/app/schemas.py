from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field

# Роли, которые можно выбрать при регистрации. admin назначается только другим администратором.
PublicRole = Literal["customer", "restaurant", "courier"]
Role = Literal["customer", "restaurant", "courier", "admin"]


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=2, max_length=255)
    phone: str | None = Field(default=None, pattern=r"^\+?[0-9 ()-]{6,20}$")
    role: PublicRole = "customer"


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: "UserOut"


class UserOut(BaseModel):
    id: str
    email: str
    full_name: str
    phone: str | None
    role: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ProfileUpdateIn(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=255)
    phone: str | None = Field(default=None, pattern=r"^\+?[0-9 ()-]{6,20}$")


class RoleIn(BaseModel):
    role: Role


TokenOut.model_rebuild()
