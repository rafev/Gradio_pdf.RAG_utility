"""Persistent Chroma collection of paper chunks. Embeddings are computed by us, not Chroma."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from paper_rag.ingest.chunking import Chunk

COLLECTION = "paper_chunks"
_UPSERT_BATCH = 1000


@dataclass(frozen=True)
class Hit:
    chunk_id: str
    paper_id: str
    page: int
    section: str
    text: str
    score: float  # cosine similarity, higher is better


class VectorStore:
    def __init__(self, path: Path):
        import chromadb

        path.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(path))
        self._collection = self._open()

    def _open(self):
        return self._client.get_or_create_collection(
            COLLECTION, configuration={"hnsw": {"space": "cosine"}}, embedding_function=None
        )

    def reset(self) -> None:
        if COLLECTION in [c.name for c in self._client.list_collections()]:
            self._client.delete_collection(COLLECTION)
        self._collection = self._open()

    def count(self) -> int:
        return self._collection.count()

    def add(self, chunks: list[Chunk], embeddings: np.ndarray) -> None:
        for start in range(0, len(chunks), _UPSERT_BATCH):
            batch = chunks[start : start + _UPSERT_BATCH]
            self._collection.upsert(
                ids=[c.id for c in batch],
                embeddings=embeddings[start : start + len(batch)].tolist(),
                documents=[c.text for c in batch],
                metadatas=[
                    {"paper_id": c.paper_id, "page": c.page, "section": c.section, "chunk_n": c.chunk_n}
                    for c in batch
                ],
            )

    def delete_paper(self, paper_id: str) -> None:
        self._collection.delete(where={"paper_id": paper_id})

    def query(self, embedding: np.ndarray, k: int = 8, paper_ids: list[str] | None = None) -> list[Hit]:
        if self.count() == 0:
            return []
        where = None
        if paper_ids:
            where = {"paper_id": paper_ids[0]} if len(paper_ids) == 1 else {"paper_id": {"$in": paper_ids}}
        res = self._collection.query(
            query_embeddings=[embedding.tolist()],
            n_results=k,
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        hits = []
        for cid, doc, meta, dist in zip(res["ids"][0], res["documents"][0], res["metadatas"][0], res["distances"][0]):
            hits.append(Hit(cid, str(meta["paper_id"]), int(meta["page"]), str(meta.get("section", "")), doc,
                            1.0 - float(dist)))
        return hits

    def get(self, chunk_ids: list[str]) -> list[Hit]:
        res = self._collection.get(ids=chunk_ids, include=["documents", "metadatas"])
        by_id = {
            cid: Hit(cid, str(m["paper_id"]), int(m["page"]), str(m.get("section", "")), d, 1.0)
            for cid, d, m in zip(res["ids"], res["documents"], res["metadatas"])
        }
        return [by_id[c] for c in chunk_ids if c in by_id]

    def page_passages(self, paper_id: str, page: int, limit: int = 3) -> list[Hit]:
        res = self._collection.get(
            where={"$and": [{"paper_id": paper_id}, {"page": page}]}, include=["documents", "metadatas"], limit=limit
        )
        hits = [
            Hit(cid, str(m["paper_id"]), int(m["page"]), str(m.get("section", "")), d, 1.0)
            for cid, d, m in zip(res["ids"], res["documents"], res["metadatas"])
        ]
        return sorted(hits, key=lambda h: int(h.chunk_id.rsplit(":", 1)[1]))
