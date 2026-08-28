"""Contrato de testes do Weekly Disk Guardian.

Gerado manualmente no Gate 2 porque o WF5 atual é específico para FastAPI.
Os testes usam apenas diretórios temporários e adapters falsos: nunca executam
Docker, sudo, journalctl ou exclusões no host.
"""

from __future__ import annotations

import json
import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from collectors.docker import DockerImageEvidence, is_removable_image
from disk_guardian import build_parser
from executor import (
    ExecutionContext,
    ManifestExecutor,
    deduplicate_files_transactional,
    migrate_file_transactional,
)
from notifications import build_remote_summary
from planner import build_plan_views, classify_pressure, target_reached
from reports import render_report
from schemas import (
    SCHEMA_VERSION,
    Action,
    ActionResult,
    ActionStatus,
    ActionType,
    Approval,
    PressureState,
    RiskLevel,
    RunManifest,
    RunStatus,
    SchemaError,
)
from state import StateStore


GIB = 1024**3
NOW = datetime(2026, 8, 23, 18, 0, tzinfo=UTC)


def action(
    action_id: str,
    action_type: ActionType,
    risk: RiskLevel,
    reclaim_gib: int,
    **params,
) -> Action:
    return Action(
        action_id=action_id,
        type=action_type,
        risk=risk,
        expected_reclaim_bytes=reclaim_gib * GIB,
        reversible=risk is not RiskLevel.HIGH,
        params=params,
    )


class FakeRunner:
    def __init__(self, responses=None):
        self.calls: list[tuple[str, ...]] = []
        self.responses = responses or {}

    def run(self, argv, *, check=True, timeout=None):
        assert isinstance(argv, (list, tuple))
        assert not isinstance(argv, str)
        call = tuple(str(part) for part in argv)
        self.calls.append(call)
        response = self.responses.get(call, {"returncode": 0, "stdout": ""})
        if check and response.get("returncode", 0) != 0:
            raise RuntimeError(f"command failed: {call}")
        return response


class FakeService:
    def __init__(self, healthy=True):
        self.healthy = healthy
        self.events: list[str] = []

    def stop(self, name):
        self.events.append(f"stop:{name}")

    def start(self, name):
        self.events.append(f"start:{name}")

    def wait_healthy(self, name, timeout_seconds):
        self.events.append(f"health:{name}")
        return self.healthy


class FakeHasher:
    def __init__(self, hashes=None):
        self.hashes = hashes or {}

    def sha256(self, path):
        path = Path(path)
        return self.hashes.get(str(path), f"same:{path.read_bytes()!r}")


class FakeLiveEvidence:
    def __init__(self, valid=True, root_percent=90, root_available_gib=10):
        self.valid = valid
        self.root_percent = root_percent
        self.root_available_bytes = root_available_gib * GIB

    def revalidate(self, _action):
        return self.valid


class RefreshingLiveEvidence(FakeLiveEvidence):
    def __init__(self, *, fail_refresh=False):
        super().__init__(valid=True, root_percent=90, root_available_gib=10)
        self.fail_refresh = fail_refresh
        self.refresh_calls = 0

    def refresh(self):
        self.refresh_calls += 1
        if self.fail_refresh:
            raise RuntimeError("refresh indisponível")
        self.root_percent = 74
        self.root_available_bytes = 101 * GIB


# ---------------------------------------------------------------------------
# RF-01/RF-02 — classificação determinística do diagnóstico
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("percent", "available_gib", "read_only", "expected"),
    [
        (70, 150, False, PressureState.GREEN),
        (75, 150, False, PressureState.AMBER),
        (70, 80, False, PressureState.AMBER),
        (85, 150, False, PressureState.RED),
        (70, 30, False, PressureState.RED),
        (92, 150, False, PressureState.CRITICAL),
        (70, 10, False, PressureState.CRITICAL),
        (10, 500, True, PressureState.CRITICAL),
    ],
)
def test_classify_pressure_uses_worst_matching_condition(
    percent, available_gib, read_only, expected
):
    assert (
        classify_pressure(
            percent_used=percent,
            available_bytes=available_gib * GIB,
            read_only=read_only,
            amber_percent=75,
            red_percent=85,
            critical_percent=92,
            amber_available_bytes=100 * GIB,
            red_available_bytes=40 * GIB,
            critical_available_bytes=20 * GIB,
        )
        is expected
    )


