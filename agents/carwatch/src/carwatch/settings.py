"""src/carwatch/settings.py"""
import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# `config/` and `migrations/` are DATA directories that live next to the
# package, not inside it, so they are not part of the installed wheel. Under
# an editable/source-tree checkout `parents[2]` is `agents/carwatch/` and the
# fallback works; under the Dockerfile's non-editable
# `uv pip install --system .` `__file__` resolves inside site-packages and
# `parents[2]` lands outside the project entirely. CARWATCH_ROOT makes the
# deployment declare where those directories actually are — the Dockerfile
# sets it to its WORKDIR. Every module that needs `config/` or `migrations/`
# must resolve them from here rather than computing its own `__file__`-relative
# path — see the git history of cli.py's CARWATCH_ROOT and cost.py's
# load_llm_pricing() call sites for two real deploy-breaking bugs caused by
# re-deriving this independently.
CARWATCH_ROOT = Path(os.environ.get("CARWATCH_ROOT", Path(__file__).resolve().parents[2]))
CONFIG_DIR = CARWATCH_ROOT / "config"
MIGRATIONS_DIR = CARWATCH_ROOT / "migrations"


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
    atom_feed_path: str = "feed.atom"
    atom_feed_url: str = "https://example.com/feed.atom"

    @property
    def user_agent(self) -> str:
        return f"CarWatchBot/1.0 (+{self.bot_info_url}; {self.contact_email})"


@lru_cache
def get_settings() -> Settings:
    return Settings()
