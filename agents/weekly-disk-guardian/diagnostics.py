"""Read-only diagnosis aggregation and deterministic action proposals."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from collectors.docker import collect_docker_runtime
from collectors.host import collect_host_evidence
from collectors.models import collect_models
from config import GuardianConfig
from schemas import Action, ActionType, RiskLevel


def collect_diagnosis(
    config: GuardianConfig,
    *,
    runner,
    now: datetime,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Collect every configured source without mutating host state."""

    host = collect_host_evidence(
        filesystems=[
            {"mount": str(target.mount), "role": target.role}
            for target in config.filesystems
        ],
        runner=runner,
        cache_paths=[
            {"name": name, "path": str(path)}
            for name, path in sorted(config.cache_roots.items())
        ],
        timeout=timeout,
    )
    docker = collect_docker_runtime(
        runner,
        compose_files=config.docker.compose_files,
        now=now,
        protected_tag_patterns=config.docker.protected_tag_patterns,
        protect_newer_than_days=config.docker.protect_newer_than_days,
        timeout=timeout,
    )
    models = collect_models(
        config.models.roots,
        min_size_bytes=config.models.large_file_bytes,
        reference_roots=config.models.reference_roots,
        consumer_mount=config.models.consumer_mount,
    )
    return {
        "host": host,
        "docker": docker,
        "models": models,
        "collector_status": {
            "host": _host_status(host),
            "docker": docker["status"],
            "models": _models_status(models),
        },
        "read_only": True,
    }


def root_filesystem(evidence: dict[str, Any]) -> dict[str, Any]:
    roots = [
        item
        for item in evidence["host"]["filesystems"]
        if item.get("role") == "root"
    ]
    if len(roots) != 1 or not _filesystem_usable(roots[0]):
        raise RuntimeError("evidência completa do filesystem root indisponível")
    return roots[0]


def build_actions(
    evidence: dict[str, Any],
    config: GuardianConfig,
) -> tuple[Action, ...]:
    """Create executable actions only from complete, allowlisted evidence."""

    actions: list[Action] = []

    cache_types = {
        "pip": (
            ActionType.CLEAN_PIP_CACHE,
            ["python3", "-m", "pip", "cache", "purge"],
        ),
        "uv": (ActionType.CLEAN_UV_CACHE, ["uv", "cache", "clean"]),
    }
    for item in evidence["host"]["caches"]:
        definition = cache_types.get(item.get("name"))
        if definition is None or item.get("status") != "ok" or item.get("size_bytes", 0) <= 0:
            continue
        cache_path = Path(str(item["path"]))
        try:
            device = cache_path.stat().st_dev
        except OSError:
            continue
        action_type, argv = definition
        actions.append(
            _action(
                actions,
                action_type,
                RiskLevel.LOW,
                int(item["size_bytes"]),
                reversible=False,
                params={
                    "argv": argv,
                    "cache_path": str(cache_path),
                    "device": device,
                    "impact": "cache será reconstruído sob demanda",
                    "preconditions": ["path_allowlisted", "device_unchanged"],
                },
            )
        )

    apt = evidence["host"]["apt_cache"]
    if apt.get("status") == "ok" and apt.get("size_bytes", 0) > 0:
        apt_path = Path(str(apt["path"]))
        try:
            device = apt_path.stat().st_dev
        except OSError:
            device = None
        if device is not None:
            actions.append(
                _action(
                    actions,
                    ActionType.CLEAN_APT_CACHE,
                    RiskLevel.LOW,
                    int(apt["size_bytes"]),
                    reversible=False,
                    params={
                        "argv": ["sudo", "apt-get", "clean"],
                        "requires_sudo": True,
                        "cache_path": str(apt_path),
                        "device": device,
                        "impact": "pacotes poderão ser baixados novamente",
                        "preconditions": ["apt_cache_unchanged", "sudo_interactive"],
                    },
                )
            )

    journal = evidence["host"]["journal"]
    vacuum_bytes = parse_size(config.journal.vacuum_size)
    if journal.get("status") == "ok" and int(journal.get("size_bytes", 0)) > vacuum_bytes:
        actions.append(
            _action(
                actions,
                ActionType.VACUUM_JOURNAL,
                RiskLevel.LOW,
                int(journal["size_bytes"]) - vacuum_bytes,
                reversible=False,
                params={
                    "argv": [
                        "sudo",
                        "journalctl",
                        f"--vacuum-size={config.journal.vacuum_size}",
                    ],
                    "requires_sudo": True,
                    "diagnosed_size_bytes": int(journal["size_bytes"]),
                    "vacuum_size_bytes": vacuum_bytes,
                    "impact": "logs antigos acima do piso serão removidos",
                    "preconditions": ["journal_usage_revalidated", "sudo_interactive"],
                },
            )
        )

    snaps = evidence["host"]["disabled_snaps"]
    if snaps.get("status") == "ok":
        for revision in sorted(
            snaps.get("revisions", []),
            key=lambda item: (str(item["name"]), str(item["revision"])),
        ):
            actions.append(
                _action(
                    actions,
                    ActionType.REMOVE_DISABLED_SNAP,
                    RiskLevel.LOW,
                    0,
                    reversible=False,
                    params={
                        "argv": [
                            "sudo",
                            "snap",
                            "remove",
                            str(revision["name"]),
                            "--revision",
                            str(revision["revision"]),
                        ],
                        "requires_sudo": True,
                        "snap_name": str(revision["name"]),
                        "revision": str(revision["revision"]),
                        "impact": "revisão snap já desabilitada será removida",
                        "preconditions": ["revision_still_disabled", "sudo_interactive"],
                    },
                )
            )

    if evidence["docker"].get("status") == "complete":
        for candidate in sorted(
            evidence["docker"].get("candidates", []),
            key=lambda item: item["image_id"],
        ):
            actions.append(
                _action(
                    actions,
                    ActionType.REMOVE_DOCKER_IMAGE,
                    RiskLevel.MEDIUM,
                    int(candidate["size_bytes"]),
                    reversible=False,
                    params={
                        "image_id": candidate["image_id"],
                        "diagnosed_proofs": dict(candidate["proofs"]),
                        "impact": "imagem precisará ser baixada ou reconstruída para reutilização",
                        "preconditions": [
                            "not_active",
                            "not_compose_referenced",
                            "no_protected_tag",
                            "not_recent",
                        ],
                    },
                )
            )

    return tuple(actions)


