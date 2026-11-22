from common.config import BaseServiceSettings


class Settings(BaseServiceSettings):
    service_name: str = "notification-service"
    database_url: str = "postgresql+asyncpg://notification:notification@localhost:5432/notification_db"
