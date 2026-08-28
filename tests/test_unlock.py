import time

import pytest

from keenv import agent, cli
from keenv.config import Settings
from keenv.secret import unseal
from keenv.vault import WrongCredentials

PASSWORD = 'not-the-real-master-password'
PIN = '123456'
TTL = 60
TIMEOUT = 10.0


@pytest.fixture(name='runtime')
def runtime_fixture(tmp_path, monkeypatch):
    home = tmp_path / 'run'
    home.mkdir()
    monkeypatch.setenv('XDG_RUNTIME_DIR', str(home))
    return home


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
    monkeypatch.setattr(cli, 'prompt_pin', lambda path: pin)
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
    assert cli._open(Settings(database, None, None), True) == 'opened'
    assert agent.connect(database) is None


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
        monkeypatch.setattr(cli, 'prompt_pin', lambda path: '999999')
        with pytest.raises(ValueError, match='wrong PIN'):
            cli._open(Settings(database, None, TTL), True)
    finally:
        agent.lock(database)


def test_a_window_of_wrong_pins_drops_the_agent(runtime, database, opened,
                                                monkeypatch):
    _answers(monkeypatch)
    cli._open(Settings(database, None, TTL), True)

    _refuse_everything(monkeypatch)
    monkeypatch.setattr(cli, 'prompt_pin', lambda path: '999999')
    for _ in range(agent.ATTEMPTS):
        with pytest.raises(ValueError, match='wrong PIN'):
            cli._open(Settings(database, None, TTL), True)

    assert _wait_gone(database)
