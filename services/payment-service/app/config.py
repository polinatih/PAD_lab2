from common.config import BaseServiceSettings


class Settings(BaseServiceSettings):
    service_name: str = "payment-service"
    database_url: str = "postgresql+asyncpg://payment:payment@localhost:5432/payment_db"

    # Сколько минут ждём оплату, прежде чем отменить заказ (saga: компенсирующее действие)
    payment_timeout_minutes: float = 15
    max_attempts: int = 3
    expiry_check_seconds: float = 30
    outbox_poll_seconds: float = 2.0
