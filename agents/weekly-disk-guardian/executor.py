"""Fail-closed action executor and transactional file cutovers."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol, Sequence

from planner import target_reached
from schemas import (
    Action,
    ActionResult,
    ActionStatus,
    ActionType,
    Approval,
    ExecutionResult,
    RiskLevel,
    RunManifest,
    RunStatus,
    SCHEMA_VERSION,
)


class Runner(Protocol):
    def run(self, argv: Sequence[str], *, check: bool = True, timeout: int | None = None): ...


class ServiceController(Protocol):
    def stop(self, name: str) -> None: ...
    def start(self, name: str) -> None: ...
    def wait_healthy(self, name: str, timeout_seconds: int) -> bool: ...


class Hasher(Protocol):
    def sha256(self, path: str | Path) -> str: ...


@dataclass
class ExecutionContext:
    runner: Runner
    state_store: object
    service: ServiceController
    hasher: Hasher
    now: Callable
    sudo_available: Callable[[], bool] = field(default=lambda: False)


class ManifestExecutor:
    def __init__(
        self,
        context: ExecutionContext,
        *,
        target_percent: int = 75,
        min_available_bytes: int = 100 * 1024**3,
    ):
        self.context = context
        self.target_percent = target_percent
        self.min_available_bytes = min_available_bytes

    def apply(self, manifest: RunManifest, approval: Approval, live_evidence) -> ExecutionResult:
        """Apply exactly one approved, current manifest; completed runs are inert."""
        if manifest.status is RunStatus.COMPLETED:
            return ExecutionResult(status=RunStatus.COMPLETED, already_completed=True)
        if (
            manifest.schema_version != SCHEMA_VERSION
            or approval.schema_version != SCHEMA_VERSION
            or manifest.run_id != approval.run_id
            or manifest.status is not RunStatus.APPROVED
        ):
            return ExecutionResult(status=RunStatus.FAILED_SAFE)

        now = self.context.now()
        if now.tzinfo is None or now < approval.approved_at or now >= approval.expires_at:
            return ExecutionResult(status=RunStatus.FAILED_SAFE)
        manifest_ids = {item.action_id for item in manifest.actions}
        if not set(approval.approved_action_ids) <= manifest_ids:
            return ExecutionResult(status=RunStatus.FAILED_SAFE)
        results: list[ActionResult] = []
        refresh_failed = False
        for item in manifest.actions:
            if refresh_failed:
                results.append(
                    ActionResult(
                        item.action_id,
                        ActionStatus.FAILED_SAFE,
                        message="ação bloqueada: atualização da evidência falhou",
                    )
                )
                continue
            if target_reached(
                percent_used=live_evidence.root_percent,
                available_bytes=live_evidence.root_available_bytes,
                target_percent=self.target_percent,
                min_available_bytes=self.min_available_bytes,
            ):
                results.append(
                    ActionResult(item.action_id, ActionStatus.NOT_NEEDED, message="meta já atingida")
                )
                continue
            if not approval.allows(item.action_id, now=now):
                results.append(
                    ActionResult(
                        item.action_id,
                        ActionStatus.SKIPPED_UNAPPROVED,
                        message="ação ausente da aprovação válida",
                    )
                )
                continue
            results.append(self.apply_action(item, live_evidence, authorized=True))
            refresh = getattr(live_evidence, "refresh", None)
            if callable(refresh):
                try:
                    refresh()
                except Exception:
                    refresh_failed = True

        status = _run_status_for(results)
        if refresh_failed and status is RunStatus.COMPLETED:
            status = RunStatus.FAILED_SAFE
        result = ExecutionResult(status=status, action_results=tuple(results))
        try:
            self.context.state_store.write_json(
                f"runs/{manifest.run_id}/execution.json", result.to_dict()
            )
        except (AttributeError, OSError, ValueError):
            # Execution results are still returned, but audit failure is fail-closed.
            if any(item.status is ActionStatus.APPLIED for item in results):
                return ExecutionResult(
                    status=RunStatus.NEEDS_ATTENTION,
                    action_results=tuple(results),
                )
        return result

    def apply_action(self, item: Action, live_evidence, *, authorized: bool = False) -> ActionResult:
        try:
            if not live_evidence.revalidate(item):
                return ActionResult(
                    item.action_id,
                    ActionStatus.SKIPPED_DRIFT,
                    message="evidência mudou desde o diagnóstico",
                )
        except Exception:
            return ActionResult(
                item.action_id,
                ActionStatus.FAILED_SAFE,
                message="não foi possível revalidar a evidência",
            )

        if item.type in {ActionType.MANUAL_PERSONAL_CLEANUP, ActionType.ADJUST_EXT4_RESERVE}:
            return ActionResult(
                item.action_id,
                ActionStatus.PENDING_MANUAL,
                message="tipo deliberadamente não executável",
            )

        raw_argv = item.params.get("argv")
        if raw_argv is not None and not _safe_argv(raw_argv):
            return ActionResult(
                item.action_id,
                ActionStatus.FAILED_SAFE,
                message="argv deve ser lista literal sem shell ou glob",
            )

        if item.risk in {RiskLevel.MEDIUM, RiskLevel.HIGH} and not authorized:
            return ActionResult(
                item.action_id,
                ActionStatus.SKIPPED_UNAPPROVED,
                message="ação de médio/alto risco sem autorização do manifesto",
            )

        requires_sudo = item.params.get("requires_sudo", False)
        if requires_sudo:
            if not isinstance(raw_argv, (list, tuple)) or not _allowed_argv(item.type, raw_argv):
                return ActionResult(item.action_id, ActionStatus.FAILED_SAFE, message="comando não permitido")
            if not self.context.sudo_available():
                return ActionResult(
                    item.action_id,
                    ActionStatus.PENDING_MANUAL,
                    message="sudo interativo indisponível",
                    manual_argv=tuple(str(part) for part in raw_argv),
                )

        try:
            if item.type is ActionType.REMOVE_DOCKER_IMAGE:
                image_id = item.params.get("image_id")
                if not isinstance(image_id, str) or not image_id.startswith("sha256:"):
                    return ActionResult(item.action_id, ActionStatus.FAILED_SAFE, message="image ID inválido")
                argv = ["docker", "image", "rm", image_id]
            elif item.type is ActionType.CLEAN_PIP_CACHE:
                argv = list(raw_argv or ["python3", "-m", "pip", "cache", "purge"])
            elif item.type is ActionType.CLEAN_UV_CACHE:
                argv = list(raw_argv or ["uv", "cache", "clean"])
            elif item.type in {
                ActionType.CLEAN_APT_CACHE,
                ActionType.VACUUM_JOURNAL,
                ActionType.REMOVE_DISABLED_SNAP,
            }:
                if not isinstance(raw_argv, (list, tuple)) or not _allowed_argv(item.type, raw_argv):
                    return ActionResult(item.action_id, ActionStatus.FAILED_SAFE, message="comando não permitido")
                argv = list(raw_argv)
            elif item.type is ActionType.MIGRATE_MODEL:
                return migrate_file_transactional(
                    source=Path(str(item.params["source"])),
                    destination=Path(str(item.params["destination"])),
                    consumer_link=Path(str(item.params.get("consumer_link", item.params["source"]))),
                    service_name=str(item.params["service_name"]),
                    service=self.context.service,
                    hasher=self.context.hasher,
                    destination_min_free_bytes=int(item.params["destination_min_free_bytes"]),
                    action_id=item.action_id,
                )
            elif item.type is ActionType.DEDUPLICATE_FILE:
                raw_sources = item.params["sources"]
                if not isinstance(raw_sources, (list, tuple)):
                    raise ValueError("sources inválido")
                return deduplicate_files_transactional(
                    sources=tuple(Path(str(path)) for path in raw_sources),
                    canonical=Path(str(item.params["canonical"])),
                    service_name=str(item.params["service_name"]),
                    service=self.context.service,
                    hasher=self.context.hasher,
                    destination_min_free_bytes=int(item.params["destination_min_free_bytes"]),
                    action_id=item.action_id,
                )
            else:
                return ActionResult(item.action_id, ActionStatus.FAILED_SAFE, message="tipo desconhecido")

            if not _allowed_argv(item.type, argv):
                return ActionResult(item.action_id, ActionStatus.FAILED_SAFE, message="comando não permitido")
            self.context.runner.run(argv, check=True)
            return ActionResult(
                item.action_id,
                ActionStatus.APPLIED,
                actual_reclaim_bytes=item.expected_reclaim_bytes,
            )
        except Exception as exc:
            return ActionResult(
                item.action_id,
                ActionStatus.FAILED_SAFE,
                message=f"ação bloqueada/falhou com segurança: {type(exc).__name__}",
            )


def migrate_file_transactional(
    *,
    source: Path,
    destination: Path,
    consumer_link: Path,
    service_name: str,
    service: ServiceController,
    hasher: Hasher,
    destination_min_free_bytes: int,
    action_id: str = "migration",
    health_timeout_seconds: int = 120,
) -> ActionResult:
    """Copy, verify, publish, cut over, healthcheck, then remove backup."""
    source = Path(source)
    destination = Path(destination)
    consumer_link = Path(consumer_link)
    incoming = destination.with_suffix(destination.suffix + ".incoming")
    backup = source.with_name(source.name + ".backup-before-migration")
    temporary_link = consumer_link.with_name(consumer_link.name + ".link-incoming")
    cutover_started = False

    try:
        source_stat = source.lstat()
        if source.is_symlink() or not source.is_file() or source_stat.st_nlink < 1:
            raise ValueError("origem não é arquivo regular")
        if destination.exists() or incoming.exists() or backup.exists() or temporary_link.exists():
            raise FileExistsError("artefato transacional preexistente")
        if not destination.parent.is_dir() or not os.access(destination.parent, os.W_OK):
            raise PermissionError("destino não gravável")
        if consumer_link != source and consumer_link.exists():
            raise FileExistsError("consumer_link já existe")
        _check_destination_space(destination.parent, source_stat.st_size, destination_min_free_bytes)

        shutil.copy2(source, incoming)
        if source.lstat().st_ino != source_stat.st_ino or source.stat().st_size != source_stat.st_size:
            raise RuntimeError("origem mudou durante a cópia")
        if hasher.sha256(source) != hasher.sha256(incoming):
            raise RuntimeError("hash divergente")
        os.replace(incoming, destination)

        os.symlink(destination.resolve(), temporary_link)
        service.stop(service_name)
        os.replace(source, backup)
        cutover_started = True
        os.replace(temporary_link, consumer_link)
        service.start(service_name)
        healthy = service.wait_healthy(service_name, health_timeout_seconds)
        if not healthy or not consumer_link.is_symlink() or not consumer_link.is_file():
            raise RuntimeError("healthcheck/cutover inválido")
        if consumer_link.resolve() != destination.resolve():
            raise RuntimeError("consumer não converge ao destino")
        backup.unlink()
        return ActionResult(
            action_id,
            ActionStatus.APPLIED,
            actual_reclaim_bytes=source_stat.st_size,
            message="cópia, hash, link e healthcheck validados",
        )
    except Exception as exc:
        incoming.unlink(missing_ok=True)
        temporary_link.unlink(missing_ok=True)
        if cutover_started:
            rollback_ok = _rollback_one(
                source=source,
                consumer_link=consumer_link,
                backup=backup,
                service_name=service_name,
                service=service,
            )
            return ActionResult(
                action_id,
                ActionStatus.ROLLED_BACK if rollback_ok else ActionStatus.NEEDS_ATTENTION,
                message=f"falha após cutover ({type(exc).__name__}); original restaurado"
                if rollback_ok
                else f"falha após cutover ({type(exc).__name__}); rollback incompleto",
            )
        return ActionResult(
            action_id,
            ActionStatus.FAILED_SAFE,
            message=f"migração bloqueada antes do cutover: {type(exc).__name__}",
        )


def deduplicate_files_transactional(
    *,
    sources: tuple[Path, ...],
    canonical: Path,
    service_name: str,
    service: ServiceController,
    hasher: Hasher,
    destination_min_free_bytes: int,
    action_id: str = "deduplication",
    health_timeout_seconds: int = 120,
) -> ActionResult:
    """Verify all hashes, then switch all consumers in one service window."""
    sources = tuple(Path(item) for item in sources)
    canonical = Path(canonical)
    if len(sources) < 2 or len(set(sources)) != len(sources):
        return ActionResult(action_id, ActionStatus.FAILED_SAFE, message="grupo de duplicatas inválido")

    incoming = canonical.with_suffix(canonical.suffix + ".incoming")
    backups = {source: source.with_name(source.name + ".backup-before-dedup") for source in sources}
    links = {source: source.with_name(source.name + ".link-incoming") for source in sources}
    cutover_started = False
    sizes: dict[Path, int] = {}

    try:
        for source in sources:
            if source.is_symlink() or not source.is_file():
                raise ValueError("candidato não é arquivo regular")
            sizes[source] = source.stat().st_size
            if backups[source].exists() or links[source].exists():
                raise FileExistsError("artefato transacional preexistente")
        if len(set(sizes.values())) != 1:
            raise ValueError("tamanhos divergentes")
        hashes = {hasher.sha256(source) for source in sources}
        if len(hashes) != 1:
            raise ValueError("hashes divergentes")
        if canonical.exists() or incoming.exists():
            raise FileExistsError("canônico já existe")
        if not canonical.parent.is_dir() or not os.access(canonical.parent, os.W_OK):
            raise PermissionError("destino não gravável")
        _check_destination_space(canonical.parent, sizes[sources[0]], destination_min_free_bytes)
        shutil.copy2(sources[0], incoming)
        if hasher.sha256(incoming) != next(iter(hashes)):
            raise RuntimeError("hash do canônico divergente")
        os.replace(incoming, canonical)

        for temporary in links.values():
            os.symlink(canonical.resolve(), temporary)
        service.stop(service_name)
        for source in sources:
            os.replace(source, backups[source])
            cutover_started = True
            os.replace(links[source], source)
        service.start(service_name)
        if not service.wait_healthy(service_name, health_timeout_seconds):
            raise RuntimeError("healthcheck falhou")
        if any(not source.is_symlink() or source.resolve() != canonical.resolve() for source in sources):
            raise RuntimeError("consumidores não convergem ao canônico")
        for backup in backups.values():
            backup.unlink()
        return ActionResult(
            action_id,
            ActionStatus.APPLIED,
            actual_reclaim_bytes=sum(sizes.values()) - sizes[sources[0]],
            message="duplicatas convergem ao canônico verificado",
        )
    except Exception as exc:
        incoming.unlink(missing_ok=True)
        for temporary in links.values():
            temporary.unlink(missing_ok=True)
        if cutover_started:
            rollback_ok = True
            for source in reversed(sources):
                backup = backups[source]
                try:
                    if source.is_symlink():
                        source.unlink()
                    if backup.exists():
                        os.replace(backup, source)
                except OSError:
                    rollback_ok = False
            try:
                service.start(service_name)
            except Exception:
                rollback_ok = False
            return ActionResult(
                action_id,
                ActionStatus.ROLLED_BACK if rollback_ok else ActionStatus.NEEDS_ATTENTION,
                message=f"deduplicação falhou ({type(exc).__name__}); rollback "
                + ("concluído" if rollback_ok else "incompleto"),
            )
        return ActionResult(
            action_id,
            ActionStatus.FAILED_SAFE,
            message=f"deduplicação bloqueada antes do cutover: {type(exc).__name__}",
        )


def _rollback_one(
    *,
    source: Path,
    consumer_link: Path,
    backup: Path,
    service_name: str,
    service: ServiceController,
) -> bool:
    try:
        if consumer_link.is_symlink():
            consumer_link.unlink()
        if backup.exists():
            os.replace(backup, source)
        service.start(service_name)
        return source.is_file() and not source.is_symlink()
    except Exception:
        return False


def _check_destination_space(parent: Path, copy_size: int, configured_minimum: int) -> None:
    usage = shutil.disk_usage(parent)
    minimum_after = max(configured_minimum, int(usage.total * 0.20))
    if usage.free - copy_size < minimum_after:
        raise OSError("espaço livre insuficiente após a cópia")


def _safe_argv(argv: object) -> bool:
    return (
        isinstance(argv, (list, tuple))
        and bool(argv)
        and all(isinstance(part, str) and part and not any(char in part for char in "*?[]\n\r\0") for part in argv)
    )


def _allowed_argv(action_type: ActionType, argv: Sequence[str]) -> bool:
    if not _safe_argv(argv):
        return False
    parts = tuple(argv)
    if action_type is ActionType.CLEAN_PIP_CACHE:
        return parts in {("python3", "-m", "pip", "cache", "purge"), ("pip", "cache", "purge")}
    if action_type is ActionType.CLEAN_UV_CACHE:
        return parts == ("uv", "cache", "clean")
    if action_type is ActionType.CLEAN_APT_CACHE:
        return parts == ("sudo", "apt-get", "clean")
    if action_type is ActionType.VACUUM_JOURNAL:
        return (
            len(parts) == 3
            and parts[:2] == ("sudo", "journalctl")
            and parts[2].startswith("--vacuum-size=")
            and parts[2][14:].replace(".", "", 1).rstrip("KMGTP") .isdigit()
        )
    if action_type is ActionType.REMOVE_DISABLED_SNAP:
        return (
            len(parts) == 6
            and parts[:3] == ("sudo", "snap", "remove")
            and parts[4] == "--revision"
            and parts[3].replace("-", "").isalnum()
            and parts[5].isdigit()
        )
    if action_type is ActionType.REMOVE_DOCKER_IMAGE:
        return len(parts) == 4 and parts[:3] == ("docker", "image", "rm") and parts[3].startswith("sha256:")
    return False


def _run_status_for(results: Sequence[ActionResult]) -> RunStatus:
    statuses = {item.status for item in results}
    if ActionStatus.NEEDS_ATTENTION in statuses:
        return RunStatus.NEEDS_ATTENTION
    if ActionStatus.ROLLED_BACK in statuses:
        return RunStatus.ROLLED_BACK
    if ActionStatus.FAILED_SAFE in statuses:
        return RunStatus.FAILED_SAFE
    if ActionStatus.SKIPPED_UNAPPROVED in statuses:
        return RunStatus.FAILED_SAFE
    return RunStatus.COMPLETED
