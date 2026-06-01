"""Tests for capability registry and intent router."""

import asyncio

import pytest

from max_engine.capabilities.registry import CapabilityRegistry
from max_engine.capabilities.router import classify_intent
from max_engine.capabilities.interface import Capability


class _DummyCapability(Capability):
    name = "dummy"
    description = "A test capability"
    domains = ["test_domain"]

    async def invoke(self, query, context=None):
        yield "result"


# ---- Registry ----------------------------------------------------------------

def test_registry_singleton():
    r1 = CapabilityRegistry.get()
    r2 = CapabilityRegistry.get()
    assert r1 is r2


def test_register_and_get():
    registry = CapabilityRegistry()
    cap = _DummyCapability()
    registry.register(cap)
    assert registry.get_capability("dummy") is cap


def test_find_for_domain():
    registry = CapabilityRegistry()
    cap = _DummyCapability()
    registry.register(cap)
    found = registry.find_for_domain("test_domain")
    assert found is cap


def test_find_for_unknown_domain():
    registry = CapabilityRegistry()
    assert registry.find_for_domain("nonexistent") is None


def test_list_capabilities():
    registry = CapabilityRegistry()
    cap = _DummyCapability()
    registry.register(cap)
    caps = registry.list_capabilities()
    assert len(caps) >= 1
    names = [c["name"] for c in caps]
    assert "dummy" in names


# ---- Intent router -----------------------------------------------------------

@pytest.mark.asyncio
async def test_classify_intent_web_search():
    class FakeProvider:
        async def chat(self, model, messages, **kw):
            yield type("C", (), {"text": "web_search", "done": False})()
            yield type("C", (), {"text": "", "done": True})()

    domain = await classify_intent("What is the capital of France?", FakeProvider(), "m")
    assert domain == "web_search"


@pytest.mark.asyncio
async def test_classify_intent_spotify():
    class FakeProvider:
        async def chat(self, model, messages, **kw):
            yield type("C", (), {"text": "spotify", "done": False})()
            yield type("C", (), {"text": "", "done": True})()

    domain = await classify_intent("Play some jazz music", FakeProvider(), "m")
    assert domain == "spotify"


@pytest.mark.asyncio
async def test_classify_intent_fallback_on_error():
    class BrokenProvider:
        async def chat(self, model, messages, **kw):
            raise RuntimeError("connection refused")
            yield  # make it an async generator

    domain = await classify_intent("anything", BrokenProvider(), "m")
    assert domain == "chat"


@pytest.mark.asyncio
async def test_classify_intent_normalises_partial():
    class FakeProvider:
        async def chat(self, model, messages, **kw):
            yield type("C", (), {"text": "web", "done": False})()
            yield type("C", (), {"text": "", "done": True})()

    domain = await classify_intent("search the web for X", FakeProvider(), "m")
    assert domain == "web_search"


@pytest.mark.asyncio
async def test_classify_intent_unknown_falls_back_to_chat():
    class FakeProvider:
        async def chat(self, model, messages, **kw):
            yield type("C", (), {"text": "blabla", "done": True})()

    domain = await classify_intent("?", FakeProvider(), "m")
    assert domain == "chat"