# ---------------------------------------------------------------------------
# RF-03/RF-04/RF-09 — proposta e planos
# ---------------------------------------------------------------------------


def test_plan_views_reference_only_action_ids_from_the_same_proposal():
    actions = [
        action("A-001", ActionType.CLEAN_PIP_CACHE, RiskLevel.LOW, 5),
        action("A-002", ActionType.REMOVE_DOCKER_IMAGE, RiskLevel.MEDIUM, 8),
        action("A-003", ActionType.MIGRATE_MODEL, RiskLevel.MEDIUM, 40),
        action("A-004", ActionType.MANUAL_PERSONAL_CLEANUP, RiskLevel.HIGH, 10),
    ]

    views = build_plan_views(actions)
    known_ids = {item.action_id for item in actions}

    assert set(views) == {"conservative", "balanced", "custom"}
    assert set(views["conservative"]) == {"A-001"}
    assert set(views["balanced"]) == {"A-001", "A-002", "A-003"}
    assert set(views["custom"]) == known_ids
    assert all(set(ids) <= known_ids for ids in views.values())


def test_manual_personal_cleanup_never_enters_an_executable_default_plan():
    actions = [
        action("A-001", ActionType.MANUAL_PERSONAL_CLEANUP, RiskLevel.HIGH, 100)
    ]
    views = build_plan_views(actions)

    assert views["conservative"] == []
    assert views["balanced"] == []
    assert views["custom"] == ["A-001"]


@pytest.mark.parametrize(
    ("percent", "available_gib", "expected"),
    [(74, 10, False), (80, 101, False), (74, 101, True), (75, 100, False)],
)
def test_target_reached_requires_both_percent_and_available_space(
    percent, available_gib, expected
):
    assert (
        target_reached(
            percent_used=percent,
            available_bytes=available_gib * GIB,
            target_percent=75,
            min_available_bytes=100 * GIB,
        )
        is expected
    )


# ---------------------------------------------------------------------------
# RF-05/RF-12 — aprovação versionada, expiração e idempotência
# ---------------------------------------------------------------------------


def test_medium_risk_action_requires_explicit_action_id_in_approval():
    approval = Approval(
        run_id="run-1",
        schema_version=SCHEMA_VERSION,
        approved_action_ids=("A-001",),
        approved_at=NOW,
        expires_at=NOW + timedelta(hours=48),
    )

    assert approval.allows("A-001", now=NOW)
    assert not approval.allows("A-002", now=NOW)


def test_approval_expires_after_48_hours():
    approval = Approval(
        run_id="run-1",
        schema_version=SCHEMA_VERSION,
        approved_action_ids=("A-001",),
        approved_at=NOW,
        expires_at=NOW + timedelta(hours=48),
    )

    assert approval.allows("A-001", now=NOW + timedelta(hours=47, minutes=59))
    assert not approval.allows("A-001", now=NOW + timedelta(hours=48, seconds=1))


def test_unknown_schema_version_is_rejected():
    payload = {
        "run_id": "run-1",
        "schema_version": SCHEMA_VERSION + 1,
        "approved_action_ids": ["A-001"],
        "approved_at": NOW.isoformat(),
        "expires_at": (NOW + timedelta(hours=48)).isoformat(),
    }

    with pytest.raises(SchemaError):
        Approval.from_dict(payload)


def test_completed_manifest_is_idempotent_and_runs_no_commands(tmp_path):
    runner = FakeRunner()
    store = StateStore(tmp_path)
    executor = ManifestExecutor(
        ExecutionContext(
            runner=runner,
            state_store=store,
            service=FakeService(),
            hasher=FakeHasher(),
            now=lambda: NOW,
        )
    )
    manifest = RunManifest(
        run_id="run-1",
        schema_version=SCHEMA_VERSION,
        status=RunStatus.COMPLETED,
        actions=(),
    )
    approval = Approval(
        run_id="run-1",
        schema_version=SCHEMA_VERSION,
        approved_action_ids=(),
        approved_at=NOW,
        expires_at=NOW + timedelta(hours=48),
    )

    result = executor.apply(manifest, approval, FakeLiveEvidence())

    assert result.status is RunStatus.COMPLETED
    assert result.already_completed is True
    assert runner.calls == []


