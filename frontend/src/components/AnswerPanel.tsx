import { useEffect, useMemo, useRef, useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api } from "../lib/api";
import { linkifyCitations, parseCitationHref, resolvePaperId, type Citation } from "../lib/citations";
import type { Passage } from "../lib/types";
import { useStore, type Turn } from "../state/store";
import { AgentTrace } from "./AgentTrace";

interface Peek extends Citation {
  title?: string;
  passages: { section: string; text: string }[];
  loading: boolean;
}

function PassagePeek({ peek, onClose }: { peek: Peek; onClose: () => void }) {
  return (
    <div className="peek" role="dialog" aria-label={`Passage from ${peek.paperId}, page ${peek.page}`}>
      <header>
        <strong>{peek.title ?? peek.paperId}</strong>
        <span className="muted"> · p.{peek.page}</span>
        <button type="button" className="icon" onClick={onClose} aria-label="Close">
          ×
        </button>
      </header>
      {peek.loading ? (
        <p className="muted">Loading passage…</p>
      ) : peek.passages.length ? (
        peek.passages.map((p, i) => (
          <blockquote key={i}>
            {p.section && <div className="muted small">{p.section}</div>}
            {p.text}
          </blockquote>
        ))
      ) : (
        <p className="muted">No indexed text for this page.</p>
      )}
    </div>
  );
}

function TurnView({ turn, onCite }: { turn: Turn; onCite: (c: Citation, passages: Passage[]) => void }) {
  const markdown = useMemo(() => linkifyCitations(turn.answer), [turn.answer]);
  const live = turn.status === "streaming";
  return (
    <article className="turn">
      <div className="question">{turn.question}</div>
      <AgentTrace steps={turn.steps} live={live} />
      {turn.statusMessage && <p className="muted small">{turn.statusMessage}</p>}
      {live && !turn.answer && !turn.steps.length && !turn.statusMessage && (
        <p className="muted small thinking">Thinking…</p>
      )}
      {turn.answer && (
        <div className={`answer ${live ? "live" : ""}`}>
          <Markdown
            remarkPlugins={[remarkGfm]}
            components={{
              a: ({ href, children }) => {
                const cite = parseCitationHref(href);
                if (cite)
                  return (
                    <button
                      type="button"
                      className="cite"
                      onClick={() => onCite(cite, Object.values(turn.passages))}
                      title={`Show passage: ${cite.paperId}, page ${cite.page}`}
                    >
                      {cite.paperId}
                      {cite.partial ? "…" : ""} p.{cite.page}
                    </button>
                  );
                return (
                  <a href={href} target="_blank" rel="noreferrer noopener">
                    {children}
                  </a>
                );
              },
            }}
          >
            {markdown}
          </Markdown>
        </div>
      )}
      {turn.error && <p className="error-text">{turn.error}</p>}
      {turn.usage && turn.status !== "streaming" && (
        <footer className="muted small">
          {(turn.usage.input_tokens + turn.usage.cache_read_input_tokens + turn.usage.cache_creation_input_tokens).toLocaleString()} in ·{" "}
          {turn.usage.output_tokens.toLocaleString()} out tokens
        </footer>
      )}
    </article>
  );
}

export function AnswerPanel() {
  const turns = useStore((s) => s.turns);
  const graph = useStore((s) => s.graph);
  const focus = useStore((s) => s.focus);
  const [peek, setPeek] = useState<Peek | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const last = turns[turns.length - 1];

  // Follow the stream unless the reader has scrolled up.
  useEffect(() => {
    const el = scrollRef.current;
    if (el && el.scrollHeight - el.scrollTop - el.clientHeight < 160) el.scrollTop = el.scrollHeight;
  }, [last?.answer, last?.steps.length, turns.length]);

  const onCite = (cite: Citation, seen: Passage[]) => {
    const paperIds = (graph?.nodes ?? []).flatMap((n) => (n.paper_id ? [n.paper_id] : []));
    const c = { ...cite, paperId: resolvePaperId(cite.paperId, paperIds) ?? cite.paperId };
    const node = `paper:${c.paperId}`;
    if (graph?.nodes.some((n) => n.id === node)) focus(node);
    const title = graph?.nodes.find((n) => n.id === node)?.label;
    const local = seen.filter((p) => p.paper_id === c.paperId && p.page === c.page);
    if (local.length) {
      setPeek({ ...c, title, passages: local, loading: false });
      return;
    }
    setPeek({ ...c, title, passages: [], loading: true });
    api
      .passage(c.paperId, c.page)
      .then((r) => setPeek({ ...c, title: r.title, passages: r.passages, loading: false }))
      .catch(() => setPeek({ ...c, title, passages: [], loading: false }));
  };

  return (
    <section className="answer-panel" aria-label="Answers">
      <div className="answer-scroll" ref={scrollRef}>
        {turns.length === 0 ? (
          <div className="welcome">
            <h2>Ask the corpus</h2>
            <p>
              The agent searches passages and walks the knowledge graph to answer. As it works, the graph lights up the
              papers and concepts it touches. Answers cite pages as{" "}
              <span className="cite static">paper p.N</span>, and you can click a citation to read the passage.
            </p>
            {graph && graph.stats.papers === 0 && (
              <p className="muted">
                The corpus is empty. Add PDFs to <code>corpus/papers/</code> and run{" "}
                <code>python -m paper_rag.ingest</code>.
              </p>
            )}
          </div>
        ) : (
          turns.map((t) => <TurnView key={t.id} turn={t} onCite={onCite} />)
        )}
      </div>
      {peek && <PassagePeek peek={peek} onClose={() => setPeek(null)} />}
    </section>
  );
}
