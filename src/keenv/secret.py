"""The master password kept under a PIN, sealed and opened in one place."""

import os
import re

from argon2.low_level import Type, hash_secret_raw

# Every blob is this long, so its size cannot betray the length of the
# master password hiding in it.
BLOB = 128

# Tuned to about a third of a second on a modern desktop: dear enough to
# price an offline PIN search, cheap enough to pay on every command.
TIME_COST = 12
MEMORY_COST = 131072
PARALLELISM = 4
SALT = 16

DIGITS = re.compile(r'^[0-9]{4,8}$')
SHORT = 5


class BadPin(ValueError):
    """The PIN as typed will not do, and typing it again might."""


def check_pin(pin: str) -> None:
    """Accept four to eight digits and nothing else."""
    if not DIGITS.match(pin):
        raise BadPin('the PIN must be 4 to 8 digits')


def is_short(pin: str) -> bool:
    """Whether the PIN is short enough to be worth warning about."""
    return len(pin) < SHORT


def wipe(*buffers: bytearray) -> None:
    """Overwrite buffers in place, which a bytes object can never be."""
    for buffer in buffers:
        buffer[:] = bytes(len(buffer))


def derive(pin: str, salt: bytes) -> bytearray:
    """Stretch the PIN into a keystream as long as a blob."""
    return bytearray(hash_secret_raw(
        pin.encode(), salt, TIME_COST, MEMORY_COST, PARALLELISM, BLOB,
        Type.ID,
    ))


def seal(password: str, pin: str) -> tuple[bytes, bytearray]:
    """Hide the password behind the PIN, keeping neither of them."""
    secret = password.encode()
    if len(secret) > BLOB:
        raise ValueError(
            f'the master password is longer than {BLOB} bytes',
        )

    salt = os.urandom(SALT)
    keystream = derive(pin, salt)
    blob = bytearray(
        a ^ b for a, b in zip(secret.ljust(BLOB, b'\0'), keystream)
    )
    wipe(keystream)
    return salt, blob


def unseal(blob: bytes, salt: bytes, pin: str) -> str:
    """Undo seal(). A wrong PIN gives rubbish rather than an error.

    Rubbish is decoded, never rejected: the wrong PIN has to reach the
    database and fail there, which is the only check this design has.
    """
    keystream = derive(pin, salt)
    opened = bytearray(a ^ b for a, b in zip(blob, keystream))
    wipe(keystream)
    password = bytes(opened).rstrip(b'\0')
    wipe(opened)
    return password.decode('utf-8', 'surrogateescape')
