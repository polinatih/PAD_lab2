from common.config import BaseServiceSettings


class Settings(BaseServiceSettings):
    service_name: str = "review-service"
    database_url: str = "postgresql+asyncpg://review:review@localhost:5432/review_db"
    order_service_url: str = "http://localhost:8103"
    outbox_poll_seconds: float = 2.0
