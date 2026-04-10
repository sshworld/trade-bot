from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Binance
    binance_api_key: str = ""
    binance_api_secret: str = ""
    binance_testnet: bool = True

    # Backend
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000

    # Alert
    alert_telegram_bot_token: str = ""
    alert_telegram_chat_id: str = ""
    alert_webhook_url: str = ""

    model_config = {"env_file": ["../.env", ".env"], "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
