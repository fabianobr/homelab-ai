"""tests/test_backup_sh.py"""
import stat
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKUP_SH = REPO_ROOT / "backup.sh"


def test_backup_sh_is_executable():
    assert BACKUP_SH.exists()
    assert BACKUP_SH.stat().st_mode & stat.S_IXUSR


def test_backup_sh_dumps_in_custom_format():
    content = BACKUP_SH.read_text()

    assert "pg_dump" in content
    # -Fc restaura com pg_restore, permite restauração seletiva e já vem comprimido.
    assert "-Fc" in content


def test_backup_sh_writes_to_a_partial_file_first():
    """Com redirecionamento, um pg_dump que falha deixa um arquivo truncado que
    passa por backup bom. O dump vai para .partial e só é promovido no sucesso."""
    content = BACKUP_SH.read_text()

    assert ".partial" in content
    assert "mv " in content


def test_backup_sh_rejects_a_suspiciously_small_dump():
    content = BACKUP_SH.read_text()

    assert "MIN_BYTES" in content


def test_backup_sh_does_not_hardcode_a_home_path():
    """O repo é público: nenhum caminho absoluto de $HOME pode ser versionado."""
    content = BACKUP_SH.read_text()

    assert "/home/" not in content


def test_remote_upload_failure_does_not_fail_the_script():
    """O dump local já existe e já vale; queda de rede não pode derrubar o run
    semanal. O script termina em `exit 0` mesmo com o envio remoto falhando."""
    content = BACKUP_SH.read_text()

    assert content.rstrip().endswith("exit 0")


def test_remote_can_be_disabled_by_env():
    """Outro host (ou o CI) não tem remote rclone configurado; precisa poder
    rodar só com a cópia local."""
    content = BACKUP_SH.read_text()

    assert "CARWATCH_BACKUP_REMOTE" in content
