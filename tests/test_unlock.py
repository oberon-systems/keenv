import shutil
import sys
import tempfile
import time
from pathlib import Path

import pytest

from keenv import agent, cli
from keenv.config import Settings
from keenv.secret import unseal
from keenv.vault import PinTimeout, WrongCredentials

PASSWORD = 'not-the-real-master-password'
PIN = '123456'
TTL = 60
TIMEOUT = 10.0


@pytest.fixture(name='runtime')
def runtime_fixture(tmp_path, monkeypatch):
    if sys.platform == 'darwin':
        # A socket path is capped at 104 bytes there; tmp_path runs longer.
        home = Path(tempfile.mkdtemp(dir='/tmp'))
    else:
        home = tmp_path / 'run'
        home.mkdir()
    monkeypatch.setenv('XDG_RUNTIME_DIR', str(home))
    yield home
    if sys.platform == 'darwin':
        shutil.rmtree(home, ignore_errors=True)


@pytest.fixture(name='database')
def database_fixture(tmp_path):
    """A path to route on; the stub below means it is never opened."""
    path = tmp_path / 'unlock.kdbx'
    path.write_bytes(b'not a real database')
    return path


@pytest.fixture(name='opened')
def opened_fixture(monkeypatch):
    """Record the password each Vault() was handed, opening nothing."""
    seen = []

    def fake(path, keyfile=None, password=None):
        seen.append(password)
        return 'opened'

    monkeypatch.setattr(cli, 'Vault', fake)
    return seen


def _answers(monkeypatch, pin=PIN):
    monkeypatch.setattr(cli, 'prompt_password', lambda path: PASSWORD)
    monkeypatch.setattr(cli, 'prompt_pin', lambda path, left, deadline: pin)
    monkeypatch.setattr(cli, 'prompt_new_pin', lambda path: PIN)


def _refuse_everything(monkeypatch):
    def refuse(path, keyfile=None, password=None):
        raise WrongCredentials('nope')

    monkeypatch.setattr(cli, 'Vault', refuse)


def _wait_gone(database):
    deadline = time.monotonic() + TIMEOUT
    while time.monotonic() < deadline:
        if agent.connect(database) is None:
            return True
        time.sleep(0.05)
    return False


def test_without_a_ttl_no_agent_appears(runtime, database, opened,
                                        monkeypatch):
    _answers(monkeypatch)
    assert cli._open(Settings(database, None), True) == 'opened'
    assert agent.connect(database) is None


def test_a_zero_ttl_ignores_an_agent_that_is_up(runtime, database, opened,
                                                monkeypatch):
    _answers(monkeypatch)
    cli._open(Settings(database, None, TTL), True)
    try:
        def refuse(path, left, deadline):
            raise AssertionError('a PIN was asked for with ttl 0')

        monkeypatch.setattr(cli, 'prompt_pin', refuse)
        assert cli._open(Settings(database, None, 0), True) == 'opened'
    finally:
        agent.lock(database)


def test_a_key_file_makes_the_ttl_moot(runtime, database, opened,
                                       monkeypatch, capsys):
    _answers(monkeypatch)
    keyfile = database.with_suffix('.keyx')
    keyfile.write_bytes(b'not a real key file')

    cli._open(Settings(database, keyfile, TTL), True)
    assert 'ttl does nothing' in capsys.readouterr().err
    assert agent.connect(database) is None


def test_the_first_run_seeds_the_agent(runtime, database, opened,
                                       monkeypatch):
    _answers(monkeypatch)
    cli._open(Settings(database, None, TTL), True)

    client = agent.connect(database)
    try:
        assert client is not None
        salt, blob = client.get()
        assert unseal(blob, salt, PIN) == PASSWORD
    finally:
        agent.lock(database)


def test_the_second_run_never_asks_for_the_password(runtime, database,
                                                    opened, monkeypatch):
    _answers(monkeypatch)
    cli._open(Settings(database, None, TTL), True)
    try:
        def refuse(path):
            raise AssertionError('the master password was asked for again')

        monkeypatch.setattr(cli, 'prompt_password', refuse)
        assert cli._open(Settings(database, None, TTL), True) == 'opened'
        assert opened == [PASSWORD, PASSWORD]
    finally:
        agent.lock(database)


def test_check_never_starts_an_agent(runtime, database, opened, monkeypatch):
    _answers(monkeypatch)
    assert cli._open(Settings(database, None, TTL), False) == 'opened'
    assert agent.connect(database) is None


def test_check_does_use_an_agent_that_is_already_up(runtime, database,
                                                    opened, monkeypatch):
    _answers(monkeypatch)
    cli._open(Settings(database, None, TTL), True)
    try:
        def refuse(path):
            raise AssertionError('the master password was asked for again')

        monkeypatch.setattr(cli, 'prompt_password', refuse)
        assert cli._open(Settings(database, None, TTL), False) == 'opened'
    finally:
        agent.lock(database)


def test_a_wrong_pin_is_named_as_one(runtime, database, opened, monkeypatch):
    _answers(monkeypatch)
    cli._open(Settings(database, None, TTL), True)
    try:
        _refuse_everything(monkeypatch)
        monkeypatch.setattr(cli, 'prompt_pin', lambda *asked: '999999')
        with pytest.raises(ValueError, match='wrong PIN'):
            cli._open(Settings(database, None, TTL), True)
    finally:
        agent.lock(database)


def test_three_wrong_pins_close_the_agent(runtime, database, opened,
                                          monkeypatch):
    _answers(monkeypatch)
    cli._open(Settings(database, None, TTL), True)

    _refuse_everything(monkeypatch)
    left = []

    def wrong(path, tries, deadline):
        left.append(tries)
        return '999999'

    monkeypatch.setattr(cli, 'prompt_pin', wrong)
    with pytest.raises(ValueError, match='the agent is closed'):
        cli._open(Settings(database, None, TTL), True)

    assert left == [3, 2, 1]
    assert _wait_gone(database)


