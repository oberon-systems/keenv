import os
import pty
import select
import signal
import time

import pytest
from pykeepass import PyKeePass

from conftest import ACCESS_KEY, SECRET_KEY, TOKEN
from keenv import vault as keenv_vault
from keenv.uri import parse
from keenv.vault import (
    PinTimeout,
    Vault,
    prompt_new_pin,
    prompt_password,
    prompt_pin,
)

PASSWORD = 'not-the-real-master-password'
PROMPT = b'Master password for'
CPR = b'\x1b[6n'
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


def test_a_leading_root_group_name_is_tolerated(vault, vault_path, keyfile):
    root = PyKeePass(str(vault_path), keyfile=str(keyfile)).root_group.name
    reference = f'keenv://{root}/Oberon/R2/indech-state/username'
    assert vault.field(parse(reference)) == ACCESS_KEY


def test_a_literal_root_prefix_is_tolerated(vault):
    reference = 'keenv://root/Oberon/R2/indech-state/username'
    assert vault.field(parse(reference)) == ACCESS_KEY


def test_the_wrong_path_names_the_right_one(vault):
    with pytest.raises(ValueError, match='it is at Oberon/R2/indech-state'):
        vault.field(parse('keenv://Nowhere/indech-state/username'))


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


def _answer_cpr(master: int, needle: bytes) -> bytes:
    """Read like _read_until, answering cursor position requests as a
    terminal would: prompt_toolkit draws the toolbar only once it has one.
    """
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
        if CPR in chunk:
            os.write(master, b'\x1b[1;1R')
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


def _pins(monkeypatch, answers):
    """Answer the prompts in turn, and keep the text of each one."""
    given, asked = iter(answers), []

    def answer(vault, message, deadline, hidden=True):
        asked.append(''.join(text for _, text in message))
        return next(given)

    monkeypatch.setattr(keenv_vault, '_ask', answer)
    monkeypatch.setattr(keenv_vault, 'say', lambda text: None)
    return asked


def test_a_pin_of_the_wrong_length_is_asked_again(vault_path, monkeypatch):
    _pins(monkeypatch, ['123', '123456', '123456'])
    assert prompt_new_pin(vault_path) == '123456'


def test_a_mistyped_repeat_asks_only_the_repeat_again(vault_path,
                                                      monkeypatch):
    asked = _pins(monkeypatch, ['123456', '654321', '123456'])
    assert prompt_new_pin(vault_path) == '123456'
    assert asked[1:] == ['Repeat PIN [3]: ', 'Repeat PIN [2]: ']


def test_a_pin_wrong_three_times_gives_up(vault_path, monkeypatch):
    _pins(monkeypatch, ['12', '34', '56'])
    with pytest.raises(ValueError, match='after 3 attempts'):
        prompt_new_pin(vault_path)


def test_a_repeat_wrong_three_times_gives_up(vault_path, monkeypatch):
    _pins(monkeypatch, ['123456', '1', '2', '3'])
    with pytest.raises(ValueError, match='not repeated after 3 attempts'):
        prompt_new_pin(vault_path)


def test_an_empty_new_pin_skips_the_agent(vault_path, monkeypatch):
    _pins(monkeypatch, [''])
    assert prompt_new_pin(vault_path) is None


def test_only_the_first_prompt_offers_the_skip(vault_path, monkeypatch):
    asked = _pins(monkeypatch, ['12', '', '123456', '123456'])
    assert prompt_new_pin(vault_path) == '123456'
    assert asked[:3] == [
        'New PIN (4 to 8 digits), press Enter to skip: ',
        'New PIN (4 to 8 digits) [2]: ',
        'New PIN (4 to 8 digits) [1]: ',
    ]


def test_a_refused_short_pin_is_asked_again(vault_path, monkeypatch):
    _pins(monkeypatch, ['1234', 'n', '123456', '123456'])
    assert prompt_new_pin(vault_path) == '123456'


def test_an_accepted_short_pin_is_kept(vault_path, monkeypatch):
    _pins(monkeypatch, ['1234', 'y', '1234'])
    assert prompt_new_pin(vault_path) == '1234'


def test_a_spent_deadline_asks_nothing(vault_path):
    with pytest.raises(PinTimeout, match='timed out'):
        prompt_pin(vault_path, 3, time.monotonic())


def test_the_pin_is_read_from_the_controlling_terminal(vault_path):
    pid, master = pty.fork()
    if pid == 0:
        try:
            typed = prompt_pin(vault_path, 3, time.monotonic() + TIMEOUT)
        except BaseException:
            os._exit(2)
        os._exit(0 if typed == '123456' else 1)

    try:
        seen = _answer_cpr(master, b'vault: ')
        prompted = b'[3]' in seen and b'vault: ' in seen
        if prompted:
            os.write(master, b'123456\r')
        code = _exit_code(pid)
    finally:
        os.close(master)

    assert prompted, 'no PIN prompt reached the terminal'
    assert code == 0


def test_an_abandoned_pin_prompt_times_out(vault_path):
    pid, master = pty.fork()
    if pid == 0:
        try:
            prompt_pin(vault_path, 3, time.monotonic() + 1)
        except PinTimeout:
            os._exit(0)
        except BaseException:
            os._exit(2)
        os._exit(1)

    try:
        _answer_cpr(master, b'vault: ')
        code = _exit_code(pid)
    finally:
        os.close(master)

    assert code == 0


def test_a_dumb_terminal_gets_the_plain_prompt(vault_path, monkeypatch):
    monkeypatch.setenv('TERM', 'dumb')
    pid, master = pty.fork()
    if pid == 0:
        try:
            typed = prompt_pin(vault_path, 3, time.monotonic() + TIMEOUT)
        except BaseException:
            os._exit(2)
        os._exit(0 if typed == '123456' else 1)

    try:
        seen = _read_until(master, b'PIN [3]: ')
        if b'PIN [3]: ' in seen:
            os.write(master, b'123456\n')
        code = _exit_code(pid)
    finally:
        os.close(master)

    assert seen == f'vault: {vault_path}\r\nPIN [3]: '.encode()
    assert code == 0


def test_a_dumb_terminal_times_out_as_well(vault_path, monkeypatch):
    monkeypatch.setenv('TERM', 'dumb')
    pid, master = pty.fork()
    if pid == 0:
        try:
            prompt_pin(vault_path, 3, time.monotonic() + 1)
        except PinTimeout:
            os._exit(0)
        except BaseException:
            os._exit(2)
        os._exit(1)

    try:
        _read_until(master, b'PIN [3]: ')
        code = _exit_code(pid)
    finally:
        os.close(master)

    assert code == 0
