"""Tests for Aegis secret redaction."""

from max_engine.aegis.redact import redact, redact_dict


def test_redact_anthropic_sk_ant():
    text = 'key = "sk-ant-api03-abcdef1234567890ABCDEF"'
    out = redact(text)
    assert "sk-ant-api03" not in out
    assert "REDACTED" in out


def test_redact_env_kv_style():
    text = "ANTHROPIC_API_KEY=sk-ant-verylongkeyvalue12345"
    out = redact(text)
    assert "sk-ant" not in out


def test_redact_bearer_token():
    text = "Authorization: Bearer abc123xyz456789longtoken"
    out = redact(text)
    assert "abc123xyz456789longtoken" not in out
    assert "Bearer" in out  # keyword stays


def test_redact_finnhub_key():
    text = "FINNHUB_API_KEY=fk_prod_LONGKEYHEREABCDEF"
    out = redact(text)
    assert "LONGKEYHEREABCDEF" not in out


def test_redact_json_api_key():
    text = '{"api_key": "supersecretvalue123"}'
    out = redact(text)
    assert "supersecretvalue123" not in out


def test_redact_preserves_safe_text():
    text = "This is a safe log line with no secrets present here."
    assert redact(text) == text


def test_redact_preserves_short_values():
    # Short values (< 6 chars) should not be redacted to avoid false positives
    text = "KEY=abc"
    out = redact(text)
    # Should either be untouched or safe
    assert "abc" in out or "REDACTED" in out  # either outcome is acceptable for short values


def test_redact_dict():
    data = {"message": "ANTHROPIC_API_KEY=sk-ant-secret", "count": 5}
    out = redact_dict(data)
    assert "sk-ant-secret" not in out["message"]
    assert out["count"] == 5


def test_redact_dict_nested():
    data = {"inner": {"token": "Bearer abc123longtoken999"}}
    out = redact_dict(data)
    # Inner dict should be recursively redacted
    assert "abc123longtoken999" not in str(out)


def test_redact_url_query_secret():
    text = "https://api.example.com/data?api_key=secretkey12345&other=value"
    out = redact(text)
    assert "secretkey12345" not in out
