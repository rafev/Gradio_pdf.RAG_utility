"""VRAM-aware sentence-transformers wrapper.

Sized for an 8 GB GPU: fp16 on CUDA, capped sequence length, bounded batches that halve on
OOM (falling back to CPU as a last resort), and an explicit `release()` to free VRAM.
"""

from __future__ import annotations

import logging
import threading
from typing import Protocol

import numpy as np

log = logging.getLogger(__name__)

_BGE_EN_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


class Embedder(Protocol):
    def encode_documents(self, texts: list[str]) -> np.ndarray: ...
    def encode_query(self, text: str) -> np.ndarray: ...
    def release(self) -> None: ...


def query_prefix_for(model_name: str) -> str:
    name = model_name.lower()
    return _BGE_EN_QUERY_PREFIX if "bge-" in name and "-en" in name else ""


class SentenceTransformerEmbedder:
    def __init__(self, model_name: str, device: str = "auto", batch_size: int = 32, max_seq_length: int = 512):
        self.model_name = model_name
        self.requested_device = device
        self.batch_size = batch_size
        self.max_seq_length = max_seq_length
        self.query_prefix = query_prefix_for(model_name)
        self._model = None
        self._device: str | None = None
        self._lock = threading.Lock()

    @property
    def device(self) -> str:
        if self._device is None:
            import torch

            want = self.requested_device
            self._device = "cuda" if want in ("auto", "cuda") and torch.cuda.is_available() else "cpu"
        return self._device

    def _load(self, device: str | None = None):
        with self._lock:
            if self._model is not None and (device is None or device == self._device):
                return self._model
            import torch
            from sentence_transformers import SentenceTransformer

            if device:
                self._device = device
            kwargs = {"model_kwargs": {"torch_dtype": torch.float16}} if self.device == "cuda" else {}
            log.info("Loading embedder %s on %s", self.model_name, self.device)
            model = SentenceTransformer(self.model_name, device=self.device, **kwargs)
            model.max_seq_length = min(model.max_seq_length or self.max_seq_length, self.max_seq_length)
            self._model = model
            return model

    def _encode(self, texts: list[str], show_progress: bool) -> np.ndarray:
        import torch

        model = self._load()
        out: list[np.ndarray] = []
        batch = self.batch_size
        i = 0
        while i < len(texts):
            chunk = texts[i : i + batch]
            try:
                emb = model.encode(chunk, batch_size=batch, normalize_embeddings=True, convert_to_numpy=True,
                                   show_progress_bar=False)
            except torch.cuda.OutOfMemoryError:
                torch.cuda.empty_cache()
                if batch > 1:
                    batch = max(1, batch // 2)
                    log.warning("CUDA OOM while embedding; retrying with batch size %d", batch)
                    continue
                log.warning("CUDA OOM at batch size 1; falling back to CPU")
                model = self._load(device="cpu")
                continue
            out.append(emb.astype(np.float32))
            i += len(chunk)
            if show_progress:
                log.info("Embedded %d/%d chunks", i, len(texts))
        get_dim = getattr(model, "get_embedding_dimension", None) or model.get_sentence_embedding_dimension
        dim = get_dim() or 0
        return np.vstack(out) if out else np.zeros((0, dim), dtype=np.float32)

    def encode_documents(self, texts: list[str]) -> np.ndarray:
        return self._encode(texts, show_progress=len(texts) > self.batch_size * 4)

    def encode_query(self, text: str) -> np.ndarray:
        return self._encode([self.query_prefix + text], show_progress=False)[0]

    def release(self) -> None:
        with self._lock:
            if self._model is None:
                return
            self._model = None
            if self._device == "cuda":
                import torch

                torch.cuda.empty_cache()


class Reranker:
    """Optional cross-encoder reranker (≈0.6 GB fp16 for bge-reranker-base)."""

    def __init__(self, model_name: str, device: str = "auto"):
        self.model_name = model_name
        self.requested_device = device
        self._model = None
        self._lock = threading.Lock()

    def _load(self):
        with self._lock:
            if self._model is None:
                import torch
                from sentence_transformers import CrossEncoder

                cuda = self.requested_device in ("auto", "cuda") and torch.cuda.is_available()
                kwargs = {"model_kwargs": {"torch_dtype": torch.float16}} if cuda else {}
                self._model = CrossEncoder(self.model_name, device="cuda" if cuda else "cpu", max_length=512, **kwargs)
            return self._model

    def scores(self, query: str, passages: list[str]) -> list[float]:
        if not passages:
            return []
        return [float(s) for s in self._load().predict([(query, p) for p in passages], batch_size=16)]
