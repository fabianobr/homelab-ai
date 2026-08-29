"""Read-only filesystem collectors with independently degradable evidence."""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

from collectors.host import DEFAULT_TIMEOUT_SECONDS, Runner, finish, issue, path_text, safe_command


def collect_filesystem(mount: str | Path) -> dict[str, int | str | bool]:
    path = Path(mount).expanduser().resolve()
    usage = shutil.disk_usage(path)
    stat = os.statvfs(path)
    used = usage.total - usage.free
    percent = round((used / usage.total) * 100) if usage.total else 0
    return {
        "mount": str(path),
        "total_bytes": usage.total,
        "used_bytes": used,
        "available_bytes": usage.free,
        "percent_used": percent,
        "inodes_total": stat.f_files,
        "inodes_free": stat.f_favail,
        "read_only": bool(stat.f_flag & getattr(os, "ST_RDONLY", 1)),
    }


def _last_data_line(output: str) -> list[str]:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if not lines:
        return []
    return lines[-1].split()


def collect_filesystem_evidence(
    mount: str | Path,
    *,
    runner: Runner,
    which: Callable[[str], str | None] = shutil.which,
    statvfs: Callable[[str], Any] = os.statvfs,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Collect mount, byte, statvfs and inode evidence without failing the run."""

    mount_text = path_text(mount)
    payload: dict[str, Any] = {"mount": mount_text}
    errors: list[dict[str, str]] = []
    populated = False

    result, error = safe_command(
        ("findmnt", "--noheadings", "--output", "SOURCE,TARGET,FSTYPE,OPTIONS", "--target", mount_text),
        runner=runner,
        which=which,
        timeout=timeout,
    )
    if error:
        errors.append(error)
    elif result is not None:
        fields = str(result.get("stdout", "")).strip().split(maxsplit=3)
        if len(fields) == 4:
            options = tuple(item for item in fields[3].split(",") if item)
            payload["mount_info"] = {
                "source": fields[0],
                "target": fields[1],
                "fstype": fields[2],
                "options": list(options),
                "read_only": "ro" in options,
            }
            populated = True
        else:
            errors.append(issue("findmnt", "parse-error", "unexpected output"))

    result, error = safe_command(
        ("df", "--block-size=1", "--output=size,used,avail,pcent,target", mount_text),
        runner=runner,
        which=which,
        timeout=timeout,
    )
    if error:
        errors.append(error)
    elif result is not None:
        fields = _last_data_line(str(result.get("stdout", "")))
        try:
            payload.update(
                total_bytes=int(fields[0]),
                used_bytes=int(fields[1]),
                available_bytes=int(fields[2]),
                percent_used=int(fields[3].rstrip("%")),
                df_target=fields[4],
            )
            populated = True
        except (IndexError, ValueError):
            errors.append(issue("df", "parse-error", "unexpected byte output"))

    try:
        stats = statvfs(mount_text)
        fragment_size = int(stats.f_frsize or stats.f_bsize)
        payload["statvfs"] = {
            "free_bytes": int(stats.f_bfree) * fragment_size,
            "available_bytes": int(stats.f_bavail) * fragment_size,
            "reserved_bytes": max(0, int(stats.f_bfree - stats.f_bavail) * fragment_size),
        }
        populated = True
    except PermissionError:
        errors.append(issue("statvfs", "permission-denied", "permission denied"))
    except OSError as exc:
        errors.append(issue("statvfs", "os-error", str(exc)))

    result, error = safe_command(
        ("df", "--output=itotal,iused,iavail,ipcent,target", mount_text),
        runner=runner,
        which=which,
        timeout=timeout,
    )
    if error:
        errors.append(error | {"source": "df-inodes"})
    elif result is not None:
        fields = _last_data_line(str(result.get("stdout", "")))
        try:
            payload["inodes"] = {
                "total": int(fields[0]),
                "used": int(fields[1]),
                "available": int(fields[2]),
                "percent_used": int(fields[3].rstrip("%")),
            }
            populated = True
        except (IndexError, ValueError):
            errors.append(issue("df-inodes", "parse-error", "unexpected inode output"))

    return finish(payload, errors, any_data=populated)


def collect_filesystems(
    configured: Iterable[str | Path | Mapping[str, Any]],
    **kwargs: Any,
) -> list[dict[str, Any]]:
    """Collect every configured filesystem while preserving role metadata."""

    snapshots = []
    for entry in configured:
        if isinstance(entry, Mapping):
            mount = entry.get("mount", "")
            snapshot = collect_filesystem_evidence(str(mount), **kwargs)
            if "role" in entry:
                snapshot["role"] = entry["role"]
        else:
            snapshot = collect_filesystem_evidence(entry, **kwargs)
        snapshots.append(snapshot)
    return snapshots
