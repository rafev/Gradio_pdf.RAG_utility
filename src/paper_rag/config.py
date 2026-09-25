"""Runtime settings, read from environment variables and a `.env` file.

The `.env` file is looked up next to the active virtualenv first (so a venv kept outside
the repo, e.g. `C:\\project_envs\\Paper_Atlas\\.venv`, brings its own secrets), then at the
repo root.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]


def _env(name: str, default: str) -> str:
    return os.getenv(name, default).strip()


def _env_bool(name: str, default: bool) -> bool:
    return _env(name, str(default)).lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    return int(_env(name, str(default)))


def _env_file() -> Path:
    """`.env` beside the active venv if there is one, else the repo root's."""
    if sys.prefix != sys.base_prefix:
        beside_venv = Path(sys.prefix).parent / ".env"
        if beside_venv.is_file():
            return beside_venv
    return REPO_ROOT / ".env"


def _env_path(name: str, default: Path) -> Path:
    value = os.getenv(name)
    path = Path(value) if value else default
    return path if path.is_absolute() else REPO_ROOT / path


@dataclass(frozen=True)
class Settings:
    # Claude
    agent_model: str = "claude-opus-5"
    extract_model: str = "claude-opus-5"
    agent_effort: str = "high"
    agent_max_tool_rounds: int = 12
    enable_fallbacks: bool = True

    # Embeddings (sized for an 8 GB GPU)
    embed_model: str = "BAAI/bge-base-en-v1.5"
    embed_device: str = "auto"  # auto | cuda | cpu
    embed_batch_size: int = 32
    embed_max_seq_length: int = 512
    rerank: bool = False
    rerank_model: str = "BAAI/bge-reranker-base"

    # Chunking
    chunk_size: int = 1000
    chunk_overlap: int = 150

    # Paths
    corpus_dir: Path = field(default_factory=lambda: REPO_ROOT / "corpus" / "papers")
    data_dir: Path = field(default_factory=lambda: REPO_ROOT / "data")
    frontend_dist: Path = field(default_factory=lambda: REPO_ROOT / "frontend" / "dist")

    # Serving
    host: str = "127.0.0.1"
    port: int = 8000
    admin_port: int = 8001
    max_concurrent_chats: int = 2
    session_hours: int = 24
    session_question_quota: int = 30

    @property
    def chroma_dir(self) -> Path:
        return self.data_dir / "chroma"

    @property
    def graph_path(self) -> Path:
        return self.data_dir / "graph.json"

    @property
    def manifest_path(self) -> Path:
        return self.data_dir / "manifest.json"

    @property
    def extractions_dir(self) -> Path:
        """Claude KG extractions cached by PDF sha256, so re-ingesting unchanged content is free."""
        return self.data_dir / "extractions"

    @property
    def access_db_path(self) -> Path:
        return self.data_dir / "access.db"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    load_dotenv(_env_file())
    return Settings(
        agent_model=_env("AGENT_MODEL", Settings.agent_model),
        extract_model=_env("EXTRACT_MODEL", Settings.extract_model),
        agent_effort=_env("AGENT_EFFORT", Settings.agent_effort),
        agent_max_tool_rounds=_env_int("AGENT_MAX_TOOL_ROUNDS", Settings.agent_max_tool_rounds),
        enable_fallbacks=_env_bool("ENABLE_FALLBACKS", Settings.enable_fallbacks),
        embed_model=_env("EMBED_MODEL", Settings.embed_model),
        embed_device=_env("EMBED_DEVICE", Settings.embed_device),
        embed_batch_size=_env_int("EMBED_BATCH_SIZE", Settings.embed_batch_size),
        embed_max_seq_length=_env_int("EMBED_MAX_SEQ_LENGTH", Settings.embed_max_seq_length),
        rerank=_env_bool("RERANK", Settings.rerank),
        rerank_model=_env("RERANK_MODEL", Settings.rerank_model),
        chunk_size=_env_int("CHUNK_SIZE", Settings.chunk_size),
        chunk_overlap=_env_int("CHUNK_OVERLAP", Settings.chunk_overlap),
        corpus_dir=_env_path("CORPUS_DIR", REPO_ROOT / "corpus" / "papers"),
        data_dir=_env_path("DATA_DIR", REPO_ROOT / "data"),
        frontend_dist=_env_path("FRONTEND_DIST", REPO_ROOT / "frontend" / "dist"),
        host=_env("HOST", Settings.host),
        port=_env_int("PORT", Settings.port),
        admin_port=_env_int("ADMIN_PORT", Settings.admin_port),
        max_concurrent_chats=_env_int("MAX_CONCURRENT_CHATS", Settings.max_concurrent_chats),
        session_hours=_env_int("SESSION_HOURS", Settings.session_hours),
        session_question_quota=_env_int("SESSION_QUESTION_QUOTA", Settings.session_question_quota),
    )
