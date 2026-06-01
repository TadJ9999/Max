"""Tests for reports skill — generation, persistence, list/delete."""

import json
import time
from pathlib import Path

import pytest

from max_engine.skills.reports import ReportService, _extract_title, _REPORTS_DIR


@pytest.fixture
def svc(tmp_path, monkeypatch):
    monkeypatch.setattr("max_engine.skills.reports._REPORTS_DIR", tmp_path)
    return ReportService()


def test_list_reports_empty(svc):
    assert svc.list_reports() == []


def test_get_nonexistent(svc):
    assert svc.get_report("nonexistent") is None


def test_delete_nonexistent(svc):
    assert svc.delete_report("nonexistent") is False


def test_extract_title_from_h1():
    md = "# My Report\n\nContent here."
    assert _extract_title(md, "fallback") == "My Report"


def test_extract_title_fallback():
    md = "No heading here."
    assert _extract_title(md, "fallback") == "fallback"


@pytest.mark.asyncio
async def test_generate_saves_report(svc, tmp_path, monkeypatch):
    monkeypatch.setattr("max_engine.skills.reports._REPORTS_DIR", tmp_path)

    class FakeProvider:
        async def chat(self, model, messages, **kw):
            yield type("C", (), {"text": "# My Report\n\nGreat content.", "done": False})()
            yield type("C", (), {"text": "", "done": True})()

    chunks = []
    async for chunk in svc.generate_stream("My Report", "Write a report", FakeProvider(), "m"):
        chunks.append(chunk)

    full = "".join(c for c in chunks if not c.startswith("<!-- report_id:"))
    assert "My Report" in full

    reports = svc.list_reports()
    assert len(reports) == 1
    assert reports[0]["title"] == "My Report"


@pytest.mark.asyncio
async def test_delete_report(svc, tmp_path, monkeypatch):
    monkeypatch.setattr("max_engine.skills.reports._REPORTS_DIR", tmp_path)

    class FakeProvider:
        async def chat(self, model, messages, **kw):
            yield type("C", (), {"text": "Content.", "done": False})()
            yield type("C", (), {"text": "", "done": True})()

    async for _ in svc.generate_stream("T", "I", FakeProvider(), "m"):
        pass

    reports = svc.list_reports()
    assert len(reports) == 1
    rid = reports[0]["id"]
    assert svc.delete_report(rid) is True
    assert svc.list_reports() == []
    assert svc.get_report(rid) is None
