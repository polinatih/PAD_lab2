from common.config import BaseServiceSettings


class Settings(BaseServiceSettings):
    service_name: str = "restaurant-service"
    database_url: str = "postgresql+asyncpg://restaurant:restaurant@localhost:5432/restaurant_db"

    max_items_per_order: int = 50
