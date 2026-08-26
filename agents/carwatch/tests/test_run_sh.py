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
