"""tests/test_run_sh.py"""
import stat
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_run_sh_is_executable_and_does_not_pass_redundant_carwatch_arg():
    run_sh = REPO_ROOT / "run.sh"
    content = run_sh.read_text()

    assert "docker compose run --rm app carwatch weekly-run" not in content
    assert "docker compose run --rm app weekly-run" in content
    mode = run_sh.stat().st_mode
    assert mode & stat.S_IXUSR


def test_run_sh_backs_up_after_the_weekly_run():
    """O backup captura os dados da semana, então roda depois do weekly-run --
    e protegido, porque `set -e` faria uma falha de backup reportar como falha
    um run que na verdade deu certo."""
    content = (REPO_ROOT / "run.sh").read_text()

    assert "./backup.sh" in content
    assert "if ! ./backup.sh" in content
    assert content.index("weekly-run") < content.index("./backup.sh")
