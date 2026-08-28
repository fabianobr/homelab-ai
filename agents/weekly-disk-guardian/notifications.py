"""Privacy-preserving notification rendering."""

from __future__ import annotations

from collections.abc import Mapping


def build_remote_summary(local_report: Mapping[str, object]) -> str:
    """Render only the aggregate allowlist; ignore every other input field."""
    run_id = str(local_report.get("run_id", "desconhecido"))
    state = str(local_report.get("state", "unknown")).upper()
    percent = int(local_report.get("percent_used", 0))
    available = int(local_report.get("available_bytes", 0))
    reclaim = int(local_report.get("suggested_reclaim_bytes", 0))
    action_count = int(local_report.get("action_count", 0))
    return (
        f"Weekly Disk Guardian — {run_id}\n"
        f"Estado: {state} | uso: {percent}%\n"
        f"Disponível: {_format_gib(available)} GiB | ganho possível: {_format_gib(reclaim)} GiB\n"
        f"Ações sugeridas: {action_count}"
    )


def _format_gib(value: int) -> str:
    return f"{value / (1024**3):.1f}"
