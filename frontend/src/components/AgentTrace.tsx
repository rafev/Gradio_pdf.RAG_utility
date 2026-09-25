import { useEffect, useState } from "react";
import type { Step } from "../state/store";

const TOOL_LABELS: Record<string, string> = {
  search_passages: "Searched passages",
  list_papers: "Listed papers",
  get_paper: "Read paper",
  find_entities: "Looked up entities",
  graph_neighbors: "Explored graph",
  graph_path: "Traced connection",
  papers_for_entity: "Found papers for",
};

function describeInput(name: string | undefined, input: Record<string, unknown> | undefined): string {
  if (!input) return "";
  const pick = (k: string) => (typeof input[k] === "string" ? (input[k] as string) : "");
  switch (name) {
    case "search_passages":
      return `“${pick("query")}”`;
    case "graph_path":
      return `${pick("a")} ↔ ${pick("b")}`;
    case "graph_neighbors":
      return pick("node").replace(/^(entity|paper):/, "");
    case "papers_for_entity":
      return pick("entity").replace(/^entity:/, "");
    case "get_paper":
      return pick("paper_id");
    default:
      return pick("query") || pick("filter");
  }
}

export function AgentTrace({ steps, live }: { steps: Step[]; live: boolean }) {
  const [open, setOpen] = useState(live);
  useEffect(() => setOpen(live), [live]);
  if (!steps.length) return null;
  const tools = steps.filter((s) => s.kind === "tool").length;

  return (
    <details className="trace" open={open} onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}>
      <summary>
        {live ? <span className="spinner" aria-hidden /> : <span className="check" aria-hidden>✓</span>}
        {live ? "Researching" : "Research"} · {tools} tool call{tools === 1 ? "" : "s"}
      </summary>
      <ul>
        {steps.map((s) =>
          s.kind === "note" ? (
            <li key={s.id} className="note">
              {s.text}
            </li>
          ) : (
            <li key={s.id} className={s.isError ? "error" : s.running ? "running" : ""}>
              <span className="tool">{TOOL_LABELS[s.name ?? ""] ?? s.name}</span>{" "}
              <span className="input">{describeInput(s.name, s.input)}</span>
              {s.summary && <span className="summary muted"> → {s.summary}</span>}
            </li>
          ),
        )}
      </ul>
    </details>
  );
}
