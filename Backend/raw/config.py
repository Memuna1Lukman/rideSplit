from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    database_url_direct: str | None = None
    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    redis_url: str = ""
    # Kept small so an unavailable webhook receiver cannot tie up API workers.
    webhook_timeout_seconds: float = 5.0
    webhook_max_attempts: int = 5
    webhook_retry_base_seconds: int = 30
    stripe_secret_key: str
    stripe_webhook_secret: str
    payment_currency: str = "usd"
    ride_base_fare_cents: int = 500
    ride_per_km_cents: int = 150

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")






settings = Settings()
