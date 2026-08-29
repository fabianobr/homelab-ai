"""Best-effort delivery of the privacy-preserving diagnosis summary."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from config import GuardianConfig


MAX_REMOTE_MESSAGE_LENGTH = 4096


def dispatch_summary(
    summary: str,
    config: GuardianConfig,
    *,
    desktop_sender: Callable[[str, str], bool] | None = None,
    telegram_sender: Callable[[str], bool] | None = None,
) -> dict[str, bool]:
    """Deliver only the already-sanitized summary to enabled destinations."""
    if len(summary) > MAX_REMOTE_MESSAGE_LENGTH:
        raise ValueError("resumo de notificação excede 4096 caracteres")

    delivered: dict[str, bool] = {}
    if config.notifications.desktop:
        sender = desktop_sender or _send_desktop
        delivered["desktop"] = bool(sender("Weekly Disk Guardian", summary))
    if config.notifications.telegram:
        sender = telegram_sender or _telegram_sender()
        delivered["telegram"] = bool(sender(summary))
    return delivered


def _send_desktop(title: str, summary: str) -> bool:
    try:
        completed = subprocess.run(
            ["notify-send", title, summary],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


def _telegram_sender() -> Callable[[str], bool]:
    shared_lib = Path(__file__).resolve().parents[1] / "lib"
    shared_lib_text = str(shared_lib)
    if shared_lib_text not in sys.path:
        sys.path.insert(0, shared_lib_text)
    from telegram_notify import send_telegram_message

    return send_telegram_message
