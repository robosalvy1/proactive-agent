"""Built-in Home recall, alongside native notes and the selected external provider."""
from __future__ import annotations

import logging
import re
import sqlite3

from agent.memory_provider import MemoryProvider, RecallStatus
from hermes_state_home import HomeStore
from hermes_state_home_context import home_context_on

logger = logging.getLogger(__name__)
_OVERVIEW = re.compile(r"\b(overview|attention|progress|updates|catch me up)\b|working on|where are we", re.IGNORECASE)


class HomeMemoryProvider(MemoryProvider):
    """Read Home evidence and already-completed reflection notes; never run a model here."""

    name = "builtin"

    def __init__(self, db, warning_callback=None):
        self.db = db
        self.warning_callback = warning_callback
        self._last_count = 0
        self._warned = False

    def is_available(self) -> bool:
        return True

    def initialize(self, session_id: str, **kwargs) -> None:
        pass

    def get_tool_schemas(self) -> list[dict]:
        return []

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        self._last_count = 0
        try:
            from agent.runtime_session_store import RuntimeSessionStore

            if isinstance(self.db, RuntimeSessionStore):
                packet = self.db.home_recall(session_id, query, overview=bool(_OVERVIEW.search(query)))
                self._last_count = packet["count"]
                return packet["context"]
            row = self.db.get_session(session_id)
            store = HomeStore(self.db, principal_id=row.get("user_id") if row else None)
            status = store.status()
            overview = status["session_id"] == session_id and bool(_OVERVIEW.search(query))
            with self.db._read_ctx() as conn:
                packet = home_context_on(self.db, conn, store.principal_id, session_id, query, overview=overview)
            self._last_count = packet['count']
            return packet['context']
        except (sqlite3.Error, ValueError) as exc:
            logger.warning("Home recall unavailable: %s", exc)
            if not self._warned and self.warning_callback:
                self.warning_callback("Home recall is unavailable; this chat can continue without it.")
                self._warned = True
            return ""

    def recall_status(self) -> RecallStatus | None:
        return RecallStatus(provider_label="Home", count=self._last_count) if self._last_count else None


def attach_home_memory(agent, *, skip_memory: bool, platform: str | None) -> None:
    """Personal harnesses recall locally or through their assigned owner's read operation."""
    from hermes_state import SessionDB
    from agent.runtime_session_store import RuntimeSessionStore

    db = getattr(agent, "_session_db", None)
    if (skip_memory or platform not in (None, "cli", "tui", "gui", "desktop", "dashboard", "local")
            or not isinstance(db, (SessionDB, RuntimeSessionStore))):
        return
    from agent.memory_manager import MemoryManager

    manager = agent._memory_manager
    if manager is None:
        manager = agent._memory_manager = MemoryManager()
    if manager.get_provider("builtin") is None:
        manager.add_provider(HomeMemoryProvider(db, warning_callback=agent._emit_warning))
