"""Opening the KeePass database and reading single fields out of it."""

import getpass
from pathlib import Path

from pykeepass import PyKeePass
from pykeepass.entry import Entry
from pykeepass.exceptions import CredentialsError

from .secret import check_pin, is_short
from .uri import Reference

# How many real paths a 'no entry' message names before it stops.
LISTED = 3

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
    # 'w+' would need a seekable stream and a tty is not one; getpass
    # opens /dev/tty itself to read, so writing the prompt is enough.
    with open('/dev/tty', 'w', encoding='utf-8') as tty:
        return getpass.getpass(prompt, stream=tty)


def _confirm(question: str) -> bool:
    """Put a question on the terminal and read the answer from it."""
    try:
        with open('/dev/tty', 'w', encoding='utf-8') as out:
            out.write(question)
            out.flush()
            with open('/dev/tty', 'r', encoding='utf-8') as tty:
                return tty.readline().strip().lower() in ('y', 'yes')
    except OSError:
        return False


def prompt_password(vault: Path) -> str:
    """Ask for the master password on the terminal, never on stdin."""
    try:
        return _hidden(f'Master password for {vault}: ')
    except OSError as exc:
        raise ValueError(
            f'no terminal to ask for the master password of {vault}; '
            'run keenv from a terminal or point it at a key file',
        ) from exc
    except EOFError as exc:
        raise ValueError(
            f'no master password given for {vault}',
        ) from exc


def prompt_pin(vault: Path, prompt: str | None = None) -> str:
    """Ask for the PIN, on the same terms as the master password."""
    try:
        return _hidden(prompt or f'PIN for {vault}: ')
    except OSError as exc:
        raise ValueError(
            f'no terminal to ask for the PIN of {vault}; '
            'run keenv from a terminal',
        ) from exc
    except EOFError as exc:
        raise ValueError(f'no PIN given for {vault}') from exc


def prompt_new_pin(vault: Path) -> str:
    """Take a PIN twice over, and argue about it if it is a short one."""
    pin = prompt_pin(vault, 'New PIN (4 to 8 digits): ')
    check_pin(pin)
    if pin != prompt_pin(vault, 'Repeat the PIN: '):
        raise ValueError('the two PINs do not match')

    if is_short(pin) and not _confirm(f'{SHORT_PIN}\nUse it anyway? [y/N] '):
        raise ValueError('cancelled: choose a longer PIN')
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
