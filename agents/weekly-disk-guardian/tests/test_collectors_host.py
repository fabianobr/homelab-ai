"""Focused contracts for read-only host collectors."""

from __future__ import annotations

import subprocess
from types import SimpleNamespace

from collectors.caches import (
    collect_apt_cache,
    collect_disabled_snaps,
    collect_journal_usage,
)
from collectors.filesystems import collect_filesystem_evidence, collect_filesystems
from collectors.host import collect_deleted_open_files, collect_host_evidence


class FakeRunner:
    def __init__(self, responses=None, failures=None):
        self.responses = responses or {}
        self.failures = failures or {}
        self.calls = []

    def run(self, argv, *, check=True, timeout=None):
        call = tuple(argv)
        self.calls.append((call, check, timeout))
        if call in self.failures:
            raise self.failures[call]
        return self.responses.get(call, {"returncode": 0, "stdout": "", "stderr": ""})


def available(*names):
    names = set(names)
    return lambda command: f"/usr/bin/{command}" if command in names else None


def filesystem_responses(mount="/"):
    return {
        (
            "findmnt",
            "--noheadings",
            "--output",
            "SOURCE,TARGET,FSTYPE,OPTIONS",
            "--target",
            mount,
        ): {"returncode": 0, "stdout": "/dev/root / ext4 rw,relatime\n"},
        (
            "df",
            "--block-size=1",
            "--output=size,used,avail,pcent,target",
            mount,
        ): {
            "returncode": 0,
            "stdout": "1B-blocks Used Available Use% Mounted on\n1000 700 250 70% /\n",
        },
        (
            "df",
            "--output=itotal,iused,iavail,ipcent,target",
            mount,
        ): {
            "returncode": 0,
            "stdout": "Inodes IUsed IFree IUse% Mounted on\n100 25 75 25% /\n",
        },
    }


def fake_statvfs(_path):
    return SimpleNamespace(
        f_frsize=10,
        f_bsize=10,
        f_bfree=30,
        f_bavail=25,
    )


def test_filesystem_combines_mount_df_statvfs_and_inode_evidence():
    runner = FakeRunner(filesystem_responses())

    result = collect_filesystem_evidence(
        "/",
        runner=runner,
        which=available("findmnt", "df"),
        statvfs=fake_statvfs,
    )

    assert result["status"] == "ok"
    assert result["mount_info"] == {
        "source": "/dev/root",
        "target": "/",
        "fstype": "ext4",
        "options": ["rw", "relatime"],
        "read_only": False,
    }
    assert result["available_bytes"] == 250
    assert result["statvfs"] == {
        "free_bytes": 300,
        "available_bytes": 250,
        "reserved_bytes": 50,
    }
    assert result["inodes"]["available"] == 75
    assert all(call[1] is False for call in runner.calls)


def test_configured_filesystems_keep_roles_and_degrade_independently():
    runner = FakeRunner(filesystem_responses("/"))

    results = collect_filesystems(
        [{"mount": "/", "role": "root"}, {"mount": "/missing", "role": "store"}],
        runner=runner,
        which=available("findmnt", "df"),
        statvfs=lambda path: fake_statvfs(path)
        if path == "/"
        else (_ for _ in ()).throw(FileNotFoundError(path)),
    )

    assert results[0]["role"] == "root"
    assert results[0]["status"] == "ok"
    assert results[1]["role"] == "store"
    assert results[1]["status"] == "unavailable"
    assert {error["source"] for error in results[1]["errors"]} == {
        "findmnt",
        "df",
        "df-inodes",
        "statvfs",
    }


def test_timeout_and_missing_tool_are_explicit_partial_results():
    command = (
        "df",
        "--block-size=1",
        "--output=size,used,avail,pcent,target",
        "/",
    )
    runner = FakeRunner(
        filesystem_responses(),
        failures={command: subprocess.TimeoutExpired(command, 2)},
    )

    result = collect_filesystem_evidence(
        "/",
        runner=runner,
        which=available("df"),
        statvfs=fake_statvfs,
        timeout=2,
    )

    assert result["status"] == "partial"
    assert ("findmnt", "tool-unavailable") in {
        (error["source"], error["kind"]) for error in result["errors"]
    }
    assert ("df", "timeout") in {
        (error["source"], error["kind"]) for error in result["errors"]
    }
    assert result["statvfs"]["reserved_bytes"] == 50


def test_journal_apt_and_disabled_snaps_are_read_only(tmp_path):
    apt = tmp_path / "apt"
    apt.mkdir()
    (apt / "one.deb").write_bytes(b"x" * 11)
    runner = FakeRunner(
        {
            ("journalctl", "--disk-usage"): {
                "returncode": 0,
                "stdout": "Archived and active journals take up 1.5G in the file system.\n",
            },
            ("snap", "list", "--all"): {
                "returncode": 0,
                "stdout": (
                    "Name Version Rev Tracking Publisher Notes\n"
                    "core 1.0 10 latest stable base disabled\n"
                    "core 1.1 11 latest stable base -\n"
                ),
            },
        }
    )

    journal = collect_journal_usage(
        runner=runner, which=available("journalctl")
    )
    apt_result = collect_apt_cache(apt)
    snaps = collect_disabled_snaps(runner=runner, which=available("snap"))

    assert journal["size_bytes"] == 1_500_000_000
    assert apt_result["size_bytes"] == 11
    assert snaps["revisions"] == [{"name": "core", "revision": "10"}]
    assert [call[0] for call in runner.calls] == [
        ("journalctl", "--disk-usage"),
        ("snap", "list", "--all"),
    ]


def test_deleted_open_files_are_reported_when_lsof_exists():
    runner = FakeRunner(
        {
            ("lsof", "-nP", "+L1"): {
                "returncode": 0,
                "stdout": (
                    "COMMAND PID USER FD TYPE DEVICE SIZE/OFF NLINK NODE NAME\n"
                    "python 42 user 3w REG 8,1 4096 0 99 /tmp/report (deleted)\n"
                ),
            }
        }
    )

    result = collect_deleted_open_files(runner=runner, which=available("lsof"))

    assert result["status"] == "ok"
    assert result["total_size_bytes"] == 4096
    assert result["files"][0]["path"] == "/tmp/report (deleted)"


def test_host_snapshot_keeps_results_when_optional_tools_are_absent(tmp_path):
    cache = tmp_path / "pip"
    apt = tmp_path / "apt"
    cache.mkdir()
    apt.mkdir()
    (cache / "wheel").write_bytes(b"abc")
    runner = FakeRunner(filesystem_responses())

    snapshot = collect_host_evidence(
        filesystems=[{"mount": "/", "role": "root"}],
        runner=runner,
        cache_paths=[{"name": "pip", "path": cache}],
        apt_cache_path=apt,
        which=available("findmnt", "df"),
    )

    assert snapshot["filesystems"][0]["status"] in {"ok", "partial"}
    assert snapshot["caches"][0]["size_bytes"] == 3
    assert snapshot["apt_cache"]["status"] == "ok"
    assert snapshot["journal"]["errors"][0]["kind"] == "tool-unavailable"
    assert snapshot["disabled_snaps"]["status"] == "unavailable"
    assert snapshot["deleted_open_files"]["status"] == "unavailable"
