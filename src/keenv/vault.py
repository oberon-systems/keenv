"""Opening the KeePass database and reading single fields out of it."""

import asyncio
import getpass
import os
import select
import selectors
import sys
from pathlib import Path
from time import monotonic

from prompt_toolkit import Application, PromptSession
from prompt_toolkit.formatted_text import (
    FormattedText,
    fragment_list_to_text,
)
from prompt_toolkit.input import create_input
from prompt_toolkit.output import ColorDepth, create_output
from prompt_toolkit.styles import Style
from prompt_toolkit.utils import is_dumb_terminal
from pykeepass import PyKeePass
from pykeepass.entry import Entry
from pykeepass.exceptions import CredentialsError

from . import paint
from .secret import BadPin, check_pin, is_short
from .uri import Reference

# How many real paths a 'no entry' message names before it stops.
LISTED = 3

# How many times a PIN may be typed badly before keenv gives up on it.
TRIES = 3

# The whole PIN exchange, every try included: an abandoned prompt must not
# leave the master password waiting in memory.
PIN_TIMEOUT = 60

# paint.YELLOW, spelled the way prompt_toolkit takes a colour.
YELLOW = '#af8700'

NEW_PIN = 'New PIN (4 to 8 digits)'

WINDOWS = sys.platform == 'win32'

if not WINDOWS:
    import termios

# KeePass field name -> the attribute pykeepass exposes it under.
PROPERTIES = {
    'UserName': 'username',
    'Password': 'password',
    'URL': 'url',
    'Notes': 'notes',
    'Title': 'title',
}


# What a short PIN really costs, said once and plainly.
SHORT_PIN = (
    'A 4-digit PIN is ten thousand guesses. Anyone holding both a dump of '
    'the agent and a copy of the database can search that offline. Six '
    'digits or more is the only thing that moves this much.'
)


def _hidden(prompt: str) -> str:
    """Read a hidden answer on the terminal, never on stdin.

    Falling back to stdin would silently eat the first line of a pipe, so a
    session without a terminal is an error the caller has to fix.
    """
    if WINDOWS:
        # There getpass reads the console itself, never a redirected stdin.
        return getpass.getpass(prompt)
    # 'w+' would need a seekable stream and a tty is not one; getpass
    # opens /dev/tty itself to read, so writing the prompt is enough.
    with open('/dev/tty', 'w', encoding='utf-8') as tty:
        return getpass.getpass(prompt, stream=tty)


def say(text: str) -> None:
    """Put a line where the prompt it answers went: on the terminal."""
    try:
        with open('/dev/tty', 'w', encoding='utf-8') as tty:
            tty.write(f'{text}\n')
    except OSError:
        pass


def prompt_password(vault: Path) -> str:
    """Ask for the master password on the terminal, never on stdin."""
    try:
        return _hidden(paint.info(f'Master password for {vault}: '))
    except OSError as exc:
        raise ValueError(
            f'no terminal to ask for the master password of {vault}; '
            'run keenv from a terminal or point it at a key file',
        ) from exc
    except EOFError as exc:
        raise ValueError(
            f'no master password given for {vault}',
        ) from exc


class PinTimeout(ValueError):
    """Nobody finished with the PIN inside PIN_TIMEOUT."""


def _style() -> Style:
    colour = f'fg:{YELLOW}' if paint.enabled() else ''
    return Style.from_dict({
        'prompt': colour,
        'strong': f'{colour} bold',
        'bottom-toolbar': f'{colour} italic noreverse',
    })


def _counted(label: str, left: int) -> FormattedText:
    return FormattedText([
        ('class:prompt', f'{label} '),
        ('class:strong', f'[{left}]'),
        ('class:prompt', ': '),
    ])


def _expire(app: Application[str], vault: Path) -> None:
    if app.is_running:
        app.exit(exception=PinTimeout(
            f'timed out waiting for the PIN of {vault}',
        ))


def _plain(vault: Path, message: FormattedText, remaining: float,
           hidden: bool) -> str:
    """The same question for a terminal that takes no escape codes."""
    tty = os.open('/dev/tty', os.O_RDWR | os.O_NOCTTY)
    try:
        prompt = fragment_list_to_text(message)
        os.write(tty, f'vault: {vault}\n{prompt}'.encode())
        before = termios.tcgetattr(tty)
        if hidden:
            quiet = termios.tcgetattr(tty)
            quiet[3] &= ~termios.ECHO
            termios.tcsetattr(tty, termios.TCSAFLUSH, quiet)
        try:
            # The line discipline wakes select only once Enter is pressed.
            if not select.select([tty], [], [], remaining)[0]:
                raise PinTimeout(f'timed out waiting for the PIN of {vault}')
            answer = os.read(tty, 1024)
        finally:
            termios.tcsetattr(tty, termios.TCSAFLUSH, before)
            if hidden:
                os.write(tty, b'\n')
    finally:
        os.close(tty)
    if not answer:
        raise EOFError
    return answer.decode('utf-8').rstrip('\r\n')


