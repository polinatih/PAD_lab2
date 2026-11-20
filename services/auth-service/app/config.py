from common.config import BaseServiceSettings


class Settings(BaseServiceSettings):
    service_name: str = "auth-service"
    database_url: str = "postgresql+asyncpg://auth:auth@localhost:5432/auth_db"

    access_token_ttl_minutes: int = 60
    password_iterations: int = 200_000

    # Администратор, который создаётся при первом запуске (если его ещё нет)
    admin_email: str = "admin@example.com"
    admin_password: str = "admin12345"