# ---------------------------------------------------------------------------
# RF-03/RF-06 — elegibilidade e drift Docker
# ---------------------------------------------------------------------------


def docker_image(**changes):
    base = DockerImageEvidence(
        image_id="sha256:old",
        tags=("example/old:1",),
        created_at=NOW - timedelta(days=30),
        active_container_ids=(),
        compose_referenced=False,
    )
    return replace(base, **changes)


@pytest.mark.parametrize(
    "image",
    [
        docker_image(tags=("example/rollback-20260823",)),
        docker_image(active_container_ids=("container-1",)),
        docker_image(compose_referenced=True),
        docker_image(created_at=NOW - timedelta(days=2)),
    ],
)
def test_protected_active_referenced_or_recent_docker_image_is_not_removable(image):
    assert not is_removable_image(
        image,
        now=NOW,
        protected_tag_patterns=("rollback-*", "backup-*"),
        protect_newer_than_days=7,
    )


def test_old_unreferenced_inactive_docker_image_is_removable():
    assert is_removable_image(
        docker_image(),
        now=NOW,
        protected_tag_patterns=("rollback-*", "backup-*"),
        protect_newer_than_days=7,
    )


def test_docker_drift_skips_image_removal_without_command(tmp_path):
    runner = FakeRunner()
    executor = ManifestExecutor(
        ExecutionContext(
            runner=runner,
            state_store=StateStore(tmp_path),
            service=FakeService(),
            hasher=FakeHasher(),
            now=lambda: NOW,
        )
    )
    item = action(
        "A-001",
        ActionType.REMOVE_DOCKER_IMAGE,
        RiskLevel.MEDIUM,
        8,
        image_id="sha256:old",
    )

    result = executor.apply_action(item, live_evidence=FakeLiveEvidence(valid=False))

    assert result.status is ActionStatus.SKIPPED_DRIFT
    assert runner.calls == []


# ---------------------------------------------------------------------------
# RF-06/RF-07/RF-08 — migração transacional e rollback
# ---------------------------------------------------------------------------


def test_hash_mismatch_keeps_source_and_never_stops_service(tmp_path):
    source = tmp_path / "source" / "model.bin"
    destination = tmp_path / "destination" / "model.bin"
    consumer = tmp_path / "consumer" / "model.bin"
    source.parent.mkdir()
    destination.parent.mkdir()
    consumer.parent.mkdir()
    source.write_bytes(b"model")
    service = FakeService()
    hasher = FakeHasher(
        {str(source): "source-hash", str(destination.with_suffix(".bin.incoming")): "bad"}
    )

    result = migrate_file_transactional(
        source=source,
        destination=destination,
        consumer_link=consumer,
        service_name="comfyui",
        service=service,
        hasher=hasher,
        destination_min_free_bytes=0,
    )

    assert result.status is ActionStatus.FAILED_SAFE
    assert source.read_bytes() == b"model"
    assert not consumer.exists()
    assert service.events == []


def test_successful_migration_publishes_link_after_hash_and_health(tmp_path):
    source = tmp_path / "source" / "model.bin"
    destination = tmp_path / "destination" / "model.bin"
    source.parent.mkdir()
    destination.parent.mkdir()
    source.write_bytes(b"model")
    service = FakeService(healthy=True)

    result = migrate_file_transactional(
        source=source,
        destination=destination,
        consumer_link=source,
        service_name="comfyui",
        service=service,
        hasher=FakeHasher(),
        destination_min_free_bytes=0,
    )

    assert result.status is ActionStatus.APPLIED
    assert source.is_symlink()
    assert source.resolve() == destination.resolve()
    assert destination.read_bytes() == b"model"
    assert not source.with_name("model.bin.backup-before-migration").exists()
    assert service.events == ["stop:comfyui", "start:comfyui", "health:comfyui"]


