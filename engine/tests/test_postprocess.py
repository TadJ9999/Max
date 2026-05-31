"""Tests for engine/max_engine/postprocess.py"""

import pytest
from max_engine.postprocess import postprocess, reindent, strip_fences


class TestStripFences:
    def test_strips_python_fence(self):
        inp = "```python\ndef foo():\n    return 42\n```"
        assert strip_fences(inp) == "def foo():\n    return 42"

    def test_strips_plain_fence(self):
        inp = "```\nx = 1\n```"
        assert strip_fences(inp) == "x = 1"

    def test_no_fence_passthrough(self):
        inp = "def foo():\n    return 42"
        assert strip_fences(inp) == inp

    def test_single_line_no_fence(self):
        assert strip_fences("x = 1") == "x = 1"

    def test_only_strips_outer_fence(self):
        # Inner fences (e.g. in docstrings) should survive
        inp = "```python\ndef doc():\n    '''\n    ```example```\n    '''\n```"
        result = strip_fences(inp)
        assert "```example```" in result
        assert not result.startswith("```")


class TestReindent:
    def test_no_base_indent_passthrough(self):
        text = "def foo():\n    return 42"
        assert reindent(text, "") == text

    def test_adds_indent_to_continuation_lines(self):
        text = "def foo():\n    return 42"
        result = reindent(text, "    ")
        assert result == "def foo():\n        return 42"

    def test_blank_lines_stay_blank(self):
        text = "def foo():\n\n    return 42"
        result = reindent(text, "    ")
        assert result == "def foo():\n\n        return 42"

    def test_single_line_unchanged(self):
        assert reindent("x = 1", "    ") == "x = 1"


class TestPostprocess:
    def test_full_pipeline_with_fence_and_indent(self):
        raw = "```python\ndef foo():\n    return 42\n```"
        result = postprocess(raw, "    ")
        assert result == "def foo():\n        return 42"

    def test_no_fence_only_reindent(self):
        # base_indent="  " (2 spaces) is prepended to continuation lines.
        # LLM's own 4-space indent is preserved: 2+4 = 6 spaces on line 2.
        raw = "def foo():\n    return 42"
        result = postprocess(raw, "  ")
        assert result == "def foo():\n      return 42"

    def test_empty_after_strip(self):
        raw = "```\n```"
        result = postprocess(raw, "")
        assert result == ""

    def test_single_line_fence(self):
        raw = "```python\nx = 1\n```"
        assert postprocess(raw, "") == "x = 1"

    def test_streaming_intermediate_no_close_fence(self):
        # Simulate mid-stream: opening fence present, no closing fence yet
        raw = "```python\ndef foo():\n    return 42"
        result = postprocess(raw, "    ")
        assert result == "def foo():\n        return 42"
