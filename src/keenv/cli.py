"""The keenv command line: resolve the plan, then hand the process over."""

import argparse
import os
import sys
from pathlib import Path

from .config import DEFAULT_CONFIG, DEFAULT_ENV, Binding, Plan, build
from .uri import Reference
from .vault import Vault

USAGE_ERROR = 2
NOT_FOUND = 127

ACTIONS = (
    ('run', 'run a command with the resolved environment'),
    ('check', 'resolve every reference and report, without the values'),
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='keenv',
        description='Put KeePass secrets in the environment of one '
                    'command and nowhere else.',
    )
    subparsers = parser.add_subparsers(dest='action', required=True)

    for action, help_text in ACTIONS:
        sub = subparsers.add_parser(action, help=help_text)
        sub.add_argument(
            '-c', '--config', type=Path, default=DEFAULT_CONFIG,
            help=f'keenv.yaml to read (default: {DEFAULT_CONFIG})',
        )
        sub.add_argument(
            '-e', '--env', type=Path, default=DEFAULT_ENV,
            help=f'.env to read (default: {DEFAULT_ENV})',
        )
        sub.add_argument(
            '--vault', type=Path, default=None,
            help='database, overriding keenv.yaml and KEENV_VAULT',
        )
        sub.add_argument(
            '--keyfile', type=Path, default=None,
            help='key file for the database',
        )

    return parser


def _split_command(argv: list[str]) -> tuple[list[str], list[str]]:
    if '--' not in argv:
        return argv, []
    index = argv.index('--')
    return argv[:index], argv[index + 1:]


def _resolve(plan: Plan) -> dict[str, str]:
    if not plan.bindings:
        raise ValueError(
            'nothing to resolve: no env in keenv.yaml and no .env',
        )

    vault = None
    if any(isinstance(v, Reference) for v in plan.bindings.values()):
        if plan.settings.vault is None:
            raise ValueError(
                'no vault: name it in keenv.yaml, in KEENV_VAULT '
                'or with --vault',
            )
        vault = Vault(plan.settings.vault, plan.settings.keyfile)

    resolved: dict[str, str] = {}
    for name, value in plan.bindings.items():
        if not isinstance(value, Reference):
            resolved[name] = value
            continue
        try:
            resolved[name] = vault.field(value)
        except ValueError as exc:
            origin = plan.origins.get(name, 'the command line')
            raise ValueError(f'{exc} ({name} comes from {origin})') from exc

    return resolved


def _describe(name: str, binding: Binding, value: str, origin: str) -> str:
    source = str(binding) if isinstance(binding, Reference) else 'literal'
    return f'{name:<28} {source:<52} {len(value):>3} chars  {origin}'


def _check(plan: Plan) -> int:
    resolved = _resolve(plan)
    for name, binding in plan.bindings.items():
        origin = plan.origins.get(name, '')
        print(_describe(name, binding, resolved[name], origin))
    return 0


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns an exit code; `run` never returns at all."""
    given = list(sys.argv[1:] if argv is None else argv)
    given, command = _split_command(given)
    options = _parser().parse_args(given)

    try:
        plan = build(
            options.config, options.env, options.vault, options.keyfile,
        )

        if options.action == 'check':
            return _check(plan)

        if not command:
            print(
                'keenv run needs a command: keenv run -- tofu plan',
                file=sys.stderr,
            )
            return USAGE_ERROR

        environment = dict(os.environ)
        environment.update(_resolve(plan))
        os.execvpe(command[0], command, environment)
    except ValueError as exc:
        print(f'keenv: {exc}', file=sys.stderr)
        return 1
    except FileNotFoundError:
        print(f'keenv: command not found: {command[0]}', file=sys.stderr)
        return NOT_FOUND

    return 0
