import time

import pytest

from keenv import agent

SALT = b'0123456789abcdef'
BLOB = bytes(range(128))
TIMEOUT = 10.0


@pytest.fixture(name='runtime')
def runtime_fixture(tmp_path, monkeypatch):
    """Point the agent at a throwaway runtime directory."""
    home = tmp_path / 'run'
    home.mkdir()
    monkeypatch.setenv('XDG_RUNTIME_DIR', str(home))
    return home


@pytest.fixture(name='database')
def database_fixture(tmp_path):
    """A path to name an agent after; it is never opened."""
    path = tmp_path / 'agent.kdbx'
    path.write_bytes(b'not a real database')
    return path


@pytest.fixture(name='running')
def running_fixture(runtime, database):
    assert agent.spawn(database, 60)
    client = agent.connect(database)
    client.put(SALT, bytearray(BLOB))
    yield client
    agent.lock(database)


def _wait_gone(database, timeout=TIMEOUT):
    """Wait for the agent to stop answering, or give up."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if agent.connect(database) is None:
            return True
        time.sleep(0.05)
    return False


def test_a_spawned_agent_answers(running, database):
    assert agent.connect(database) is not None


def test_a_second_spawn_leaves_the_first_alone(running, database):
    assert agent.spawn(database, 60) is False


def test_what_went_in_comes_back(running):
    salt, blob = running.get()
    assert salt == SALT
    assert blob == BLOB


def test_a_second_put_is_refused(running):
    with pytest.raises(ValueError, match='already holds'):
        running.put(SALT, bytearray(BLOB))


def test_two_databases_get_two_agents(runtime, database, tmp_path):
    other = tmp_path / 'other.kdbx'
    other.write_bytes(b'another')
    assert agent.paths(database) != agent.paths(other)

    assert agent.spawn(database, 60)
    assert agent.spawn(other, 60)
    try:
        assert agent.connect(database) is not None
        assert agent.connect(other) is not None
    finally:
        agent.lock(database)
        agent.lock(other)


def test_lock_drops_the_agent(running, database):
    assert agent.lock(database)
    assert _wait_gone(database)


def test_the_files_go_with_it(running, database):
    lock_path, sock_path = agent.paths(database)
    agent.lock(database)
    assert _wait_gone(database)
    assert not lock_path.exists()
    assert not sock_path.exists()


def test_locking_nothing_is_not_an_error(runtime, database):
    assert agent.lock(database) is False


def test_a_full_window_of_failures_kills_it(running, database):
    for _ in range(agent.ATTEMPTS):
        running.fail()
    assert _wait_gone(database)


def test_fewer_failures_leave_it_alone(running, database):
    for _ in range(agent.ATTEMPTS - 1):
        running.fail()
    time.sleep(0.2)
    assert agent.connect(database) is not None


def test_the_agent_expires_on_its_own(runtime, database):
    assert agent.spawn(database, 1)
    agent.connect(database).put(SALT, bytearray(BLOB))
    assert _wait_gone(database)


def test_using_it_puts_the_deadline_back(runtime, database):
    assert agent.spawn(database, 2)
    client = agent.connect(database)
    client.put(SALT, bytearray(BLOB))
    try:
        for _ in range(6):
            time.sleep(0.5)
            client.ok()
        assert agent.connect(database) is not None
    finally:
        agent.lock(database)


def test_a_stale_lock_file_is_cleared(runtime, database):
    lock_path, _ = agent.paths(database)
    lock_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock_path.write_text('{"pid": 2147483, "socket": "/nowhere"}')

    assert agent.connect(database) is None
    assert not lock_path.exists()


def test_a_cleared_lock_file_lets_the_next_agent_in(runtime, database):
    lock_path, _ = agent.paths(database)
    lock_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock_path.write_text('{"pid": 2147483, "socket": "/nowhere"}')
    agent.connect(database)

    assert agent.spawn(database, 60)
    agent.lock(database)


def test_the_socket_is_private(running, database):
    _, sock_path = agent.paths(database)
    assert sock_path.stat().st_mode & 0o077 == 0


def test_an_empty_agent_says_it_holds_nothing(runtime, database):
    assert agent.spawn(database, 60)
    try:
        assert agent.connect(database).get() is None
    finally:
        agent.lock(database)


def test_a_vanished_agent_is_reported_as_a_value_error(runtime, database):
    assert agent.spawn(database, 60)
    client = agent.connect(database)
    agent.lock(database)
    assert _wait_gone(database)

    with pytest.raises(agent.Gone):
        client.get()
