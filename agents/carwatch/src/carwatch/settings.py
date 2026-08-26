"""src/carwatch/settings.py"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    anthropic_api_key: str
    telegram_bot_token: str
    telegram_chat_id: str
    bot_info_url: str
    contact_email: str
    fetch_min_interval_sec: float = 3.0
    fetch_global_concurrency: int = 10
    log_level: str = "INFO"

    @property
    def user_agent(self) -> str:
        return f"CarWatchBot/1.0 (+{self.bot_info_url}; {self.contact_email})"


@lru_cache
def get_settings() -> Settings:
    return Settings()
