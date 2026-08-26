import subprocess
import sys

from conftest import ACCESS_KEY, SECRET_KEY
from keenv.cli import main


def keenv(*arguments):
    return subprocess.run(
        [sys.executable, '-m', 'keenv', *arguments],
        capture_output=True, text=True, check=False,
    )


def test_run_hands_the_values_to_the_child(config_file, keyfile, tmp_path):
    result = keenv(
        'run', '-c', str(config_file), '-e', str(tmp_path / '.env'),
        '--keyfile', str(keyfile),
        '--', 'sh', '-c',
        'printf "%s %s" "$AWS_ACCESS_KEY_ID" "$AWS_SECRET_ACCESS_KEY"',
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == f'{ACCESS_KEY} {SECRET_KEY}'


def test_run_inherits_the_environment(config_file, keyfile, tmp_path):
    result = keenv(
        'run', '-c', str(config_file), '-e', str(tmp_path / '.env'),
        '--keyfile', str(keyfile), '--', 'sh', '-c', 'printf %s "$PATH"',
    )
    assert result.stdout


def test_run_resolves_a_reference_from_a_dotenv(vault_path, keyfile, tmp_path):
    env_file = tmp_path / '.env'
    env_file.write_text(
        'TOKEN=keenv://Oberon/R2/indech-state/api-token\nTF_LOG=INFO\n',
        encoding='utf-8',
    )
    result = keenv(
        'run', '-c', str(tmp_path / 'absent.yaml'), '-e', str(env_file),
        '--vault', str(vault_path), '--keyfile', str(keyfile),
        '--', 'sh', '-c', 'printf "%s %s" "$TOKEN" "$TF_LOG"',
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == 'a-custom-attribute INFO'


def test_check_never_prints_a_value(config_file, keyfile, tmp_path):
    result = keenv(
        'check', '-c', str(config_file), '-e', str(tmp_path / '.env'),
        '--keyfile', str(keyfile),
    )
    assert result.returncode == 0, result.stderr
    assert ACCESS_KEY not in result.stdout
    assert SECRET_KEY not in result.stdout
    assert 'AWS_ACCESS_KEY_ID' in result.stdout
    assert f'{len(ACCESS_KEY)} chars' in result.stdout


def test_run_without_a_command_is_usage_error(
        config_file, keyfile, tmp_path,
):
    result = keenv(
        'run', '-c', str(config_file), '-e', str(tmp_path / '.env'),
        '--keyfile', str(keyfile),
    )
    assert result.returncode == 2
    assert 'needs a command' in result.stderr


def test_an_unknown_command_exits_127(config_file, keyfile, tmp_path):
    result = keenv(
        'run', '-c', str(config_file), '-e', str(tmp_path / '.env'),
        '--keyfile', str(keyfile), '--', 'no-such-binary-anywhere',
    )
    assert result.returncode == 127
    assert 'command not found' in result.stderr


def test_nothing_to_resolve_is_an_error(tmp_path, capsys):
    code = main([
        'check',
        '-c', str(tmp_path / 'absent.yaml'),
        '-e', str(tmp_path / 'absent.env'),
    ])
    assert code == 1
    assert 'nothing to resolve' in capsys.readouterr().err


def test_a_reference_without_a_vault_is_an_error(tmp_path, capsys):
    env_file = tmp_path / '.env'
    env_file.write_text('A=keenv://Oberon/A/username\n', encoding='utf-8')
    code = main([
        'check', '-c', str(tmp_path / 'absent.yaml'), '-e', str(env_file),
    ])
    assert code == 1
    assert 'no vault' in capsys.readouterr().err
