import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { colorOf } from "../lib/palette";
import type { NodeDetail } from "../lib/types";
import { useStore } from "../state/store";

export function NodeCard() {
  const focusId = useStore((s) => s.focusId);
  const focus = useStore((s) => s.focus);
  const setDraft = useStore((s) => s.setDraft);
  const [detail, setDetail] = useState<NodeDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!focusId) {
      setDetail(null);
      return;
    }
    let cancelled = false;
    setError(null);
    api
      .node(focusId)
      .then((d) => !cancelled && setDetail(d))
      .catch((e) => !cancelled && setError(String(e.message ?? e)));
    return () => {
      cancelled = true;
    };
  }, [focusId]);

  if (!focusId) return null;
  if (error) return <aside className="node-card">Could not load node: {error}</aside>;
  if (!detail || detail.id !== focusId) return <aside className="node-card loading">Loading…</aside>;

  const isPaper = detail.kind === "paper";
  const relations = detail.edges.filter((e) => e.relation !== "MENTIONS").slice(0, 10);
  const ask = () =>
    setDraft(
      isPaper
        ? `What are the key contributions of “${detail.label}”, and how does it relate to other papers in the corpus?`
        : `How is ${detail.label} used across the papers in the corpus?`,
    );

  return (
    <aside className="node-card" aria-label={`Details for ${detail.label}`}>
      <header>
        <span className="type-badge" style={{ borderColor: colorOf(detail.type) }}>
          <span className="dot" style={{ background: colorOf(detail.type) }} />
          {detail.type}
        </span>
        <button type="button" className="icon" onClick={() => focus(null, false)} aria-label="Close">
          ×
        </button>
      </header>
      <h3>{detail.label}</h3>
      {isPaper ? (
        <>
          <p className="muted small">
            {(detail.authors ?? []).slice(0, 5).join(", ")}
            {(detail.authors?.length ?? 0) > 5 ? " et al." : ""}
            {detail.year ? ` · ${detail.year}` : ""}
            {detail.venue ? ` · ${detail.venue}` : ""}
          </p>
          {detail.summary && <p>{detail.summary}</p>}
        </>
      ) : (
        <>
          {detail.description && <p>{detail.description}</p>}
          {!!detail.aliases?.length && <p className="muted small">Also: {detail.aliases.join(", ")}</p>}
        </>
      )}

      {relations.length > 0 && (
        <section>
          <h4>Relations</h4>
          <ul className="relations">
            {relations.map((e) => {
              const other = e.source === detail.id ? e.target : e.source;
              const otherLabel = e.source === detail.id ? e.target_label : e.source_label;
              const q = e.evidence[0];
              return (
                <li key={e.id}>
                  <span className="rel">{e.source === detail.id ? e.relation : `← ${e.relation}`}</span>{" "}
                  <button type="button" className="link" onClick={() => focus(other)}>
                    {otherLabel}
                  </button>
                  {q?.quote && (
                    <blockquote title={`${q.paper_id}${q.page ? ` p.${q.page}` : ""}`}>“{q.quote}”</blockquote>
                  )}
                </li>
              );
            })}
          </ul>
        </section>
      )}

      {!isPaper && !!detail.papers?.length && (
        <section>
          <h4>Papers</h4>
          <ul className="papers">
            {detail.papers.slice(0, 12).map((p) => (
              <li key={p.id}>
                <button type="button" className="link" onClick={() => focus(p.id)}>
                  {p.label}
                </button>
                <span className="muted small"> {p.relations.join(", ").toLowerCase()}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <button type="button" className="primary small" onClick={ask}>
        Ask about this
      </button>
    </aside>
  );
}
