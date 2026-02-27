from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://postgres:password@localhost:5432/shortgame"
    ANTHROPIC_API_KEY: str = ""
    FINNHUB_API_KEY: str = ""
    LOG_LEVEL: str = "INFO"
    PORT: int = 8000
    APP_PASSWORD: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
