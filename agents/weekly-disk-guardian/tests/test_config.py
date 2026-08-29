from pathlib import Path

import pytest

from config import ConfigError, load_config


def write_config(path: Path, extra: str = "") -> Path:
    path.write_text(
        """
schedule:
  approval_ttl_hours: 24
policy:
  target_root_percent: 70
filesystems:
  - mount: "/"
    role: root
caches:
  pip: "$HOME/.cache/pip"
docker:
  compose_files: ["compose.yml"]
models:
  roots: ["~/models"]
  reference_roots: ["refs"]
  migration_root: "/mnt/models"
notifications:
  telegram: false
"""
        + extra,
        encoding="utf-8",
    )
    return path


def test_config_resolves_relative_paths_and_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    source = write_config(tmp_path / "guardian.yaml")

    config = load_config(source)

    assert config.approval_ttl_hours == 24
    assert config.policy.target_root_percent == 70
    assert config.docker.compose_files == ((tmp_path / "compose.yml").resolve(),)
    assert config.models.reference_roots == ((tmp_path / "refs").resolve(),)
    assert config.cache_roots["pip"] == (tmp_path / "home/.cache/pip").resolve()


def test_config_requires_exactly_one_root_role(tmp_path):
    source = write_config(tmp_path / "guardian.yaml")
    source.write_text(source.read_text().replace("role: root", "role: data"), encoding="utf-8")

    with pytest.raises(ConfigError, match="role=root"):
        load_config(source)


def test_config_rejects_unknown_environment_expansion(tmp_path):
    source = write_config(tmp_path / "guardian.yaml")
    source.write_text(source.read_text().replace("~/models", "$SECRET/models"), encoding="utf-8")

    with pytest.raises(ConfigError, match="variável não permitida"):
        load_config(source)


def test_config_rejects_unknown_top_level_key(tmp_path):
    source = write_config(tmp_path / "guardian.yaml", "\nsecret_backend: true\n")

    with pytest.raises(ConfigError, match="campos desconhecidos"):
        load_config(source)


def test_config_rejects_unknown_nested_key(tmp_path):
    source = write_config(tmp_path / "guardian.yaml")
    source.write_text(
        source.read_text().replace("telegram: false", "telegram: false\n  token: segredo"),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="notifications contém campos desconhecidos"):
        load_config(source)
