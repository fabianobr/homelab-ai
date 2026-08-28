"""Read-only sizing for explicitly allowlisted cache roots."""

from __future__ import annotations

import os
import re
import shutil
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from collectors.host import DEFAULT_TIMEOUT_SECONDS, Runner, finish, issue, path_text, safe_command


def directory_size_no_cross_mount(path: str | Path) -> int | None:
    root = Path(path).expanduser()
    if not root.is_dir() or root.is_symlink():
        return None
    try:
        root_device = root.stat().st_dev
    except OSError:
        return None
    total = 0
    for current, directories, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        try:
            if current_path.stat().st_dev != root_device:
                directories[:] = []
                continue
        except OSError:
            directories[:] = []
            continue
        for name in files:
            candidate = current_path / name
            try:
                info = candidate.lstat()
                if not candidate.is_symlink() and info.st_dev == root_device:
                    total += info.st_size
            except OSError:
                continue
    return total


def _directory_size_with_errors(path: str | Path) -> tuple[int | None, list[dict[str, str]]]:
    root = Path(path).expanduser()
    if not root.is_dir() or root.is_symlink():
        return None, [issue("filesystem", "unavailable", "path missing or a symlink")]
    try:
        root_device = root.stat().st_dev
    except PermissionError:
        return None, [issue("filesystem", "permission-denied", "permission denied")]
    except OSError as exc:
        return None, [issue("filesystem", "os-error", str(exc))]

    errors: list[dict[str, str]] = []
    total = 0

    def record_walk_error(exc: OSError) -> None:
        kind = "permission-denied" if isinstance(exc, PermissionError) else "os-error"
        errors.append(issue("filesystem", kind, str(exc)))

    for current, directories, files in os.walk(
        root, followlinks=False, onerror=record_walk_error
    ):
        current_path = Path(current)
        try:
            if current_path.stat().st_dev != root_device:
                directories[:] = []
                continue
        except OSError as exc:
            directories[:] = []
            record_walk_error(exc)
            continue
        for name in files:
            candidate = current_path / name
            try:
                info = candidate.lstat()
                if not candidate.is_symlink() and info.st_dev == root_device:
                    total += info.st_size
            except OSError as exc:
                record_walk_error(exc)
    return total, errors


def collect_cache_directory(path: str | Path, *, name: str | None = None) -> dict[str, Any]:
    """Size one explicitly allowlisted path and expose inaccessible paths."""

    path_value = path_text(path)
    size, errors = _directory_size_with_errors(path_value)
    payload: dict[str, Any] = {"name": name or Path(path_value).name, "path": path_value}
    if size is None:
        return finish(
            payload,
            errors,
            any_data=False,
        )
    payload["size_bytes"] = size
    return finish(payload, errors, any_data=True)


def collect_allowlisted_caches(entries: Iterable[str | Path | dict[str, Any]]) -> list[dict[str, Any]]:
    results = []
    for entry in entries:
        if isinstance(entry, dict):
            if "path" not in entry:
                results.append(
                    finish(
                        {"name": entry.get("name", "unknown"), "path": ""},
                        [issue("configuration", "invalid", "cache path is missing")],
                        any_data=False,
                    )
                )
                continue
            results.append(
                collect_cache_directory(entry["path"], name=entry.get("name"))
            )
        else:
            results.append(collect_cache_directory(entry))
    return results


def collect_apt_cache(path: str | Path = "/var/cache/apt/archives") -> dict[str, Any]:
    """Size APT's package cache by traversing it read-only."""

    result = collect_cache_directory(path, name="apt")
    result["kind"] = "apt-cache"
    return result


_SIZE_UNITS = {
    "B": 1,
    "K": 1000,
    "KB": 1000,
    "M": 1000**2,
    "MB": 1000**2,
    "G": 1000**3,
    "GB": 1000**3,
    "T": 1000**4,
    "TB": 1000**4,
    "KI": 1024,
    "KIB": 1024,
    "MI": 1024**2,
    "MIB": 1024**2,
    "GI": 1024**3,
    "GIB": 1024**3,
    "TI": 1024**4,
    "TIB": 1024**4,
}


def _parse_human_size(text: str) -> int | None:
    matches = re.findall(r"(?<![\w.])(\d+(?:[.,]\d+)?)\s*([KMGT]i?B?|B)(?!\w)", text, re.I)
    if not matches:
        return None
    number, unit = matches[-1]
    return round(float(number.replace(",", ".")) * _SIZE_UNITS[unit.upper()])


def collect_journal_usage(
    *,
    runner: Runner,
    which: Callable[[str], str | None] = shutil.which,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"kind": "journal"}
    result, error = safe_command(
        ("journalctl", "--disk-usage"), runner=runner, which=which, timeout=timeout
    )
    if error:
        return finish(payload, [error], any_data=False)
    output = str(result.get("stdout", "")) if result is not None else ""
    size = _parse_human_size(output)
    if size is None:
        return finish(payload, [issue("journalctl", "parse-error", "disk usage not found")], any_data=False)
    payload.update(size_bytes=size, raw=output.strip())
    return finish(payload, [], any_data=True)


def collect_disabled_snaps(
    *,
    runner: Runner,
    which: Callable[[str], str | None] = shutil.which,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"kind": "disabled-snaps", "revisions": []}
    result, error = safe_command(
        ("snap", "list", "--all"), runner=runner, which=which, timeout=timeout
    )
    if error:
        return finish(payload, [error], any_data=False)
    lines = [line for line in str(result.get("stdout", "")).splitlines() if line.strip()]
    if not lines:
        return finish(payload, [issue("snap", "parse-error", "empty output")], any_data=False)
    for line in lines[1:]:
        fields = line.split()
        if len(fields) >= 6 and fields[-1].lower() == "disabled":
            payload["revisions"].append({"name": fields[0], "revision": fields[2]})
    return finish(payload, [], any_data=True)
