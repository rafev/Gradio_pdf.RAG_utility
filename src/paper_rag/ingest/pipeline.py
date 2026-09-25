"""Incremental corpus ingestion.

For each PDF in the corpus directory whose content hash changed since the last run:
  1. extract text per page,
  2. Claude extracts paper metadata + entities + relations (skipped with with_kg=False),
  3. chunk, embed (title/section-prefixed), and upsert into Chroma,
  4. merge into the knowledge graph.
State is saved after every paper so an interrupted run resumes where it stopped.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from paper_rag.config import Settings
from paper_rag.graph.store import KnowledgeGraph
from paper_rag.ingest.chunking import Chunk, chunk_pages
from paper_rag.ingest.embed import Embedder
from paper_rag.ingest.kg_extract import Extraction, ExtractionError, Extractor, PaperMeta
from paper_rag.ingest.pdf import PdfDocument, file_sha256, load_pdf, slugify
from paper_rag.ingest.vectorstore import VectorStore

log = logging.getLogger(__name__)


@dataclass
class IngestReport:
    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    pruned: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)
    kg_missing: list[str] = field(default_factory=list)


def load_manifest(path: Path) -> dict[str, dict]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def save_manifest(path: Path, manifest: dict[str, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def assign_paper_ids(pdfs: list[Path], manifest: dict[str, dict]) -> dict[Path, str]:
    """Slug of the filename; stable across runs; disambiguated when two files slugify the same."""
    by_file = {entry["file"]: pid for pid, entry in manifest.items()}
    ids: dict[Path, str] = {}
    taken: set[str] = set()
    for pdf in pdfs:
        pid = by_file.get(pdf.name)
        if pid is None:
            base = slugify(pdf.stem)
            pid, n = base, 2
            while pid in taken or (pid in manifest and manifest[pid]["file"] != pdf.name):
                pid, n = f"{base}-{n}", n + 1
        ids[pdf] = pid
        taken.add(pid)
    return ids


def fallback_extraction(doc: PdfDocument) -> Extraction:
    """Graph entry for a paper when KG extraction is disabled or failed: a lone paper node."""
    return Extraction(
        paper=PaperMeta(title=doc.title_hint, authors=[], year=None, venue=None, doi=None, abstract="", summary=""),
        entities=[], relations=[], references=[],
    )


def contextualize(chunk: Chunk, title: str) -> str:
    return f"{title} | {chunk.section}\n{chunk.text}"


def ingest(
    settings: Settings,
    embedder: Embedder,
    extractor: Extractor | None,
    *,
    rebuild: bool = False,
    prune: bool = False,
    only: str | None = None,
    vectorstore: VectorStore | None = None,
) -> IngestReport:
    report = IngestReport()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    vs = vectorstore or VectorStore(settings.chroma_dir)
    manifest = load_manifest(settings.manifest_path)
    kg = KnowledgeGraph.load(settings.graph_path)
    if rebuild:
        log.info("Rebuilding from scratch")
        vs.reset()
        kg = KnowledgeGraph()
        manifest = {}

    pdfs = sorted(p for p in settings.corpus_dir.glob("*.pdf") if p.is_file())
    if only:
        pdfs = [p for p in pdfs if p.name == only or p.stem == only]
        if not pdfs:
            raise FileNotFoundError(f"No PDF named {only!r} in {settings.corpus_dir}")
    ids = assign_paper_ids(pdfs, manifest)

    try:
        for pdf in pdfs:
            pid = ids[pdf]
            prev = manifest.get(pid)
            sha = file_sha256(pdf)
            if prev and prev["sha256"] == sha and (prev.get("kg") or extractor is None):
                report.skipped.append(pid)
                continue
            try:
                _ingest_one(pdf, pid, settings, embedder, extractor, vs, kg, manifest, report)
            except Exception as exc:  # keep going; one bad PDF shouldn't stop the corpus build
                log.exception("Failed to ingest %s", pdf.name)
                report.failed[pid] = f"{type(exc).__name__}: {exc}"
                continue
            (report.updated if prev else report.added).append(pid)
            kg.save(settings.graph_path)
            save_manifest(settings.manifest_path, manifest)

        if prune and not only:
            present = set(ids.values())
            for pid in [p for p in manifest if p not in present]:
                log.info("Pruning %s (file removed)", pid)
                vs.delete_paper(pid)
                kg.remove_paper(pid)
                del manifest[pid]
                report.pruned.append(pid)
            kg.save(settings.graph_path)
            save_manifest(settings.manifest_path, manifest)
    finally:
        embedder.release()
    return report


def _ingest_one(pdf, pid, settings, embedder, extractor, vs, kg, manifest, report) -> None:
    t0 = time.perf_counter()
    doc = load_pdf(pdf, paper_id=pid)
    if not any(page.strip() for page in doc.pages):
        raise ValueError("no extractable text (scanned PDF? run OCR first)")

    kg_ok = False
    extraction = fallback_extraction(doc)
    if extractor is not None:
        cache = settings.extractions_dir / f"{doc.sha256}.json"
        if cache.exists():
            # Same file content seen before (rename, --rebuild, re-chunking): no new Claude call.
            extraction = Extraction.model_validate_json(cache.read_text(encoding="utf-8"))
            kg_ok = True
            log.info("Reusing cached extraction for %s", pid)
        else:
            try:
                extraction = extractor.extract(doc, kg.entity_names_by_type())
                kg_ok = True
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_text(extraction.model_dump_json(indent=1), encoding="utf-8")
            except ExtractionError as exc:
                log.warning("%s — indexing text only", exc)
    if not kg_ok:
        report.kg_missing.append(pid)

    chunks = chunk_pages(pid, doc.pages, settings.chunk_size, settings.chunk_overlap)
    title = extraction.paper.title or doc.title_hint
    embeddings = embedder.encode_documents([contextualize(c, title) for c in chunks])
    vs.delete_paper(pid)
    vs.add(chunks, embeddings)

    kg.remove_paper(pid)
    kg.merge_paper(pid, extraction, source_file=pdf.name, n_chunks=len(chunks))
    manifest[pid] = {"file": pdf.name, "sha256": doc.sha256, "n_chunks": len(chunks), "kg": kg_ok,
                     "ingested_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    log.info("Ingested %s: %d pages, %d chunks, kg=%s (%.1fs)", pid, len(doc.pages), len(chunks), kg_ok,
             time.perf_counter() - t0)
