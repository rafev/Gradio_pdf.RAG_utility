"""PDF loading with per-page text, basic metadata, and a content hash for change detection."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class PdfDocument:
    paper_id: str
    path: Path
    sha256: str
    pages: list[str]  # index 0 == page 1
    metadata: dict[str, str] = field(default_factory=dict)

    @property
    def title_hint(self) -> str:
        return (self.metadata.get("title") or "").strip() or self.path.stem

    def text_with_page_markers(self) -> str:
        """Full text with `[page N]` markers, used for KG extraction so evidence can cite pages."""
        return "\n\n".join(f"[page {i}]\n{text}" for i, text in enumerate(self.pages, start=1))


def slugify(name: str) -> str:
    """Filename stem → stable, citation-friendly paper id (e.g. 'Attention Is All You Need' → 'attention-is-all-you-need')."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")
    return slug[:80] or "paper"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load_pdf(path: Path, paper_id: str | None = None) -> PdfDocument:
    import pymupdf

    with pymupdf.open(path) as doc:
        pages = [page.get_text("text") for page in doc]
        metadata = {k: v for k, v in (doc.metadata or {}).items() if isinstance(v, str) and v}
    return PdfDocument(
        paper_id=paper_id or slugify(path.stem),
        path=path,
        sha256=file_sha256(path),
        pages=pages,
        metadata=metadata,
    )
