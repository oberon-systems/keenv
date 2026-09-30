"""keenv conf: a --config rendered out of KeePass into memory only."""

import fcntl
import os
import re
from pathlib import Path
from typing import NamedTuple

from .config import Binding, Settings
from .uri import is_reference, parse

# `# keenv: vault ~/oberon.kdbx` - a plain comment to the command itself.
DIRECTIVE = re.compile(r'^\s*#\s*keenv:\s*(\S*)\s*(.*?)\s*$')

DIRECTIVES = ('vault', 'keyfile')

# Where the command reads its config, as `find -exec` and `xargs` mark theirs.
PLACEHOLDER = '{}'

# The first descriptor past stdio: stdin stays the terminal for prompts.
CARRIER = 3
CARRIER_PATH = f'/dev/fd/{CARRIER}'


class Template(NamedTuple):
    """A config: the database it names, its references and its lines."""

    settings: Settings
    bindings: dict[str, Binding]
    origins: dict[str, str]
    lines: list[str]


def place(command: list[str]) -> list[str]:
    """The command with its one {} pointing at the carrier descriptor."""
    count = sum(arg.count(PLACEHOLDER) for arg in command)
    if count == 0:
        raise ValueError(
            f'the command needs {PLACEHOLDER} where the config goes: '
            f'keenv conf work.ovpn -- sudo openvpn --config {PLACEHOLDER}',
        )
    if count > 1:
        raise ValueError(
            f'one {PLACEHOLDER} only: the config reaches the command once',
        )
    return [arg.replace(PLACEHOLDER, CARRIER_PATH) for arg in command]


def _key(number: int) -> str:
    return f'line {number}'


def _directive(match: re.Match[str]) -> tuple[str, Path]:
    name, value = match.group(1), match.group(2)
    if name == 'ttl':
        raise ValueError('ttl: keenv conf never remembers the master password')
    if name not in DIRECTIVES:
        raise ValueError(
            f'unknown keenv directive {name!r}; '
            f'only {" and ".join(DIRECTIVES)} are known',
        )
    if not value:
        raise ValueError(f'keenv directive {name} needs a path')
    return name, Path(value).expanduser()


def load(path: Path) -> Template:
    """Read a config: `# keenv:` directives and whole-line references."""
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
    """The config as rendered: values in, directives out, the rest as is."""
    out: list[str] = []
    for number, line in enumerate(template.lines, 1):
        key = _key(number)
        if key in template.bindings:
            out.append(resolved[key].replace('\r\n', '\n').rstrip('\n'))
        elif not DIRECTIVE.match(line):
            out.append(line)
    return ('\n'.join(out) + '\n').encode('utf-8')


def pipe(content: bytes) -> int:
    """The read end of a pipe holding all of `content` and nothing more.

    Its write end is closed, so one read drains it to end of file and the
    config is left only in the memory of whoever read it.
    """
    read_end, write_end = os.pipe()
    try:
        if len(content) > fcntl.fcntl(write_end, fcntl.F_GETPIPE_SZ):
            fcntl.fcntl(write_end, fcntl.F_SETPIPE_SZ, len(content))
        view = memoryview(content)
        while view:
            view = view[os.write(write_end, view):]
    except OSError as exc:
        os.close(read_end)
        raise ValueError(
            f'the config is {len(content)} bytes, more than a pipe holds',
        ) from exc
    finally:
        os.close(write_end)
    return read_end


def launch(content: bytes, command: list[str]) -> None:
    """Put the config on the carrier and become the command. Never returns."""
    fd = pipe(content)
    if fd != CARRIER:
        os.dup2(fd, CARRIER)
        os.close(fd)
    os.set_inheritable(CARRIER, True)
    os.execvpe(command[0], command, dict(os.environ))
