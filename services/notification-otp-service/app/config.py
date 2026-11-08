import os
from typing import List
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    SERVICE_NAME: str = "notification-otp-service"
    DATABASE_URL: str = os.getenv(
        "NOTIFICATION_DATABASE_URL",
        "postgresql+psycopg2://postgres:postgres@localhost:5432/notification_db",
    )
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    OTP_TTL_SECONDS: int = int(os.getenv("OTP_TTL_SECONDS", "300"))
    SMTP_HOST: str = os.getenv("SMTP_HOST", "localhost")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "1025"))
    SMTP_FROM_EMAIL: str = os.getenv(
        "SMTP_FROM_EMAIL", "ibanking-noreply@tdtu.edu.vn"
    )
    SMTP_FROM_NAME: str = os.getenv("SMTP_FROM_NAME", "TDTU iBanking System")
    INTERNAL_SERVICE_SECRET: str = os.getenv(
        "INTERNAL_SERVICE_SECRET", "tdtu-soa-2026-internal-service-secret-9999"
    )
    CORS_ORIGINS: str = os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000",
    )

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


settings = Settings()
