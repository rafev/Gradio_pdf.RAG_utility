from conftest import extraction

from paper_rag.graph.export import node_detail, to_force_graph
from paper_rag.graph.store import KnowledgeGraph, canonical_key, entity_node, link_id, paper_node


def build_two_paper_graph() -> KnowledgeGraph:
    kg = KnowledgeGraph()
    kg.merge_paper("rag", extraction(
        "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks",
        [("Retrieval-Augmented Generation", "Method", ["RAG"]), ("Natural Questions", "Dataset", ["NQ"]),
         ("Dense Passage Retrieval", "Method", ["DPR"])],
        [("THIS_PAPER", "PROPOSES", "Retrieval-Augmented Generation"),
         ("Retrieval-Augmented Generation", "USES", "DPR"),
         ("THIS_PAPER", "EVALUATES_ON", "Natural Questions")],
        references=["Dense Passage Retrieval for Open-Domain Question Answering"],
    ))
    kg.merge_paper("dpr", extraction(
        "Dense Passage Retrieval for Open-Domain Question Answering",
        [("Dense Passage Retrieval", "Method", []), ("NQ", "Dataset", [])],
        [("THIS_PAPER", "PROPOSES", "Dense Passage Retrieval"), ("THIS_PAPER", "EVALUATES_ON", "NQ")],
    ))
    return kg


def test_canonical_key():
    assert canonical_key("  BERT-Base ") == "bert base"
    assert canonical_key("Naïve Bayes") == "naive bayes"


def test_entities_merge_across_papers_by_name_and_alias():
    kg = build_two_paper_graph()
    dpr = kg.resolve("DPR")
    assert dpr == entity_node("dense passage retrieval")
    assert sorted(kg.g.nodes[dpr]["paper_ids"]) == ["dpr", "rag"]
    # "NQ" in paper 2 resolves to the "Natural Questions" entity via the alias from paper 1
    nq = kg.resolve("NQ")
    assert nq == entity_node("natural questions")
    assert sorted(kg.g.nodes[nq]["paper_ids"]) == ["dpr", "rag"]


def test_citations_link_in_both_directions():
    kg = build_two_paper_graph()
    assert kg.g.has_edge(paper_node("rag"), paper_node("dpr"))
    # Reverse order: the citing paper arrives first; the edge appears when the cited paper is added.
    kg2 = KnowledgeGraph()
    kg2.merge_paper("rag", extraction("RAG", [], [], references=["Dense passage retrieval for open-domain question answering"]))
    kg2.merge_paper("dpr", extraction("Dense Passage Retrieval for Open-Domain Question Answering", [], []))
    cites = [(u, v, a["paper_id"]) for u, v, a in kg2.g.edges(data=True) if a["relation"] == "CITES"]
    assert cites == [(paper_node("rag"), paper_node("dpr"), "rag")]


def test_remove_paper_keeps_shared_entities_and_drops_orphans():
    kg = build_two_paper_graph()
    kg.remove_paper("rag")
    assert paper_node("rag") not in kg.g
    assert kg.resolve("Retrieval-Augmented Generation") is None  # only rag mentioned it
    dpr = kg.resolve("Dense Passage Retrieval")
    assert kg.g.nodes[dpr]["paper_ids"] == ["dpr"]
    assert all(a["paper_id"] != "rag" for _, _, a in kg.g.edges(data=True))


def test_save_load_roundtrip(tmp_path):
    kg = build_two_paper_graph()
    path = tmp_path / "graph.json"
    kg.save(path)
    loaded = KnowledgeGraph.load(path)
    assert loaded.stats() == kg.stats()
    assert loaded.resolve("RAG") == kg.resolve("RAG")


def test_queries():
    kg = build_two_paper_graph()
    found = kg.find_entities("dense retrieval")
    assert found and found[0]["id"] == entity_node("dense passage retrieval")
    rag = kg.resolve("RAG")
    nb = kg.neighbors(rag)
    assert any(e["relation"] == "USES" for e in nb["edges"])
    paths = kg.paths(rag, paper_node("dpr"))
    assert paths and len(paths[0]) <= 3
    papers = kg.papers_for_entity(kg.resolve("DPR"))
    assert {p["paper_id"] for p in papers} == {"rag", "dpr"}
    assert next(p for p in papers if p["paper_id"] == "dpr")["relations"] == ["PROPOSES"]


def test_force_graph_export_aggregates_links():
    kg = build_two_paper_graph()
    fg = to_force_graph(kg)
    ids = {n["id"] for n in fg["nodes"]}
    assert paper_node("rag") in ids
    lid = link_id(paper_node("rag"), "PROPOSES", kg.resolve("RAG"))
    assert any(l["id"] == lid for l in fg["links"])
    assert all(l["source"] in ids and l["target"] in ids for l in fg["links"])
    detail = node_detail(kg, kg.resolve("DPR"))
    assert detail["papers"] and detail["edges"]
