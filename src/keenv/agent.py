"""A short-lived daemon holding the sealed password, one per database."""

import ctypes
import hashlib
import json
import os
import resource
import socket
import struct
import time
from collections import deque
from pathlib import Path

from .secret import wipe

VERSION = 1
TIMEOUT = 10.0

# This many failures inside the window and the agent forgets everything.
ATTEMPTS = 5
WINDOW = 300

PR_SET_DUMPABLE = 4
MCL_CURRENT = 1
MCL_FUTURE = 2

READY = b'1'


def _home() -> Path:
    runtime = os.environ.get('XDG_RUNTIME_DIR')
    if not runtime:
        raise ValueError(
            'no XDG_RUNTIME_DIR: keenv will not keep an agent anywhere '
            'that outlives the session',
        )
    return Path(runtime) / 'keenv'


def paths(vault: Path) -> tuple[Path, Path]:
    """The lock file and socket of one database, named from its path."""
    digest = hashlib.sha256(str(vault.resolve()).encode()).hexdigest()
    home = _home()
    return home / f'{digest[:16]}.lock', home / f'{digest[:16]}.sock'


def _unlink(*targets: Path) -> None:
    for target in targets:
        try:
            target.unlink()
        except OSError:
            pass


def _harden() -> None:
    """Keep the blob out of core dumps, out of ptrace and out of swap."""
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        libc.prctl(PR_SET_DUMPABLE, 0, 0, 0, 0)
        libc.mlockall(MCL_CURRENT | MCL_FUTURE)
    except (OSError, AttributeError):
        pass


class _State:
    """What the agent holds: a blob, a deadline and recent failures."""

    def __init__(self, ttl: int) -> None:
        self.ttl = ttl
        self.deadline = time.monotonic() + ttl
        self.failures: deque[float] = deque()
        self.salt: bytearray | None = None
        self.blob: bytearray | None = None

    def touch(self) -> None:
        self.deadline = time.monotonic() + self.ttl

    def forget(self) -> None:
        if self.salt is not None:
            wipe(self.salt, self.blob)
        self.salt = self.blob = None

    def failed(self) -> bool:
        """Record a failure, and say whether the window has filled up."""
        now = time.monotonic()
        self.failures.append(now)
        while self.failures and now - self.failures[0] > WINDOW:
            self.failures.popleft()
        return len(self.failures) >= ATTEMPTS


def _handle(state: _State, request: dict) -> tuple[dict, bool]:
    """Answer one request, and say whether the agent should stop."""
    action = request.get('op')

    if action == 'put':
        if state.blob is not None:
            return {'error': 'this agent already holds a password'}, False
        state.salt = bytearray(bytes.fromhex(request['salt']))
        state.blob = bytearray(bytes.fromhex(request['blob']))
        state.touch()
        return {'ok': True}, False

    if action == 'get':
        if state.blob is None:
            return {'error': 'this agent holds nothing yet'}, False
        return {
            'salt': bytes(state.salt).hex(),
            'blob': bytes(state.blob).hex(),
        }, False

    if action == 'ok':
        state.touch()
        return {'ok': True}, False

    if action == 'fail':
        return {'ok': True}, state.failed()

    if action == 'lock':
        return {'ok': True}, True

    return {'error': f'unknown op: {action}'}, False


def _readline(conn: socket.socket) -> bytes:
    chunks = bytearray()
    while b'\n' not in chunks:
        chunk = conn.recv(4096)
        if not chunk:
            break
        chunks += chunk
    return bytes(chunks).split(b'\n', 1)[0]


def _ours(conn: socket.socket) -> bool:
    """Whether the peer runs as us. A different uid is never served."""
    raw = conn.getsockopt(
        socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize('3i'),
    )
    _, uid, _ = struct.unpack('3i', raw)
    return uid == os.getuid()


def _exchange(conn: socket.socket, state: _State) -> bool:
    conn.settimeout(TIMEOUT)
    try:
        line = _readline(conn)
        if not line:
            return False
        reply, stop = _handle(state, json.loads(line))
    except (OSError, ValueError, KeyError) as exc:
        reply, stop = {'error': str(exc)}, False
    conn.sendall(json.dumps(reply).encode() + b'\n')
    return stop


