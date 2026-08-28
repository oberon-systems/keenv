import pytest

from keenv.secret import (
    BLOB,
    check_pin,
    derive,
    is_short,
    seal,
    unseal,
    wipe,
)

PASSWORD = 'not-the-real-master-password'
PIN = '123456'


def test_a_sealed_password_comes_back_with_the_right_pin():
    salt, blob = seal(PASSWORD, PIN)
    assert unseal(blob, salt, PIN) == PASSWORD


def test_a_wrong_pin_gives_rubbish_rather_than_an_error():
    salt, blob = seal(PASSWORD, PIN)
    assert unseal(blob, salt, '654321') != PASSWORD


def test_rubbish_that_is_not_even_text_comes_back_as_nothing():
    salt = b'0123456789abcdef'
    keystream = derive(PIN, salt)
    rubbish = b'\xff\xfe'.ljust(BLOB, b'\0')
    blob = bytes(a ^ b for a, b in zip(rubbish, keystream))
    assert unseal(blob, salt, PIN) is None


def test_the_blob_never_betrays_the_password_length():
    assert len(seal('a', PIN)[1]) == len(seal('a' * 100, PIN)[1]) == BLOB


def test_every_seal_draws_a_fresh_salt():
    assert seal(PASSWORD, PIN)[0] != seal(PASSWORD, PIN)[0]


def test_the_same_pin_and_salt_give_the_same_keystream():
    salt = b'0123456789abcdef'
    assert derive(PIN, salt) == derive(PIN, salt)


def test_a_different_salt_gives_a_different_keystream():
    assert derive(PIN, b'0' * 16) != derive(PIN, b'1' * 16)


def test_wipe_really_zeroes_the_buffer():
    _, blob = seal(PASSWORD, PIN)
    wipe(blob)
    assert bytes(blob) == bytes(BLOB)


def test_a_password_longer_than_a_blob_is_refused():
    with pytest.raises(ValueError, match='longer than'):
        seal('x' * (BLOB + 1), PIN)


@pytest.mark.parametrize('pin', ['1234', '12345678'])
def test_the_pins_at_the_edges_are_accepted(pin):
    check_pin(pin)


@pytest.mark.parametrize('pin', ['123', '123456789', 'abcd', '', '12 34'])
def test_anything_else_is_refused(pin):
    with pytest.raises(ValueError, match='4 to 8 digits'):
        check_pin(pin)


def test_only_the_shortest_pin_counts_as_short():
    assert is_short('1234')
    assert not is_short('12345')
