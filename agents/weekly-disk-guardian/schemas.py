"""Versioned data contracts for Weekly Disk Guardian.

The executor accepts only these structured records.  Shell snippets are never a
part of the persisted contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Mapping


SCHEMA_VERSION = 1


class SchemaError(ValueError):
    """Raised when persisted state cannot be trusted."""


class PressureState(str, Enum):
    GREEN = "green"
    AMBER = "amber"
    RED = "red"
    CRITICAL = "critical"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ActionType(str, Enum):
    CLEAN_PIP_CACHE = "clean_pip_cache"
    CLEAN_UV_CACHE = "clean_uv_cache"
    CLEAN_APT_CACHE = "clean_apt_cache"
    VACUUM_JOURNAL = "vacuum_journal"
    REMOVE_DISABLED_SNAP = "remove_disabled_snap"
    REMOVE_DOCKER_IMAGE = "remove_docker_image"
    MIGRATE_MODEL = "migrate_model"
    DEDUPLICATE_FILE = "deduplicate_file"
    MANUAL_PERSONAL_CLEANUP = "manual_personal_cleanup"
    ADJUST_EXT4_RESERVE = "adjust_ext4_reserve"


class ActionStatus(str, Enum):
    APPLIED = "applied"
    SKIPPED_DRIFT = "skipped-drift"
    SKIPPED_UNAPPROVED = "skipped-unapproved"
    NOT_NEEDED = "not-needed"
    PENDING_MANUAL = "pending-manual"
    FAILED_SAFE = "failed-safe"
    ROLLED_BACK = "rolled-back"
    NEEDS_ATTENTION = "needs-attention"


class RunStatus(str, Enum):
    DISCOVERING = "DISCOVERING"
    PROPOSED = "PROPOSED"
    EXPIRED = "EXPIRED"
    APPROVED = "APPROVED"
    APPLYING = "APPLYING"
    FAILED_SAFE = "FAILED_SAFE"
    ROLLED_BACK = "ROLLED_BACK"
    VERIFYING = "VERIFYING"
    NEEDS_ATTENTION = "NEEDS_ATTENTION"
    COMPLETED = "COMPLETED"


@dataclass(frozen=True)
class Action:
    action_id: str
    type: ActionType
    risk: RiskLevel
    expected_reclaim_bytes: int
    reversible: bool
    params: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.action_id or not self.action_id.startswith("A-"):
            raise SchemaError("action_id inválido")
        if self.expected_reclaim_bytes < 0:
            raise SchemaError("expected_reclaim_bytes não pode ser negativo")
        if not isinstance(self.params, Mapping):
            raise SchemaError("params deve ser um objeto")

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "type": self.type.value,
            "risk": self.risk.value,
            "expected_reclaim_bytes": self.expected_reclaim_bytes,
            "reversible": self.reversible,
            "params": dict(self.params),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "Action":
        _require_exact_keys(
            payload,
            {"action_id", "type", "risk", "expected_reclaim_bytes", "reversible", "params"},
        )
        try:
            return cls(
                action_id=str(payload["action_id"]),
                type=ActionType(payload["type"]),
                risk=RiskLevel(payload["risk"]),
                expected_reclaim_bytes=int(payload["expected_reclaim_bytes"]),
                reversible=bool(payload["reversible"]),
                params=dict(payload["params"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SchemaError("ação inválida") from exc


@dataclass(frozen=True)
class Approval:
    run_id: str
    schema_version: int
    approved_action_ids: tuple[str, ...]
    approved_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise SchemaError("versão de schema incompatível")
        if self.approved_at.tzinfo is None or self.expires_at.tzinfo is None:
            raise SchemaError("timestamps de aprovação devem ter timezone")
        if self.expires_at <= self.approved_at:
            raise SchemaError("aprovação sem validade positiva")
        if len(set(self.approved_action_ids)) != len(self.approved_action_ids):
            raise SchemaError("IDs duplicados na aprovação")

    def allows(self, action_id: str, *, now: datetime) -> bool:
        return (
            now.tzinfo is not None
            and self.approved_at <= now < self.expires_at
            and action_id in self.approved_action_ids
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "schema_version": self.schema_version,
            "approved_action_ids": list(self.approved_action_ids),
            "approved_at": self.approved_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "Approval":
        _require_exact_keys(
            payload,
            {"run_id", "schema_version", "approved_action_ids", "approved_at", "expires_at"},
        )
        try:
            version = int(payload["schema_version"])
            if version != SCHEMA_VERSION:
                raise SchemaError("versão de schema incompatível")
            ids = payload["approved_action_ids"]
            if not isinstance(ids, list) or not all(isinstance(item, str) for item in ids):
                raise SchemaError("approved_action_ids inválido")
            return cls(
                run_id=str(payload["run_id"]),
                schema_version=version,
                approved_action_ids=tuple(ids),
                approved_at=datetime.fromisoformat(str(payload["approved_at"])),
                expires_at=datetime.fromisoformat(str(payload["expires_at"])),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SchemaError("aprovação inválida") from exc


@dataclass(frozen=True)
class RunManifest:
    run_id: str
    schema_version: int
    status: RunStatus
    actions: tuple[Action, ...]

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise SchemaError("versão de schema incompatível")
        ids = [item.action_id for item in self.actions]
        if len(ids) != len(set(ids)):
            raise SchemaError("manifesto contém IDs duplicados")

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "schema_version": self.schema_version,
            "status": self.status.value,
            "actions": [item.to_dict() for item in self.actions],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RunManifest":
        _require_exact_keys(payload, {"run_id", "schema_version", "status", "actions"})
        try:
            version = int(payload["schema_version"])
            if version != SCHEMA_VERSION:
                raise SchemaError("versão de schema incompatível")
            raw_actions = payload["actions"]
            if not isinstance(raw_actions, list):
                raise SchemaError("actions inválido")
            return cls(
                run_id=str(payload["run_id"]),
                schema_version=version,
                status=RunStatus(payload["status"]),
                actions=tuple(Action.from_dict(item) for item in raw_actions),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SchemaError("manifesto inválido") from exc


@dataclass(frozen=True)
class ActionResult:
    action_id: str
    status: ActionStatus
    actual_reclaim_bytes: int = 0
    message: str = ""
    manual_argv: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "status": self.status.value,
            "actual_reclaim_bytes": self.actual_reclaim_bytes,
            "message": self.message,
            "manual_argv": list(self.manual_argv),
        }


@dataclass(frozen=True)
class ExecutionResult:
    status: RunStatus
    action_results: tuple[ActionResult, ...] = ()
    already_completed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "already_completed": self.already_completed,
            "action_results": [item.to_dict() for item in self.action_results],
        }


def _require_exact_keys(payload: Mapping[str, Any], expected: set[str]) -> None:
    if not isinstance(payload, Mapping) or set(payload) != expected:
        raise SchemaError("campos ausentes ou desconhecidos")
