import pytest
from pykeepass import create_database

ACCESS_KEY = 'r2-access-key-id'
SECRET_KEY = 'r2-secret-access-key'
TOKEN = 'a-custom-attribute'


@pytest.fixture(name='keyfile')
def keyfile_fixture(tmp_path):
    path = tmp_path / 'oberon.keyx'
    path.write_bytes(b'not-a-real-key-file-just-bytes')
    return path


@pytest.fixture(name='vault_path')
def vault_path_fixture(tmp_path, keyfile):
    """One entry, opened by key file so no test ever needs a tty."""
    path = tmp_path / 'oberon.kdbx'
    database = create_database(str(path), keyfile=str(keyfile))

    oberon = database.add_group(database.root_group, 'Oberon')
    r2 = database.add_group(oberon, 'R2')
    entry = database.add_entry(
        r2, 'indech-state', username=ACCESS_KEY, password=SECRET_KEY,
    )
    entry.set_custom_property('api-token', TOKEN)
    database.save()

    return path


@pytest.fixture(name='config_file')
def config_file_fixture(tmp_path, vault_path):
    path = tmp_path / 'keenv.yaml'
    path.write_text(
        f'vault: {vault_path}\n'
        'env:\n'
        '  AWS_ACCESS_KEY_ID:\n'
        '    entry: Oberon/R2/indech-state\n'
        '    field: username\n'
        '  AWS_SECRET_ACCESS_KEY:\n'
        '    entry: Oberon/R2/indech-state\n'
        '    field: password\n',
        encoding='utf-8',
    )
    return path