def test_failed_healthcheck_rolls_back_original_file(tmp_path):
    source = tmp_path / "source" / "model.bin"
    destination = tmp_path / "destination" / "model.bin"
    source.parent.mkdir()
    destination.parent.mkdir()
    source.write_bytes(b"original")
    service = FakeService(healthy=False)

    result = migrate_file_transactional(
        source=source,
        destination=destination,
        consumer_link=source,
        service_name="comfyui",
        service=service,
        hasher=FakeHasher(),
        destination_min_free_bytes=0,
    )

    assert result.status is ActionStatus.ROLLED_BACK
    assert source.is_file() and not source.is_symlink()
    assert source.read_bytes() == b"original"
    assert service.events[:3] == ["stop:comfyui", "start:comfyui", "health:comfyui"]
    assert service.events[-1] == "start:comfyui"


def test_deduplication_makes_two_consumers_converge_on_verified_canonical(tmp_path):
    first = tmp_path / "models" / "text_encoders" / "gemma.bin"
    second = tmp_path / "models" / "latent_upscale_models" / "gemma.bin"
    canonical = tmp_path / "model-store" / "text_encoders" / "gemma.bin"
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    canonical.parent.mkdir(parents=True)
    first.write_bytes(b"same-model")
    second.write_bytes(b"same-model")
    service = FakeService(healthy=True)

    result = deduplicate_files_transactional(
        sources=(first, second),
        canonical=canonical,
        service_name="comfyui",
        service=service,
        hasher=FakeHasher(),
        destination_min_free_bytes=0,
    )

    assert result.status is ActionStatus.APPLIED
    assert canonical.read_bytes() == b"same-model"
    assert first.is_symlink() and second.is_symlink()
    assert first.resolve() == canonical.resolve()
    assert second.resolve() == canonical.resolve()
    assert service.events == ["stop:comfyui", "start:comfyui", "health:comfyui"]


def test_read_only_destination_blocks_migration_before_copy(tmp_path, monkeypatch):
    source = tmp_path / "source.bin"
    destination = tmp_path / "destination" / "model.bin"
    destination.parent.mkdir()
    source.write_bytes(b"model")
    monkeypatch.setattr(os, "access", lambda path, mode: False)

    result = migrate_file_transactional(
        source=source,
        destination=destination,
        consumer_link=source,
        service_name="comfyui",
        service=FakeService(),
        hasher=FakeHasher(),
        destination_min_free_bytes=0,
    )

    assert result.status is ActionStatus.FAILED_SAFE
    assert source.read_bytes() == b"model"
    assert not destination.exists()


def test_destination_free_space_guard_uses_larger_of_50_gib_or_20_percent(tmp_path):
    source = tmp_path / "source.bin"
    destination = tmp_path / "destination" / "model.bin"
    destination.parent.mkdir()
    source.write_bytes(b"model")

    result = migrate_file_transactional(
        source=source,
        destination=destination,
        consumer_link=source,
        service_name="comfyui",
        service=FakeService(),
        hasher=FakeHasher(),
        destination_min_free_bytes=10**30,
    )

    assert result.status is ActionStatus.FAILED_SAFE
    assert source.read_bytes() == b"model"


# ---------------------------------------------------------------------------
# RF-06/RF-09/RF-10 — executor, sudo pendente e parada por meta
# ---------------------------------------------------------------------------


def test_executor_stops_starting_actions_when_target_is_reached(tmp_path):
    runner = FakeRunner()
    executor = ManifestExecutor(
        ExecutionContext(
            runner=runner,
            state_store=StateStore(tmp_path),
            service=FakeService(),
            hasher=FakeHasher(),
            now=lambda: NOW,
        ),
        target_percent=75,
        min_available_bytes=100 * GIB,
    )
    actions = (
        action("A-001", ActionType.CLEAN_PIP_CACHE, RiskLevel.LOW, 5),
        action("A-002", ActionType.REMOVE_DOCKER_IMAGE, RiskLevel.MEDIUM, 8),
    )
    manifest = RunManifest(
        run_id="run-1",
        schema_version=SCHEMA_VERSION,
        status=RunStatus.APPROVED,
        actions=actions,
    )
    approval = Approval(
        run_id="run-1",
        schema_version=SCHEMA_VERSION,
        approved_action_ids=("A-001", "A-002"),
        approved_at=NOW,
        expires_at=NOW + timedelta(hours=48),
    )
    live = FakeLiveEvidence(valid=True, root_percent=74, root_available_gib=101)

    result = executor.apply(manifest, approval, live)

    assert result.action_results[0].status is ActionStatus.NOT_NEEDED
    assert result.action_results[1].status is ActionStatus.NOT_NEEDED
    assert runner.calls == []


