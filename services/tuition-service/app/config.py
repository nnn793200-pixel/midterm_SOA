import os
from typing import List
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    SERVICE_NAME: str = "tuition-service"
    DATABASE_URL: str = os.getenv(
        "TUITION_DATABASE_URL",
        "postgresql+psycopg2://postgres:postgres@localhost:5432/tuition_db",
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
