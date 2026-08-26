"""tests/test_settings.py"""
import os

import pytest

from carwatch.settings import Settings, get_settings


def test_settings_loads_from_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h:5432/d")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tg-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")
    monkeypatch.setenv("BOT_INFO_URL", "https://example.com/bot")
    monkeypatch.setenv("CONTACT_EMAIL", "you@example.com")
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.database_url == "postgresql://u:p@h:5432/d"
    assert settings.fetch_min_interval_sec == 3.0
    assert settings.fetch_global_concurrency == 10


def test_settings_missing_required_field_raises(monkeypatch, tmp_path):
    # Move to temporary directory without .env file to test field validation
    monkeypatch.chdir(tmp_path)
    for key in (
        "DATABASE_URL",
        "ANTHROPIC_API_KEY",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "BOT_INFO_URL",
        "CONTACT_EMAIL",
    ):
        monkeypatch.delenv(key, raising=False)
    get_settings.cache_clear()

    with pytest.raises(Exception):
        get_settings()
