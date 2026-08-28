#!/usr/bin/env python3
"""Weekly Disk Guardian command-line interface.

The scheduled command is diagnosis only.  Mutating commands require a frozen,
non-expired approval and are intentionally separate from the systemd service.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import secrets
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from collectors.caches import collect_disabled_snaps, collect_journal_usage
from collectors.docker import collect_docker_runtime
from collectors.filesystems import collect_filesystem
from config import ConfigError, GuardianConfig, default_config_path, load_config
from diagnostics import build_actions, collect_diagnosis, root_filesystem
from executor import ExecutionContext, ManifestExecutor
from notification_dispatch import dispatch_summary
from notifications import build_remote_summary
from planner import build_plan_views, classify_pressure
from reports import render_report
from schemas import (
    SCHEMA_VERSION,
    Action,
    ActionType,
    Approval,
    RunManifest,
    RunStatus,
    SchemaError,
)
from state import StateStore
from trends import load_trend


GIB = 1024**3


class SubprocessRunner:
    def run(self, argv, *, check=True, timeout=None):
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
            raise RuntimeError(f"comando falhou com exit code {completed.returncode}")
        return result


class Sha256Hasher:
    def sha256(self, path):
        digest = hashlib.sha256()
        with Path(path).open("rb") as handle:
            for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()


class UserServiceController:
    """Narrow systemd user-service adapter; no sudo and no shell."""

    def __init__(self, runner: SubprocessRunner):
        self.runner = runner

    def stop(self, name):
        self._validate(name)
        self.runner.run(["systemctl", "--user", "stop", name])

    def start(self, name):
        self._validate(name)
        self.runner.run(["systemctl", "--user", "start", name])

    def wait_healthy(self, name, timeout_seconds):
        self._validate(name)
        result = self.runner.run(
            ["systemctl", "--user", "is-active", name],
            check=False,
            timeout=timeout_seconds,
        )
        return result["returncode"] == 0 and result["stdout"].strip() == "active"

    @staticmethod
    def _validate(name):
        if not isinstance(name, str) or not name or not all(c.isalnum() or c in "@_.-" for c in name):
            raise ValueError("nome de serviço inválido")


class LiveEvidence:
    def __init__(self, root_snapshot, *, config=None, runner=None, now=None):
        self.config = config
        self.runner = runner
        self.now = now or (lambda: datetime.now(UTC))
        self.refresh()
        self._diagnosed = root_snapshot

    def refresh(self):
        """Refresh root metrics after an action, before the next target check."""
        snapshot = collect_filesystem("/")
        self.root_percent = snapshot["percent_used"]
        self.root_available_bytes = snapshot["available_bytes"]

    def revalidate(self, action):
        """Require type-specific, complete preconditions; unknown evidence fails."""
        params = action.params
        if action.type in {ActionType.CLEAN_PIP_CACHE, ActionType.CLEAN_UV_CACHE}:
            path = params.get("cache_path")
            expected_device = params.get("device")
            if not isinstance(path, str) or not isinstance(expected_device, int):
                return False
            candidate = Path(path).expanduser()
            return candidate.is_dir() and not candidate.is_symlink() and candidate.stat().st_dev == expected_device
        if action.type is ActionType.CLEAN_APT_CACHE:
            path = params.get("cache_path")
            expected_device = params.get("device")
            if not isinstance(path, str) or not isinstance(expected_device, int):
                return False
            candidate = Path(path)
            return candidate.is_dir() and not candidate.is_symlink() and candidate.stat().st_dev == expected_device
        if action.type is ActionType.VACUUM_JOURNAL:
            if self.runner is None:
                return False
            fresh = collect_journal_usage(runner=self.runner)
            return (
                fresh.get("status") == "ok"
                and int(fresh.get("size_bytes", 0)) > int(params.get("vacuum_size_bytes", 0))
            )
        if action.type is ActionType.REMOVE_DISABLED_SNAP:
            if self.runner is None:
                return False
            fresh = collect_disabled_snaps(runner=self.runner)
            expected = {
                "name": params.get("snap_name"),
                "revision": params.get("revision"),
            }
            return fresh.get("status") == "ok" and expected in fresh.get("revisions", [])
        if action.type is ActionType.REMOVE_DOCKER_IMAGE:
            if self.runner is None or self.config is None:
                return False
            fresh = collect_docker_runtime(
                self.runner,
                compose_files=self.config.docker.compose_files,
                now=self.now(),
                protected_tag_patterns=self.config.docker.protected_tag_patterns,
                protect_newer_than_days=self.config.docker.protect_newer_than_days,
            )
            return fresh.get("status") == "complete" and any(
                item.get("image_id") == params.get("image_id")
                for item in fresh.get("candidates", [])
            )
        if action.type in {ActionType.MIGRATE_MODEL, ActionType.DEDUPLICATE_FILE}:
            return _revalidate_files(action)
        # Docker and privileged host operations need collectors not enabled by
        # the minimal public config, so incomplete evidence blocks execution.
        return False


def default_state_root() -> Path:
    xdg = os.environ.get("XDG_STATE_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".local" / "state"
    return base / "homelab-ai" / "disk-guardian"


def generate_run_id(now: datetime) -> str:
    return f"{now.astimezone(UTC):%Y%m%dT%H%M%S}-{secrets.token_hex(4)}"


def diagnose(
    store: StateStore,
    now: datetime,
    config: GuardianConfig,
    *,
    runner: SubprocessRunner | None = None,
    notify: bool = False,
) -> str:
    run_id = generate_run_id(now)
    active_runner = runner or SubprocessRunner()
    evidence = collect_diagnosis(config, runner=active_runner, now=now)
    root = root_filesystem(evidence)
    policy = config.policy
    state = classify_pressure(
        percent_used=root["percent_used"],
        available_bytes=root["available_bytes"],
        read_only=bool(root.get("mount_info", {}).get("read_only", False)),
        amber_percent=policy.amber_percent,
        red_percent=policy.red_percent,
        critical_percent=policy.critical_percent,
        amber_available_bytes=policy.amber_available_bytes,
        red_available_bytes=policy.red_available_bytes,
        critical_available_bytes=policy.critical_available_bytes,
    )
    actions = build_actions(evidence, config)
    manifest = RunManifest(run_id, SCHEMA_VERSION, RunStatus.PROPOSED, actions)
    plans = build_plan_views(actions)
    diagnosis = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "created_at": now.isoformat(),
        "pressure": state.value,
        "filesystems": evidence["host"]["filesystems"],
        "collector_status": evidence["collector_status"],
        "evidence": evidence,
    }
    proposal = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "plans": plans,
        "actions": [item.to_dict() for item in actions],
    }
    store.write_json(f"runs/{run_id}/diagnosis.json", diagnosis)
    store.write_json(f"runs/{run_id}/proposal.json", proposal)
    store.write_json(f"runs/{run_id}/manifest.json", manifest.to_dict())
    trend = load_trend(store, red_percent=policy.red_percent)
    report = render_report(
        run_id=run_id,
        status=RunStatus.PROPOSED,
        before=root,
        after=root,
        action_results=[],
        next_steps=[f"Revisar: run.sh review --run {run_id}"],
        trend=trend,
    )
    _write_private_text(store, f"reports/{run_id}.md", report)
    summary = build_remote_summary(
        {
            "run_id": run_id,
            "state": state.value,
            "percent_used": root["percent_used"],
            "available_bytes": root["available_bytes"],
            "suggested_reclaim_bytes": sum(item.expected_reclaim_bytes for item in actions),
            "action_count": len(actions),
        }
    )
    print(summary)
    if notify:
        dispatch_summary(summary, config)
    return run_id


def review(store: StateStore, run_id: str) -> None:
    resolved = _resolve_run(store, run_id)
    proposal = store.read_json(f"runs/{resolved}/proposal.json")
    print(f"Run: {resolved}")
    for raw in proposal["actions"]:
        print(
            f"[{raw['action_id']}] {raw['type']} — "
            f"{raw['expected_reclaim_bytes'] / GIB:.1f} GiB — risco {raw['risk']}"
        )
    print("Planos:")
    for name, ids in proposal["plans"].items():
        print(f"  {name}: {', '.join(ids) if ids else 'nenhuma ação'}")


def approve(
    store: StateStore,
    run_id: str,
    plan: str,
    now: datetime,
    config: GuardianConfig,
) -> None:
    resolved = _resolve_run(store, run_id)
    proposal = store.read_json(f"runs/{resolved}/proposal.json")
    if plan not in {"conservative", "balanced"}:
        raise ValueError("approve aceita conservative ou balanced; custom exige interface futura")
    action_ids = tuple(proposal["plans"][plan])
    approval = Approval(
        resolved,
        SCHEMA_VERSION,
        action_ids,
        now,
        now + timedelta(hours=config.approval_ttl_hours),
    )
    manifest = RunManifest.from_dict(store.read_json(f"runs/{resolved}/manifest.json"))
    approved_manifest = RunManifest(resolved, SCHEMA_VERSION, RunStatus.APPROVED, manifest.actions)
    store.write_json(f"runs/{resolved}/approval.json", approval.to_dict())
    store.write_json(f"runs/{resolved}/manifest.json", approved_manifest.to_dict())
    print(
        f"Aprovação criada para {resolved}: {plan} ({len(action_ids)} ações), "
        f"válida por {config.approval_ttl_hours}h."
    )


def apply_approved(
    store: StateStore,
    run_id: str,
    *,
    confirmed: bool,
    plan: str | None,
    now: datetime,
    config: GuardianConfig,
) -> int:
    resolved = _resolve_run(store, run_id)
    if confirmed:
        if plan is None:
            raise ValueError("--yes exige --plan explícito")
        proposal = store.read_json(f"runs/{resolved}/proposal.json")
        approval_payload = store.read_json(f"runs/{resolved}/approval.json")
        if approval_payload["approved_action_ids"] != proposal["plans"].get(plan):
            raise ValueError("--plan não corresponde à aprovação congelada")
    if not confirmed:
        typed = input(f"Digite APLICAR {resolved} para continuar: ").strip()
        if typed != f"APLICAR {resolved}":
            print("Confirmação não corresponde; nenhuma ação executada.", file=sys.stderr)
            return 2
    manifest = RunManifest.from_dict(store.read_json(f"runs/{resolved}/manifest.json"))
    approval = Approval.from_dict(store.read_json(f"runs/{resolved}/approval.json"))
    diagnosis = store.read_json(f"runs/{resolved}/diagnosis.json")
    root_before = next(
        item for item in diagnosis["filesystems"] if item.get("role") == "root"
    )
    runner = SubprocessRunner()
    executor = ManifestExecutor(
        ExecutionContext(
            runner=runner,
            state_store=store,
            service=UserServiceController(runner),
            hasher=Sha256Hasher(),
            now=lambda: now,
            sudo_available=lambda: sys.stdin.isatty(),
        ),
        target_percent=config.policy.target_root_percent,
        min_available_bytes=config.policy.min_root_available_bytes,
    )
    result = executor.apply(
        manifest,
        approval,
        LiveEvidence(
            root_before,
            config=config,
            runner=runner,
            now=lambda: datetime.now(UTC),
        ),
    )
    root_after = collect_filesystem("/")
    estimated_reclaim = sum(
        action.expected_reclaim_bytes
        for action in manifest.actions
        if any(
            item.action_id == action.action_id and item.status.value == "applied"
            for item in result.action_results
        )
    )
    actual_reclaim = max(
        0,
        int(root_after["available_bytes"]) - int(root_before["available_bytes"]),
    )
    store.write_json(
        f"runs/{resolved}/execution.json",
        {
            "schema_version": SCHEMA_VERSION,
            "run_id": resolved,
            "created_at": now.isoformat(),
            "status": result.status.value,
            "estimated_reclaim_bytes": estimated_reclaim,
            "actual_reclaim_bytes": actual_reclaim,
            "estimation_error_bytes": actual_reclaim - estimated_reclaim,
            "before": {
                "percent_used": root_before["percent_used"],
                "available_bytes": root_before["available_bytes"],
            },
            "after": {
                "percent_used": root_after["percent_used"],
                "available_bytes": root_after["available_bytes"],
            },
            "action_results": [item.to_dict() for item in result.action_results],
        },
    )
    report = render_report(
        run_id=resolved,
        status=result.status,
        before=root_before,
        after=root_after,
        action_results=result.action_results,
        next_steps=["Verificar ações pending-manual ou needs-attention antes de novo apply"],
    )
    _write_private_text(store, f"reports/{resolved}.md", report)
    if result.status is RunStatus.COMPLETED:
        completed = RunManifest(resolved, SCHEMA_VERSION, RunStatus.COMPLETED, manifest.actions)
        store.write_json(f"runs/{resolved}/manifest.json", completed.to_dict())
    print(report)
    return 0 if result.status is RunStatus.COMPLETED else 1


def show_report(store: StateStore, run_id: str) -> None:
    resolved = _resolve_run(store, run_id)
    path = store.root / "reports" / f"{resolved}.md"
    print(path.read_text(encoding="utf-8"), end="")


def verify(store: StateStore, run_id: str) -> int:
    resolved = _resolve_run(store, run_id)
    manifest = RunManifest.from_dict(store.read_json(f"runs/{resolved}/manifest.json"))
    broken = []
    for action in manifest.actions:
        if action.type is ActionType.MIGRATE_MODEL:
            link = Path(str(action.params.get("consumer_link", action.params.get("source", ""))))
            if link.is_symlink() and not link.is_file():
                broken.append(str(link))
    print(f"{resolved}: {manifest.status.value}; links quebrados: {len(broken)}")
    return 1 if broken else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Weekly Disk Guardian")
    parser.add_argument("--state-dir", type=Path, default=default_state_root())
    parser.add_argument("--config", type=Path, default=default_config_path())
    commands = parser.add_subparsers(dest="command", required=True)
    diagnosis = commands.add_parser("diagnose")
    diagnosis.add_argument(
        "--notify",
        action="store_true",
        help="envia apenas o resumo sanitizado aos destinos habilitados",
    )
    for name in ("review", "report", "verify"):
        run_command = commands.add_parser(name)
        run_command.add_argument("--run", required=True, metavar="RUN_ID")
    approval = commands.add_parser("approve")
    approval.add_argument("--run", required=True)
    approval.add_argument("--plan", required=True, choices=("conservative", "balanced"))
    application = commands.add_parser("apply")
    application.add_argument("--run", required=True)
    application.add_argument("--yes", action="store_true")
    application.add_argument("--plan", choices=("conservative", "balanced"))
    commands.add_parser("maintain")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    store = StateStore(args.state_dir)
    now = datetime.now(UTC)
    try:
        config = load_config(args.config)
        if args.command == "diagnose":
            with store.exclusive_lock():
                diagnose(store, now, config, notify=args.notify)
            return 0
        if args.command == "review":
            review(store, args.run)
            return 0
        if args.command == "approve":
            approve(store, args.run, args.plan, now, config)
            return 0
        if args.command == "apply":
            with store.exclusive_lock():
                return apply_approved(
                    store,
                    args.run,
                    confirmed=args.yes,
                    plan=args.plan,
                    now=now,
                    config=config,
                )
        if args.command == "report":
            show_report(store, args.run)
            return 0
        if args.command == "verify":
            return verify(store, args.run)
        if args.command == "maintain":
            with store.exclusive_lock():
                run_id = diagnose(store, now, config)
            review(store, run_id)
            print(f"Aprove explicitamente com: run.sh approve --run {run_id} --plan balanced")
            return 0
    except (
        ConfigError,
        FileNotFoundError,
        KeyError,
        OSError,
        RuntimeError,
        SchemaError,
        ValueError,
    ) as exc:
        print(f"Weekly Disk Guardian falhou fechado: {exc}", file=sys.stderr)
        return 2
    return 2


def _revalidate_files(action: Action) -> bool:
    paths = action.params.get("sources")
    if action.type is ActionType.MIGRATE_MODEL:
        paths = [action.params.get("source")]
    expected = action.params.get("source_evidence")
    if not isinstance(paths, (list, tuple)) or not isinstance(expected, dict):
        return False
    for raw in paths:
        if not isinstance(raw, str) or raw not in expected:
            return False
        path = Path(raw)
        evidence = expected[raw]
        try:
            info = path.lstat()
        except OSError:
            return False
        if path.is_symlink() or not path.is_file():
            return False
        if info.st_ino != evidence.get("inode") or info.st_size != evidence.get("size"):
            return False
    return True


def _resolve_run(store: StateStore, run_id: str) -> str:
    return store.latest_run_id() if run_id == "latest" else run_id


def _write_private_text(store: StateStore, relative_path: str, content: str) -> Path:
    # Reuse atomic JSON persistence, then store the Markdown string without ever
    # relaxing permissions.  The temporary JSON quoting is decoded locally.
    json_path = store.write_json(relative_path + ".json-tmp", {"content": content})
    target = store.root / relative_path
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = target.with_name(f".{target.name}.{secrets.token_hex(4)}")
    temporary.write_text(content, encoding="utf-8")
    temporary.chmod(0o600)
    os.replace(temporary, target)
    json_path.unlink(missing_ok=True)
    return target


if __name__ == "__main__":
    raise SystemExit(main())
