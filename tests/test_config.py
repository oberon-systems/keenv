import pytest

from keenv.config import build, load_config, load_env
from keenv.uri import Reference


def write(path, text):
    path.write_text(text, encoding='utf-8')
    return path


def test_a_missing_file_is_an_empty_layer(tmp_path):
    assert load_env(tmp_path / '.env') == {}
    assert load_config(tmp_path / 'keenv.yaml').bindings == {}


def test_env_separates_references_from_literals(tmp_path):
    path = write(tmp_path / '.env', '\n'.join([
        '# a comment',
        '',
        'AWS_ACCESS_KEY_ID=keenv://Oberon/R2/indech-state/username',
        'export TF_LOG=INFO',
        'QUOTED="double"',
        "SINGLE='single'",
        'SPACED  =  spaced  ',
    ]))

    assert load_env(path) == {
        'AWS_ACCESS_KEY_ID':
            Reference(('Oberon', 'R2', 'indech-state'), 'UserName'),
        'TF_LOG': 'INFO',
        'QUOTED': 'double',
        'SINGLE': 'single',
        'SPACED': 'spaced',
    }


def test_env_keeps_a_hash_inside_a_value(tmp_path):
    path = write(tmp_path / '.env', 'PASSPHRASE=abc#def\n')
    assert load_env(path) == {'PASSPHRASE': 'abc#def'}


def test_env_rejects_a_line_that_is_not_an_assignment(tmp_path):
    path = write(tmp_path / '.env', 'AWS_ACCESS_KEY_ID\n')
    with pytest.raises(ValueError, match='not a NAME=value line'):
        load_env(path)


def test_env_reports_the_line_of_a_broken_reference(tmp_path):
    path = write(tmp_path / '.env', 'A=1\nB=keenv://oops\n')
    with pytest.raises(ValueError, match=':2:'):
        load_env(path)


def test_env_expands_a_variable_from_the_environment(tmp_path, monkeypatch):
    monkeypatch.setenv('PWD', '/home/zombig/oberon/balor')
    path = write(tmp_path / '.env', 'SUIL_BASE_DIR="${PWD}"\n')
    assert load_env(path) == {'SUIL_BASE_DIR': '/home/zombig/oberon/balor'}


def test_env_expands_a_name_without_braces(tmp_path, monkeypatch):
    monkeypatch.setenv('STAGE', 'prod')
    path = write(tmp_path / '.env', 'CLUSTER=$STAGE-eu\n')
    assert load_env(path) == {'CLUSTER': 'prod-eu'}


def test_env_expands_a_literal_declared_earlier(tmp_path, monkeypatch):
    monkeypatch.setenv('PWD', '/home/zombig/oberon')
    path = write(tmp_path / '.env', '\n'.join([
        'PROJECT=balor',
        'SUIL_BASE_DIR="${PWD}/${PROJECT}"',
    ]))
    assert load_env(path)['SUIL_BASE_DIR'] == '/home/zombig/oberon/balor'


def test_env_beats_the_environment_it_expands_from(tmp_path, monkeypatch):
    monkeypatch.setenv('STAGE', 'from-environment')
    path = write(tmp_path / '.env', 'STAGE=from-file\nCLUSTER="${STAGE}"\n')
    assert load_env(path)['CLUSTER'] == 'from-file'


def test_env_leaves_a_single_quoted_value_alone(tmp_path, monkeypatch):
    monkeypatch.setenv('PWD', '/home/zombig')
    path = write(tmp_path / '.env', "LITERAL='${PWD}'\n")
    assert load_env(path) == {'LITERAL': '${PWD}'}


def test_env_keeps_an_escaped_dollar(tmp_path):
    path = write(tmp_path / '.env', 'PRICE="100\\$"\n')
    assert load_env(path) == {'PRICE': '100$'}


def test_env_expands_a_name_that_is_not_set_to_nothing(tmp_path, monkeypatch):
    monkeypatch.delenv('NOWHERE', raising=False)
    path = write(tmp_path / '.env', 'EMPTY="a${NOWHERE}b"\n')
    assert load_env(path) == {'EMPTY': 'ab'}


def test_env_takes_the_default_when_the_name_is_not_set(tmp_path, monkeypatch):
    monkeypatch.delenv('TF_LOG', raising=False)
    path = write(tmp_path / '.env', 'LOG="${TF_LOG:-INFO}"\n')
    assert load_env(path) == {'LOG': 'INFO'}


def test_env_takes_the_default_when_the_name_is_empty(tmp_path, monkeypatch):
    monkeypatch.setenv('TF_LOG', '')
    path = write(tmp_path / '.env', 'LOG="${TF_LOG:-INFO}"\n')
    assert load_env(path) == {'LOG': 'INFO'}


def test_env_expands_inside_a_reference(tmp_path, monkeypatch):
    monkeypatch.setenv('STAGE', 'prod')
    path = write(
        tmp_path / '.env', 'KEY=keenv://Oberon/vaults/${STAGE}-age/password\n',
    )
    assert load_env(path) == {
        'KEY': Reference(('Oberon', 'vaults', 'prod-age'), 'Password'),
    }


def test_env_refuses_to_expand_a_secret_into_another_value(tmp_path):
    path = write(tmp_path / '.env', '\n'.join([
        'KEY=keenv://Oberon/A/password',
        'LEAK="${KEY}"',
    ]))
    with pytest.raises(ValueError, match=':2:.*never'):
        load_env(path)


