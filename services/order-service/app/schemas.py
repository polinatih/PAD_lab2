from datetime import datetime

from pydantic import BaseModel, Field, computed_field

from .states import LABELS


class OrderLineIn(BaseModel):
    menu_item_id: str = Field(min_length=1, max_length=32)
    quantity: int = Field(ge=1, le=50)


class OrderIn(BaseModel):
    restaurant_id: str = Field(min_length=1, max_length=32)
    items: list[OrderLineIn] = Field(min_length=1, max_length=50)
    delivery_address: str = Field(min_length=5, max_length=255)
    phone: str | None = Field(default=None, pattern=r"^\+?[0-9 ()-]{6,20}$")
    comment: str = Field(default="", max_length=500)


class CancelIn(BaseModel):
    reason: str = Field(default="", max_length=300)


class OrderItemOut(BaseModel):
    menu_item_id: str
    name: str
    unit_price: float
    quantity: int
    line_total: float
    model_config = {"from_attributes": True}


class StatusChangeOut(BaseModel):
    status: str
    note: str | None
    at: datetime
    model_config = {"from_attributes": True}


class OrderOut(BaseModel):
    id: str
    number: str
    status: str
    customer_id: str
    customer_name: str
    customer_phone: str | None
    restaurant_id: str
    restaurant_owner_id: str
    restaurant_name: str
    restaurant_address: str
    delivery_address: str
    comment: str
    cancel_reason: str | None
    subtotal: float
    delivery_fee: float
    total: float
    prep_minutes: int
    courier_id: str | None
    courier_name: str | None = None
    courier_phone: str | None = None
    created_at: datetime
    updated_at: datetime
    items: list[OrderItemOut]
    history: list[StatusChangeOut]
    model_config = {"from_attributes": True}

    @computed_field
    @property
    def status_label(self) -> str:
        return LABELS.get(self.status, self.status)
