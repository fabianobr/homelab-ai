"""tests/test_deadman_ping_sh.py"""
import stat
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PING_SH = REPO_ROOT / "deadman-ping.sh"


def test_deadman_ping_sh_is_executable():
    assert PING_SH.exists()
    assert PING_SH.stat().st_mode & stat.S_IXUSR


def test_deadman_ping_sh_posts_with_bearer_and_timeout():
    content = PING_SH.read_text()

    assert "-X POST" in content
    assert "Authorization: Bearer" in content
    # Sem timeout, um Worker inacessível penduraria o fim do run semanal.
    assert "--max-time" in content


def test_deadman_ping_sh_is_a_noop_when_url_is_empty():
    """Mesmo padrão do backup: sem destino configurado, sai 0 sem fazer nada."""
    content = PING_SH.read_text()

    assert "CARWATCH_DEADMAN_URL" in content
    assert "exit 0" in content


def test_deadman_ping_sh_does_not_hardcode_a_home_path():
    """Repo público: nenhum caminho absoluto de $HOME pode ser versionado."""
    assert "/home/" not in PING_SH.read_text()


def test_deadman_ping_sh_noop_exits_zero_without_url():
    result = subprocess.run(
        ["bash", str(PING_SH)],
        env={"PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "desligado" in result.stdout
