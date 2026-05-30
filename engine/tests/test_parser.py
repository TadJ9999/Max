from max_engine.dsl import parse_command, ParseError

import pytest


def test_generate_default():
    cmd = parse_command(". add a function to do X .")
    assert cmd.action == "generate"
    assert cmd.body == "add a function to do X"
    assert cmd.sigil is None
    assert cmd.provider == "default"
    assert cmd.is_cloud is False


def test_summarize_default():
    cmd = parse_command(".. def foo(): return 1 ..")
    assert cmd.action == "summarize"
    assert cmd.body == "def foo(): return 1"


def test_cloud_sigil_generate():
    cmd = parse_command("!. refactor this .")
    assert cmd.action == "generate"
    assert cmd.sigil == "!"
    assert cmd.provider == "claude"
    assert cmd.is_cloud is True


def test_local_sigil_summarize():
    cmd = parse_command("@.. x = 1 ..")
    assert cmd.action == "summarize"
    assert cmd.provider == "ollama"
    assert cmd.is_cloud is False


def test_qwen_sigil():
    cmd = parse_command("#. write a parser .")
    assert cmd.provider == "qwen"


def test_summarize_takes_priority_over_generate():
    # ".." must be matched before "."
    cmd = parse_command(".. body ..")
    assert cmd.action == "summarize"


@pytest.mark.parametrize("bad", ["", "   ", "no operator here", ". unclosed", ".. unclosed ."])
def test_invalid_commands(bad):
    with pytest.raises(ParseError):
        parse_command(bad)
