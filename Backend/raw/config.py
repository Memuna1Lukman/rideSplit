from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    database_url_direct: str | None = None
    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    redis_url: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")






settings = Settings()

