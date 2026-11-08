import os
from typing import List
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
