from common.config import BaseServiceSettings


class Settings(BaseServiceSettings):
    service_name: str = "delivery-service"
    database_url: str = "postgresql+asyncpg://delivery:delivery@localhost:5432/delivery_db"
    auth_service_url: str = "http://localhost:8101"
    order_service_url: str = "http://localhost:8103"

    # Сколько заказов курьер может везти одновременно
    max_active_per_courier: int = 1
    outbox_poll_seconds: float = 2.0
