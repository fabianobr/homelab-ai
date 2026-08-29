"""Deterministic pressure classification and proposal views."""

from __future__ import annotations

from collections.abc import Iterable

from schemas import Action, ActionType, PressureState, RiskLevel


_CONSERVATIVE_TYPES = {
    ActionType.CLEAN_PIP_CACHE,
    ActionType.CLEAN_UV_CACHE,
    ActionType.CLEAN_APT_CACHE,
    ActionType.VACUUM_JOURNAL,
    ActionType.REMOVE_DISABLED_SNAP,
}


def classify_pressure(
    *,
    percent_used: int | float,
    available_bytes: int,
    read_only: bool,
    amber_percent: int | float,
    red_percent: int | float,
    critical_percent: int | float,
    amber_available_bytes: int,
    red_available_bytes: int,
    critical_available_bytes: int,
) -> PressureState:
    """Return the worst state matched by percentage, bytes, or mount mode."""
    if read_only or percent_used >= critical_percent or available_bytes < critical_available_bytes:
        return PressureState.CRITICAL
    if percent_used >= red_percent or available_bytes < red_available_bytes:
        return PressureState.RED
    if percent_used >= amber_percent or available_bytes < amber_available_bytes:
        return PressureState.AMBER
    return PressureState.GREEN


def build_plan_views(actions: Iterable[Action]) -> dict[str, list[str]]:
    """Derive all views from one immutable collection of action IDs."""
    items = list(actions)
    conservative = [
        item.action_id
        for item in items
        if item.risk is RiskLevel.LOW and item.type in _CONSERVATIVE_TYPES
    ]
    balanced = [
        item.action_id
        for item in items
        if item.risk is not RiskLevel.HIGH
        and item.type
        not in {ActionType.MANUAL_PERSONAL_CLEANUP, ActionType.ADJUST_EXT4_RESERVE}
    ]
    return {
        "conservative": conservative,
        "balanced": balanced,
        "custom": [item.action_id for item in items],
    }


def target_reached(
    *,
    percent_used: int | float,
    available_bytes: int,
    target_percent: int | float,
    min_available_bytes: int,
) -> bool:
    """Both policy goals are strict: equality still means no safety margin."""
    return percent_used < target_percent and available_bytes > min_available_bytes
