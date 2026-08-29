from __future__ import annotations

import hashlib
import json

import pytest

import collectors.models as models
from collectors.models import (
    collect_models,
    confirm_duplicate_candidates,
    confirm_duplicates,
    scan_model_root,
    search_model_references,
)


def test_scan_inventory_records_large_files_and_symlinks_without_following(tmp_path):
    root = tmp_path / "models"
    root.mkdir()
    large = root / "model.safetensors"
    large.write_bytes(b"x" * 32)
    (root / "small.bin").write_bytes(b"tiny")
    (root / "alias.safetensors").symlink_to(large.name)
    (root / "broken.safetensors").symlink_to("missing.safetensors")

    evidence = scan_model_root(root, min_size_bytes=16, consumer_mount="/models")

    assert [item["name"] for item in evidence["files"]] == ["model.safetensors"]
    assert evidence["files"][0]["consumer_path"] == "/models/model.safetensors"
    by_name = {item["relative_path"]: item for item in evidence["symlinks"]}
    assert by_name["alias.safetensors"]["broken"] is False
    assert by_name["alias.safetensors"]["target_within_root"] is True
    assert by_name["broken.safetensors"]["broken"] is True
    json.dumps(evidence)


def test_reference_search_is_bounded_and_absence_never_authorizes_deletion(tmp_path):
    refs = tmp_path / "refs"
    refs.mkdir()
    (refs / "workflow.json").write_text('{"model": "model.safetensors"}', encoding="utf-8")
    (refs / "ignored.bin").write_bytes(b"model.safetensors")

    result = search_model_references(["model.safetensors", "missing.gguf"], [refs])

    assert result["matches"]["model.safetensors"] == [str(refs / "workflow.json")]
    assert result["matches"]["missing.gguf"] == []
    assert result["absence_authorizes_deletion"] is False
    assert result["files_scanned"] == 1


def test_collect_models_builds_unconfirmed_candidates_without_hashing(tmp_path, monkeypatch):
    left = tmp_path / "left"
    right = tmp_path / "right"
    refs = tmp_path / "refs"
    left.mkdir()
    right.mkdir()
    refs.mkdir()
    (left / "same.bin").write_bytes(b"same")
    (right / "same.bin").write_bytes(b"same")
    monkeypatch.setattr(
        models,
        "sha256_file",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unexpected hash")),
    )

    evidence = collect_models(
        [left, right],
        min_size_bytes=1,
        reference_roots=[refs],
    )

    assert evidence["hashes_computed"] is False
    assert evidence["read_only"] is True
    assert evidence["duplicate_candidates"][0]["confirmed"] is False
    assert evidence["duplicate_candidates"][0]["confirmation_required"] == "sha256"


def test_explicit_duplicate_confirmation_returns_only_equal_content(tmp_path):
    first = tmp_path / "a.bin"
    second = tmp_path / "b.bin"
    different = tmp_path / "c.bin"
    first.write_bytes(b"equal")
    second.write_bytes(b"equal")
    different.write_bytes(b"other")

    confirmed = confirm_duplicates([first, second, different])

    assert confirmed == [
        {
            "size_bytes": 5,
            "sha256": hashlib.sha256(b"equal").hexdigest(),
            "paths": sorted([str(first), str(second)]),
            "confirmed": True,
        }
    ]


def test_candidate_adapter_hashes_only_explicit_paths(tmp_path):
    first = tmp_path / "same.bin"
    nested = tmp_path / "nested"
    nested.mkdir()
    second = nested / "same.bin"
    first.write_bytes(b"equal")
    second.write_bytes(b"equal")
    candidate = {
        "files": [{"path": str(first)}, {"path": str(second)}],
    }

    confirmed = confirm_duplicate_candidates([candidate])

    assert confirmed[0]["confirmed"] is True
    assert set(confirmed[0]["paths"]) == {str(first), str(second)}


def test_paths_reject_unknown_environment_variables():
    with pytest.raises(ValueError, match="unsupported environment"):
        scan_model_root("$SECRET/models", min_size_bytes=0)
