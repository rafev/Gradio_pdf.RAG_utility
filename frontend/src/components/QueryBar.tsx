import { useEffect, useMemo, useRef } from "react";
import { useStore } from "../state/store";

export function QueryBar() {
  const draft = useStore((s) => s.draft);
  const setDraft = useStore((s) => s.setDraft);
  const ask = useStore((s) => s.ask);
  const stop = useStore((s) => s.stop);
  const streaming = useStore((s) => s.streaming);
  const graph = useStore((s) => s.graph);
  const turns = useStore((s) => s.turns);
  const access = useStore((s) => s.access);
  const ref = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (draft) ref.current?.focus();
  }, [draft]);

  const suggestions = useMemo(() => {
    if (!graph || turns.length) return [];
    const top = (types: string[]) =>
      graph.nodes.filter((n) => types.includes(n.type)).sort((a, b) => b.degree - a.degree);
    const methods = top(["Method", "Model"]);
    const datasets = top(["Dataset"]);
    const out: string[] = [];
    if (methods[0]) out.push(`Which papers build on ${methods[0].label}, and how?`);
    if (methods[0] && methods[1]) out.push(`How are ${methods[0].label} and ${methods[1].label} related?`);
    if (datasets[0]) out.push(`Compare the results reported on ${datasets[0].label}.`);
    if (graph.stats.papers > 1) out.push("What are the main research themes across the corpus?");
    return out.slice(0, 3);
  }, [graph, turns.length]);

  const noQuestionsLeft = access?.gated && access.questions_left === 0;
  const submit = () => {
    if (!streaming && !noQuestionsLeft) void ask(draft);
  };

  return (
    <div className="query-bar">
      {suggestions.length > 0 && (
        <div className="suggestions">
          {suggestions.map((s) => (
            <button key={s} type="button" className="chip" onClick={() => void ask(s)} disabled={streaming}>
              {s}
            </button>
          ))}
        </div>
      )}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <textarea
          ref={ref}
          value={draft}
          rows={2}
          maxLength={2000}
          placeholder={noQuestionsLeft ? "You have used all your questions for this session." : "Ask the corpus a question…"}
          disabled={noQuestionsLeft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
          aria-label="Question"
        />
        {streaming ? (
          <button type="button" className="secondary" onClick={stop}>
            Stop
          </button>
        ) : (
          <button type="submit" className="primary" disabled={!draft.trim() || noQuestionsLeft}>
            Ask
          </button>
        )}
      </form>
      <div className="hint muted small">
        Enter to send · Shift+Enter for a new line
        {access?.gated && access.questions_left != null && ` · ${access.questions_left} questions left`}
      </div>
    </div>
  );
}
