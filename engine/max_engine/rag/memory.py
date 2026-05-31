"""Session memory — short conversational history for grounded chat.

Keeps a rolling, capped list of turns per session id so follow-up questions have
continuity ("what about its error handling?" knows what "it" was). In-memory and
local; cleared on restart. Used by ``/rag/ask`` to (a) feed prior turns to the
model and (b) widen the retrieval query with the last user turns so retrieval
follows the conversation.
"""

from __future__ import annotations


class SessionMemory:
    def __init__(self, max_messages: int = 24) -> None:
        # max_messages caps stored entries (~max_messages/2 turns) per session.
        self.max_messages = max_messages
        self._by_session: dict[str, list[dict]] = {}

    def history(self, session_id: str) -> list[dict]:
        """Prior turns for a session ({role, content}), oldest first."""
        return list(self._by_session.get(session_id, []))

    def append(self, session_id: str, role: str, content: str) -> None:
        if not session_id or not content:
            return
        turns = self._by_session.setdefault(session_id, [])
        turns.append({"role": role, "content": content})
        if len(turns) > self.max_messages:
            del turns[: len(turns) - self.max_messages]  # keep the most recent

    def recent_user_text(self, session_id: str, n: int = 2) -> str:
        """The last ``n`` user messages joined — used to widen RAG retrieval so a
        terse follow-up still pulls the right code."""
        users = [t["content"] for t in self._by_session.get(session_id, []) if t["role"] == "user"]
        return "\n".join(users[-n:])

    def clear(self, session_id: str) -> None:
        self._by_session.pop(session_id, None)

    def stats(self) -> dict:
        return {
            "sessions": len(self._by_session),
            "messages": sum(len(v) for v in self._by_session.values()),
        }
