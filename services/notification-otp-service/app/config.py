import os
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


settings = Settings()
