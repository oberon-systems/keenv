import pytest

from conftest import ACCESS_KEY, SECRET_KEY, TOKEN
from keenv.uri import parse
from keenv.vault import Vault


@pytest.fixture(name='vault')
def vault_fixture(vault_path, keyfile):
    return Vault(vault_path, keyfile=keyfile)


@pytest.mark.parametrize(('reference', 'expected'), [
    ('keenv://Oberon/R2/indech-state/username', ACCESS_KEY),
    ('keenv://Oberon/R2/indech-state/password', SECRET_KEY),
    ('keenv://Oberon/R2/indech-state/title', 'indech-state'),
    ('keenv://Oberon/R2/indech-state/api-token', TOKEN),
])
def test_field_reads_standard_and_custom(vault, reference, expected):
    assert vault.field(parse(reference)) == expected


def test_field_reports_a_missing_entry(vault):
    with pytest.raises(ValueError, match='no entry at Oberon/R2/nope'):
        vault.field(parse('keenv://Oberon/R2/nope/username'))


def test_field_reports_a_missing_field(vault):
    with pytest.raises(ValueError, match='has no absent-one field'):
        vault.field(parse('keenv://Oberon/R2/indech-state/absent-one'))


def test_a_missing_vault_is_named(tmp_path, keyfile):
    with pytest.raises(ValueError, match='vault not found'):
        Vault(tmp_path / 'nowhere.kdbx', keyfile=keyfile)


def test_a_missing_key_file_is_named(vault_path, tmp_path):
    with pytest.raises(ValueError, match='key file not found'):
        Vault(vault_path, keyfile=tmp_path / 'nowhere.keyx')


def test_the_wrong_key_file_is_reported_as_credentials(vault_path, tmp_path):
    wrong = tmp_path / 'wrong.keyx'
    wrong.write_bytes(b'some-other-bytes')
    with pytest.raises(ValueError, match='wrong master password or key file'):
        Vault(vault_path, keyfile=wrong)
