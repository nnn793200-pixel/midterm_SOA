import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    SERVICE_NAME: str = "auth-account-service"
    DATABASE_URL: str = os.getenv(
        "ACCOUNT_DATABASE_URL",
        "postgresql+psycopg2://postgres:postgres@localhost:5432/account_db",
    )
    JWT_SECRET_KEY: str = os.getenv(
        "JWT_SECRET_KEY", "tdtu-soa-2026-super-secret-jwt-key-9999"
    )
    JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(
        os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440")
    )


settings = Settings()
