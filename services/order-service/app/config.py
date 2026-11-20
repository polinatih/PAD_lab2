from common.config import BaseServiceSettings


class Settings(BaseServiceSettings):
    service_name: str = "order-service"
    database_url: str = "postgresql+asyncpg://orders:orders@localhost:5432/order_db"

    restaurant_service_url: str = "http://localhost:8102"
    auth_service_url: str = "http://localhost:8101"

    # Transactional outbox: как часто проверять неотправленные события
    outbox_poll_seconds: float = 2.0