def _ask(vault: Path, message: FormattedText, deadline: float,
         hidden: bool = True) -> str:
    """Ask on the terminal, the vault named under the line, by `deadline`."""
    remaining = deadline - monotonic()
    if remaining <= 0:
        raise PinTimeout(f'timed out waiting for the PIN of {vault}')
    try:
        if is_dumb_terminal():
            return _plain(vault, message, remaining, hidden)
        with open('/dev/tty', 'r', encoding='utf-8') as tty_in, \
                open('/dev/tty', 'w', encoding='utf-8') as tty_out:
            session: PromptSession[str] = PromptSession(
                input=create_input(tty_in),
                output=create_output(tty_out),
                style=_style(),
                color_depth=(
                    None if paint.enabled() else ColorDepth.DEPTH_1_BIT
                ),
                is_password=hidden,
                bottom_toolbar=[('', f'vault: {vault}')],
            )
            # kqueue, the macOS default, refuses /dev/tty; select takes it.
            loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
            try:
                loop.call_later(remaining, _expire, session.app, vault)
                return loop.run_until_complete(session.prompt_async(message))
            finally:
                loop.close()
    except OSError as exc:
        raise ValueError(
            f'no terminal to ask for the PIN of {vault}; '
            'run keenv from a terminal',
        ) from exc
    except EOFError as exc:
        raise ValueError(f'no PIN given for {vault}') from exc


def prompt_pin(vault: Path, left: int, deadline: float) -> str:
    """Ask for the PIN of a filled agent, saying how many tries are left."""
    return _ask(vault, _counted('PIN', left), deadline)


def _confirm(vault: Path, deadline: float) -> bool:
    say(paint.info(SHORT_PIN))
    answer = _ask(
        vault, FormattedText([('class:prompt', 'Use it anyway? [y/N] ')]),
        deadline, hidden=False,
    )
    return answer.strip().lower() in ('y', 'yes')


def _choose_pin(vault: Path, deadline: float) -> str | None:
    """Take a usable PIN. Only an empty first answer skips the agent."""
    for attempt in range(TRIES):
        if attempt:
            message = _counted(NEW_PIN, TRIES - attempt)
        else:
            message = FormattedText([
                ('class:prompt', f'{NEW_PIN}, '),
                ('class:strong', 'press Enter to skip'),
                ('class:prompt', ': '),
            ])
        pin = _ask(vault, message, deadline)
        if not pin and not attempt:
            return None
        try:
            check_pin(pin)
            if is_short(pin) and not _confirm(vault, deadline):
                raise BadPin('choose a longer PIN')
            return pin
        except BadPin as exc:
            say(paint.info(f'keenv: {exc}'))
    raise ValueError(f'no usable PIN after {TRIES} attempts')


def _repeat_pin(vault: Path, pin: str, deadline: float) -> None:
    for attempt in range(TRIES):
        if _ask(vault, _counted('Repeat PIN', TRIES - attempt),
                deadline) == pin:
            return
        say(paint.info('keenv: that is not the new PIN'))
    raise ValueError(f'the new PIN was not repeated after {TRIES} attempts')


def prompt_new_pin(vault: Path) -> str | None:
    """Take a new PIN and its repeat, TRIES of each, inside PIN_TIMEOUT.

    None is the skip: Enter at the very first prompt, and nowhere else.
    """
    deadline = monotonic() + PIN_TIMEOUT
    pin = _choose_pin(vault, deadline)
    if pin is not None:
        _repeat_pin(vault, pin, deadline)
    return pin


class WrongCredentials(ValueError):
    """The database turned down the password or key file it was given."""


class Vault:
    """A KeePass database, opened once and read many times."""

    def __init__(self, path: Path, keyfile: Path | None = None,
                 password: str | None = None) -> None:
        if not path.is_file():
            raise ValueError(f'vault not found: {path}')
        if keyfile is not None and not keyfile.is_file():
            raise ValueError(f'key file not found: {keyfile}')
        if password is None and keyfile is None:
            password = prompt_password(path)

        try:
            self._database = PyKeePass(
                str(path),
                password=password,
                keyfile=str(keyfile) if keyfile else None,
            )
        except CredentialsError as exc:
            raise WrongCredentials(
                f'{path}: wrong master password or key file',
            ) from exc
        self.path = path

    def _find(self, path: tuple[str, ...]) -> Entry | None:
        """Look an entry up, tolerating a leading root group name.

        pykeepass paths start below the root group, but KeePass shows that
        group in the path it displays, so a reference may carry it, either
        under its real name or as a plain `root`.
        """
        entry = self._database.find_entries(path=list(path), first=True)
        if entry is not None or len(path) < 2:
            return entry

        root = self._database.root_group.name or ''
        if path[0].casefold() in {root.casefold(), 'root'}:
            return self._database.find_entries(path=list(path[1:]), first=True)
        return None

    def _elsewhere(self, title: str) -> str:
        """Name where an entry with that title does sit, if anywhere."""
        found = [
            '/'.join(entry.path)
            for entry in self._database.find_entries(title=title) or []
            if entry.path and None not in entry.path
        ]
        if not found:
            return ''
        return '; it is at ' + ', '.join(sorted(found)[:LISTED])

    def field(self, reference: Reference) -> str:
        """Read one field of one entry, or explain which half is missing."""
        entry = self._find(reference.path)
        if entry is None:
            raise ValueError(
                f'{self.path}: no entry at {"/".join(reference.path)}'
                f'{self._elsewhere(reference.path[-1])}',
            )

        attribute = PROPERTIES.get(reference.field)
        if attribute is not None:
            value = getattr(entry, attribute)
        else:
            value = entry.get_custom_property(reference.field)

        if value is None:
            raise ValueError(
                f'{self.path}: entry {"/".join(reference.path)} '
                f'has no {reference.field} field',
            )
        return str(value)
