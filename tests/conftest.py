from __future__ import annotations

import hashlib
import re
from pathlib import Path

import numpy as np
import pytest

from paper_rag.config import Settings
from paper_rag.ingest.kg_extract import Entity, Extraction, PaperMeta, Relation

DIM = 64


class FakeEmbedder:
    """Deterministic bag-of-words hashing embedder: shared words → similar vectors."""

    released = 0

    def _vec(self, text: str) -> np.ndarray:
        v = np.zeros(DIM, dtype=np.float32)
        for word in re.findall(r"[a-z0-9]+", text.lower()):
            v[int(hashlib.md5(word.encode()).hexdigest(), 16) % DIM] += 1.0
        n = np.linalg.norm(v)
        return v / n if n else v

    def encode_documents(self, texts: list[str]) -> np.ndarray:
        return np.vstack([self._vec(t) for t in texts]) if texts else np.zeros((0, DIM), dtype=np.float32)

    def encode_query(self, text: str) -> np.ndarray:
        return self._vec(text)

    def release(self) -> None:
        FakeEmbedder.released += 1


def extraction(title: str, entities: list[tuple[str, str, list[str]]], relations: list[tuple[str, str, str]],
               references: list[str] | None = None, year: int = 2020) -> Extraction:
    return Extraction(
        paper=PaperMeta(title=title, authors=["A. Author"], year=year, venue=None, doi=None,
                        abstract=f"Abstract of {title}.", summary=f"Summary of {title}."),
        entities=[Entity(name=n, type=t, description=f"{n} description", aliases=a) for n, t, a in entities],
        relations=[Relation(source=s, target=t, type=r, evidence=f"{s} {r} {t}", page=1) for s, r, t in relations],
        references=references or [],
    )


class StubExtractor:
    """Returns canned extractions keyed by paper id; records the known-entity lists it was given."""

    def __init__(self, by_paper: dict[str, Extraction]):
        self.by_paper = by_paper
        self.calls: list[tuple[str, dict]] = []

    def extract(self, doc, known_entities):
        self.calls.append((doc.paper_id, known_entities))
        return self.by_paper.get(doc.paper_id) or extraction(doc.title_hint, [], [])


def make_pdf(path: Path, pages: list[str]) -> Path:
    import pymupdf

    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page()
        page.insert_textbox(pymupdf.Rect(50, 50, 550, 800), text, fontsize=10)
    doc.save(path)
    doc.close()
    return path


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    return Settings(corpus_dir=corpus, data_dir=tmp_path / "data", frontend_dist=tmp_path / "dist",
                    chunk_size=400, chunk_overlap=50)


@pytest.fixture
def embedder() -> FakeEmbedder:
    return FakeEmbedder()

