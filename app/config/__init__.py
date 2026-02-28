from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://postgres:password@localhost:5432/shortgame"
    ANTHROPIC_API_KEY: str = ""
    FINNHUB_API_KEY: str = ""
    LOG_LEVEL: str = "INFO"
    PORT: int = 8000
    APP_PASSWORD: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @property
    def async_database_url(self) -> str:
        """Ensure DATABASE_URL uses asyncpg driver for SQLAlchemy async."""
        url = self.DATABASE_URL
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return url


settings = Settings()
