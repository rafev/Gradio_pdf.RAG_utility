from conftest import StubExtractor, extraction, make_pdf

from paper_rag.graph.store import KnowledgeGraph, paper_node
from paper_rag.ingest.pipeline import assign_paper_ids, ingest, load_manifest
from paper_rag.ingest.vectorstore import VectorStore

TEXT = ("Abstract\nWe study dense retrieval for question answering and propose a new retriever. " * 5,
        "1 Introduction\nRetrieval augmented generation combines a retriever with a generator. " * 5)


def test_incremental_ingest_skip_update_prune(settings, embedder):
    make_pdf(settings.corpus_dir / "Paper One.pdf", list(TEXT))
    make_pdf(settings.corpus_dir / "paper-two.pdf", ["Abstract\nA second paper about graph neural networks. " * 8])
    extractor = StubExtractor({
        "paper-one": extraction("Paper One", [("Dense Retrieval", "Method", [])], [("THIS_PAPER", "PROPOSES", "Dense Retrieval")]),
        "paper-two": extraction("Paper Two", [("Graph Neural Network", "Model", ["GNN"])], []),
    })
    vs = VectorStore(settings.chroma_dir)

    report = ingest(settings, embedder, extractor, vectorstore=vs)
    assert sorted(report.added) == ["paper-one", "paper-two"] and not report.failed
    assert vs.count() > 0
    kg = KnowledgeGraph.load(settings.graph_path)
    assert kg.g.nodes[paper_node("paper-one")]["label"] == "Paper One"
    # the second extraction call was told about entities from the first
    assert any("Dense Retrieval" in names for names in extractor.calls[1][1].values())

    report = ingest(settings, embedder, extractor, vectorstore=vs)
    assert sorted(report.skipped) == ["paper-one", "paper-two"] and not report.added

    make_pdf(settings.corpus_dir / "paper-two.pdf", ["Abstract\nRevised text about graph transformers. " * 8])
    report = ingest(settings, embedder, extractor, vectorstore=vs)
    assert report.updated == ["paper-two"]

    (settings.corpus_dir / "paper-two.pdf").unlink()
    report = ingest(settings, embedder, extractor, prune=True, vectorstore=vs)
    assert report.pruned == ["paper-two"]
    assert "paper-two" not in load_manifest(settings.manifest_path)
    assert KnowledgeGraph.load(settings.graph_path).resolve("GNN") is None
    assert all(h.paper_id == "paper-one" for h in vs.query(embedder.encode_query("graph"), k=20))


def test_no_kg_mode_then_backfill(settings, embedder):
    make_pdf(settings.corpus_dir / "a.pdf", list(TEXT))
    vs = VectorStore(settings.chroma_dir)
    report = ingest(settings, embedder, None, vectorstore=vs)
    assert report.added == ["a"] and report.kg_missing == ["a"]
    # Re-running with an extractor re-processes papers that have no KG yet.
    report = ingest(settings, embedder, StubExtractor({}), vectorstore=vs)
    assert report.updated == ["a"]


def test_extraction_cache_survives_rename_and_rebuild(settings, embedder):
    make_pdf(settings.corpus_dir / "long original name.pdf", list(TEXT))
    extractor = StubExtractor({"long-original-name": extraction("Paper One", [("Dense Retrieval", "Method", [])], [])})
    vs = VectorStore(settings.chroma_dir)
    ingest(settings, embedder, extractor, vectorstore=vs)
    assert len(extractor.calls) == 1

    (settings.corpus_dir / "long original name.pdf").rename(settings.corpus_dir / "short.pdf")
    report = ingest(settings, embedder, extractor, prune=True, vectorstore=vs)
    assert report.added == ["short"] and report.pruned == ["long-original-name"]
    ingest(settings, embedder, extractor, rebuild=True, vectorstore=vs)
    assert len(extractor.calls) == 1  # no new extraction calls
    kg = KnowledgeGraph.load(settings.graph_path)
    assert kg.g.nodes[paper_node("short")]["label"] == "Paper One"
    assert kg.resolve("Dense Retrieval") is not None


def test_paper_id_collisions(tmp_path):
    a, b = tmp_path / "My Paper.pdf", tmp_path / "my_paper.pdf"
    ids = assign_paper_ids([a, b], {})
    assert ids[a] == "my-paper" and ids[b] == "my-paper-2"
    # stable once in the manifest
    ids2 = assign_paper_ids([b], {"my-paper-2": {"file": "my_paper.pdf"}})
    assert ids2[b] == "my-paper-2"
