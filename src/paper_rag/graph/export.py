"""Export the knowledge graph in the {nodes, links} shape react-force-graph consumes."""

from __future__ import annotations

from typing import Any

from paper_rag.graph.store import KnowledgeGraph, link_id


def to_force_graph(kg: KnowledgeGraph) -> dict[str, Any]:
    g = kg.g
    links: dict[str, dict[str, Any]] = {}
    for u, v, a in g.edges(data=True):
        lid = link_id(u, a["relation"], v)
        entry = links.setdefault(lid, {"id": lid, "source": u, "target": v, "relation": a["relation"], "papers": []})
        if a["paper_id"] not in entry["papers"]:
            entry["papers"].append(a["paper_id"])

    degree: dict[str, int] = {n: 0 for n in g.nodes}
    for link in links.values():
        degree[link["source"]] += 1
        degree[link["target"]] += 1

    nodes = []
    for n, a in g.nodes(data=True):
        node = {"id": n, "label": a.get("label", n), "type": a.get("type", "Concept"), "degree": degree[n]}
        if a.get("kind") == "paper":
            node.update(paper_id=a["paper_id"], year=a.get("year"))
        else:
            node.update(n_papers=len(a.get("paper_ids", [])))
        nodes.append(node)
    return {"nodes": nodes, "links": list(links.values()), "stats": kg.stats()}


def node_detail(kg: KnowledgeGraph, node: str) -> dict[str, Any]:
    a = kg.g.nodes[node]
    detail: dict[str, Any] = {"id": node, **{k: v for k, v in a.items() if k != "references"}}
    if a.get("kind") == "paper":
        detail["n_references"] = len(a.get("references", []))
    edges = kg.edges_of(node)
    edges.sort(key=lambda e: (e["relation"] == "MENTIONS", -len(e["evidence"])))
    labels = {n: kg.g.nodes[n].get("label", n) for e in edges for n in (e["source"], e["target"])}
    detail["edges"] = [{**e, "id": link_id(e["source"], e["relation"], e["target"]),
                        "source_label": labels[e["source"]], "target_label": labels[e["target"]]} for e in edges[:80]]
    if a.get("kind") == "entity":
        detail["papers"] = kg.papers_for_entity(node)
    return detail
