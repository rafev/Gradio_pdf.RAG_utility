# Corpus

Put the paper PDFs in `corpus/papers/`, then build or update the index:

```bash
uv run python -m paper_rag.ingest
```

- The filename becomes the paper id used in citations. `Attention Is All You Need.pdf` becomes `attention-is-all-you-need`, so short, descriptive filenames work best.
- Ingest is incremental. Unchanged files are skipped, and a changed file is re-indexed. `--prune` removes papers whose PDF was deleted. `--rebuild` starts from scratch.
- PDFs need a text layer. Scanned papers must be OCR'd first.
- `*.pdf` files here are gitignored by default, because papers often can't be redistributed. Remove that line from `.gitignore` to version the corpus.
