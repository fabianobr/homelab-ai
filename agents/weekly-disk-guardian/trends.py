"""Eight-run local trend calculation; never used to authorize actions."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from state import StateStore


def load_trend(store: StateStore, *, red_percent: int, limit: int = 8) -> dict[str, Any]:
    points: list[dict[str, Any]] = []
    for run_id in store.run_ids()[-limit:]:
        try:
            diagnosis = store.read_json(f"runs/{run_id}/diagnosis.json")
            root = next(
                item for item in diagnosis["filesystems"] if item.get("role") == "root"
            )
            created_at = datetime.fromisoformat(str(diagnosis["created_at"]))
        except (FileNotFoundError, KeyError, StopIteration, TypeError, ValueError):
            continue

        execution = _optional_execution(store, run_id)
        points.append(
            {
                "run_id": run_id,
                "created_at": created_at.isoformat(),
                "percent_used": int(root["percent_used"]),
                "used_bytes": int(root["used_bytes"]),
                "available_bytes": int(root["available_bytes"]),
                "growth_bytes": 0,
                "actual_reclaim_bytes": int(execution.get("actual_reclaim_bytes", 0)),
                "estimation_error_bytes": int(execution.get("estimation_error_bytes", 0)),
            }
        )

    points.sort(key=lambda item: item["created_at"])
    for previous, current in zip(points, points[1:]):
        current["growth_bytes"] = current["used_bytes"] - previous["used_bytes"]
    return {
        "points": points,
        "projected_days_to_red": _project_days_to_red(points, red_percent),
        "informational_only": True,
    }


def _optional_execution(store: StateStore, run_id: str) -> dict[str, Any]:
    try:
        payload = store.read_json(f"runs/{run_id}/execution.json")
    except FileNotFoundError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _project_days_to_red(points: list[dict[str, Any]], red_percent: int) -> float | None:
    if len(points) < 4:
        return None
    timestamps = [datetime.fromisoformat(item["created_at"]).timestamp() / 86400 for item in points]
    origin = timestamps[0]
    x_values = [value - origin for value in timestamps]
    y_values = [float(item["percent_used"]) for item in points]
    x_mean = sum(x_values) / len(x_values)
    y_mean = sum(y_values) / len(y_values)
    denominator = sum((value - x_mean) ** 2 for value in x_values)
    if denominator == 0:
        return None
    slope = sum(
        (x_value - x_mean) * (y_value - y_mean)
        for x_value, y_value in zip(x_values, y_values)
    ) / denominator
    latest = y_values[-1]
    if slope <= 0 or latest >= red_percent:
        return None
    return round((red_percent - latest) / slope, 1)
