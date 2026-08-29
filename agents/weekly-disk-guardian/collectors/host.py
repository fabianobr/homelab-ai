"""Shared, read-only host collection helpers.

Collectors deliberately return evidence about failures instead of raising.  The
runner is injectable so tests never need to inspect the real host.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol


DEFAULT_TIMEOUT_SECONDS = 10.0


class Runner(Protocol):
    def run(
        self,
        argv: Sequence[str],
        *,
        check: bool = True,
        timeout: float | None = None,
    ) -> Mapping[str, Any]: ...


class ReadOnlySubprocessRunner:
    """Narrow subprocess adapter: argument vectors only, never a shell."""

    def run(
        self,
        argv: Sequence[str],
        *,
        check: bool = True,
        timeout: float | None = None,
    ) -> Mapping[str, Any]:
        completed = subprocess.run(
            list(argv),
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )
        result = {
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }
        if check and completed.returncode:
            raise RuntimeError(f"command exited with {completed.returncode}")
        return result


def issue(source: str, kind: str, message: str) -> dict[str, str]:
    """Build a stable, JSON-friendly description of incomplete evidence."""

    return {"source": source, "kind": kind, "message": message}


def safe_command(
    argv: Sequence[str],
    *,
    runner: Runner,
    which: Callable[[str], str | None] = shutil.which,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> tuple[Mapping[str, Any] | None, dict[str, str] | None]:
    """Run a known read-only command and convert host failures to evidence."""

    command = str(argv[0]) if argv else ""
    if not command or which(command) is None:
        return None, issue(command or "command", "tool-unavailable", "tool not found")
    try:
        result = runner.run(tuple(str(part) for part in argv), check=False, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, issue(command, "timeout", f"timed out after {timeout:g}s")
    except PermissionError:
        return None, issue(command, "permission-denied", "permission denied")
    except OSError as exc:
        return None, issue(command, "os-error", str(exc))
    except Exception as exc:  # Runner implementations may use their own errors.
        return None, issue(command, "command-error", str(exc))

    returncode = int(result.get("returncode", 0))
    if returncode != 0:
        stderr = str(result.get("stderr", "")).strip()
        return None, issue(
            command,
            "permission-denied" if "permission denied" in stderr.lower() else "command-failed",
            stderr or f"exit status {returncode}",
        )
    return result, None


def finish(payload: dict[str, Any], errors: list[dict[str, str]], *, any_data: bool) -> dict[str, Any]:
    payload["status"] = "partial" if errors else "ok"
    if errors and not any_data:
        payload["status"] = "unavailable"
    payload["errors"] = errors
    return payload


def path_text(path: str | Path) -> str:
    """Expand user syntax without resolving or requiring the path to exist."""

    return str(Path(path).expanduser())


def collect_deleted_open_files(
    *,
    runner: Runner,
    which: Callable[[str], str | None] = shutil.which,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Report deleted files still held open, when lsof is usable."""

    payload: dict[str, Any] = {
        "kind": "deleted-open-files",
        "files": [],
        "total_size_bytes": 0,
    }
    result, error = safe_command(
        ("lsof", "-nP", "+L1"), runner=runner, which=which, timeout=timeout
    )
    if error:
        return finish(payload, [error], any_data=False)

    errors: list[dict[str, str]] = []
    lines = [line for line in str(result.get("stdout", "")).splitlines() if line.strip()]
    for line in lines[1:]:
        # COMMAND PID USER FD TYPE DEVICE SIZE/OFF NLINK NODE NAME
        fields = line.split(maxsplit=9)
        if len(fields) < 10:
            errors.append(issue("lsof", "parse-error", "skipped malformed row"))
            continue
        try:
            size = int(fields[6])
            links = int(fields[7])
        except ValueError:
            errors.append(issue("lsof", "parse-error", "skipped non-numeric row"))
            continue
        if links != 0 and "(deleted)" not in fields[9]:
            continue
        payload["files"].append(
            {
                "command": fields[0],
                "pid": fields[1],
                "fd": fields[3],
                "size_bytes": size,
                "path": fields[9],
            }
        )
        payload["total_size_bytes"] += size
    return finish(payload, errors, any_data=True)


def collect_host_evidence(
    *,
    filesystems: Iterable[str | Path | Mapping[str, Any]],
    runner: Runner,
    cache_paths: Iterable[str | Path | dict[str, Any]] = (),
    apt_cache_path: str | Path = "/var/cache/apt/archives",
    which: Callable[[str], str | None] = shutil.which,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Collect host evidence; every component retains its own partial status."""

    # Local imports avoid making the focused collectors depend cyclically on
    # this orchestration convenience function.
    from collectors.caches import (
        collect_allowlisted_caches,
        collect_apt_cache,
        collect_disabled_snaps,
        collect_journal_usage,
    )
    from collectors.filesystems import collect_filesystems

    return {
        "filesystems": collect_filesystems(
            filesystems, runner=runner, which=which, timeout=timeout
        ),
        "caches": collect_allowlisted_caches(cache_paths),
        "apt_cache": collect_apt_cache(apt_cache_path),
        "journal": collect_journal_usage(
            runner=runner, which=which, timeout=timeout
        ),
        "disabled_snaps": collect_disabled_snaps(
            runner=runner, which=which, timeout=timeout
        ),
        "deleted_open_files": collect_deleted_open_files(
            runner=runner, which=which, timeout=timeout
        ),
    }
