import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    SERVICE_NAME: str = "tuition-service"
    DATABASE_URL: str = os.getenv(
        "TUITION_DATABASE_URL",
        "postgresql+psycopg2://postgres:postgres@localhost:5432/tuition_db",
    )


settings = Settings()
