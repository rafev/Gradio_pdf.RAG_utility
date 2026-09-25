import { useMemo, useState } from "react";
import { GROUPS, colorOf, groupOf, type ColorGroup } from "../lib/palette";
import { useStore } from "../state/store";

export function GraphControls() {
  const graph = useStore((s) => s.graph);
  const hiddenGroups = useStore((s) => s.hiddenGroups);
  const minDegree = useStore((s) => s.minDegree);
  const toggleGroup = useStore((s) => s.toggleGroup);
  const setMinDegree = useStore((s) => s.setMinDegree);
  const focus = useStore((s) => s.focus);
  const resetView = useStore((s) => s.resetView);
  const [query, setQuery] = useState("");
  const [expanded, setExpanded] = useState(false); // filters are collapsible on narrow screens

  const counts = useMemo(() => {
    const c: Record<ColorGroup, number> = { paper: 0, approach: 0, evaluation: 0, idea: 0 };
    for (const n of graph?.nodes ?? []) c[groupOf(n.type)]++;
    return c;
  }, [graph]);

  const maxDegree = useMemo(() => Math.max(1, ...(graph?.nodes ?? []).map((n) => n.degree)), [graph]);

  const matches = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q || !graph) return [];
    return graph.nodes
      .filter((n) => n.label.toLowerCase().includes(q))
      .sort((a, b) => Number(!a.label.toLowerCase().startsWith(q)) - Number(!b.label.toLowerCase().startsWith(q)) || b.degree - a.degree)
      .slice(0, 8);
  }, [query, graph]);

  if (!graph) return null;

  return (
    <div className={`graph-controls ${expanded ? "expanded" : ""}`}>
      <div className="search">
        <button
          type="button"
          className="ghost filters-toggle"
          aria-expanded={expanded}
          onClick={() => setExpanded((v) => !v)}
        >
          Filters
        </button>
        <input
          type="search"
          placeholder="Find a paper or concept…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && matches[0]) {
              focus(matches[0].id);
              setQuery("");
            }
          }}
          aria-label="Search the knowledge graph"
        />
        {matches.length > 0 && (
          <ul className="search-results" role="listbox">
            {matches.map((n) => (
              <li key={n.id}>
                <button
                  type="button"
                  onClick={() => {
                    focus(n.id);
                    setQuery("");
                  }}
                >
                  <span className="dot" style={{ background: colorOf(n.type) }} />
                  <span className="name">{n.label}</span>
                  <span className="muted">{n.type}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="legend" role="group" aria-label="Show or hide node groups">
        {GROUPS.map((g) => (
          <button
            key={g.id}
            type="button"
            className={`chip ${hiddenGroups.has(g.id) ? "off" : ""}`}
            aria-pressed={!hiddenGroups.has(g.id)}
            onClick={() => toggleGroup(g.id)}
            title={g.types.join(", ")}
          >
            <span className={`dot ${g.id === "paper" ? "ring" : ""}`} style={{ background: g.color }} />
            {g.label}
            <span className="muted">{counts[g.id]}</span>
          </button>
        ))}
      </div>

      <div className="row">
        <label className="degree">
          <span>Min links</span>
          <input
            type="range"
            min={0}
            max={Math.min(20, maxDegree)}
            value={minDegree}
            onChange={(e) => setMinDegree(Number(e.target.value))}
          />
          <span className="muted">{minDegree}</span>
        </label>
        <button type="button" className="ghost" onClick={resetView}>
          Reset view
        </button>
      </div>
      <div className="stats muted">
        {graph.stats.papers} papers · {graph.stats.nodes - graph.stats.papers} entities · {graph.links.length} links
      </div>
    </div>
  );
}
