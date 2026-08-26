import os
import pty
import select
import signal
import time

import pytest

from conftest import ACCESS_KEY, SECRET_KEY, TOKEN
from keenv.uri import parse
from keenv.vault import Vault, prompt_password

PASSWORD = 'not-the-real-master-password'
PROMPT = b'Master password for'
TIMEOUT = 10.0


@pytest.fixture(name='vault')
def vault_fixture(vault_path, keyfile):
    return Vault(vault_path, keyfile=keyfile)


@pytest.mark.parametrize(('reference', 'expected'), [
    ('keenv://Oberon/R2/indech-state/username', ACCESS_KEY),
    ('keenv://Oberon/R2/indech-state/password', SECRET_KEY),
    ('keenv://Oberon/R2/indech-state/title', 'indech-state'),
    ('keenv://Oberon/R2/indech-state/api-token', TOKEN),
])
def test_field_reads_standard_and_custom(vault, reference, expected):
    assert vault.field(parse(reference)) == expected


def test_field_reports_a_missing_entry(vault):
    with pytest.raises(ValueError, match='no entry at Oberon/R2/nope'):
        vault.field(parse('keenv://Oberon/R2/nope/username'))


def test_field_reports_a_missing_field(vault):
    with pytest.raises(ValueError, match='has no absent-one field'):
        vault.field(parse('keenv://Oberon/R2/indech-state/absent-one'))


def test_a_missing_vault_is_named(tmp_path, keyfile):
    with pytest.raises(ValueError, match='vault not found'):
        Vault(tmp_path / 'nowhere.kdbx', keyfile=keyfile)


def test_a_missing_key_file_is_named(vault_path, tmp_path):
    with pytest.raises(ValueError, match='key file not found'):
        Vault(vault_path, keyfile=tmp_path / 'nowhere.keyx')


def test_the_wrong_key_file_is_reported_as_credentials(vault_path, tmp_path):
    wrong = tmp_path / 'wrong.keyx'
    wrong.write_bytes(b'some-other-bytes')
    with pytest.raises(ValueError, match='wrong master password or key file'):
        Vault(vault_path, keyfile=wrong)


def _read_until(master: int, needle: bytes) -> bytes:
    """Read the child's pty until the prompt shows up, or time out."""
    seen = b''
    while needle not in seen:
        if not select.select([master], [], [], TIMEOUT)[0]:
            break
        try:
            chunk = os.read(master, 1024)
        except OSError:
            break
        if not chunk:
            break
        seen += chunk
    return seen


def _exit_code(pid: int) -> int | None:
    """Reap the child within the timeout, killing it if it overstays."""
    deadline = time.monotonic() + TIMEOUT
    while time.monotonic() < deadline:
        done, status = os.waitpid(pid, os.WNOHANG)
        if done == pid:
            return os.waitstatus_to_exitcode(status)
        time.sleep(0.05)

    os.kill(pid, signal.SIGKILL)
    os.waitpid(pid, 0)
    return None


def test_the_password_is_read_from_the_controlling_terminal(vault_path):
    pid, master = pty.fork()
    if pid == 0:
        try:
            typed = prompt_password(vault_path)
        except BaseException:
            os._exit(2)
        os._exit(0 if typed == PASSWORD else 1)

    try:
        prompted = PROMPT in _read_until(master, PROMPT)
        if prompted:
            os.write(master, PASSWORD.encode() + b'\n')
        code = _exit_code(pid)
    finally:
        os.close(master)

    assert prompted, 'no password prompt reached the terminal'
    assert code == 0


def test_a_session_without_a_terminal_is_reported(vault_path):
    pid = os.fork()
    if pid == 0:
        os.setsid()
        try:
            prompt_password(vault_path)
        except ValueError:
            os._exit(0)
        except BaseException:
            os._exit(2)
        os._exit(1)

    assert _exit_code(pid) == 0
