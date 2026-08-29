from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime

from collectors.docker import collect_docker_runtime


ACTIVE = "sha256:active"
COMPOSE = "sha256:compose"
PROTECTED = "sha256:protected"
RECENT = "sha256:recent"
ELIGIBLE = "sha256:eligible"


class FakeRunner:
    def __init__(self, responses, *, timeout_argv=None):
        self.responses = responses
        self.timeout_argv = timeout_argv
        self.calls = []

    def run(self, argv, *, check=False, timeout=None):
        key = tuple(argv)
        self.calls.append((key, check, timeout))
        if key == self.timeout_argv:
            raise subprocess.TimeoutExpired(argv, timeout)
        return self.responses.get(key, {"returncode": 0, "stdout": "", "stderr": ""})


def _json_lines(*values):
    return "".join(json.dumps(value) + "\n" for value in values)


def _responses():
    ids = (ACTIVE, COMPOSE, PROTECTED, RECENT, ELIGIBLE)
    return {
        ("docker", "system", "df", "-v"): {
            "returncode": 0,
            "stdout": "Images space usage:\nTOTAL 5\n",
        },
        ("docker", "container", "ls", "--quiet", "--no-trunc"): {
            "returncode": 0,
            "stdout": "container-1\n",
        },
        (
            "docker",
            "container",
            "inspect",
            "--format",
            "{{json .}}",
            "container-1",
        ): {
            "returncode": 0,
            "stdout": _json_lines({"Id": "container-1", "Image": ACTIVE}),
        },
        ("docker", "image", "ls", "--quiet", "--no-trunc"): {
            "returncode": 0,
            "stdout": "\n".join(ids) + "\n",
        },
        (
            "docker",
            "image",
            "inspect",
            "--format",
            "{{json .}}",
            *sorted(ids),
        ): {
            "returncode": 0,
            "stdout": _json_lines(
                {"Id": ACTIVE, "RepoTags": ["active:latest"], "RepoDigests": [], "Created": "2025-01-01T00:00:00Z", "Size": 10},
                {"Id": COMPOSE, "RepoTags": ["configured:latest"], "RepoDigests": ["configured@sha256:d1"], "Created": "2025-01-01T00:00:00Z", "Size": 20},
                {"Id": PROTECTED, "RepoTags": ["repo:rollback-v1"], "Created": "2025-01-01T00:00:00Z", "Size": 30},
                {"Id": RECENT, "RepoTags": ["recent:v1"], "Created": "2026-08-20T00:00:00Z", "Size": 40},
                {"Id": ELIGIBLE, "RepoTags": None, "Created": "2025-01-01T00:00:00Z", "Size": 50},
            ),
        },
        (
            "docker",
            "compose",
            "-f",
            "compose.yaml",
            "--profile",
            "*",
            "config",
            "--images",
        ): {"returncode": 0, "stdout": "configured\n"},
        ("docker", "volume", "ls", "--quiet"): {
            "returncode": 0,
            "stdout": "database\n",
        },
        (
            "docker",
            "volume",
            "inspect",
            "--format",
            "{{json .}}",
            "database",
        ): {
            "returncode": 0,
            "stdout": _json_lines(
                {"Name": "database", "Driver": "local", "Mountpoint": "/var/lib/docker/volumes/database"}
            ),
        },
    }


def test_collects_four_proofs_and_reports_volumes_without_candidate_volume():
    runner = FakeRunner(_responses())

    evidence = collect_docker_runtime(
        runner,
        compose_files=["compose.yaml"],
        now=datetime(2026, 8, 23, tzinfo=UTC),
    )

    assert evidence["status"] == "complete"
    assert [item["image_id"] for item in evidence["candidates"]] == [ELIGIBLE]
    assert evidence["candidates"][0]["proofs"] == {
        "not_active": True,
        "not_compose_referenced": True,
        "no_protected_tag": True,
        "not_recent": True,
    }
    by_id = {item["image_id"]: item for item in evidence["images"]}
    assert by_id[ACTIVE]["active_container_ids"] == ["container-1"]
    assert by_id[COMPOSE]["compose_referenced"] is True
    assert by_id[PROTECTED]["protected_tag"] is True
    assert by_id[RECENT]["recent"] is True
    assert evidence["volumes"] == [
        {"name": "database", "driver": "local", "mountpoint": "/var/lib/docker/volumes/database"}
    ]
    json.dumps(evidence)


def test_uses_only_read_only_argv_and_enables_all_compose_profiles():
    runner = FakeRunner(_responses())
    collect_docker_runtime(
        runner,
        compose_files=["compose.yaml"],
        now=datetime(2026, 8, 23, tzinfo=UTC),
    )

    argvs = [call[0] for call in runner.calls]
    assert (
        "docker",
        "compose",
        "-f",
        "compose.yaml",
        "--profile",
        "*",
        "config",
        "--images",
    ) in argvs
    assert all(call[1] is False for call in runner.calls)
    assert all("rm" not in argv and "prune" not in argv for argv in argvs)


def test_timeout_marks_partial_and_suppresses_all_candidates():
    timed_out = ("docker", "compose", "-f", "compose.yaml", "--profile", "*", "config", "--images")
    runner = FakeRunner(_responses(), timeout_argv=timed_out)

    evidence = collect_docker_runtime(
        runner,
        compose_files=["compose.yaml"],
        now=datetime(2026, 8, 23, tzinfo=UTC),
    )

    assert evidence["status"] == "partial"
    assert evidence["candidates"] == []
    assert any(error.startswith("timeout:") for error in evidence["errors"])


def test_incomplete_image_parse_marks_partial_and_suppresses_candidates():
    responses = _responses()
    image_inspect = next(key for key in responses if key[:3] == ("docker", "image", "inspect"))
    responses[image_inspect] = {"returncode": 0, "stdout": "{not-json}\n"}

    evidence = collect_docker_runtime(
        FakeRunner(responses),
        compose_files=["compose.yaml"],
        now=datetime(2026, 8, 23, tzinfo=UTC),
    )

    assert evidence["status"] == "partial"
    assert evidence["candidates"] == []
    assert any("parse incomplete" in error for error in evidence["errors"])
