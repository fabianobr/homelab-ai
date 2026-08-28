from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from config import (
    DockerConfig,
    FilesystemTarget,
    GuardianConfig,
    JournalConfig,
    ModelsConfig,
    NotificationsConfig,
    PolicyConfig,
)
from diagnostics import build_actions, parse_size, root_filesystem
from schemas import ActionType


def fake_config(tmp_path: Path) -> GuardianConfig:
    return GuardianConfig(
        source=tmp_path / "config.yaml",
        approval_ttl_hours=48,
        filesystems=(FilesystemTarget(Path("/"), "root"),),
        cache_roots={},
        policy=PolicyConfig(
            75,
            100,
            75,
            85,
            92,
            100,
            40,
            20,
            50,
            20,
            False,
            20,
        ),
        docker=DockerConfig((), ("rollback-*",), 7, False),
        models=ModelsConfig((), (), tmp_path / "models", "comfyui", "/models", 5, True),
        journal=JournalConfig("200M"),
        notifications=NotificationsConfig(True, False, False),
    )


def base_evidence(tmp_path: Path):
    pip = tmp_path / "pip"
    apt = tmp_path / "apt"
    pip.mkdir()
    apt.mkdir()
    return {
        "host": {
            "filesystems": [
                {
                    "role": "root",
                    "status": "ok",
                    "total_bytes": 1000,
                    "used_bytes": 800,
                    "available_bytes": 200,
                    "percent_used": 80,
                }
            ],
            "caches": [
                {
                    "name": "pip",
                    "path": str(pip),
                    "size_bytes": 10,
                    "status": "ok",
                }
            ],
            "apt_cache": {
                "name": "apt",
                "path": str(apt),
                "size_bytes": 20,
                "status": "ok",
            },
            "journal": {"size_bytes": 300_000_000, "status": "ok"},
            "disabled_snaps": {
                "revisions": [{"name": "core", "revision": "10"}],
                "status": "ok",
            },
            "deleted_open_files": {"status": "ok", "files": []},
        },
        "docker": {
            "status": "complete",
            "candidates": [
                {
                    "image_id": "sha256:unused",
                    "size_bytes": 30,
                    "proofs": {
                        "not_active": True,
                        "not_compose_referenced": True,
                        "no_protected_tag": True,
                        "not_recent": True,
                    },
                }
            ],
        },
        "models": {"roots": [], "reference_search": {}},
    }


def test_build_actions_uses_only_complete_evidence(tmp_path):
    evidence = base_evidence(tmp_path)

    actions = build_actions(evidence, fake_config(tmp_path))

    assert [item.type for item in actions] == [
        ActionType.CLEAN_PIP_CACHE,
        ActionType.CLEAN_APT_CACHE,
        ActionType.VACUUM_JOURNAL,
        ActionType.REMOVE_DISABLED_SNAP,
        ActionType.REMOVE_DOCKER_IMAGE,
    ]
    assert [item.action_id for item in actions] == [
        "A-001",
        "A-002",
        "A-003",
        "A-004",
        "A-005",
    ]
    assert actions[-1].params["image_id"] == "sha256:unused"


def test_partial_docker_evidence_never_creates_image_action(tmp_path):
    evidence = base_evidence(tmp_path)
    evidence["docker"]["status"] = "partial"

    actions = build_actions(evidence, fake_config(tmp_path))

    assert ActionType.REMOVE_DOCKER_IMAGE not in {item.type for item in actions}


def test_root_filesystem_requires_complete_root_evidence(tmp_path):
    evidence = base_evidence(tmp_path)
    assert root_filesystem(evidence)["percent_used"] == 80
    del evidence["host"]["filesystems"][0]["available_bytes"]

    try:
        root_filesystem(evidence)
    except RuntimeError as exc:
        assert "root indisponível" in str(exc)
    else:
        raise AssertionError("incomplete root evidence was accepted")


def test_size_parser_uses_explicit_units():
    assert parse_size("200M") == 200_000_000
    assert parse_size("1.5GiB") == int(1.5 * 1024**3)


def test_fixture_timestamp_is_timezone_aware():
    assert datetime(2026, 8, 23, tzinfo=UTC).tzinfo is UTC
