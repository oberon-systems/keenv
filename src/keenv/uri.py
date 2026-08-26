"""The `keenv://` reference: which entry and field a variable comes from."""

from typing import NamedTuple

SCHEME = 'keenv://'

# KeePass spells the built-in fields this way; anything else is a custom
# attribute and keeps whatever spelling the reference used.
STANDARD_FIELDS = {
    'username': 'UserName',
    'user': 'UserName',
    'password': 'Password',
    'url': 'URL',
    'notes': 'Notes',
    'title': 'Title',
}


class Reference(NamedTuple):
    """An entry path inside the database plus the field to read from it."""

    path: tuple[str, ...]
    field: str

    def __str__(self) -> str:
        return SCHEME + '/'.join((*self.path, self.field))


def normalize_field(field: str) -> str:
    """Map a field onto its KeePass spelling, leaving custom ones be."""
    field = field.strip()
    return STANDARD_FIELDS.get(field.lower(), field)


def is_reference(value: str) -> bool:
    """Whether a value is a keenv:// reference rather than a literal."""
    return value.startswith(SCHEME)


def parse(value: str) -> Reference:
    """Parse `keenv://Group/Sub/Entry/field` into a Reference.

    The last segment is the field and everything before it is the path to the
    entry, so a field name containing a slash cannot be addressed this way.
    """
    if not is_reference(value):
        raise ValueError(f'not a keenv reference: {value!r}')

    segments = value[len(SCHEME):].split('/')
    if any(not segment for segment in segments):
        raise ValueError(f'empty segment in reference: {value!r}')
    if len(segments) < 2:
        raise ValueError(
            f'reference needs an entry path and a field: {value!r}',
        )

    return Reference(tuple(segments[:-1]), normalize_field(segments[-1]))


def from_entry(entry: str, field: str) -> Reference:
    """Build a Reference from the `entry:`/`field:` pair keenv.yaml uses."""
    segments = [segment for segment in entry.split('/') if segment]
    if not segments:
        raise ValueError(f'entry path is empty: {entry!r}')
    if not field.strip():
        raise ValueError(f'field is empty for entry {entry!r}')

    return Reference(tuple(segments), normalize_field(field))
