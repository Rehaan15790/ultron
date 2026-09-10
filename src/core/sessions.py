"""Per-session conversation state.

HistoryManager used to be a module-level singleton, so the CLI, and every
browser tab, and every HTTP request all appended to one conversation. Two tabs
talked into the same history and saw each other's turns.

Sessions are held in memory only: conversation does not survive a restart,
while stored memories (SQLite) do. That asymmetry is deliberate - facts are
durable, chatter is not.
"""
import threading
import time
from collections import OrderedDict

from src.core.history import HistoryManager


class SessionStore:
    """LRU + TTL map of session id -> HistoryManager. Thread-safe."""

    def __init__(self, system_prompt: str, max_sessions: int = 50, ttl_seconds: int = 3600):
        self._system_prompt = system_prompt
        self._max_sessions = max_sessions
        self._ttl = ttl_seconds
        self._sessions: OrderedDict[str, tuple[HistoryManager, float]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, session_id: str) -> HistoryManager:
        key = session_id or "default"
        now = time.time()
        with self._lock:
            self._evict(now)
            entry = self._sessions.get(key)
            if entry is None:
                history = HistoryManager(self._system_prompt)
            else:
                history = entry[0]
            self._sessions[key] = (history, now)
            self._sessions.move_to_end(key)
            while len(self._sessions) > self._max_sessions:
                self._sessions.popitem(last=False)
            return history

    def _evict(self, now: float) -> None:
        expired = [k for k, (_, seen) in self._sessions.items() if now - seen > self._ttl]
        for key in expired:
            del self._sessions[key]

    def clear(self, session_id: str | None = None) -> None:
        with self._lock:
            if session_id is None:
                self._sessions.clear()
            else:
                self._sessions.pop(session_id, None)

    def __len__(self) -> int:
        with self._lock:
            return len(self._sessions)