def test_executor_refreshes_evidence_and_stops_after_first_action_reaches_target(
    tmp_path,
):
    runner = FakeRunner()
    executor = ManifestExecutor(
        ExecutionContext(
            runner=runner,
            state_store=StateStore(tmp_path),
            service=FakeService(),
            hasher=FakeHasher(),
            now=lambda: NOW,
        ),
        target_percent=75,
        min_available_bytes=100 * GIB,
    )
    actions = (
        action("A-001", ActionType.CLEAN_PIP_CACHE, RiskLevel.LOW, 5),
        action("A-002", ActionType.REMOVE_DOCKER_IMAGE, RiskLevel.MEDIUM, 8),
    )
    manifest = RunManifest(
        run_id="run-1",
        schema_version=SCHEMA_VERSION,
        status=RunStatus.APPROVED,
        actions=actions,
    )
    approval = Approval(
        run_id="run-1",
        schema_version=SCHEMA_VERSION,
        approved_action_ids=("A-001", "A-002"),
        approved_at=NOW,
        expires_at=NOW + timedelta(hours=48),
    )
    live = RefreshingLiveEvidence()

    result = executor.apply(manifest, approval, live)

    assert [item.status for item in result.action_results] == [
        ActionStatus.APPLIED,
        ActionStatus.NOT_NEEDED,
    ]
    assert live.refresh_calls == 1
    assert runner.calls == [("python3", "-m", "pip", "cache", "purge")]


def test_executor_fails_closed_and_starts_no_later_action_when_refresh_fails(
    tmp_path,
):
    runner = FakeRunner()
    executor = ManifestExecutor(
        ExecutionContext(
            runner=runner,
            state_store=StateStore(tmp_path),
            service=FakeService(),
            hasher=FakeHasher(),
            now=lambda: NOW,
        )
    )
    actions = (
        action("A-001", ActionType.CLEAN_PIP_CACHE, RiskLevel.LOW, 5),
        action("A-002", ActionType.CLEAN_UV_CACHE, RiskLevel.LOW, 5),
    )
    manifest = RunManifest(
        run_id="run-1",
        schema_version=SCHEMA_VERSION,
        status=RunStatus.APPROVED,
        actions=actions,
    )
    approval = Approval(
        run_id="run-1",
        schema_version=SCHEMA_VERSION,
        approved_action_ids=("A-001", "A-002"),
        approved_at=NOW,
        expires_at=NOW + timedelta(hours=48),
    )
    live = RefreshingLiveEvidence(fail_refresh=True)

    result = executor.apply(manifest, approval, live)

    assert result.status is RunStatus.FAILED_SAFE
    assert [item.status for item in result.action_results] == [
        ActionStatus.APPLIED,
        ActionStatus.FAILED_SAFE,
    ]
    assert live.refresh_calls == 1
    assert runner.calls == [("python3", "-m", "pip", "cache", "purge")]


def test_sudo_unavailable_becomes_pending_manual_and_keeps_exact_argv(tmp_path):
    runner = FakeRunner()
    executor = ManifestExecutor(
        ExecutionContext(
            runner=runner,
            state_store=StateStore(tmp_path),
            service=FakeService(),
            hasher=FakeHasher(),
            now=lambda: NOW,
            sudo_available=lambda: False,
        )
    )
    item = action(
        "A-001",
        ActionType.VACUUM_JOURNAL,
        RiskLevel.LOW,
        1,
        argv=["sudo", "journalctl", "--vacuum-size=200M"],
        requires_sudo=True,
    )

    result = executor.apply_action(item, FakeLiveEvidence(valid=True))

    assert result.status is ActionStatus.PENDING_MANUAL
    assert result.manual_argv == ("sudo", "journalctl", "--vacuum-size=200M")
    assert runner.calls == []


