"""tests/test_scaffolding.py"""
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_docker_compose_config_is_valid():
    result = subprocess.run(
        ["docker", "compose", "-f", str(REPO_ROOT / "docker-compose.yml"), "config"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stderr


def test_pyproject_declares_carwatch_entrypoint():
    content = (REPO_ROOT / "pyproject.toml").read_text()
    assert 'carwatch = "carwatch.cli:app"' in content
