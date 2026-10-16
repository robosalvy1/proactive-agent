"""Built-in Home recall, alongside native notes and the selected external provider."""
from __future__ import annotations

import logging
import re
import sqlite3

from agent.memory_provider import MemoryProvider, RecallStatus
from agent.runtime_session_store import RuntimeSessionStore
from websockets.exceptions import WebSocketException
from hermes_state_home import HomeStore
from hermes_state_home_context import home_context_on

logger = logging.getLogger(__name__)
_OVERVIEW = re.compile(r"\b(overview|attention|progress|updates|catch me up)\b|working on|where are we", re.IGNORECASE)


class HomeMemoryProvider(MemoryProvider):
    """Read authorized Home evidence and already-completed reflection notes."""

    name = "builtin"

    def __init__(self, db, warning_callback=None, runtime_identity=None):
        self.db = db
        self.runtime_identity = runtime_identity
        self._author_id = None
        self._author_is_bot = False
        self.warning_callback = warning_callback
        self._last_count = 0
        self._warned = False

    def is_available(self) -> bool:
        return True

    def initialize(self, session_id: str, **kwargs) -> None:
        pass

    def get_tool_schemas(self) -> list[dict]:
        return []

    def on_turn_start(self, turn_number: int, message: str, **kwargs) -> None:
        self._author_id = kwargs.get('author_id')
        self._author_is_bot = bool(kwargs.get('author_is_bot'))

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        self._last_count = 0
        try:
            if isinstance(self.db, RuntimeSessionStore):
                packet = self.db.home_recall(session_id, query, overview=bool(_OVERVIEW.search(query)))
                self._last_count = packet["count"]
                return packet["context"]
            row = self.db.get_session(session_id)
            from hermes_state_home import PERSONAL_SOURCES
            from hermes_state_home_links import link_on, recall_principal_on
            with self.db._read_ctx() as conn:
                initial = HomeStore(self.db)
                if row and row['source'] not in PERSONAL_SOURCES:
                    grant = link_on(initial, conn, session_id)
                    if not grant or not self._matches_runtime(grant['identity']):
                        return ''
                principal = recall_principal_on(initial, conn, session_id)
            store = HomeStore(self.db, principal_id=principal)
            status = store.status()
            overview = status["session_id"] == session_id and bool(_OVERVIEW.search(query))
            from hermes_state_home_semantic import prepare_semantic_query
            plan = None if overview else prepare_semantic_query(self.db, session_id, query, principal_id=principal)
            with self.db._read_ctx() as conn:
                fresh = conn.execute('SELECT * FROM sessions WHERE id=?', (session_id,)).fetchone()
                if fresh is None:
                    return ''
                if fresh['source'] not in PERSONAL_SOURCES:
                    grant = link_on(store, conn, session_id)
                    if (not grant or grant['principal_id'] != principal
                            or not self._matches_runtime(grant['identity'])):
                        return ''
                packet = home_context_on(self.db, conn, store.principal_id, session_id, query,
                                         overview=overview, semantic_plan=plan)
            self._last_count = packet['count']
            return packet['context']
        except (sqlite3.Error, ValueError, RuntimeError, OSError, WebSocketException) as exc:
            logger.warning("Home recall unavailable: %s", exc)
            if not self._warned and self.warning_callback:
                self.warning_callback("Home recall is unavailable; this chat can continue without it.")
                self._warned = True
            return ""

    def _matches_runtime(self, identity: dict) -> bool:
        if self.runtime_identity is None or self._author_is_bot:
            return False
        if self._author_id is not None and self._author_id != identity['user_id']:
            return False
        return self.runtime_identity == identity

    def recall_status(self) -> RecallStatus | None:
        return RecallStatus(provider_label="Home", count=self._last_count) if self._last_count else None


def attach_home_memory(agent, *, skip_memory: bool, platform: str | None) -> None:
    """Personal harnesses recall locally or through their assigned owner's read operation."""
    from hermes_state import SessionDB

    db = getattr(agent, "_session_db", None)
    from hermes_state_home import PERSONAL_SOURCES
    from hermes_state_home_links import private_platform

    local = platform is None or platform in PERSONAL_SOURCES
    private_dm = (private_platform(platform or '') and getattr(agent, '_chat_type', None) == 'dm'
                  and bool(getattr(agent, '_user_id', None)) and bool(getattr(agent, '_chat_id', None)))
    if skip_memory or not (local or private_dm) or not isinstance(db, (SessionDB, RuntimeSessionStore)):
        return
    from agent.memory_manager import MemoryManager

    manager = agent._memory_manager
    if manager is None:
        manager = agent._memory_manager = MemoryManager()
    if manager.get_provider("builtin") is None:
        identity = None
        if platform not in (None, 'cli', 'tui', 'gui', 'desktop', 'dashboard', 'local'):
            identity = {'source': platform, 'user_id': getattr(agent, '_user_id', None),
                        'chat_id': getattr(agent, '_chat_id', None), 'thread_id': getattr(agent, '_thread_id', None),
                        'session_key': getattr(agent, '_gateway_session_key', None)}
        manager.add_provider(HomeMemoryProvider(db, warning_callback=agent._emit_warning, runtime_identity=identity))


def bind_home_source(agent, source, session_key: str) -> None:
    """Bind the authenticated current gateway source, including its receiving bot."""
    manager = getattr(agent, '_memory_manager', None)
    if manager is None:
        return
    provider = manager.get_provider('builtin')
    if not isinstance(provider, HomeMemoryProvider):
        return
    from gateway.session_identity import transport_profile_of
    from hermes_state_home_links import private_platform

    platform = source.platform.value
    if not private_platform(platform) or source.chat_type != 'dm' or getattr(source, 'is_bot', False):
        provider.runtime_identity = None
        return
    provider.runtime_identity = {
        'source': platform, 'user_id': source.user_id, 'chat_id': source.chat_id,
        'thread_id': source.thread_id or None, 'transport_profile': transport_profile_of(source),
        'session_key': session_key, 'scope_id': source.scope_id or source.guild_id or None,
        'profile': source.profile or None,
    }
