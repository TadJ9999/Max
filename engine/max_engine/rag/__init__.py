"""Codebase RAG — index the workspace and retrieve context for grounded answers."""

from .chunker import Chunk, chunk_text, gather_files
from .memory import SessionMemory
from .service import RagService, format_context
from .store import RagStore

__all__ = [
    "Chunk",
    "RagService",
    "RagStore",
    "SessionMemory",
    "chunk_text",
    "format_context",
    "gather_files",
]
