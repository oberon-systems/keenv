"""Colour on the terminal: solarized dark, and nothing at all off it."""

import os
import sys
from typing import IO

# Solarized by its own indices in the 256-colour cube, so the hues are the
# palette's own on any terminal rather than whatever theme is loaded there.
YELLOW, GREEN, RED, BLUE = 136, 64, 160, 33
BASE1, BASE0, BASE01 = 245, 244, 240

RESET = '\x1b[0m'

_wanted = True


def disable() -> None:
    """Drop colour for the rest of the run, whatever the terminal is."""
    global _wanted
    _wanted = False


def _coloured(stream: IO[str] | None) -> bool:
    """Whether this destination takes colour. None is /dev/tty, which does."""
    if not _wanted or os.environ.get('NO_COLOR'):
        return False
    if os.environ.get('TERM') == 'dumb':
        return False
    return stream is None or stream.isatty()


def tint(colour: int, text: str, stream: IO[str] | None = None) -> str:
    """Wrap text in one solarized colour, or hand it back as it is."""
    if not _coloured(stream):
        return text
    return f'\x1b[38;5;{colour}m{text}{RESET}'


def info(text: str, stream: IO[str] | None = None) -> str:
    """Worth knowing, and keenv carried on regardless."""
    return tint(YELLOW, text, stream)


def good(text: str, stream: IO[str] | None = None) -> str:
    """It worked."""
    return tint(GREEN, text, stream)


def bad(text: str, stream: IO[str] | None = None) -> str:
    """It did not, and this is where the run ends."""
    return tint(RED, text, stream)


def link(text: str, stream: IO[str] | None = None) -> str:
    """A keenv:// reference, which points somewhere."""
    return tint(BLUE, text, stream)


def bright(text: str, stream: IO[str] | None = None) -> str:
    """The part of a line the eye should land on first."""
    return tint(BASE1, text, stream)


def plain(text: str, stream: IO[str] | None = None) -> str:
    """Body text, spelled out so a table reads as one thing."""
    return tint(BASE0, text, stream)


def dim(text: str, stream: IO[str] | None = None) -> str:
    """There when looked for, out of the way when not."""
    return tint(BASE01, text, stream)


def warn(text: str) -> None:
    """An advisory on stderr, after which keenv keeps going."""
    print(info(text, sys.stderr), file=sys.stderr)


def error(text: str) -> None:
    """The line the run ends on, on stderr."""
    print(bad(text, sys.stderr), file=sys.stderr)
