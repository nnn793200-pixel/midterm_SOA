import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    SERVICE_NAME: str = "api-gateway"
    JWT_SECRET_KEY: str = os.getenv(
        "JWT_SECRET_KEY", "tdtu-soa-2026-super-secret-jwt-key-9999"
    )
    JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")

    AUTH_ACCOUNT_SERVICE_URL: str = os.getenv(
        "AUTH_ACCOUNT_SERVICE_URL", "http://localhost:8001"
    )
    TUITION_SERVICE_URL: str = os.getenv(
        "TUITION_SERVICE_URL", "http://localhost:8002"
    )
    PAYMENT_SERVICE_URL: str = os.getenv(
        "PAYMENT_SERVICE_URL", "http://localhost:8003"
    )
    NOTIFICATION_OTP_SERVICE_URL: str = os.getenv(
        "NOTIFICATION_OTP_SERVICE_URL", "http://localhost:8004"
    )


settings = Settings()
