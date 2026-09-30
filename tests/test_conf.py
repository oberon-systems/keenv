import os
import subprocess
import sys

import pytest
from conftest import ACCESS_KEY, SECRET_KEY, TOKEN
from keenv import conf
from keenv.cli import main
from keenv.config import Settings


@pytest.fixture(name='hidden', autouse=True)
def hidden_fixture(monkeypatch):
    """Record hide() rather than closing the test process to its user."""
    calls = []
    monkeypatch.setattr('keenv.cli.hide', lambda: calls.append(True))
    return calls


@pytest.fixture(name='template')
def template_fixture(tmp_path, vault_path, keyfile, monkeypatch):
    monkeypatch.delenv('KEENV_VAULT', raising=False)
    monkeypatch.delenv('KEENV_KEYFILE', raising=False)
    path = tmp_path / 'work.ovpn'
    path.write_text(
        f'# keenv: vault {vault_path}\n'
        f'# keenv: keyfile {keyfile}\n'
        'client\n'
        'remote vpn.example.com 1194\n'
        '# a $HOME that stays as written\n'
        '<auth-user-pass>\n'
        '  keenv://Oberon/R2/indech-state/username\n'
        'keenv://Oberon/R2/indech-state/password\n'
        '</auth-user-pass>\n',
        encoding='utf-8',
    )
    return path


def test_load_reads_the_directives(template, vault_path, keyfile):
    loaded = conf.load(template)
    assert loaded.settings == Settings(vault_path, keyfile, None)
    assert set(loaded.bindings) == {'line 7', 'line 8'}
    assert loaded.origins['line 7'] == str(template)


def test_render_swaps_references_and_drops_directives(template):
    loaded = conf.load(template)
    rendered = conf.render(
        loaded, {'line 7': 'user', 'line 8': 'pass\r\nword\n'},
    ).decode()
    assert rendered == (
        'client\n'
        'remote vpn.example.com 1194\n'
        '# a $HOME that stays as written\n'
        '<auth-user-pass>\n'
        'user\n'
        'pass\n'
        'word\n'
        '</auth-user-pass>\n'
    )


@pytest.mark.parametrize(('line', 'message'), [
    ('# keenv: ttl 5m', 'never remembers'),
    ('# keenv: pin 1234', 'unknown keenv directive'),
    ('# keenv: vault', 'needs a path'),
    ('keenv://only-a-field', 'entry path and a field'),
])
def test_a_bad_line_names_itself(tmp_path, line, message):
    path = tmp_path / 'bad.ovpn'
    path.write_text(f'client\n{line}\n', encoding='utf-8')
    with pytest.raises(ValueError, match=message) as caught:
        conf.load(path)
    assert f'{path}:2:' in str(caught.value)


def test_a_template_without_references_is_an_error(tmp_path):
    path = tmp_path / 'plain.ovpn'
    path.write_text('client\n', encoding='utf-8')
    with pytest.raises(ValueError, match='nothing to render'):
        conf.load(path)


def test_the_pipe_is_drained_by_one_read():
    fd = conf.pipe(b'client\n')
    try:
        assert os.read(fd, 100) == b'client\n'
        assert os.read(fd, 100) == b''
    finally:
        os.close(fd)


def test_a_config_larger_than_the_default_pipe_still_fits():
    content = b'x' * 200_000
    fd = conf.pipe(content)
    try:
        read = b''
        while chunk := os.read(fd, 65536):
            read += chunk
        assert read == content
    finally:
        os.close(fd)


def test_launch_reads_the_config_once_and_leaves_stdin_alone():
    script = (
        'from keenv.conf import launch; '
        "launch(b'client\\n', ['cat', '/dev/fd/3', '/dev/fd/3', '-'])"
    )
    result = subprocess.run(
        [sys.executable, '-c', script],
        input='from stdin\n', capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == 'client\nfrom stdin\n'


@pytest.mark.parametrize(('command', 'placed'), [
    (['openvpn', '--config', '{}'], ['openvpn', '--config', '/dev/fd/3']),
    (['tool', '--config={}'], ['tool', '--config=/dev/fd/3']),
])
def test_place_points_the_placeholder_at_the_carrier(command, placed):
    assert conf.place(command) == placed


@pytest.mark.parametrize(('command', 'message'), [
    (['openvpn', '--config', 'work.ovpn'], 'needs {}'),
    (['tool', '-c', '{}', '-d', '{}'], 'one {} only'),
])
def test_place_refuses_a_command_it_cannot_point(command, message):
    with pytest.raises(ValueError, match=message):
        conf.place(command)


def test_conf_becomes_the_command_given(template, monkeypatch, hidden):
    launched = {}

    def fake_launch(content, command):
        launched['content'] = content.decode()
        launched['command'] = command

    monkeypatch.setattr('keenv.cli.conf.launch', fake_launch)
    assert main([
        'conf', str(template), '--', 'sudo', '/usr/sbin/openvpn',
        '--config', '{}', '--verb', '4',
    ]) == 0

    assert launched['command'] == [
        'sudo', '/usr/sbin/openvpn', '--config', conf.CARRIER_PATH,
        '--verb', '4',
    ]
    assert f'{ACCESS_KEY}\n{SECRET_KEY}\n' in launched['content']
    assert 'keenv' not in launched['content']
    assert hidden == [True]


def test_the_vault_flag_beats_the_directive(
        template, vault_path, tmp_path, monkeypatch,
):
    moved = tmp_path / 'moved.kdbx'
    vault_path.rename(moved)
    monkeypatch.setattr('keenv.cli.conf.launch', lambda *arguments: None)
    assert main([
        'conf', str(template), '--vault', str(moved),
        '--', 'openvpn', '--config', '{}',
    ]) == 0


def test_conf_without_a_vault_is_an_error(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv('KEENV_VAULT', raising=False)
    path = tmp_path / 'novault.ovpn'
    path.write_text(
        'keenv://Oberon/R2/indech-state/api-token\n', encoding='utf-8',
    )
    assert main(['conf', str(path), '--', 'openvpn', '--config', '{}']) == 1
    assert '# keenv: vault' in capsys.readouterr().err


def test_a_custom_attribute_renders(template, monkeypatch):
    template.write_text(
        template.read_text(encoding='utf-8')
        + 'keenv://Oberon/R2/indech-state/api-token\n',
        encoding='utf-8',
    )
    launched = {}
    monkeypatch.setattr(
        'keenv.cli.conf.launch',
        lambda content, command: launched.update(content=content.decode()),
    )
    assert main(['conf', str(template), '--', 'openvpn', '-c', '{}']) == 0
    assert launched['content'].endswith(f'{TOKEN}\n')


def test_conf_without_a_command_is_usage_error(template, capsys):
    assert main(['conf', str(template)]) == 2
    assert 'needs a command' in capsys.readouterr().err
