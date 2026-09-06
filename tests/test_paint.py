import io

import pytest

from keenv import paint


class Terminal(io.StringIO):
    """A stream that says it is one, which io.StringIO does not."""

    def isatty(self):
        return True


@pytest.fixture(autouse=True)
def colour_fixture(monkeypatch):
    """Every test starts with colour on and the environment saying nothing."""
    monkeypatch.setattr(paint, '_wanted', True)
    monkeypatch.delenv('NO_COLOR', raising=False)
    monkeypatch.setenv('TERM', 'xterm-256color')


def test_a_terminal_gets_the_solarized_index():
    assert paint.info('x', Terminal()) == '\x1b[38;5;136mx\x1b[0m'
    assert paint.good('x', Terminal()) == '\x1b[38;5;64mx\x1b[0m'
    assert paint.bad('x', Terminal()) == '\x1b[38;5;160mx\x1b[0m'


def test_no_stream_is_the_tty_and_takes_colour():
    assert paint.info('x') == '\x1b[38;5;136mx\x1b[0m'


def test_a_pipe_gets_the_text_and_nothing_else():
    assert paint.info('x', io.StringIO()) == 'x'


def test_no_color_silences_even_a_terminal(monkeypatch):
    monkeypatch.setenv('NO_COLOR', '1')
    assert paint.info('x', Terminal()) == 'x'
    assert paint.info('x') == 'x'


def test_a_dumb_terminal_gets_nothing(monkeypatch):
    monkeypatch.setenv('TERM', 'dumb')
    assert paint.info('x', Terminal()) == 'x'


def test_disable_silences_the_rest_of_the_run():
    paint.disable()
    assert paint.info('x', Terminal()) == 'x'
    assert paint.good('x') == 'x'
