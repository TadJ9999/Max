"""Tests for Aegis event store."""

import os
import tempfile

import pytest

from max_engine.aegis.store import AegisStore


@pytest.fixture
def store(tmp_path):
    path = str(tmp_path / "test.db")
    return AegisStore(path)


def test_ingest_creates_event(store):
    eid = store.ingest({
        "source": "engine",
        "severity": "High",
        "kind": "ValueError",
        "message": "list index out of range",
    })
    assert eid
    events = store.list_events()
    assert len(events) == 1
    assert events[0]["kind"] == "ValueError"
    assert events[0]["source"] == "engine"
    assert events[0]["count"] == 1


def test_ingest_deduplicates_by_fingerprint(store):
    store.ingest({"source": "engine", "severity": "High", "kind": "TypeError", "message": "bad type"})
    store.ingest({"source": "engine", "severity": "High", "kind": "TypeError", "message": "bad type"})
    events = store.list_events()
    assert len(events) == 1
    assert events[0]["count"] == 2


def test_ingest_different_kinds_not_deduped(store):
    store.ingest({"source": "engine", "severity": "Medium", "kind": "ValueError", "message": "v"})
    store.ingest({"source": "engine", "severity": "Medium", "kind": "KeyError", "message": "k"})
    events = store.list_events()
    assert len(events) == 2


def test_get_event_by_id(store):
    eid = store.ingest({"source": "frontend", "severity": "Low", "kind": "TypeError", "message": "t"})
    event = store.get_event(eid)
    assert event is not None
    assert event["id"] == eid
    assert event["source"] == "frontend"


def test_get_event_missing(store):
    assert store.get_event("nonexistent-id") is None


def test_list_events_limit(store):
    for i in range(5):
        store.ingest({"source": "engine", "severity": "Low", "kind": f"Error{i}", "message": f"msg{i}"})
    events = store.list_events(limit=3)
    assert len(events) == 3


def test_append_and_list_log(store):
    lid = store.append_log({
        "event_id": "evt1",
        "status": "proposed",
        "severity": "High",
        "symptom": "crash on startup",
        "root_cause": "missing env var",
        "provider": "claude/claude-sonnet-4-6",
    })
    assert lid
    log = store.list_log()
    assert len(log) == 1
    assert log[0]["status"] == "proposed"


def test_update_log_status(store):
    lid = store.append_log({"event_id": "e", "status": "proposed"})
    store.update_log_status(lid, "verified", "pytest passed")
    log = store.list_log()
    assert log[0]["status"] == "verified"
    assert log[0]["verification"] == "pytest passed"


def test_fingerprint_stability():
    fp1 = AegisStore.fingerprint("ValueError", "engine", "test message")
    fp2 = AegisStore.fingerprint("ValueError", "engine", "test message")
    assert fp1 == fp2


def test_fingerprint_differs_by_kind():
    fp1 = AegisStore.fingerprint("ValueError", "engine", "msg")
    fp2 = AegisStore.fingerprint("TypeError", "engine", "msg")
    assert fp1 != fp2


def test_context_stored_as_dict(store):
    store.ingest({
        "source": "engine",
        "severity": "Medium",
        "kind": "RuntimeError",
        "message": "oops",
        "context": {"path": "/api/test", "session_id": "s1"},
    })
    events = store.list_events()
    assert isinstance(events[0]["context"], dict)
    assert events[0]["context"]["path"] == "/api/test"
