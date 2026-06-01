"""Subscription Claude (claude-cli) provider — tests with an injected fake spawn.

No real `claude` process is launched: a fake process feeds canned stream-json so
we can assert streaming, env-stripping, arg construction, and error surfacing.
"""

import asyncio
import os

import pytest

from max_engine.providers.claude_agent import (
    ClaudeAgentProvider,
    _split_messages,
    find_claude,
    subscription_env,
)


# ---- fake subprocess plumbing ------------------------------------------------


class _FakeStdout:
    def __init__(self, lines):
        self._lines = [ln if isinstance(ln, bytes) else ln.encode("utf-8") for ln in lines]

    def __aiter__(self):
        async def gen():
            for ln in self._lines:
                yield ln

        return gen()


class _FakeStderr:
    def __init__(self, data=b""):
        self._data = data

    async def read(self):
        return self._data


class _FakeProc:
    def __init__(self, lines, returncode=0, stderr=b""):
        self.stdout = _FakeStdout(lines)
        self.stderr = _FakeStderr(stderr)
        self._rc = returncode
        self.returncode = None
        self.killed = False

    async def wait(self):
        self.returncode = self._rc
        return self._rc

    def kill(self):
        self.killed = True


def _spawn_returning(proc, captured):
    async def spawn(argv, env, stdin_data):
        captured["argv"] = list(argv)
        captured["env"] = dict(env)
        captured["stdin"] = stdin_data
        return proc

    return spawn


def _collect(provider, model, messages):
    async def run():
        return [c async for c in provider.chat(model, messages)]

    return asyncio.run(run())


def _result_line(text="ok", is_error=False, in_tok=3, out_tok=5):
    import json

    ev = {
        "type": "result",
        "subtype": "success",
        "is_error": is_error,
        "result": text,
        "usage": {"input_tokens": in_tok, "output_tokens": out_tok},
    }
    return json.dumps(ev)


# ---- streaming ---------------------------------------------------------------


def test_streams_partial_text_deltas():
    lines = [
        '{"type":"system","subtype":"init"}',
        '{"type":"stream_event","event":{"type":"content_block_delta","delta":{"type":"text_delta","text":"Hello"}}}',
        '{"type":"stream_event","event":{"type":"content_block_delta","delta":{"type":"text_delta","text":" world"}}}',
        '{"type":"assistant","message":{"content":[{"type":"text","text":"Hello world"}]}}',
        _result_line("Hello world"),
    ]
    captured = {}
    provider = ClaudeAgentProvider(spawn=_spawn_returning(_FakeProc(lines), captured))
    chunks = _collect(provider, "claude-opus-4-8", [{"role": "user", "content": "hi"}])
    # Partial deltas win; the assistant fallback must NOT double-append.
    assert "".join(c.text for c in chunks) == "Hello world"
    assert chunks[-1].done is True


def test_falls_back_to_assistant_message_when_no_partials():
    lines = [
        '{"type":"assistant","message":{"content":[{"type":"text","text":"pong"}]}}',
        _result_line("pong"),
    ]
    provider = ClaudeAgentProvider(spawn=_spawn_returning(_FakeProc(lines), {}))
    chunks = _collect(provider, "claude-sonnet-4-6", [{"role": "user", "content": "ping"}])
    assert "".join(c.text for c in chunks) == "pong"
    assert chunks[-1].done is True


def test_falls_back_to_result_text_when_no_assistant_block():
    lines = [_result_line("final answer")]
    provider = ClaudeAgentProvider(spawn=_spawn_returning(_FakeProc(lines), {}))
    chunks = _collect(provider, "claude-opus-4-8", [{"role": "user", "content": "q"}])
    assert "".join(c.text for c in chunks) == "final answer"


# ---- the linchpin: subscription auth -----------------------------------------


