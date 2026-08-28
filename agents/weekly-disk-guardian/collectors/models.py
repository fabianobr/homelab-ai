"""Read-only inventory and duplicate evidence for model files.

Discovery deliberately does not hash files.  Hashing multi-gigabyte models is
available only through the explicit confirmation functions at the bottom of
this module.
"""

from __future__ import annotations

import hashlib
import os
import time
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any


DEFAULT_REFERENCE_SUFFIXES = frozenset(
    {".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".txt", ".md", ".py"}
)


def _configured_path(value: str | Path) -> Path:
    """Expand configuration variables without invoking a shell."""

    text = os.fspath(value)
    home = str(Path.home())
    if text == "$HOME":
        text = home
    elif text.startswith("$HOME/"):
        text = str(Path(home) / text.removeprefix("$HOME/"))
    if "$" in text:
        raise ValueError("unsupported environment variable in configured path")
    return Path(os.path.expanduser(text)).absolute()


def _consumer_path(path: Path, root: Path, consumer_mount: str | None) -> str | None:
    if not consumer_mount:
        return None
    try:
        relative = path.relative_to(root)
    except ValueError:
        return None
    return str(PurePosixPath(consumer_mount).joinpath(*relative.parts))


def scan_model_root(
    root: str | Path,
    *,
    min_size_bytes: int,
    consumer_mount: str | None = None,
) -> dict[str, Any]:
    """Inventory large regular files and symlinks without crossing boundaries.

    Directory symlinks are recorded but never traversed.  Nested mount points
    and entries on a different device are also not traversed.  Errors are
    evidence in the result rather than reasons to make a destructive inference.
    """

    if min_size_bytes < 0:
        raise ValueError("min_size_bytes must be non-negative")

    configured_root = _configured_path(root)
    result: dict[str, Any] = {
        "root": str(configured_root),
        "exists": False,
        "device": None,
        "files": [],
        "symlinks": [],
        "skipped_boundaries": [],
        "errors": [],
    }
    try:
        root_info = configured_root.lstat()
    except OSError as exc:
        result["errors"].append({"path": str(configured_root), "error": type(exc).__name__})
        return result

    result["exists"] = True
    result["device"] = root_info.st_dev
    if configured_root.is_symlink():
        result["symlinks"].append(_symlink_record(configured_root, configured_root, consumer_mount))
        result["skipped_boundaries"].append({"path": str(configured_root), "reason": "root-symlink"})
        return result
    if not configured_root.is_dir():
        result["errors"].append({"path": str(configured_root), "error": "NotADirectory"})
        return result

    root_device = root_info.st_dev
    pending = [configured_root]
    while pending:
        directory = pending.pop()
        try:
            entries = list(os.scandir(directory))
        except OSError as exc:
            result["errors"].append({"path": str(directory), "error": type(exc).__name__})
            continue

        for entry in entries:
            path = Path(entry.path)
            try:
                info = entry.stat(follow_symlinks=False)
                if entry.is_symlink():
                    result["symlinks"].append(_symlink_record(path, configured_root, consumer_mount))
                    continue
                if info.st_dev != root_device:
                    result["skipped_boundaries"].append({"path": str(path), "reason": "different-device"})
                    continue
                if entry.is_dir(follow_symlinks=False):
                    if path != configured_root and os.path.ismount(path):
                        result["skipped_boundaries"].append({"path": str(path), "reason": "mount-point"})
                    else:
                        pending.append(path)
                    continue
                if entry.is_file(follow_symlinks=False) and info.st_size >= min_size_bytes:
                    relative = path.relative_to(configured_root)
                    result["files"].append(
                        {
                            "path": str(path),
                            "relative_path": str(relative),
                            "name": path.name,
                            "size_bytes": info.st_size,
                            "physical_size_bytes": getattr(info, "st_blocks", 0) * 512,
                            "inode": info.st_ino,
                            "device": info.st_dev,
                            "mtime_ns": info.st_mtime_ns,
                            "consumer_path": _consumer_path(path, configured_root, consumer_mount),
                        }
                    )
            except OSError as exc:
                result["errors"].append({"path": str(path), "error": type(exc).__name__})

    result["files"].sort(key=lambda item: item["relative_path"])
    result["symlinks"].sort(key=lambda item: item["relative_path"])
    result["skipped_boundaries"].sort(key=lambda item: item["path"])
    return result


def _symlink_record(path: Path, root: Path, consumer_mount: str | None) -> dict[str, Any]:
    try:
        raw_target = os.readlink(path)
        resolved = path.resolve(strict=False)
        broken = not resolved.exists()
        try:
            resolved.relative_to(root)
            target_within_root = True
        except ValueError:
            target_within_root = False
        return {
            "path": str(path),
            "relative_path": str(path.relative_to(root)) if path != root else ".",
            "target": raw_target,
            "resolved_path": str(resolved),
            "broken": broken,
            "target_within_root": target_within_root,
            "consumer_path": _consumer_path(path, root, consumer_mount),
            "consumer_resolved_path": (
                _consumer_path(resolved, root, consumer_mount) if target_within_root else None
            ),
        }
    except OSError as exc:
        return {
            "path": str(path),
            "relative_path": str(path.relative_to(root)) if path != root else ".",
            "target": None,
            "resolved_path": None,
            "broken": True,
            "target_within_root": False,
            "consumer_path": _consumer_path(path, root, consumer_mount),
            "consumer_resolved_path": None,
            "error": type(exc).__name__,
        }


def search_model_references(
    names: Iterable[str],
    roots: Iterable[str | Path],
    *,
    timeout_seconds: float = 5.0,
    max_files: int = 10_000,
    max_file_bytes: int = 2 * 1024 * 1024,
    max_total_bytes: int = 64 * 1024 * 1024,
    suffixes: Iterable[str] = DEFAULT_REFERENCE_SUFFIXES,
) -> dict[str, Any]:
    """Conservatively search bounded workflow/config text for model names."""

    if timeout_seconds < 0 or min(max_files, max_file_bytes, max_total_bytes) < 0:
        raise ValueError("search limits must be non-negative")
    wanted = sorted({name for name in names if name}, key=lambda value: (-len(value), value))
    allowed_suffixes = {suffix.lower() for suffix in suffixes}
    matches: dict[str, list[str]] = {name: [] for name in wanted}
    errors: list[dict[str, str]] = []
    files_scanned = 0
    bytes_scanned = 0
    truncated = False
    timed_out = False
    deadline = time.monotonic() + timeout_seconds

    pending: list[tuple[Path, int]] = []
    for raw_root in roots:
        root = _configured_path(raw_root)
        try:
            info = root.lstat()
            if root.is_dir() and not root.is_symlink():
                pending.append((root, info.st_dev))
        except OSError as exc:
            errors.append({"path": str(root), "error": type(exc).__name__})

    while pending:
        if time.monotonic() >= deadline:
            timed_out = True
            break
        directory, root_device = pending.pop()
        try:
            entries = list(os.scandir(directory))
        except OSError as exc:
            errors.append({"path": str(directory), "error": type(exc).__name__})
            continue
        for entry in entries:
            if time.monotonic() >= deadline:
                timed_out = True
                break
            path = Path(entry.path)
            try:
                info = entry.stat(follow_symlinks=False)
                if entry.is_symlink() or info.st_dev != root_device:
                    continue
                if entry.is_dir(follow_symlinks=False):
                    if not os.path.ismount(path):
                        pending.append((path, root_device))
                    continue
                if not entry.is_file(follow_symlinks=False) or path.suffix.lower() not in allowed_suffixes:
                    continue
                if files_scanned >= max_files or bytes_scanned >= max_total_bytes:
                    truncated = True
                    pending.clear()
                    break
                budget = min(max_file_bytes, max_total_bytes - bytes_scanned)
                if budget <= 0:
                    truncated = True
                    pending.clear()
                    break
                with path.open("rb") as handle:
                    payload = handle.read(budget)
                files_scanned += 1
                bytes_scanned += len(payload)
                text = payload.decode("utf-8", errors="ignore")
                for name in wanted:
                    if name in text:
                        matches[name].append(str(path))
                if info.st_size > budget:
                    truncated = True
            except OSError as exc:
                errors.append({"path": str(path), "error": type(exc).__name__})
        if timed_out:
            break

    return {
        "matches": matches,
        "files_scanned": files_scanned,
        "bytes_scanned": bytes_scanned,
        "timed_out": timed_out,
        "truncated": truncated,
        "errors": errors,
        "absence_authorizes_deletion": False,
    }


def find_duplicate_candidates(files: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Group cheap candidates by exact filename and logical size only."""

    groups: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for item in files:
        path = str(item["path"])
        name = str(item.get("name", Path(path).name))
        size = int(item["size_bytes"])
        groups[(name, size)].append({"path": path, "inode": item.get("inode"), "device": item.get("device")})
    return [
        {
            "name": name,
            "size_bytes": size,
            "files": sorted(items, key=lambda item: item["path"]),
            "confirmed": False,
            "confirmation_required": "sha256",
        }
        for (name, size), items in sorted(groups.items())
        if len(items) > 1
    ]


def collect_models(
    roots: Iterable[str | Path],
    *,
    min_size_bytes: int,
    reference_roots: Iterable[str | Path] = (),
    consumer_mount: str | None = None,
    reference_timeout_seconds: float = 5.0,
    reference_max_files: int = 10_000,
    reference_max_file_bytes: int = 2 * 1024 * 1024,
    reference_max_total_bytes: int = 64 * 1024 * 1024,
) -> dict[str, Any]:
    """Collect serializable model evidence without mutation or content hashing."""

    inventories = [
        scan_model_root(root, min_size_bytes=min_size_bytes, consumer_mount=consumer_mount)
        for root in roots
    ]
    files = [item for inventory in inventories for item in inventory["files"]]
    reference_search = search_model_references(
        (item["name"] for item in files),
        reference_roots,
        timeout_seconds=reference_timeout_seconds,
        max_files=reference_max_files,
        max_file_bytes=reference_max_file_bytes,
        max_total_bytes=reference_max_total_bytes,
    )
    for item in files:
        item["references"] = reference_search["matches"].get(item["name"], [])
        item["reference_absence_is_authorization"] = False
    return {
        "roots": inventories,
        "files": files,
        "reference_search": reference_search,
        "duplicate_candidates": find_duplicate_candidates(files),
        "hashes_computed": False,
        "read_only": True,
    }


def sha256_file(path: str | Path, *, chunk_size: int = 1024 * 1024) -> str:
    """Hash one explicitly selected regular file."""

    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    candidate = _configured_path(path)
    if candidate.is_symlink() or not candidate.is_file():
        raise ValueError("hash target must be a regular non-symlink file")
    digest = hashlib.sha256()
    with candidate.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def confirm_duplicates(paths: Iterable[str | Path]) -> list[dict[str, Any]]:
    """Explicitly hash selected paths and return only equal-content groups."""

    by_size: dict[int, list[Path]] = defaultdict(list)
    for raw_path in paths:
        path = _configured_path(raw_path)
        info = path.lstat()
        if path.is_symlink() or not path.is_file():
            raise ValueError("duplicate target must be a regular non-symlink file")
        by_size[info.st_size].append(path)

    confirmed: list[dict[str, Any]] = []
    for size, candidates in sorted(by_size.items()):
        if len(candidates) < 2:
            continue
        by_hash: dict[str, list[str]] = defaultdict(list)
        for path in candidates:
            by_hash[sha256_file(path)].append(str(path))
        for digest, matching_paths in sorted(by_hash.items()):
            if len(matching_paths) > 1:
                confirmed.append(
                    {
                        "size_bytes": size,
                        "sha256": digest,
                        "paths": sorted(matching_paths),
                        "confirmed": True,
                    }
                )
    return confirmed


def confirm_duplicate_candidates(candidates: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Explicit confirmation adapter for records from ``find_duplicate_candidates``."""

    paths = [item["path"] for candidate in candidates for item in candidate["files"]]
    return confirm_duplicates(paths)
