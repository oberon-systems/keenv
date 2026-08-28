"""Where the variables come from: keenv.yaml and .env, merged into a plan."""

import os
import re
from pathlib import Path
from typing import NamedTuple

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from .uri import Reference, from_entry, is_reference, parse

DEFAULT_CONFIG = Path('keenv.yaml')
DEFAULT_ENV = Path('.env')

# `export ` is accepted so a .env can also be sourced by hand. An inline `#`
# is not a comment: a secret may legitimately contain one.
ENV_LINE = re.compile(
    r'^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$',
)

# The ceiling is deliberate: a remembered master password is a liability
# that grows with the time it is kept, so the choice is not left open.
TTL_CAP = 900

DURATION = re.compile(r'^(\d+)([sm]?)$')

Binding = Reference | str


def parse_ttl(value: str | int) -> int:
    """Read `30s`, `5m` or a bare count of seconds, within the ceiling."""
    match = DURATION.match(str(value).strip())
    if not match:
        raise ValueError(
            f'not a duration: {value!r}; write it as 30s, 5m or 900',
        )

    amount = int(match.group(1))
    seconds = amount * 60 if match.group(2) == 'm' else amount
    if seconds <= 0:
        raise ValueError('must be more than zero')
    if seconds > TTL_CAP:
        raise ValueError(
            f'must not exceed {TTL_CAP // 60}m, which is the longest '
            'keenv will remember a master password',
        )
    return seconds


class EntrySpec(BaseModel):
    """One variable in keenv.yaml: which entry, and which field of it."""

    model_config = ConfigDict(extra='forbid')

    entry: str
    field: str

    @field_validator('entry', 'field')
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError('must not be empty')
        return value


class ConfigFile(BaseModel):
    """The schema of keenv.yaml. Unknown keys are typos, so they fail."""

    model_config = ConfigDict(extra='forbid')

    vault: Path | None = None
    keyfile: Path | None = None
    ttl: int | None = None
    env: dict[str, EntrySpec] = {}

    @field_validator('vault', 'keyfile')
    @classmethod
    def _expand(cls, value: Path | None) -> Path | None:
        return value.expanduser() if value else None

    @field_validator('ttl', mode='before')
    @classmethod
    def _duration(cls, value: str | int | None) -> int | None:
        return None if value is None else parse_ttl(value)


class Settings(NamedTuple):
    """Which database to open, how, and how long to remember it."""

    vault: Path | None
    keyfile: Path | None
    ttl: int | None = None


class Plan(NamedTuple):
    """The database, the environment to build, and where each came from."""

    settings: Settings
    bindings: dict[str, Binding]
    origins: dict[str, str]


def _expand(value: str | None) -> Path | None:
    return Path(value).expanduser() if value else None


def _unquote(value: str) -> str:
    quoted = len(value) >= 2 and value[0] == value[-1]
    return value[1:-1] if quoted and value[0] in ('"', "'") else value


def _explain(path: Path, error: ValidationError) -> str:
    lines = [
        '  {}: {}'.format(
            '.'.join(str(part) for part in item['loc']) or '<root>',
            item['msg'],
        )
        for item in error.errors()
    ]
    return '\n'.join([f'{path}:', *lines])


def load_config(path: Path) -> Plan:
    """Read a keenv.yaml. A missing file is an empty layer, not an error."""
    if not path.is_file():
        return Plan(Settings(None, None), {}, {})

    try:
        document = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f'{path}: {exc}') from exc

    try:
        config = ConfigFile.model_validate(document)
    except ValidationError as exc:
        raise ValueError(_explain(path, exc)) from exc

    bindings: dict[str, Binding] = {
        name: from_entry(spec.entry, spec.field)
        for name, spec in config.env.items()
    }
    origins = {name: str(path) for name in bindings}
    settings = Settings(config.vault, config.keyfile, config.ttl)
    return Plan(settings, bindings, origins)


def load_env(path: Path) -> dict[str, Binding]:
    """Read a .env. keenv:// values resolve, everything else is literal."""
    if not path.is_file():
        return {}

    bindings: dict[str, Binding] = {}
    text = path.read_text(encoding='utf-8')
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.lstrip().startswith('#'):
            continue

        match = ENV_LINE.match(line)
        if not match:
            raise ValueError(f'{path}:{number}: not a NAME=value line')

        name, value = match.group(1), _unquote(match.group(2))
        try:
            bindings[name] = parse(value) if is_reference(value) else value
        except ValueError as exc:
            raise ValueError(f'{path}:{number}: {exc}') from exc

    return bindings


def build(
    config_path: Path,
    env_path: Path,
    vault: Path | None = None,
    keyfile: Path | None = None,
) -> Plan:
    """Merge both layers. .env beats keenv.yaml, the flags beat both."""
    plan = load_config(config_path)
    bindings = dict(plan.bindings)
    origins = dict(plan.origins)

    from_env = load_env(env_path)
    bindings.update(from_env)
    origins.update({name: str(env_path) for name in from_env})

    settings = Settings(
        vault
        or _expand(os.environ.get('KEENV_VAULT'))
        or plan.settings.vault,
        keyfile
        or _expand(os.environ.get('KEENV_KEYFILE'))
        or plan.settings.keyfile,
        plan.settings.ttl,
    )
    return Plan(settings, bindings, origins)
