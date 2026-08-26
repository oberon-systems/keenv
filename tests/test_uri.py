import pytest

from keenv.uri import (Reference, from_entry, is_reference,
                       normalize_field, parse)


def test_parse_takes_the_last_segment_as_the_field():
    assert parse('keenv://Oberon/R2/indech-state/username') == Reference(
        ('Oberon', 'R2', 'indech-state'), 'UserName',
    )


def test_parse_accepts_a_top_level_entry():
    assert parse('keenv://indech-state/password') == Reference(
        ('indech-state',), 'Password',
    )


def test_parse_keeps_a_custom_field_spelling():
    assert parse('keenv://Oberon/thing/api-Token').field == 'api-Token'


@pytest.mark.parametrize('value', [
    'keenv://only-one-segment',
    'keenv://Oberon//username',
    'keenv://',
])
def test_parse_rejects_a_malformed_reference(value):
    with pytest.raises(ValueError):
        parse(value)


def test_parse_rejects_a_literal():
    with pytest.raises(ValueError):
        parse('plain-value')


def test_is_reference_separates_references_from_literals():
    assert is_reference('keenv://a/b')
    assert not is_reference('keenv:/a/b')
    assert not is_reference('INFO')


@pytest.mark.parametrize(('given', 'expected'), [
    ('username', 'UserName'),
    ('USERNAME', 'UserName'),
    ('user', 'UserName'),
    ('password', 'Password'),
    ('url', 'URL'),
    ('notes', 'Notes'),
    ('title', 'Title'),
    ('api-token', 'api-token'),
])
def test_normalize_field(given, expected):
    assert normalize_field(given) == expected


def test_from_entry_matches_what_parse_produces():
    assert from_entry('Oberon/R2/indech-state', 'password') == parse(
        'keenv://Oberon/R2/indech-state/password',
    )


def test_str_round_trips():
    reference = parse('keenv://Oberon/R2/indech-state/password')
    assert str(reference) == 'keenv://Oberon/R2/indech-state/Password'


@pytest.mark.parametrize(
    ('entry', 'field'), [('', 'username'), ('Oberon', ' ')],
)
def test_from_entry_rejects_empty_halves(entry, field):
    with pytest.raises(ValueError):
        from_entry(entry, field)