def test_an_empty_pin_is_a_wrong_one(runtime, database, opened,
                                     monkeypatch):
    _answers(monkeypatch)
    cli._open(Settings(database, None, TTL), True)

    monkeypatch.setattr(cli, 'prompt_pin', lambda *asked: '')
    with pytest.raises(ValueError, match='wrong PIN'):
        cli._open(Settings(database, None, TTL), True)

    assert opened == [PASSWORD]
    assert _wait_gone(database)


def test_a_pin_timeout_closes_the_agent(runtime, database, opened,
                                        monkeypatch):
    _answers(monkeypatch)
    cli._open(Settings(database, None, TTL), True)

    def abandoned(path, left, deadline):
        raise PinTimeout('timed out waiting for the PIN')

    monkeypatch.setattr(cli, 'prompt_pin', abandoned)
    with pytest.raises(PinTimeout):
        cli._open(Settings(database, None, TTL), True)

    assert _wait_gone(database)


def test_a_new_pin_timeout_leaves_no_agent(runtime, database, opened,
                                           monkeypatch):
    _answers(monkeypatch)

    def abandoned(path):
        raise PinTimeout('timed out waiting for the PIN')

    monkeypatch.setattr(cli, 'prompt_new_pin', abandoned)
    with pytest.raises(PinTimeout):
        cli._open(Settings(database, None, TTL), True)

    assert _wait_gone(database)


def test_a_wrong_master_password_leaves_no_agent(runtime, database,
                                                 monkeypatch):
    _answers(monkeypatch)
    _refuse_everything(monkeypatch)
    with pytest.raises(WrongCredentials):
        cli._open(Settings(database, None, TTL), True)

    assert _wait_gone(database)


def test_a_refused_pin_leaves_no_agent(runtime, database, opened,
                                       monkeypatch):
    _answers(monkeypatch)

    def refuse(path):
        raise ValueError('the two PINs do not match')

    monkeypatch.setattr(cli, 'prompt_new_pin', refuse)
    with pytest.raises(ValueError, match='do not match'):
        cli._open(Settings(database, None, TTL), True)

    assert _wait_gone(database)


def test_an_empty_pin_runs_without_the_agent(runtime, database, opened,
                                             monkeypatch):
    _answers(monkeypatch)
    said, slept = [], []
    monkeypatch.setattr(cli, 'prompt_new_pin', lambda path: None)
    monkeypatch.setattr(cli, 'say', said.append)
    monkeypatch.setattr(cli, 'sleep', slept.append)

    assert cli._open(Settings(database, None, TTL), True) == 'opened'
    assert opened == [PASSWORD]
    assert slept == [cli.SKIP_PAUSE]
    assert any('without the agent' in line for line in said)
    assert _wait_gone(database)


def test_an_empty_agent_is_filled_rather_than_refused(runtime, database,
                                                      opened, monkeypatch):
    _answers(monkeypatch)
    assert agent.spawn(database, TTL)
    try:
        assert cli._open(Settings(database, None, TTL), True) == 'opened'
        salt, blob = agent.connect(database).get()
        assert unseal(blob, salt, PIN) == PASSWORD
    finally:
        agent.lock(database)


def test_check_leaves_an_empty_agent_empty(runtime, database, opened,
                                           monkeypatch):
    _answers(monkeypatch)
    assert agent.spawn(database, TTL)
    try:
        assert cli._open(Settings(database, None, TTL), False) == 'opened'
        assert agent.connect(database).get() is None
    finally:
        agent.lock(database)


def test_a_wrong_pin_can_be_typed_again(runtime, database, opened,
                                        monkeypatch):
    _answers(monkeypatch)
    cli._open(Settings(database, None, TTL), True)
    try:
        given = iter(['999999', '888888', PIN])
        monkeypatch.setattr(cli, 'prompt_pin', lambda *asked: next(given))

        def refuse_the_rubbish(path, keyfile=None, password=None):
            if password != PASSWORD:
                raise WrongCredentials('nope')
            return 'opened'

        monkeypatch.setattr(cli, 'Vault', refuse_the_rubbish)
        assert cli._open(Settings(database, None, TTL), True) == 'opened'
    finally:
        agent.lock(database)


def test_a_wrong_pin_never_reaches_the_database_as_rubbish(
    runtime, database, opened, monkeypatch,
):
    """The real unseal(), so the rubbish a wrong PIN gives is genuine."""
    _answers(monkeypatch)
    cli._open(Settings(database, None, TTL), True)
    try:
        monkeypatch.setattr(cli, 'prompt_pin', lambda *asked: '999999')

        def like_pykeepass(path, keyfile=None, password=None):
            # pykeepass encodes the password, and that is where a wrong PIN
            # used to die with a codec error instead of being named one.
            if password.encode() != PASSWORD.encode():
                raise WrongCredentials('nope')
            return 'opened'

        monkeypatch.setattr(cli, 'Vault', like_pykeepass)
        with pytest.raises(ValueError, match='wrong PIN'):
            cli._open(Settings(database, None, TTL), True)
    finally:
        agent.lock(database)


def test_a_refused_pin_drops_an_agent_that_was_already_up(runtime, database,
                                                          opened,
                                                          monkeypatch):
    _answers(monkeypatch)
    assert agent.spawn(database, TTL)

    def refuse(path):
        raise ValueError('the two PINs do not match')

    monkeypatch.setattr(cli, 'prompt_new_pin', refuse)
    with pytest.raises(ValueError, match='do not match'):
        cli._open(Settings(database, None, TTL), True)

    assert _wait_gone(database)
