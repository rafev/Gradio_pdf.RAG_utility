"""Process-wide state shared by the public and admin apps."""

from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass, field

from paper_rag.agent.agent import Agent
from paper_rag.agent.tools import ToolBox
from paper_rag.api.access import AccessManager
from paper_rag.config import Settings
from paper_rag.graph.store import KnowledgeGraph
from paper_rag.ingest.embed import Reranker, SentenceTransformerEmbedder
from paper_rag.ingest.vectorstore import VectorStore

log = logging.getLogger(__name__)


@dataclass
class AppState:
    settings: Settings
    kg: KnowledgeGraph
    vs: VectorStore
    toolbox: ToolBox
    agent: Agent
    access: AccessManager | None  # None in local mode (no gate)
    semaphore: asyncio.Semaphore
    active_sessions: set[str] = field(default_factory=set)
    _graph_mtime: float = 0.0
    _reload_lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def gated(self) -> bool:
        return self.access is not None

    def refresh_graph(self) -> KnowledgeGraph:
        """Pick up a graph.json rewritten by a concurrent `ingest` run."""
        path = self.settings.graph_path
        try:
            mtime = path.stat().st_mtime
        except FileNotFoundError:
            return self.kg
        if mtime != self._graph_mtime:
            with self._reload_lock:
                if mtime != self._graph_mtime:
                    self.kg = KnowledgeGraph.load(path)
                    self.toolbox.kg = self.kg
                    self._graph_mtime = mtime
                    log.info("Loaded knowledge graph: %s", self.kg.stats())
        return self.kg


def build_state(settings: Settings, public: bool) -> AppState:
    kg = KnowledgeGraph.load(settings.graph_path)
    vs = VectorStore(settings.chroma_dir)
    embedder = SentenceTransformerEmbedder(settings.embed_model, settings.embed_device, settings.embed_batch_size,
                                           settings.embed_max_seq_length)
    reranker = Reranker(settings.rerank_model, settings.embed_device) if settings.rerank else None
    toolbox = ToolBox(kg, vs, embedder, reranker)
    access = AccessManager(settings.access_db_path, settings.session_hours, settings.session_question_quota) if public else None
    state = AppState(settings, kg, vs, toolbox, Agent(settings, toolbox), access,
                     asyncio.Semaphore(settings.max_concurrent_chats))
    state.refresh_graph()
    return state
