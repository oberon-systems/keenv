"""Opening the KeePass database and reading single fields out of it."""

import getpass
from pathlib import Path

from pykeepass import PyKeePass
from pykeepass.exceptions import CredentialsError

from .uri import Reference

# KeePass field name -> the attribute pykeepass exposes it under.
PROPERTIES = {
    'UserName': 'username',
    'Password': 'password',
    'URL': 'url',
    'Notes': 'notes',
    'Title': 'title',
}


def prompt_password(vault: Path) -> str:
    """Ask for the master password on the terminal, never on stdin.

    Falling back to stdin would silently eat the first line of a pipe, so a
    session without a terminal is an error the caller has to fix.
    """
    try:
        with open('/dev/tty', 'w+', encoding='utf-8') as tty:
            prompt = f'Master password for {vault}: '
            return getpass.getpass(prompt, stream=tty)
    except OSError as exc:
        raise ValueError(
            f'no terminal to ask for the master password of {vault}; '
            'run keenv from a terminal or point it at a key file',
        ) from exc


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
            raise ValueError(
                f'{path}: wrong master password or key file',
            ) from exc
        self.path = path

    def field(self, reference: Reference) -> str:
        """Read one field of one entry, or explain which half is missing."""
        entry = self._database.find_entries(
            path=list(reference.path), first=True,
        )
        if entry is None:
            raise ValueError(
                f'{self.path}: no entry at {"/".join(reference.path)}',
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
