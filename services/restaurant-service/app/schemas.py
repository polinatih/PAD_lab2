from datetime import datetime

from pydantic import BaseModel, Field

CUISINES = ["Пицца", "Бургеры", "Суши", "Молдавская", "Грузинская", "Азиатская", "Выпечка", "Здоровая еда", "Десерты"]


class RestaurantIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    description: str = Field(default="", max_length=1000)
    cuisine: str = Field(min_length=2, max_length=40, examples=CUISINES)
    address: str = Field(min_length=3, max_length=255)
    phone: str | None = Field(default=None, pattern=r"^\+?[0-9 ()-]{6,20}$")
    delivery_fee: float = Field(default=25, ge=0, le=1000)
    min_order: float = Field(default=0, ge=0, le=10000)
    prep_minutes: int = Field(default=25, ge=5, le=180)


class RestaurantPatch(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    cuisine: str | None = Field(default=None, min_length=2, max_length=40)
    address: str | None = Field(default=None, min_length=3, max_length=255)
    phone: str | None = Field(default=None, pattern=r"^\+?[0-9 ()-]{6,20}$")
    is_open: bool | None = None
    delivery_fee: float | None = Field(default=None, ge=0, le=1000)
    min_order: float | None = Field(default=None, ge=0, le=10000)
    prep_minutes: int | None = Field(default=None, ge=5, le=180)


class RestaurantOut(BaseModel):
    id: str
    owner_id: str
    name: str
    description: str
    cuisine: str
    address: str
    phone: str | None
    is_open: bool
    delivery_fee: float
    min_order: float
    prep_minutes: int
    rating_avg: float
    rating_count: int
    created_at: datetime
    model_config = {"from_attributes": True}


class MenuItemIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    description: str = Field(default="", max_length=500)
    category: str = Field(default="Основное", min_length=2, max_length=60)
    price: float = Field(gt=0, le=100000)
    is_available: bool = True


class MenuItemPatch(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    category: str | None = Field(default=None, min_length=2, max_length=60)
    price: float | None = Field(default=None, gt=0, le=100000)
    is_available: bool | None = None


class MenuItemOut(BaseModel):
    id: str
    restaurant_id: str
    name: str
    description: str
    category: str
    price: float
    is_available: bool
    model_config = {"from_attributes": True}


class RestaurantDetail(RestaurantOut):
    menu: list[MenuItemOut]


# --- внутренний API для order-service ---

class QuoteLineIn(BaseModel):
    menu_item_id: str
    quantity: int = Field(ge=1, le=50)


class QuoteIn(BaseModel):
    items: list[QuoteLineIn] = Field(min_length=1, max_length=50)


class QuoteLineOut(BaseModel):
    menu_item_id: str
    name: str
    unit_price: float
    quantity: int
    line_total: float


class QuoteOut(BaseModel):
    restaurant_id: str
    restaurant_name: str
    restaurant_address: str
    owner_id: str
    prep_minutes: int
    items: list[QuoteLineOut]
    subtotal: float
    delivery_fee: float
    total: float