def test_config_reads_the_vault_and_the_entries(tmp_path):
    path = write(tmp_path / 'keenv.yaml', '\n'.join([
        'vault: ~/vault.kdbx',
        'env:',
        '  AWS_ACCESS_KEY_ID:',
        '    entry: Oberon/R2/indech-state',
        '    field: username',
    ]))

    plan = load_config(path)
    assert plan.settings.vault.name == 'vault.kdbx'
    assert plan.settings.vault.is_absolute()
    assert plan.bindings == {
        'AWS_ACCESS_KEY_ID':
            Reference(('Oberon', 'R2', 'indech-state'), 'UserName'),
    }


def test_config_rejects_an_entry_without_a_field(tmp_path):
    path = write(
        tmp_path / 'keenv.yaml', 'env:\n  A:\n    entry: Oberon/A\n',
    )
    with pytest.raises(ValueError, match=r'env\.A\.field'):
        load_config(path)


def test_config_rejects_an_unknown_top_level_key(tmp_path):
    path = write(tmp_path / 'keenv.yaml', 'vualt: /typo.kdbx\n')
    with pytest.raises(ValueError, match='vualt'):
        load_config(path)


def test_config_rejects_an_unknown_key_inside_an_entry(tmp_path):
    path = write(tmp_path / 'keenv.yaml', '\n'.join([
        'env:',
        '  A:',
        '    entry: Oberon/A',
        '    field: password',
        '    attribute: password',
    ]))
    with pytest.raises(ValueError, match='attribute'):
        load_config(path)


def test_config_rejects_a_blank_entry(tmp_path):
    path = write(
        tmp_path / 'keenv.yaml', 'env:\n  A:\n    entry: " "\n    field: x\n',
    )
    with pytest.raises(ValueError, match='must not be empty'):
        load_config(path)


def test_config_rejects_a_non_mapping_document(tmp_path):
    path = write(tmp_path / 'keenv.yaml', '- one\n- two\n')
    with pytest.raises(ValueError):
        load_config(path)


def test_env_overrides_the_config(tmp_path):
    config = write(tmp_path / 'keenv.yaml', '\n'.join([
        'vault: /vault.kdbx',
        'env:',
        '  SHARED:',
        '    entry: Oberon/A',
        '    field: password',
        '  ONLY_IN_CONFIG:',
        '    entry: Oberon/B',
        '    field: password',
    ]))
    env = write(tmp_path / '.env', 'SHARED=literal-wins\nONLY_IN_ENV=x\n')

    plan = build(config, env)
    assert plan.bindings['SHARED'] == 'literal-wins'
    assert plan.bindings['ONLY_IN_CONFIG'] == Reference(
        ('Oberon', 'B'), 'Password',
    )
    assert plan.bindings['ONLY_IN_ENV'] == 'x'


def test_the_vault_flag_beats_the_config(tmp_path):
    config = write(tmp_path / 'keenv.yaml', 'vault: /from-config.kdbx\n')
    plan = build(config, tmp_path / '.env', vault=tmp_path / 'from-flag.kdbx')
    assert plan.settings.vault == tmp_path / 'from-flag.kdbx'


def test_keenv_vault_beats_the_config(tmp_path, monkeypatch):
    monkeypatch.setenv('KEENV_VAULT', '/from-environment.kdbx')
    config = write(tmp_path / 'keenv.yaml', 'vault: /from-config.kdbx\n')
    plan = build(config, tmp_path / '.env')
    assert str(plan.settings.vault) == '/from-environment.kdbx'


def test_build_records_the_file_each_variable_came_from(tmp_path):
    config = write(tmp_path / 'keenv.yaml', '\n'.join([
        'env:',
        '  SHARED:',
        '    entry: Oberon/A',
        '    field: password',
        '  ONLY_IN_CONFIG:',
        '    entry: Oberon/B',
        '    field: password',
    ]))
    env = write(tmp_path / '.env', 'SHARED=literal-wins\nONLY_IN_ENV=x\n')

    assert build(config, env).origins == {
        'SHARED': str(env),
        'ONLY_IN_CONFIG': str(config),
        'ONLY_IN_ENV': str(env),
    }


def test_a_ttl_in_minutes_is_read(tmp_path):
    config = write(tmp_path / 'keenv.yaml', 'ttl: 15m\n')
    assert load_config(config).settings.ttl == 900


def test_a_ttl_in_seconds_is_read(tmp_path):
    config = write(tmp_path / 'keenv.yaml', 'ttl: 30s\n')
    assert load_config(config).settings.ttl == 30


def test_a_bare_ttl_counts_as_seconds(tmp_path):
    config = write(tmp_path / 'keenv.yaml', 'ttl: 90\n')
    assert load_config(config).settings.ttl == 90


def test_no_ttl_means_nothing_is_remembered(tmp_path):
    config = write(tmp_path / 'keenv.yaml', 'vault: /a.kdbx\n')
    assert load_config(config).settings.ttl is None


def test_a_ttl_past_the_ceiling_is_an_error(tmp_path):
    config = write(tmp_path / 'keenv.yaml', 'ttl: 16m\n')
    with pytest.raises(ValueError, match='must not exceed 15m'):
        load_config(config)


def test_an_hour_is_not_a_duration_keenv_takes(tmp_path):
    config = write(tmp_path / 'keenv.yaml', 'ttl: 1h\n')
    with pytest.raises(ValueError, match='not a duration'):
        load_config(config)


def test_a_zero_ttl_is_an_error(tmp_path):
    config = write(tmp_path / 'keenv.yaml', 'ttl: 0\n')
    with pytest.raises(ValueError, match='more than zero'):
        load_config(config)


def test_the_ttl_survives_the_merge(tmp_path):
    config = write(tmp_path / 'keenv.yaml', 'ttl: 5m\nvault: /a.kdbx\n')
    plan = build(config, tmp_path / '.env', vault=tmp_path / 'b.kdbx')
    assert plan.settings.ttl == 300
