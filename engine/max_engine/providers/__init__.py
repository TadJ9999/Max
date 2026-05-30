"""Provider adapters — local (Ollama) and cloud (Claude), behind one interface."""

from .base import ChatChunk, Provider

__all__ = ["Provider", "ChatChunk"]
