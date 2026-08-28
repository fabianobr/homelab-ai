"""Private, atomic XDG state persistence."""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import fcntl


class StateStore:
    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root.chmod(0o700)

    def _resolve(self, relative_path: str | Path) -> Path:
        relative = Path(relative_path)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("state path deve ser relativo e não pode escapar da raiz")
        result = (self.root / relative).resolve()
        if not result.is_relative_to(self.root):
            raise ValueError("state path escapou da raiz")
        return result

    def write_json(self, relative_path: str | Path, payload: Any) -> Path:
        target = self._resolve(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        target.parent.chmod(0o700)
        fd, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
        temporary = Path(temporary_name)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
            target.chmod(0o600)
        except BaseException:
            try:
                temporary.unlink(missing_ok=True)
            finally:
                raise
        return target

    def read_json(self, relative_path: str | Path) -> Any:
        target = self._resolve(relative_path)
        with target.open(encoding="utf-8") as handle:
            return json.load(handle)

    def latest_run_id(self) -> str:
        candidates = self.run_ids()
        if not candidates:
            raise FileNotFoundError("nenhum diagnóstico encontrado")
        return candidates[-1]

    def run_ids(self) -> list[str]:
        runs = self.root / "runs"
        return sorted(item.name for item in runs.iterdir() if item.is_dir()) if runs.exists() else []

    @contextmanager
    def exclusive_lock(self):
        """Serialize diagnose/apply without ever waiting behind a stale run."""
        lock_path = self.root / "lock"
        descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            os.fchmod(descriptor, 0o600)
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeError("outro Weekly Disk Guardian está em execução") from exc
            yield
        finally:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)
