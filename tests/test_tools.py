import json

import pytest
from test_graph import build_two_paper_graph

from paper_rag.agent.agent import _history_messages
from paper_rag.agent.tools import TOOL_DEFINITIONS, ToolBox
from paper_rag.graph.store import link_id, paper_node
from paper_rag.ingest.chunking import Chunk
from paper_rag.ingest.vectorstore import VectorStore


@pytest.fixture
def toolbox(tmp_path, embedder):
    kg = build_two_paper_graph()
    vs = VectorStore(tmp_path / "chroma")
    chunks = [
        Chunk("rag", 0, "RAG combines a parametric generator with a dense passage retriever.", 2, "1 Introduction"),
        Chunk("rag", 1, "We evaluate on Natural Questions and report exact match.", 5, "4 Experiments"),
        Chunk("dpr", 0, "Dense passage retrieval uses a dual encoder trained with in-batch negatives.", 3, "3 Method"),
    ]
    vs.add(chunks, embedder.encode_documents([c.text for c in chunks]))
    return ToolBox(kg, vs, embedder)


def test_tool_definitions_are_well_formed():
    names = [t["name"] for t in TOOL_DEFINITIONS]
    assert len(names) == len(set(names))
    for t in TOOL_DEFINITIONS:
        assert t["description"] and t["input_schema"]["type"] == "object"


def test_search_passages(toolbox):
    out = toolbox.search_passages({"query": "dual encoder in-batch negatives", "k": 2})
    data = json.loads(out.content)
    assert data[0]["paper_id"] == "dpr" and data[0]["page"] == 3
    assert paper_node("dpr") in out.node_ids
    assert out.passages[0]["chunk_id"] == "dpr:0"
    restricted = json.loads(toolbox.search_passages({"query": "retriever", "paper_ids": ["paper:rag"]}).content)
    assert {p["paper_id"] for p in restricted} == {"rag"}


def test_graph_tools(toolbox):
    out = toolbox.run("graph_neighbors", {"node": "RAG"})
    assert not out.is_error
    rag = toolbox.kg.resolve("RAG")
    assert link_id(rag, "USES", toolbox.kg.resolve("DPR")) in out.link_ids

    out = toolbox.run("graph_path", {"a": "Natural Questions", "b": "dpr"})
    assert not out.is_error and "paths" in json.loads(out.content)

    out = toolbox.run("papers_for_entity", {"entity": "DPR", "relation": "PROPOSES"})
    assert [p["paper_id"] for p in json.loads(out.content)["papers"]] == ["dpr"]

    out = toolbox.run("get_paper", {"paper_id": "rag"})
    assert json.loads(out.content)["title"].startswith("Retrieval-Augmented")

    out = toolbox.run("list_papers", {"filter": "dense"})
    assert [p["paper_id"] for p in json.loads(out.content)] == ["dpr"]


def test_tool_errors_are_returned_not_raised(toolbox):
    out = toolbox.run("graph_neighbors", {"node": "Dense Passage Retrievl"})
    assert out.is_error and "Did you mean" in out.content
    assert toolbox.run("search_passages", {}).is_error
    assert toolbox.run("find_entities", {"query": "x", "type": "Bogus"}).is_error
    assert toolbox.run("nope", {}).is_error


def test_history_messages_alternate_and_trim():
    history = [{"role": "assistant", "content": "hi"}, {"role": "user", "content": "q1"},
               {"role": "assistant", "content": "a1"}, {"role": "user", "content": "dangling"}]
    msgs = _history_messages(history)
    assert [m["role"] for m in msgs] == ["user", "assistant"]