def test_strips_anthropic_api_key_from_child_env(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-not-leak")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "tok")
    monkeypatch.setenv("PATH_SENTINEL", "keep-me")
    captured = {}
    provider = ClaudeAgentProvider(spawn=_spawn_returning(_FakeProc([_result_line()]), captured))
    _collect(provider, "claude-opus-4-8", [{"role": "user", "content": "hi"}])
    assert "ANTHROPIC_API_KEY" not in captured["env"]
    assert "ANTHROPIC_AUTH_TOKEN" not in captured["env"]
    assert "ANTHROPIC_BASE_URL" not in captured["env"]
    # Unrelated env is preserved so the CLI still works.
    assert captured["env"].get("PATH_SENTINEL") == "keep-me"


def test_subscription_env_helper(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setenv("FOO", "bar")
    env = subscription_env()
    assert "ANTHROPIC_API_KEY" not in env
    assert env["FOO"] == "bar"


# ---- argument construction ---------------------------------------------------


def test_system_prompt_replaced_and_user_on_stdin():
    captured = {}
    provider = ClaudeAgentProvider(spawn=_spawn_returning(_FakeProc([_result_line()]), captured))
    _collect(
        provider,
        "claude-opus-4-8",
        [{"role": "system", "content": "be terse"}, {"role": "user", "content": "write X"}],
    )
    argv = captured["argv"]
    assert "--system-prompt" in argv
    assert argv[argv.index("--system-prompt") + 1] == "be terse"
    # User body goes to stdin, not argv (dodges Windows command-line limits).
    assert captured["stdin"] == b"write X"
    assert "write X" not in argv


def test_model_alias_and_single_shot_guards():
    captured = {}
    provider = ClaudeAgentProvider(spawn=_spawn_returning(_FakeProc([_result_line()]), captured))
    _collect(provider, "claude-opus-4-8", [{"role": "user", "content": "hi"}])
    argv = captured["argv"]
    assert argv[argv.index("--model") + 1] == "opus"  # ID → CLI alias
    assert "--max-turns" in argv and argv[argv.index("--max-turns") + 1] == "1"
    assert "--disallowed-tools" in argv
    assert "Write" in argv and "Bash" in argv  # mutating tools blocked
    assert "--print" in argv and "stream-json" in argv


# ---- error surfacing ---------------------------------------------------------


def test_not_logged_in_raises_actionable_error():
    lines = [_result_line("Not logged in · Please run /login", is_error=True)]
    provider = ClaudeAgentProvider(spawn=_spawn_returning(_FakeProc(lines), {}))
    with pytest.raises(RuntimeError, match="not logged in"):

        async def run():
            return [c async for c in provider.chat("claude-opus-4-8", [{"role": "user", "content": "x"}])]

        asyncio.run(run())


def test_nonzero_exit_with_no_output_raises_stderr():
    proc = _FakeProc([], returncode=1, stderr=b"boom from claude")
    provider = ClaudeAgentProvider(spawn=_spawn_returning(proc, {}))
    with pytest.raises(RuntimeError, match="boom from claude"):

        async def run():
            return [c async for c in provider.chat("claude-opus-4-8", [{"role": "user", "content": "x"}])]

        asyncio.run(run())


# ---- helpers -----------------------------------------------------------------


def test_split_messages_flattens_multi_turn():
    system, user = _split_messages(
        [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "a"},
            {"role": "assistant", "content": "b"},
            {"role": "user", "content": "c"},
        ]
    )
    assert system == "sys"
    assert "USER: a" in user and "ASSISTANT: b" in user and "USER: c" in user


def test_find_claude_explicit_and_cmd_shim(tmp_path):
    exe = tmp_path / "claude.exe"
    exe.write_text("")
    assert find_claude(str(exe)) == [str(exe)]

    cmd = tmp_path / "claude.cmd"
    cmd.write_text("")
    assert find_claude(str(cmd)) == ["cmd", "/c", str(cmd)]


def test_find_claude_falls_back_to_bare_name():
    # A non-existent explicit path falls through; with nothing found, bare "claude".
    result = find_claude("/no/such/claude/binary")
    assert result[-1] == "claude" or os.path.exists(result[0])
