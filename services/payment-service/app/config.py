import os
from typing import List
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    SERVICE_NAME: str = "payment-service"
    DATABASE_URL: str = os.getenv(
        "PAYMENT_DATABASE_URL",
        "postgresql+psycopg2://postgres:postgres@localhost:5432/payment_db",
    )
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    JWT_SECRET_KEY: str = os.getenv(
        "JWT_SECRET_KEY", "tdtu-soa-2026-super-secret-jwt-key-9999"
    )
    JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
    OTP_TTL_SECONDS: int = int(os.getenv("OTP_TTL_SECONDS", "300"))
    INTERNAL_SERVICE_SECRET: str = os.getenv(
        "INTERNAL_SERVICE_SECRET", "tdtu-soa-2026-internal-service-secret-9999"
    )
    CORS_ORIGINS: str = os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000",
    )

    AUTH_ACCOUNT_SERVICE_URL: str = os.getenv(
        "AUTH_ACCOUNT_SERVICE_URL", "http://localhost:8001"
    )
    TUITION_SERVICE_URL: str = os.getenv(
        "TUITION_SERVICE_URL", "http://localhost:8002"
    )
    NOTIFICATION_OTP_SERVICE_URL: str = os.getenv(
        "NOTIFICATION_OTP_SERVICE_URL", "http://localhost:8004"
    )

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


settings = Settings()
