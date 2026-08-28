"""Validated public configuration for Weekly Disk Guardian."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml


GIB = 1024**3


class ConfigError(ValueError):
    """Raised when a configuration cannot be used safely."""


@dataclass(frozen=True)
class FilesystemTarget:
    mount: Path
    role: str


@dataclass(frozen=True)
class PolicyConfig:
    target_root_percent: int
    min_root_available_bytes: int
    amber_percent: int
    red_percent: int
    critical_percent: int
    amber_available_bytes: int
    red_available_bytes: int
    critical_available_bytes: int
    destination_min_free_bytes: int
    destination_min_free_percent: int
    auto_apply_safe: bool
    auto_apply_max_bytes: int


@dataclass(frozen=True)
class DockerConfig:
    compose_files: tuple[Path, ...]
    protected_tag_patterns: tuple[str, ...]
    protect_newer_than_days: int
    allow_volume_prune: bool


@dataclass(frozen=True)
class ModelsConfig:
    roots: tuple[Path, ...]
    reference_roots: tuple[Path, ...]
    migration_root: Path
    consumer_container: str
    consumer_mount: str
    large_file_bytes: int
    require_sha256: bool


@dataclass(frozen=True)
class JournalConfig:
    vacuum_size: str


@dataclass(frozen=True)
class NotificationsConfig:
    desktop: bool
    telegram: bool
    include_paths: bool


@dataclass(frozen=True)
class GuardianConfig:
    source: Path
    approval_ttl_hours: int
    filesystems: tuple[FilesystemTarget, ...]
    cache_roots: Mapping[str, Path]
    policy: PolicyConfig
    docker: DockerConfig
    models: ModelsConfig
    journal: JournalConfig
    notifications: NotificationsConfig


def default_config_path() -> Path:
    return Path(__file__).with_name("config.yaml")


def load_config(path: str | Path) -> GuardianConfig:
    source = Path(path).expanduser().resolve()
    try:
        raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"não foi possível carregar {source}") from exc
    if not isinstance(raw, Mapping):
        raise ConfigError("configuração deve ser um objeto YAML")
    _known_keys(
        raw,
        {
            "schedule",
            "policy",
            "filesystems",
            "caches",
            "docker",
            "models",
            "journal",
            "notifications",
        },
        "raiz",
    )

    schedule = _mapping(raw, "schedule")
    policy = _mapping(raw, "policy")
    docker = _mapping(raw, "docker")
    models = _mapping(raw, "models")
    journal = _mapping(raw, "journal")
    notifications = _mapping(raw, "notifications")
    _known_keys(
        schedule,
        {"on_calendar", "randomized_delay_sec", "approval_ttl_hours"},
        "schedule",
    )
    _known_keys(
        policy,
        {
            "target_root_percent",
            "min_root_available_gib",
            "amber_percent",
            "red_percent",
            "critical_percent",
            "amber_available_gib",
            "red_available_gib",
            "critical_available_gib",
            "destination_min_free_gib",
            "destination_min_free_percent",
            "auto_apply_safe",
            "auto_apply_max_gib",
        },
        "policy",
    )
    _known_keys(
        docker,
        {
            "compose_files",
            "protected_tag_patterns",
            "protect_newer_than_days",
            "allow_volume_prune",
        },
        "docker",
    )
    _known_keys(
        models,
        {
            "roots",
            "reference_roots",
            "migration_root",
            "consumer_container",
            "consumer_mount",
            "large_file_gib",
            "require_sha256",
        },
        "models",
    )
    _known_keys(journal, {"vacuum_size"}, "journal")
    _known_keys(
        notifications,
        {"desktop", "telegram", "include_paths"},
        "notifications",
    )

    filesystems_raw = raw.get("filesystems", [{"mount": "/", "role": "root"}])
    if not isinstance(filesystems_raw, list) or not filesystems_raw:
        raise ConfigError("filesystems deve ser uma lista não vazia")
    filesystems: list[FilesystemTarget] = []
    for index, item in enumerate(filesystems_raw):
        if not isinstance(item, Mapping):
            raise ConfigError(f"filesystems[{index}] deve ser objeto")
        _known_keys(item, {"mount", "role"}, f"filesystems[{index}]")
        filesystems.append(
            FilesystemTarget(
                _path(item.get("mount"), source.parent, f"filesystems[{index}].mount"),
                _text(item.get("role"), f"filesystems[{index}].role"),
            )
        )
    if sum(target.role == "root" for target in filesystems) != 1:
        raise ConfigError("filesystems deve conter exatamente um role=root")

    caches_raw = raw.get("caches", {})
    if not isinstance(caches_raw, Mapping):
        raise ConfigError("caches deve ser objeto")
    cache_roots = {
        str(name): _path(value, source.parent, f"caches.{name}")
        for name, value in caches_raw.items()
    }

    compose_files = _path_list(docker.get("compose_files", []), source.parent, "docker.compose_files")
    model_roots = _path_list(models.get("roots", []), source.parent, "models.roots")
    reference_roots = _path_list(
        models.get("reference_roots", []), source.parent, "models.reference_roots"
    )

    return GuardianConfig(
        source=source,
        approval_ttl_hours=_integer(
            schedule.get("approval_ttl_hours", 48), "schedule.approval_ttl_hours", minimum=1
        ),
        filesystems=tuple(filesystems),
        cache_roots=cache_roots,
        policy=PolicyConfig(
            target_root_percent=_percent(policy.get("target_root_percent", 75), "policy.target_root_percent"),
            min_root_available_bytes=_gib(
                policy.get("min_root_available_gib", 100), "policy.min_root_available_gib"
            ),
            amber_percent=_percent(policy.get("amber_percent", 75), "policy.amber_percent"),
            red_percent=_percent(policy.get("red_percent", 85), "policy.red_percent"),
            critical_percent=_percent(
                policy.get("critical_percent", 92), "policy.critical_percent"
            ),
            amber_available_bytes=_gib(
                policy.get("amber_available_gib", 100), "policy.amber_available_gib"
            ),
            red_available_bytes=_gib(
                policy.get("red_available_gib", 40), "policy.red_available_gib"
            ),
            critical_available_bytes=_gib(
                policy.get("critical_available_gib", 20), "policy.critical_available_gib"
            ),
            destination_min_free_bytes=_gib(
                policy.get("destination_min_free_gib", 50),
                "policy.destination_min_free_gib",
            ),
            destination_min_free_percent=_percent(
                policy.get("destination_min_free_percent", 20),
                "policy.destination_min_free_percent",
            ),
            auto_apply_safe=_boolean(
                policy.get("auto_apply_safe", False), "policy.auto_apply_safe"
            ),
            auto_apply_max_bytes=_gib(
                policy.get("auto_apply_max_gib", 20), "policy.auto_apply_max_gib"
            ),
        ),
        docker=DockerConfig(
            compose_files=compose_files,
            protected_tag_patterns=_string_tuple(
                docker.get("protected_tag_patterns", ["rollback-*", "backup-*"]),
                "docker.protected_tag_patterns",
            ),
            protect_newer_than_days=_integer(
                docker.get("protect_newer_than_days", 7),
                "docker.protect_newer_than_days",
                minimum=0,
            ),
            allow_volume_prune=_boolean(
                docker.get("allow_volume_prune", False), "docker.allow_volume_prune"
            ),
        ),
        models=ModelsConfig(
            roots=model_roots,
            reference_roots=reference_roots,
            migration_root=_path(
                models.get("migration_root", "/mnt/models/comfyui"),
                source.parent,
                "models.migration_root",
            ),
            consumer_container=_text(
                models.get("consumer_container", "comfyui"), "models.consumer_container"
            ),
            consumer_mount=_text(
                models.get("consumer_mount", "/comfyui/models"), "models.consumer_mount"
            ),
            large_file_bytes=_gib(
                models.get("large_file_gib", 5), "models.large_file_gib"
            ),
            require_sha256=_boolean(
                models.get("require_sha256", True), "models.require_sha256"
            ),
        ),
        journal=JournalConfig(
            vacuum_size=_text(journal.get("vacuum_size", "200M"), "journal.vacuum_size")
        ),
        notifications=NotificationsConfig(
            desktop=_boolean(notifications.get("desktop", True), "notifications.desktop"),
            telegram=_boolean(notifications.get("telegram", False), "notifications.telegram"),
            include_paths=_boolean(
                notifications.get("include_paths", False), "notifications.include_paths"
            ),
        ),
    )


def _mapping(payload: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = payload.get(key, {})
    if not isinstance(value, Mapping):
        raise ConfigError(f"{key} deve ser objeto")
    return value


def _known_keys(payload: Mapping[str, Any], allowed: set[str], label: str) -> None:
    unknown = set(payload) - allowed
    if unknown:
        raise ConfigError(f"{label} contém campos desconhecidos: {', '.join(sorted(unknown))}")


def _path(value: Any, base: Path, label: str) -> Path:
    text = _text(value, label)
    home = str(Path.home())
    if text == "$HOME":
        text = home
    elif text.startswith("$HOME/"):
        text = str(Path(home) / text.removeprefix("$HOME/"))
    if "$" in text:
        raise ConfigError(f"{label} contém variável não permitida")
    path = Path(text).expanduser()
    return (base / path).resolve() if not path.is_absolute() else path.resolve()


def _path_list(value: Any, base: Path, label: str) -> tuple[Path, ...]:
    if not isinstance(value, list):
        raise ConfigError(f"{label} deve ser lista")
    return tuple(_path(item, base, f"{label}[{index}]") for index, item in enumerate(value))


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ConfigError(f"{label} deve ser texto não vazio")
    return value.strip()


def _integer(value: Any, label: str, *, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ConfigError(f"{label} deve ser inteiro >= {minimum}")
    return value


def _percent(value: Any, label: str) -> int:
    result = _integer(value, label, minimum=0)
    if result > 100:
        raise ConfigError(f"{label} deve estar entre 0 e 100")
    return result


def _gib(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise ConfigError(f"{label} deve ser número >= 0")
    return int(value * GIB)


def _boolean(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(f"{label} deve ser booleano")
    return value


def _string_tuple(value: Any, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ConfigError(f"{label} deve ser lista de textos")
    return tuple(value)