def test_executor_rejects_shell_string_and_glob_for_destructive_action(tmp_path):
    executor = ManifestExecutor(
        ExecutionContext(
            runner=FakeRunner(),
            state_store=StateStore(tmp_path),
            service=FakeService(),
            hasher=FakeHasher(),
            now=lambda: NOW,
        )
    )
    item = action(
        "A-001",
        ActionType.REMOVE_DOCKER_IMAGE,
        RiskLevel.MEDIUM,
        8,
        argv="docker image rm *",
    )

    result = executor.apply_action(item, FakeLiveEvidence(valid=True))

    assert result.status is ActionStatus.FAILED_SAFE


# ---------------------------------------------------------------------------
# RF-10/RF-11 — relatórios, estado local e notificação sanitizada
# ---------------------------------------------------------------------------


def test_state_store_writes_sensitive_json_with_mode_0600(tmp_path):
    store = StateStore(tmp_path)
    path = store.write_json("runs/run-1/diagnosis.json", {"path": "/private/model"})

    assert json.loads(path.read_text()) == {"path": "/private/model"}
    assert path.stat().st_mode & 0o777 == 0o600


def test_remote_summary_excludes_paths_tokens_ips_and_file_names():
    local_report = {
        "run_id": "run-1",
        "state": "red",
        "percent_used": 90,
        "available_bytes": 20 * GIB,
        "suggested_reclaim_bytes": 50 * GIB,
        "action_count": 3,
        "source_path": "/home/person/private/model.safetensors",
        "token": "secret-value",
        "internal_ip": "10.0.0.7",
    }

    summary = build_remote_summary(local_report)

    assert "run-1" in summary
    assert "90%" in summary
    assert "/home/" not in summary
    assert "model.safetensors" not in summary
    assert "secret-value" not in summary
    assert "10.0.0.7" not in summary


def test_report_is_generated_when_no_actions_are_eligible():
    report = render_report(
        run_id="run-1",
        status=RunStatus.COMPLETED,
        before={"percent_used": 70, "available_bytes": 200 * GIB},
        after={"percent_used": 70, "available_bytes": 200 * GIB},
        action_results=[],
        next_steps=["Nenhuma ação necessária"],
    )

    assert "run-1" in report
    assert "Nenhuma ação necessária" in report
    assert "0 ações" in report


def test_report_records_failed_safe_and_rollback():
    result = ActionResult(
        action_id="A-001",
        status=ActionStatus.ROLLED_BACK,
        actual_reclaim_bytes=0,
        message="healthcheck falhou; original restaurado",
    )

    report = render_report(
        run_id="run-1",
        status=RunStatus.ROLLED_BACK,
        before={"percent_used": 90, "available_bytes": 10 * GIB},
        after={"percent_used": 90, "available_bytes": 10 * GIB},
        action_results=[result],
        next_steps=["Investigar serviço"],
    )

    assert "ROLLED_BACK" in report
    assert "original restaurado" in report
    assert "Investigar serviço" in report


# ---------------------------------------------------------------------------
# RF-01/RF-11 — contrato dos arquivos systemd
# ---------------------------------------------------------------------------


def test_timer_is_persistent_and_service_executes_diagnose_only():
    repo_root = Path(__file__).resolve().parents[1]
    timer = repo_root / "systemd" / "weekly-disk-guardian.timer"
    service = repo_root / "systemd" / "weekly-disk-guardian.service"

    timer_text = timer.read_text()
    service_text = service.read_text()

    assert "OnCalendar=Sun 18:00" in timer_text
    assert "Persistent=true" in timer_text
    assert "RandomizedDelaySec=2min" in timer_text
    assert " diagnose" in service_text
    assert " apply" not in service_text


# ---------------------------------------------------------------------------
# Regressão CLI — cada subcomando registra --run exatamente uma vez
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("command", ["review", "report", "verify"])
def test_build_parser_accepts_one_run_argument_for_read_only_commands(command):
    parser = build_parser()

    parsed = parser.parse_args([command, "--run", "run-1"])

    assert parsed.command == command
    assert parsed.run == "run-1"


def test_build_parser_root_help_exits_successfully(capsys):
    parser = build_parser()

    with pytest.raises(SystemExit) as raised:
        parser.parse_args(["--help"])

    assert raised.value.code == 0
    assert "Weekly Disk Guardian" in capsys.readouterr().out
