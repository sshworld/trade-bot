from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Binance
    binance_api_key: str = ""
    binance_api_secret: str = ""
    binance_testnet: bool = True

    # Strategy: "live_v1" = A-fixed 4h Turtle + safety layer (spec v2 §8). Legacy strategy C is
    # disabled for live trading; "legacy_c" only re-enables its paper simulation signals.
    strategy: str = "live_v1"
    live_v1_symbol: str = "BTCUSDT"          # e.g. ETHUSDT; filters come from exchangeInfo
    live_v1_direction: str = "both"          # both | long_only (Trading Advisor decides after v2)
    healthcheck_ping_url: str = ""           # optional external heartbeat (healthchecks.io etc.)

    # Backend
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000

    # Alert
    alert_telegram_bot_token: str = ""
    alert_telegram_chat_id: str = ""
    alert_webhook_url: str = ""

    model_config = {"env_file": ["../.env", ".env"], "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
