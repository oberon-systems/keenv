import os
import subprocess
import sys

import pytest
from conftest import ACCESS_KEY
from keenv import cli, vault, windows
from keenv.cli import main


@pytest.fixture(name='on_windows')
def on_windows_fixture(monkeypatch):
    """Take the Windows branches on any system, with no console to set up."""
    monkeypatch.setattr(cli, 'WINDOWS', True)
    monkeypatch.setattr(windows, 'console', lambda: True)
    monkeypatch.delenv(windows.RESOLVER, raising=False)


def test_conf_is_refused(on_windows, tmp_path, capsys):
    template = tmp_path / 'work.ovpn'
    assert main(['conf', str(template), '--', 'openvpn', '{}']) == 1
    assert 'not available on Windows' in capsys.readouterr().err


def test_lock_has_no_agent_to_drop(on_windows, monkeypatch, capsys):
    monkeypatch.setattr(
        'keenv.cli.agent.lock', lambda path: pytest.fail('agent touched'),
    )
    assert main(['lock', '--vault', 'oberon.kdbx']) == 0
    assert 'no agents on Windows' in capsys.readouterr().out


def test_the_waiter_never_reads_the_config(on_windows, monkeypatch):
    waited = {}
    monkeypatch.setattr(
        'keenv.cli.build', lambda *arguments: pytest.fail('config read'),
    )
    monkeypatch.setattr(
        windows, 'wait', lambda argv: waited.setdefault('argv', argv) and 7,
    )
    assert main(['run', '--no-color', '--', 'tool', '-x']) == 7
    assert waited['argv'] == ['run', '--no-color', '--', 'tool', '-x']


def test_the_resolver_hands_the_values_over_without_its_marker(
        on_windows, config_file, keyfile, tmp_path, monkeypatch,
):
    handed = {}
    monkeypatch.setenv(windows.RESOLVER, '1234:5678')
    monkeypatch.setattr(
        windows, 'hand_over',
        lambda command, environment, resolver: handed.update(
            command=command, environment=environment, resolver=resolver,
        ),
    )
    assert main([
        'run', '-c', str(config_file), '-e', str(tmp_path / '.env'),
        '--keyfile', str(keyfile), '--', 'tool',
    ]) == 0
    assert handed['command'] == ['tool']
    assert handed['resolver'] == '1234:5678'
    assert windows.RESOLVER not in handed['environment']
    assert handed['environment']['AWS_ACCESS_KEY_ID'] == ACCESS_KEY


def test_ttl_opens_the_database_without_an_agent(
        on_windows, tmp_path, monkeypatch, capsys,
):
    opened = []
    monkeypatch.setattr(
        'keenv.cli.agent.connect', lambda path: pytest.fail('agent touched'),
    )
    monkeypatch.setattr(
        'keenv.cli.Vault', lambda path, keyfile: opened.append(path),
    )
    cli._open(cli.Settings(tmp_path / 'oberon.kdbx', None, 60), True)
    assert opened == [tmp_path / 'oberon.kdbx']
    assert 'no agent' in capsys.readouterr().err


def test_no_console_means_no_colour(on_windows, monkeypatch):
    disabled = []
    monkeypatch.setattr(windows, 'console', lambda: False)
    monkeypatch.setattr('keenv.cli.paint.disable', lambda: disabled.append(1))
    main(['lock', '--vault', 'oberon.kdbx'])
    assert disabled


def test_the_password_prompt_reads_the_console(monkeypatch):
    asked = []
    monkeypatch.setattr(vault, 'WINDOWS', True)
    monkeypatch.setattr(
        vault.getpass, 'getpass', lambda prompt: asked.append(prompt) or 'pw',
    )
    assert vault._hidden('Master password: ') == 'pw'
    assert asked == ['Master password: ']


@pytest.mark.skipif(sys.platform != 'win32', reason='needs kernel32')
def test_run_hands_the_exit_code_and_the_values_back(
        config_file, keyfile, tmp_path,
):
    script = (
        'import os, sys; '
        f'sys.exit(3 if os.environ["AWS_ACCESS_KEY_ID"] == "{ACCESS_KEY}" '
        f'and "{windows.RESOLVER}" not in os.environ else 1)'
    )
    result = subprocess.run(
        [
            sys.executable, '-m', 'keenv', 'run',
            '-c', str(config_file), '-e', str(tmp_path / '.env'),
            '--keyfile', str(keyfile), '--', sys.executable, '-c', script,
        ],
        capture_output=True, text=True, check=False,
        env={**os.environ, 'NO_COLOR': '1'},
    )
    assert result.returncode == 3, result.stderr
