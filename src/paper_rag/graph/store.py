"""The corpus knowledge graph.

Nodes:
  paper:<paper_id>    kind="paper",  type="Paper", label=title, plus bibliographic metadata
  entity:<key>        kind="entity", type=<EntityType>, label, description, aliases, paper_ids
Edges (MultiDiGraph, keyed "<RELATION>|<paper_id>"):
  relation, evidence, page, paper_id  — paper_id is the paper that asserted the edge (provenance),
  so a paper's contributions can be removed cleanly when it is re-ingested or pruned.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import networkx as nx
from rapidfuzz import fuzz, process
from rapidfuzz.utils import default_process

from paper_rag.ingest.kg_extract import ENTITY_TYPES, THIS_PAPER, Extraction

MENTIONS = "MENTIONS"
CITES = "CITES"
_CITE_MATCH_THRESHOLD = 90


def canonical_key(name: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().casefold()
    return re.sub(r"[^a-z0-9]+", " ", ascii_name).strip()


def paper_node(paper_id: str) -> str:
    return f"paper:{paper_id}"


def entity_node(key: str) -> str:
    return f"entity:{key}"


def link_id(source: str, relation: str, target: str) -> str:
    """Stable id of the aggregated (source, relation, target) link shown in the UI."""
    return f"{source}|{relation}|{target}"


class KnowledgeGraph:
    def __init__(self, graph: nx.MultiDiGraph | None = None):
        self.g = graph if graph is not None else nx.MultiDiGraph()
        self._alias_index: dict[str, str] = {}
        self._rebuild_alias_index()

    # ------------------------------------------------------------------ persistence
    @classmethod
    def load(cls, path: Path) -> KnowledgeGraph:
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        g = nx.MultiDiGraph()
        for node in data.get("nodes", []):
            attrs = dict(node)
            g.add_node(attrs.pop("id"), **attrs)
        for link in data.get("links", []):
            attrs = dict(link)
            g.add_edge(attrs.pop("source"), attrs.pop("target"), key=attrs.pop("key"), **attrs)
        return cls(g)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "nodes": [{"id": n, **attrs} for n, attrs in self.g.nodes(data=True)],
            "links": [{"source": u, "target": v, "key": k, **attrs} for u, v, k, attrs in self.g.edges(keys=True, data=True)],
        }
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(path)

    # ------------------------------------------------------------------ lookup
    def _rebuild_alias_index(self) -> None:
        self._alias_index = {}
        for n, attrs in self.g.nodes(data=True):
            if attrs.get("kind") != "entity":
                continue
            self._alias_index.setdefault(canonical_key(attrs.get("label", "")), n)
            for alias in attrs.get("aliases", []):
                self._alias_index.setdefault(canonical_key(alias), n)

    def resolve(self, ref: str) -> str | None:
        """Resolve a node id, paper id, entity name or alias to a node id."""
        if ref in self.g:
            return ref
        if paper_node(ref) in self.g:
            return paper_node(ref)
        key = canonical_key(ref.removeprefix("entity:"))
        if entity_node(key) in self.g:
            return entity_node(key)
        return self._alias_index.get(key)

    def papers(self) -> list[tuple[str, dict[str, Any]]]:
        return [(n, a) for n, a in self.g.nodes(data=True) if a.get("kind") == "paper"]

    def paper_ids(self) -> list[str]:
        return [a["paper_id"] for _, a in self.papers()]

    def entity_names_by_type(self) -> dict[str, list[str]]:
        """Existing entity names grouped by type, most-connected first (fed back into extraction)."""
        by_type: dict[str, list[tuple[int, str]]] = defaultdict(list)
        for n, a in self.g.nodes(data=True):
            if a.get("kind") == "entity":
                by_type[a["type"]].append((len(a.get("paper_ids", [])), a["label"]))
        return {t: [name for _, name in sorted(by_type.get(t, []), key=lambda x: (-x[0], x[1]))] for t in ENTITY_TYPES}

    # ------------------------------------------------------------------ mutation
    def remove_paper(self, paper_id: str) -> None:
        pnode = paper_node(paper_id)
        doomed = [(u, v, k) for u, v, k, a in self.g.edges(keys=True, data=True) if a.get("paper_id") == paper_id]
        self.g.remove_edges_from(doomed)
        if pnode in self.g:
            self.g.remove_node(pnode)
        orphans = []
        for n, a in self.g.nodes(data=True):
            if a.get("kind") == "entity" and paper_id in a.get("paper_ids", []):
                a["paper_ids"] = [p for p in a["paper_ids"] if p != paper_id]
                if not a["paper_ids"]:
                    orphans.append(n)
        self.g.remove_nodes_from(orphans)
        self._rebuild_alias_index()

    def _upsert_entity(self, name: str, etype: str, description: str, aliases: Iterable[str], paper_id: str) -> str:
        node = self.resolve(name)
        if node is None or self.g.nodes[node].get("kind") != "entity":
            for alias in aliases:
                found = self._alias_index.get(canonical_key(alias))
                if found:
                    node = found
                    break
        if node is None:
            node = entity_node(canonical_key(name) or name)
            self.g.add_node(node, kind="entity", type=etype, label=name.strip(), description=description.strip(),
                            aliases=[], paper_ids=[])
        attrs = self.g.nodes[node]
        if not attrs.get("description") and description:
            attrs["description"] = description.strip()
        known = {canonical_key(a) for a in attrs["aliases"]} | {canonical_key(attrs["label"])}
        for alias in aliases:
            if alias.strip() and canonical_key(alias) not in known:
                attrs["aliases"].append(alias.strip())
                known.add(canonical_key(alias))
        if paper_id not in attrs["paper_ids"]:
            attrs["paper_ids"].append(paper_id)
        self._alias_index.setdefault(canonical_key(attrs["label"]), node)
        for alias in attrs["aliases"]:
            self._alias_index.setdefault(canonical_key(alias), node)
        return node

    def _add_edge(self, u: str, v: str, relation: str, paper_id: str, evidence: str = "", page: int | None = None):
        if u == v:
            return
        self.g.add_edge(u, v, key=f"{relation}|{paper_id}", relation=relation, paper_id=paper_id,
                        evidence=evidence, page=page)

    def merge_paper(self, paper_id: str, extraction: Extraction, *, source_file: str = "", n_chunks: int = 0) -> None:
        """Add one paper's extraction. Call remove_paper(paper_id) first when re-ingesting."""
        meta = extraction.paper
        pnode = paper_node(paper_id)
        self.g.add_node(
            pnode, kind="paper", type="Paper", paper_id=paper_id, label=meta.title.strip() or paper_id,
            authors=meta.authors, year=meta.year, venue=meta.venue, doi=meta.doi, abstract=meta.abstract,
            summary=meta.summary, references=extraction.references, source_file=source_file, n_chunks=n_chunks,
        )

        local: dict[str, str] = {}  # canonical name/alias in this paper → node id
        for ent in extraction.entities:
            node = self._upsert_entity(ent.name, ent.type, ent.description, ent.aliases, paper_id)
            for name in [ent.name, *ent.aliases]:
                local.setdefault(canonical_key(name), node)
            self._add_edge(pnode, node, MENTIONS, paper_id)

        def endpoint(name: str) -> str:
            if name.strip().upper() == THIS_PAPER:
                return pnode
            node = local.get(canonical_key(name)) or self.resolve(name)
            if node is None:
                node = self._upsert_entity(name, "Concept", "", [], paper_id)
                self._add_edge(pnode, node, MENTIONS, paper_id)
            local[canonical_key(name)] = node
            return node

        for rel in extraction.relations:
            self._add_edge(endpoint(rel.source), endpoint(rel.target), rel.type, paper_id, rel.evidence, rel.page)

        self._link_citations(paper_id)

    def _link_citations(self, paper_id: str) -> None:
        """CITES edges between corpus papers, matched by fuzzy title, in both directions."""
        pnode = paper_node(paper_id)
        new_title = self.g.nodes[pnode]["label"]
        others = {n: a for n, a in self.papers() if n != pnode}
        titles = {n: a["label"] for n, a in others.items()}
        for ref in self.g.nodes[pnode].get("references", []):
            match = process.extractOne(ref, titles, scorer=fuzz.token_sort_ratio, processor=default_process,
                                       score_cutoff=_CITE_MATCH_THRESHOLD)
            if match:
                self._add_edge(pnode, match[2], CITES, paper_id)
        for n, a in others.items():
            if any(fuzz.token_sort_ratio(ref, new_title, processor=default_process) >= _CITE_MATCH_THRESHOLD
                   for ref in a.get("references", [])):
                self._add_edge(n, pnode, CITES, a["paper_id"])

    # ------------------------------------------------------------------ queries used by agent tools
    def node_summary(self, node: str) -> dict[str, Any]:
        a = self.g.nodes[node]
        base = {"id": node, "type": a.get("type"), "label": a.get("label")}
        if a.get("kind") == "paper":
            base.update(paper_id=a["paper_id"], year=a.get("year"), authors=a.get("authors", [])[:6])
        else:
            base.update(description=a.get("description", ""), aliases=a.get("aliases", []),
                        n_papers=len(a.get("paper_ids", [])))
        return base

    def find_entities(self, query: str, etype: str | None = None, limit: int = 10) -> list[dict[str, Any]]:
        choices: dict[str, str] = {}
        for n, a in self.g.nodes(data=True):
            if a.get("kind") != "entity" or (etype and a.get("type") != etype):
                continue
            choices[f"{n}\x00label"] = a["label"]
            for i, alias in enumerate(a.get("aliases", [])):
                choices[f"{n}\x00{i}"] = alias
        results: list[dict[str, Any]] = []
        seen: set[str] = set()
        for _, score, key in process.extract(query, choices, scorer=fuzz.WRatio, limit=limit * 3):
            node = key.split("\x00", 1)[0]
            if node in seen or score < 60:
                continue
            seen.add(node)
            results.append({**self.node_summary(node), "match_score": round(score)})
            if len(results) >= limit:
                break
        return results

    def edges_of(self, node: str, relation: str | None = None) -> list[dict[str, Any]]:
        """Aggregated edges touching `node`: one entry per (source, relation, target) with provenance."""
        agg: dict[tuple[str, str, str], dict[str, Any]] = {}
        for u, v, a in [*self.g.out_edges(node, data=True), *self.g.in_edges(node, data=True)]:
            if relation and a["relation"] != relation:
                continue
            key = (u, a["relation"], v)
            entry = agg.setdefault(key, {"source": u, "relation": a["relation"], "target": v, "evidence": []})
            if a.get("evidence") or a["relation"] not in (MENTIONS, CITES):
                entry["evidence"].append({"paper_id": a["paper_id"], "page": a.get("page"), "quote": a.get("evidence", "")})
        return list(agg.values())

    def neighbors(self, node: str, relation: str | None = None, depth: int = 1, limit: int = 30) -> dict[str, Any]:
        frontier, seen = {node}, {node}
        edges: list[dict[str, Any]] = []
        seen_edges: set[tuple[str, str, str]] = set()
        for _ in range(max(1, min(depth, 3))):
            nxt: set[str] = set()
            for n in frontier:
                for e in self.edges_of(n, relation):
                    k = (e["source"], e["relation"], e["target"])
                    if k in seen_edges:
                        continue
                    seen_edges.add(k)
                    edges.append(e)
                    other = e["target"] if e["source"] == n else e["source"]
                    if other not in seen:
                        seen.add(other)
                        nxt.add(other)
            frontier = nxt
        # Rank: typed relations before MENTIONS, then by how many papers support them.
        edges.sort(key=lambda e: (e["relation"] == MENTIONS, -len(e["evidence"])))
        edges = edges[:limit]
        nodes = {node} | {e["source"] for e in edges} | {e["target"] for e in edges}
        return {"center": self.node_summary(node), "nodes": [self.node_summary(n) for n in nodes if n != node],
                "edges": edges}

    def paths(self, a: str, b: str, max_len: int = 4, limit: int = 3) -> list[list[dict[str, Any]]]:
        und = nx.Graph()
        for u, v, attrs in self.g.edges(data=True):
            if not und.has_edge(u, v) or attrs["relation"] != MENTIONS:
                und.add_edge(u, v, relation=attrs["relation"], forward=(u, v))
        if a not in und or b not in und:
            return []
        try:
            raw = []
            for path in nx.all_shortest_paths(und, a, b):
                if len(path) - 1 > max_len:
                    break
                raw.append(path)
                if len(raw) >= limit:
                    break
        except nx.NetworkXNoPath:
            return []
        out = []
        for path in raw:
            steps = []
            for u, v in zip(path, path[1:]):
                data = und.edges[u, v]
                src, dst = data["forward"]
                steps.append({"source": src, "relation": data["relation"], "target": dst,
                              "source_label": self.g.nodes[src]["label"], "target_label": self.g.nodes[dst]["label"]})
            out.append(steps)
        return out

    def papers_for_entity(self, node: str, relation: str | None = None) -> list[dict[str, Any]]:
        relations_by_paper: dict[str, set[str]] = defaultdict(set)
        for _, _, a in [*self.g.in_edges(node, data=True), *self.g.out_edges(node, data=True)]:
            if (relation and a["relation"] != relation) or paper_node(a["paper_id"]) not in self.g:
                continue
            relations_by_paper[a["paper_id"]].add(a["relation"])
        results = []
        for pid, rels in relations_by_paper.items():
            if len(rels) > 1:
                rels.discard(MENTIONS)
            results.append({**self.node_summary(paper_node(pid)), "relations": sorted(rels)})
        return sorted(results, key=lambda r: (r["relations"] == [MENTIONS], -(r.get("year") or 0)))

    def stats(self) -> dict[str, Any]:
        types = Counter(a.get("type") for _, a in self.g.nodes(data=True))
        relations = Counter(a.get("relation") for _, _, a in self.g.edges(data=True))
        return {"nodes": self.g.number_of_nodes(), "edges": self.g.number_of_edges(), "papers": types.get("Paper", 0),
                "node_types": dict(types), "relations": dict(relations)}
