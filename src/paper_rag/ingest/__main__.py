"""CLI: build or update the vector store and knowledge graph from corpus/papers/*.pdf."""

from __future__ import annotations

import argparse
import logging
import sys

from paper_rag.config import get_settings
from paper_rag.ingest.embed import SentenceTransformerEmbedder
from paper_rag.ingest.kg_extract import ClaudeExtractor
from paper_rag.ingest.pipeline import ingest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m paper_rag.ingest", description=__doc__)
    parser.add_argument("--rebuild", action="store_true", help="discard existing data/ and re-ingest everything")
    parser.add_argument("--prune", action="store_true", help="remove papers whose PDF was deleted from the corpus")
    parser.add_argument("--only", metavar="FILE", help="(re)ingest a single PDF by filename or stem")
    parser.add_argument("--no-kg", action="store_true", help="skip Claude KG extraction (vector index only)")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S")
    for noisy in ("httpx", "httpx2", "httpcore", "chromadb", "sentence_transformers", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    settings = get_settings()
    if not settings.corpus_dir.exists():
        print(f"Corpus directory {settings.corpus_dir} does not exist. Put PDFs there first.", file=sys.stderr)
        return 1

    embedder = SentenceTransformerEmbedder(settings.embed_model, settings.embed_device, settings.embed_batch_size,
                                           settings.embed_max_seq_length)
    extractor = None if args.no_kg else ClaudeExtractor(settings.extract_model)
    report = ingest(settings, embedder, extractor, rebuild=args.rebuild, prune=args.prune, only=args.only)

    print(f"\nadded={len(report.added)} updated={len(report.updated)} skipped={len(report.skipped)} "
          f"pruned={len(report.pruned)} failed={len(report.failed)}")
    for pid, err in report.failed.items():
        print(f"  FAILED {pid}: {err}")
    if report.kg_missing:
        print(f"  Text-only (no KG): {', '.join(report.kg_missing)}. Re-run without --no-kg to extract.")
    return 1 if report.failed else 0


if __name__ == "__main__":
    sys.exit(main())
