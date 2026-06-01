import pytest

from max_engine.dsl import ParseError, parse_command


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
    # qwen moved from "#" to "q" when "#" became the subscription Claude sigil.
    cmd = parse_command("q. write a parser .")
    assert cmd.provider == "qwen"
    assert cmd.is_cloud is False


def test_subscription_claude_sigil():
    cmd = parse_command("#. write a parser .")
    assert cmd.sigil == "#"
    assert cmd.provider == "claude-cli"
    assert cmd.is_cloud is True  # gated like cloud (egresses to Anthropic)


def test_fix_operator():
    cmd = parse_command("~ tidy this messy block ~")
    assert cmd.action == "fix"
    assert cmd.body == "tidy this messy block"
    assert cmd.provider == "default"


def test_cloud_sigil_with_fix():
    cmd = parse_command("!~ refactor for speed ~")
    assert cmd.action == "fix"
    assert cmd.provider == "claude"
    assert cmd.is_cloud is True


def test_summarize_takes_priority_over_generate():
    # ".." must be matched before "."
    cmd = parse_command(".. body ..")
    assert cmd.action == "summarize"


@pytest.mark.parametrize("bad", ["", "   ", "no operator here", ". unclosed", ".. unclosed ."])
def test_invalid_commands(bad):
    with pytest.raises(ParseError):
        parse_command(bad)
