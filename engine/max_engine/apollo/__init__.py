"""Apollo — prediction engine.

Aggregates the highest-signal OSINT news and the live market into AI-written
reports and forward-looking predictions, with a local sqlite-vec memory: Ingest
embeds the high-signal items (Ollama ``nomic-embed-text``) and writes them to a
24h-TTL store; predictions recall related memories. All local; nothing leaves the
machine beyond the existing OSINT/Market egress.
"""

from __future__ import annotations

from .service import ApolloService
from .store import VectorStore

__all__ = ["ApolloService", "VectorStore"]
