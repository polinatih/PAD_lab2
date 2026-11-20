from pydantic_settings import BaseSettings, SettingsConfigDict


class BaseServiceSettings(BaseSettings):
    """Базовые настройки, общие для всех сервисов.

    Значения читаются из переменных окружения (и из файла .env, если он есть).
    Каждый сервис наследуется от этого класса и добавляет свои поля.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "service"
    log_level: str = "INFO"

    # JWT: токены выпускает auth-service, остальные сервисы только проверяют их
    jwt_secret: str = "change-me-in-production-please-32b"
    jwt_algorithm: str = "HS256"

    # Ключ для внутренних (service-to-service) endpoint'ов /internal/*
    internal_api_key: str = "internal-secret-change-me"

    # RabbitMQ
    rabbitmq_url: str = "amqp://guest:guest@localhost:5672/"
    events_exchange: str = "food.events"

    # Таймаут HTTP-запросов к другим сервисам (секунды)
    http_timeout: float = 5.0
    http_retries: int = 2
