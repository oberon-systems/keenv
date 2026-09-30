"""keenv ovpn: an OpenVPN config rendered out of KeePass into memory only."""

import fcntl
import os
import re
from pathlib import Path
from typing import NamedTuple

from .config import Binding, Settings
from .uri import is_reference, parse

# `# keenv: vault ~/oberon.kdbx` - a plain comment to OpenVPN itself.
DIRECTIVE = re.compile(r'^\s*#\s*keenv:\s*(\S*)\s*(.*?)\s*$')

DIRECTIVES = ('vault', 'keyfile')

SEALS = (
    fcntl.F_SEAL_SEAL
    | fcntl.F_SEAL_SHRINK
    | fcntl.F_SEAL_GROW
    | fcntl.F_SEAL_WRITE
)

# sudo closes every descriptor above 2, so stdin is the one way through it.
LAUNCHER = ('sudo', 'openvpn', '--config', '/dev/stdin')


class Template(NamedTuple):
    """A .ovpn: the database it names, its references and its lines."""

    settings: Settings
    bindings: dict[str, Binding]
    origins: dict[str, str]
    lines: list[str]


def _key(number: int) -> str:
    return f'line {number}'


def _directive(match: re.Match[str]) -> tuple[str, Path]:
    name, value = match.group(1), match.group(2)
    if name == 'ttl':
        raise ValueError('ttl: keenv ovpn never remembers the master password')
    if name not in DIRECTIVES:
        raise ValueError(
            f'unknown keenv directive {name!r}; '
            f'only {" and ".join(DIRECTIVES)} are known',
        )
    if not value:
        raise ValueError(f'keenv directive {name} needs a path')
    return name, Path(value).expanduser()


def load(path: Path) -> Template:
    """Read a .ovpn: `# keenv:` directives and whole-line references."""
    if not path.is_file():
        raise ValueError(f'template not found: {path}')

    lines = path.read_text(encoding='utf-8').splitlines()
    found: dict[str, Path] = {}
    bindings: dict[str, Binding] = {}
    for number, line in enumerate(lines, 1):
        try:
            match = DIRECTIVE.match(line)
            if match:
                name, value = _directive(match)
                found[name] = value
            elif is_reference(line.strip()):
                bindings[_key(number)] = parse(line.strip())
        except ValueError as exc:
            raise ValueError(f'{path}:{number}: {exc}') from exc

    if not bindings:
        raise ValueError(f'{path}: no keenv:// lines, nothing to render')

    settings = Settings(found.get('vault'), found.get('keyfile'))
    origins = dict.fromkeys(bindings, str(path))
    return Template(settings, bindings, origins, lines)


def render(template: Template, resolved: dict[str, str]) -> bytes:
    """The config OpenVPN gets: values in, directives out, the rest as is."""
    out: list[str] = []
    for number, line in enumerate(template.lines, 1):
        key = _key(number)
        if key in template.bindings:
            out.append(resolved[key].replace('\r\n', '\n').rstrip('\n'))
        elif not DIRECTIVE.match(line):
            out.append(line)
    return ('\n'.join(out) + '\n').encode('utf-8')


def memfd(content: bytes) -> int:
    """An anonymous, sealed in-memory file holding `content`, read from 0."""
    fd = os.memfd_create('keenv-ovpn', os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
    with open(fd, 'wb', closefd=False) as stream:
        stream.write(content)
    fcntl.fcntl(fd, fcntl.F_ADD_SEALS, SEALS)
    os.lseek(fd, 0, os.SEEK_SET)
    return fd


def launch(content: bytes, command: list[str]) -> None:
    """Put the config on stdin and become the command. Never returns."""
    fd = memfd(content)
    os.dup2(fd, 0)
    os.close(fd)
    os.execvpe(command[0], command, dict(os.environ))
