from dataclasses import replace

import pytest

from config import NotificationsConfig, load_config
from notification_dispatch import dispatch_summary


def configured(tmp_path, *, desktop: bool, telegram: bool):
    source = tmp_path / "config.yaml"
    source.write_text(
        """
filesystems:
  - mount: /
    role: root
notifications:
  desktop: false
  telegram: false
""",
        encoding="utf-8",
    )
    config = load_config(source)
    return replace(
        config,
        notifications=NotificationsConfig(
            desktop=desktop,
            telegram=telegram,
            include_paths=False,
        ),
    )


def test_dispatches_exact_sanitized_summary_to_enabled_destinations(tmp_path):
    calls = []
    config = configured(tmp_path, desktop=True, telegram=True)

    result = dispatch_summary(
        "resumo agregado",
        config,
        desktop_sender=lambda title, body: calls.append(("desktop", title, body)) or True,
        telegram_sender=lambda body: calls.append(("telegram", body)) or True,
    )

    assert calls == [
        ("desktop", "Weekly Disk Guardian", "resumo agregado"),
        ("telegram", "resumo agregado"),
    ]
    assert result == {"desktop": True, "telegram": True}


def test_disabled_destinations_do_not_call_senders(tmp_path):
    config = configured(tmp_path, desktop=False, telegram=False)

    result = dispatch_summary(
        "seguro",
        config,
        desktop_sender=lambda *_: pytest.fail("desktop não deveria ser chamado"),
        telegram_sender=lambda *_: pytest.fail("telegram não deveria ser chamado"),
    )

    assert result == {}


def test_rejects_message_larger_than_telegram_limit(tmp_path):
    config = configured(tmp_path, desktop=True, telegram=True)

    with pytest.raises(ValueError, match="4096"):
        dispatch_summary("x" * 4097, config)
