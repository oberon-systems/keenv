import os
import subprocess
import sys

import pytest
from conftest import ACCESS_KEY, SECRET_KEY, TOKEN
from keenv import ovpn
from keenv.cli import main
from keenv.config import Settings


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
    loaded = ovpn.load(template)
    assert loaded.settings == Settings(vault_path, keyfile, None)
    assert set(loaded.bindings) == {'line 7', 'line 8'}
    assert loaded.origins['line 7'] == str(template)


def test_render_swaps_references_and_drops_directives(template):
    loaded = ovpn.load(template)
    rendered = ovpn.render(
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
        ovpn.load(path)
    assert f'{path}:2:' in str(caught.value)


def test_a_template_without_references_is_an_error(tmp_path):
    path = tmp_path / 'plain.ovpn'
    path.write_text('client\n', encoding='utf-8')
    with pytest.raises(ValueError, match='nothing to render'):
        ovpn.load(path)


def test_memfd_is_sealed_and_rewound():
    fd = ovpn.memfd(b'client\n')
    try:
        assert os.read(fd, 100) == b'client\n'
        with pytest.raises(PermissionError):
            os.write(fd, b'more')
    finally:
        os.close(fd)


def test_launch_hands_a_config_that_reads_twice():
    script = (
        'from keenv.ovpn import launch; '
        "launch(b'client\\n', ['sh', '-c', 'cat /dev/stdin /dev/stdin'])"
    )
    result = subprocess.run(
        [sys.executable, '-c', script],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == 'client\nclient\n'


def test_ovpn_launches_sudo_openvpn(template, monkeypatch):
    launched = {}

    def fake_launch(content, command):
        launched['content'] = content.decode()
        launched['command'] = command

    monkeypatch.setattr('keenv.cli.ovpn.launch', fake_launch)
    assert main(['ovpn', str(template), '--', '--verb', '4']) == 0

    assert launched['command'] == [*ovpn.LAUNCHER, '--verb', '4']
    assert f'{ACCESS_KEY}\n{SECRET_KEY}\n' in launched['content']
    assert 'keenv' not in launched['content']


def test_the_vault_flag_beats_the_directive(
        template, vault_path, tmp_path, monkeypatch,
):
    moved = tmp_path / 'moved.kdbx'
    vault_path.rename(moved)
    monkeypatch.setattr('keenv.cli.ovpn.launch', lambda *arguments: None)
    assert main(['ovpn', str(template), '--vault', str(moved)]) == 0


def test_ovpn_without_a_vault_is_an_error(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv('KEENV_VAULT', raising=False)
    path = tmp_path / 'novault.ovpn'
    path.write_text(
        'keenv://Oberon/R2/indech-state/api-token\n', encoding='utf-8',
    )
    assert main(['ovpn', str(path)]) == 1
    assert '# keenv: vault' in capsys.readouterr().err


def test_a_custom_attribute_renders(template, monkeypatch):
    template.write_text(
        template.read_text(encoding='utf-8')
        + 'keenv://Oberon/R2/indech-state/api-token\n',
        encoding='utf-8',
    )
    launched = {}
    monkeypatch.setattr(
        'keenv.cli.ovpn.launch',
        lambda content, command: launched.update(content=content.decode()),
    )
    assert main(['ovpn', str(template)]) == 0
    assert launched['content'].endswith(f'{TOKEN}\n')
