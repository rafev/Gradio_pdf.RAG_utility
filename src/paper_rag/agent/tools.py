"""Agent tools over the vector store and knowledge graph.

Every tool returns a ToolOutput: JSON text for Claude, plus the graph node/link ids it touched
(so the UI can light them up) and the passages it surfaced (so citations can be resolved).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from paper_rag.graph.store import MENTIONS, KnowledgeGraph, link_id, paper_node
from paper_rag.ingest.embed import Embedder, Reranker
from paper_rag.ingest.kg_extract import ENTITY_TYPES, RELATION_TYPES
from paper_rag.ingest.vectorstore import VectorStore

ALL_RELATIONS = [*RELATION_TYPES, MENTIONS, "CITES"]


@dataclass
class ToolOutput:
    content: str
    summary: str
    node_ids: list[str] = field(default_factory=list)
    link_ids: list[str] = field(default_factory=list)
    passages: list[dict[str, Any]] = field(default_factory=list)
    is_error: bool = False


class ToolInputError(ValueError):
    pass


def _dump(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=str)


def _str(args: dict, key: str, required: bool = True, default: str | None = None) -> str | None:
    value = args.get(key, default)
    if value is None or value == "":
        if required:
            raise ToolInputError(f"'{key}' is required")
        return default
    if not isinstance(value, str):
        raise ToolInputError(f"'{key}' must be a string")
    return value.strip()


def _int(args: dict, key: str, default: int, lo: int, hi: int) -> int:
    value = args.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ToolInputError(f"'{key}' must be an integer")
    try:
        return max(lo, min(hi, int(value)))
    except ValueError as exc:
        raise ToolInputError(f"'{key}' must be an integer") from exc


def _enum(args: dict, key: str, allowed: list[str] | tuple[str, ...]) -> str | None:
    value = _str(args, key, required=False)
    if value is None:
        return None
    match = next((a for a in allowed if a.lower() == value.lower()), None)
    if match is None:
        raise ToolInputError(f"'{key}' must be one of {', '.join(allowed)}")
    return match


TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "search_passages",
        "description": (
            "Semantic search over passages from the papers in the corpus. Returns passages with chunk ids, paper ids, "
            "page numbers and similarity scores. Use it for specific claims, numbers, definitions and methods. "
            "Restrict it with paper_ids to dig into particular papers."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "A natural-language description of what to find."},
                "k": {"type": "integer", "description": "Number of passages to return (1-15, default 8)."},
                "paper_ids": {"type": "array", "items": {"type": "string"},
                              "description": "Optional: only search these papers."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "list_papers",
        "description": "List the papers in the corpus (id, title, year, authors). An optional filter matches title or author text.",
        "input_schema": {
            "type": "object",
            "properties": {"filter": {"type": "string", "description": "Optional case-insensitive text filter."}},
        },
    },
    {
        "name": "get_paper",
        "description": "Metadata, abstract, summary and main knowledge-graph relations for one paper.",
        "input_schema": {
            "type": "object",
            "properties": {"paper_id": {"type": "string"}},
            "required": ["paper_id"],
        },
    },
    {
        "name": "find_entities",
        "description": (
            "Fuzzy-find knowledge-graph entities (methods, models, datasets, tasks, metrics, concepts, fields) by name "
            "or alias. Use this to get the node id to pass to the graph tools."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "type": {"type": "string", "enum": list(ENTITY_TYPES)},
            },
            "required": ["query"],
        },
    },
    {
        "name": "graph_neighbors",
        "description": (
            "Explore the knowledge graph around a node (entity or paper). Returns typed relations with evidence quotes "
            "and the paper that asserted each one. Use depth 2 for broader context."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "node": {"type": "string", "description": "Node id (e.g. 'entity:bert', 'paper:<id>'), entity name, or paper id."},
                "relation": {"type": "string", "enum": ALL_RELATIONS, "description": "Optional: only this relation type."},
                "depth": {"type": "integer", "description": "1-3, default 1."},
                "limit": {"type": "integer", "description": "Max edges, default 30."},
            },
            "required": ["node"],
        },
    },
    {
        "name": "graph_path",
        "description": "Shortest connecting paths between two nodes in the knowledge graph. Use it to explain how two concepts or papers are related.",
        "input_schema": {
            "type": "object",
            "properties": {
                "a": {"type": "string", "description": "Node id, entity name, or paper id."},
                "b": {"type": "string", "description": "Node id, entity name, or paper id."},
                "max_len": {"type": "integer", "description": "Maximum hops, default 4."},
            },
            "required": ["a", "b"],
        },
    },
    {
        "name": "papers_for_entity",
        "description": "Which corpus papers propose, use, evaluate on, or mention an entity, and how they relate to it.",
        "input_schema": {
            "type": "object",
            "properties": {
                "entity": {"type": "string", "description": "Entity node id or name."},
                "relation": {"type": "string", "enum": ALL_RELATIONS},
            },
            "required": ["entity"],
        },
    },
]


class ToolBox:
    def __init__(self, kg: KnowledgeGraph, vs: VectorStore, embedder: Embedder, reranker: Reranker | None = None):
        self.kg = kg
        self.vs = vs
        self.embedder = embedder
        self.reranker = reranker
        self._impls: dict[str, Callable[[dict], ToolOutput]] = {
            "search_passages": self.search_passages,
            "list_papers": self.list_papers,
            "get_paper": self.get_paper,
            "find_entities": self.find_entities,
            "graph_neighbors": self.graph_neighbors,
            "graph_path": self.graph_path,
            "papers_for_entity": self.papers_for_entity,
        }

    @property
    def definitions(self) -> list[dict[str, Any]]:
        return TOOL_DEFINITIONS

    def run(self, name: str, args: Any) -> ToolOutput:
        impl = self._impls.get(name)
        if impl is None:
            return ToolOutput(f"Unknown tool {name!r}", f"unknown tool {name}", is_error=True)
        if not isinstance(args, dict):
            return ToolOutput("Tool input must be a JSON object", "invalid input", is_error=True)
        try:
            return impl(args)
        except ToolInputError as exc:
            return ToolOutput(f"Invalid input: {exc}", f"invalid input: {exc}", is_error=True)
        except Exception as exc:  # surface as a tool error so the agent can recover
            return ToolOutput(f"Tool failed: {type(exc).__name__}: {exc}", "tool error", is_error=True)

    # -------------------------------------------------------------- helpers
    def _require_node(self, ref: str) -> str:
        node = self.kg.resolve(ref)
        if node is None:
            suggestions = [e["label"] for e in self.kg.find_entities(ref, limit=5)]
            hint = f" Did you mean: {', '.join(suggestions)}?" if suggestions else ""
            raise ToolInputError(f"No graph node matches {ref!r}.{hint}")
        return node

    def _paper_label(self, paper_id: str) -> str:
        node = paper_node(paper_id)
        return self.kg.g.nodes[node]["label"] if node in self.kg.g else paper_id

    # -------------------------------------------------------------- tools
    def search_passages(self, args: dict) -> ToolOutput:
        query = _str(args, "query")
        k = _int(args, "k", 8, 1, 15)
        paper_ids = args.get("paper_ids") or None
        if paper_ids is not None and (not isinstance(paper_ids, list) or not all(isinstance(p, str) for p in paper_ids)):
            raise ToolInputError("'paper_ids' must be a list of strings")
        if paper_ids:
            paper_ids = [p.removeprefix("paper:") for p in paper_ids]
        fetch = k * 3 if self.reranker else k
        hits = self.vs.query(self.embedder.encode_query(query), fetch, paper_ids)
        if self.reranker and hits:
            scores = self.reranker.scores(query, [h.text for h in hits])
            hits = [h for _, h in sorted(zip(scores, hits), key=lambda x: -x[0])][:k]
        passages = [
            {"chunk_id": h.chunk_id, "paper_id": h.paper_id, "title": self._paper_label(h.paper_id), "page": h.page,
             "section": h.section, "score": round(h.score, 3), "text": h.text}
            for h in hits
        ]
        nodes = list(dict.fromkeys(paper_node(h.paper_id) for h in hits if paper_node(h.paper_id) in self.kg.g))
        summary = f"{len(hits)} passages from {len({h.paper_id for h in hits})} papers"
        return ToolOutput(_dump(passages) if passages else "No passages found.", summary, nodes,
                          passages=[{k_: p[k_] for k_ in ("chunk_id", "paper_id", "page", "section", "text")} for p in passages])

    def list_papers(self, args: dict) -> ToolOutput:
        flt = (_str(args, "filter", required=False) or "").lower()
        rows = []
        for n, a in self.kg.papers():
            hay = f"{a.get('label', '')} {' '.join(a.get('authors', []))}".lower()
            if flt and flt not in hay:
                continue
            rows.append({"paper_id": a["paper_id"], "title": a.get("label"), "year": a.get("year"),
                         "authors": a.get("authors", [])[:4]})
        rows.sort(key=lambda r: (r["year"] or 0, r["title"] or ""), reverse=True)
        return ToolOutput(_dump(rows) if rows else "No matching papers.", f"{len(rows)} papers",
                          [paper_node(r["paper_id"]) for r in rows])

    def get_paper(self, args: dict) -> ToolOutput:
        ref = _str(args, "paper_id")
        node = self.kg.resolve(ref) or ""
        if not node.startswith("paper:"):
            raise ToolInputError(f"No paper {ref!r}. Use list_papers to see paper ids.")
        a = self.kg.g.nodes[node]
        edges = [e for e in self.kg.edges_of(node) if e["relation"] not in (MENTIONS,)]
        relations = [
            {"relation": e["relation"], "source": self.kg.g.nodes[e["source"]]["label"],
             "target": self.kg.g.nodes[e["target"]]["label"],
             "evidence": (e["evidence"][0]["quote"] if e["evidence"] else "")}
            for e in edges[:25]
        ]
        info = {k: a.get(k) for k in ("paper_id", "label", "authors", "year", "venue", "doi", "abstract", "summary")}
        info["title"] = info.pop("label")
        info["n_chunks"] = a.get("n_chunks")
        info["key_relations"] = relations
        touched = [node, *{e["target"] if e["source"] == node else e["source"] for e in edges[:25]}]
        links = [link_id(e["source"], e["relation"], e["target"]) for e in edges[:25]]
        return ToolOutput(_dump(info), f"paper “{info['title']}”", touched, links)

    def find_entities(self, args: dict) -> ToolOutput:
        query = _str(args, "query")
        etype = _enum(args, "type", ENTITY_TYPES)
        results = self.kg.find_entities(query, etype)
        return ToolOutput(_dump(results) if results else "No matching entities.", f"{len(results)} entities",
                          [r["id"] for r in results])

    def graph_neighbors(self, args: dict) -> ToolOutput:
        node = self._require_node(_str(args, "node"))
        relation = _enum(args, "relation", ALL_RELATIONS)
        result = self.kg.neighbors(node, relation, _int(args, "depth", 1, 1, 3), _int(args, "limit", 30, 1, 80))
        labels = {n["id"]: n["label"] for n in result["nodes"]} | {node: result["center"]["label"]}
        edges = [
            {"source": labels.get(e["source"], e["source"]), "relation": e["relation"],
             "target": labels.get(e["target"], e["target"]), "source_id": e["source"], "target_id": e["target"],
             "evidence": e["evidence"][:3]}
            for e in result["edges"]
        ]
        content = {"center": result["center"], "edges": edges}
        nodes = [node, *(n["id"] for n in result["nodes"])]
        links = [link_id(e["source"], e["relation"], e["target"]) for e in result["edges"]]
        return ToolOutput(_dump(content), f"{len(edges)} relations around “{result['center']['label']}”", nodes, links)

    def graph_path(self, args: dict) -> ToolOutput:
        a = self._require_node(_str(args, "a"))
        b = self._require_node(_str(args, "b"))
        paths = self.kg.paths(a, b, _int(args, "max_len", 4, 1, 6))
        if not paths:
            return ToolOutput("No path found within the hop limit.", "no path", [a, b])
        nodes = list(dict.fromkeys(n for p in paths for s in p for n in (s["source"], s["target"])))
        links = list(dict.fromkeys(link_id(s["source"], s["relation"], s["target"]) for p in paths for s in p))
        readable = [[f"{s['source_label']} —{s['relation']}→ {s['target_label']}" for s in p] for p in paths]
        return ToolOutput(_dump({"paths": readable, "raw": paths}), f"{len(paths)} path(s), {len(paths[0])} hops",
                          nodes, links)

    def papers_for_entity(self, args: dict) -> ToolOutput:
        node = self._require_node(_str(args, "entity"))
        relation = _enum(args, "relation", ALL_RELATIONS)
        papers = self.kg.papers_for_entity(node, relation)
        label = self.kg.g.nodes[node]["label"]
        links = [link_id(p["id"], r, node) for p in papers for r in p["relations"]]
        return ToolOutput(_dump({"entity": label, "papers": papers}) if papers else f"No papers linked to {label}.",
                          f"{len(papers)} papers for “{label}”", [node, *(p["id"] for p in papers)], links)
