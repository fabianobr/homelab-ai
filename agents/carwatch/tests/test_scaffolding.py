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


def test_docker_compose_config_is_valid_without_a_dotenv_file(tmp_path):
    """IMPORTANT 9: `env_file: - .env` with no `required: false` made a fresh
    clone (which only has .env.example) unable to even run
    `docker compose config`. The test above passes on a working copy that
    already has a .env, so reproduce the fresh-clone layout explicitly.
    """
    (tmp_path / "docker-compose.yml").write_text(
        (REPO_ROOT / "docker-compose.yml").read_text()
    )
    (tmp_path / "Dockerfile").write_text((REPO_ROOT / "Dockerfile").read_text())
    assert not (tmp_path / ".env").exists()

    result = subprocess.run(
        ["docker", "compose", "config"],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr


def test_readme_tells_you_to_create_dotenv_before_running_the_tests():
    readme = (REPO_ROOT / "README.md").read_text()
    setup, _, rest = readme.partition("## Testes")
    assert "cp .env.example .env" in setup, "the one-time .env setup must precede ## Testes"
    assert ".env" in rest.split("##")[0], "the Testes section must point at the .env setup"


def test_pyproject_declares_carwatch_entrypoint():
    content = (REPO_ROOT / "pyproject.toml").read_text()
    assert 'carwatch = "carwatch.cli:app"' in content