def _loop(server: socket.socket, state: _State) -> None:
    while True:
        remaining = state.deadline - time.monotonic()
        if remaining <= 0:
            return
        server.settimeout(remaining)
        try:
            conn, _ = server.accept()
        except (socket.timeout, TimeoutError):
            return
        with conn:
            if _ours(conn) and _exchange(conn, state):
                return


def serve(vault: Path, ttl: int, ready: int | None = None) -> None:
    """Hold the blob until the idle deadline, then wipe it and go."""
    lock_path, sock_path = paths(vault)
    _harden()
    state = _State(ttl)
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        _unlink(sock_path)
        server.bind(str(sock_path))
        os.chmod(sock_path, 0o600)
        server.listen(8)
        if ready is not None:
            os.write(ready, READY)
            os.close(ready)
        _loop(server, state)
    finally:
        state.forget()
        server.close()
        _unlink(sock_path, lock_path)


class Client:
    """The other end of the socket: one request, one reply, one connect."""

    def __init__(self, sock_path: Path) -> None:
        self._path = sock_path

    def _call(self, request: dict) -> dict:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
            conn.settimeout(TIMEOUT)
            conn.connect(str(self._path))
            conn.sendall(json.dumps(request).encode() + b'\n')
            reply = json.loads(_readline(conn) or b'{}')
        if 'error' in reply:
            raise ValueError(f'keenv agent: {reply["error"]}')
        return reply

    def put(self, salt: bytes, blob: bytearray) -> None:
        self._call({
            'op': 'put',
            'salt': bytes(salt).hex(),
            'blob': bytes(blob).hex(),
        })

    def get(self) -> tuple[bytes, bytes]:
        reply = self._call({'op': 'get'})
        return bytes.fromhex(reply['salt']), bytes.fromhex(reply['blob'])

    def ok(self) -> None:
        self._call({'op': 'ok'})

    def fail(self) -> None:
        self._call({'op': 'fail'})

    def lock(self) -> None:
        self._call({'op': 'lock'})


def connect(vault: Path) -> Client | None:
    """This database's agent, or None when nothing is listening.

    A lock file whose socket refuses the connection is stale, and clearing
    it here is what lets the next run put a fresh agent in its place.
    """
    lock_path, sock_path = paths(vault)
    if not lock_path.is_file():
        return None
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
            probe.settimeout(TIMEOUT)
            probe.connect(str(sock_path))
    except OSError:
        _unlink(sock_path, lock_path)
        return None
    return Client(sock_path)


def _detach() -> None:
    os.setsid()
    with open(os.devnull, 'r+b', buffering=0) as null:
        for stream in (0, 1, 2):
            os.dup2(null.fileno(), stream)


def spawn(vault: Path, ttl: int) -> bool:
    """Fork an empty agent, false when another process got there first.

    The fork happens before any password is read, so the plaintext is
    never in the agent's address space, not even inherited across it.
    """
    lock_path, sock_path = paths(vault)
    lock_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        handle = os.open(
            str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600,
        )
    except FileExistsError:
        return False

    read_end, write_end = os.pipe()
    child = os.fork()
    if child == 0:
        os.close(read_end)
        _detach()
        if os.fork() == 0:
            _run(vault, ttl, handle, write_end, sock_path)
        os._exit(0)

    os.close(handle)
    os.close(write_end)
    os.waitpid(child, 0)
    started = os.read(read_end, 1) == READY
    os.close(read_end)
    if not started:
        _unlink(sock_path, lock_path)
    return started


def _run(vault: Path, ttl: int, handle: int, ready: int,
         sock_path: Path) -> None:
    """The grandchild: stamp the lock file, then serve until the TTL."""
    try:
        os.write(handle, json.dumps({
            'pid': os.getpid(),
            'socket': str(sock_path),
            'version': VERSION,
        }).encode())
        os.close(handle)
        serve(vault, ttl, ready)
    finally:
        os._exit(0)


def lock(vault: Path) -> bool:
    """Drop this database's agent, false when there was none to drop."""
    client = connect(vault)
    if client is None:
        return False
    try:
        client.lock()
    except (OSError, ValueError):
        pass
    return True