def parse_size(value: str) -> int:
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([KMGT]?i?B?)", value.strip(), re.I)
    if not match:
        raise ValueError("tamanho inválido")
    number = float(match.group(1))
    unit = match.group(2).upper()
    units = {
        "": 1,
        "B": 1,
        "K": 1000,
        "KB": 1000,
        "KI": 1024,
        "KIB": 1024,
        "M": 1000**2,
        "MB": 1000**2,
        "MI": 1024**2,
        "MIB": 1024**2,
        "G": 1000**3,
        "GB": 1000**3,
        "GI": 1024**3,
        "GIB": 1024**3,
        "T": 1000**4,
        "TB": 1000**4,
        "TI": 1024**4,
        "TIB": 1024**4,
    }
    return int(number * units[unit])


def _action(
    existing: list[Action],
    action_type: ActionType,
    risk: RiskLevel,
    expected_reclaim_bytes: int,
    *,
    reversible: bool,
    params: dict[str, Any],
) -> Action:
    return Action(
        action_id=f"A-{len(existing) + 1:03d}",
        type=action_type,
        risk=risk,
        expected_reclaim_bytes=expected_reclaim_bytes,
        reversible=reversible,
        params=params,
    )


def _filesystem_usable(item: dict[str, Any]) -> bool:
    return all(
        key in item
        for key in ("total_bytes", "used_bytes", "available_bytes", "percent_used")
    )


def _host_status(host: dict[str, Any]) -> str:
    statuses = [
        item.get("status", "unavailable") for item in host["filesystems"]
    ]
    statuses.extend(item.get("status", "unavailable") for item in host["caches"])
    statuses.extend(
        host[key].get("status", "unavailable")
        for key in ("apt_cache", "journal", "disabled_snaps", "deleted_open_files")
    )
    if all(status == "ok" for status in statuses):
        return "ok"
    if any(status == "ok" for status in statuses):
        return "partial"
    return "unavailable"


def _models_status(models: dict[str, Any]) -> str:
    roots = models["roots"]
    if roots and all(item["exists"] and not item["errors"] for item in roots):
        search = models["reference_search"]
        return "partial" if search["timed_out"] or search["truncated"] or search["errors"] else "ok"
    if any(item["exists"] for item in roots):
        return "partial"
    return "unavailable"
