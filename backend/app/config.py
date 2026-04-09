from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Binance
    binance_api_key: str = ""
    binance_api_secret: str = ""
    binance_testnet: bool = True

    # Database
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "tradebot"
    postgres_user: str = "tradebot"
    postgres_password: str = "changeme"

    # Backend
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000
    analysis_interval_seconds: int = 60

    # Alert channels
    alert_telegram_bot_token: str = ""
    alert_telegram_chat_id: str = ""
    alert_webhook_url: str = ""

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    model_config = {"env_file": ["../.env", ".env"], "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
