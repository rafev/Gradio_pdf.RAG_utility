import { useEffect } from "react";
import { AccessGate } from "./components/AccessGate";
import { AnswerPanel } from "./components/AnswerPanel";
import { GraphControls } from "./components/GraphControls";
import { GraphScene } from "./components/GraphScene";
import { NodeCard } from "./components/NodeCard";
import { QueryBar } from "./components/QueryBar";
import { useStore } from "./state/store";

export default function App() {
  const access = useStore((s) => s.access);
  const graph = useStore((s) => s.graph);
  const graphError = useStore((s) => s.graphError);
  const loadAccess = useStore((s) => s.loadAccess);
  const loadGraph = useStore((s) => s.loadGraph);

  useEffect(() => {
    void loadAccess();
  }, [loadAccess]);

  useEffect(() => {
    if (access?.authorized && !graph) void loadGraph();
  }, [access?.authorized, graph, loadGraph]);

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="logo" aria-hidden />
          Paper Atlas
        </div>
        {access?.gated && access.authorized && (
          <div className="muted small">
            Signed in as {access.name}
            {access.questions_left != null && ` · ${access.questions_left} questions left`}
          </div>
        )}
      </header>

      <main className="layout">
        <section className="left">
          <div className="graph-wrap">
            <GraphScene />
            <GraphControls />
            <NodeCard />
            {!graph && (
              <div className="graph-empty">
                {graphError ? `Could not load the graph: ${graphError}` : access?.authorized === false ? "" : "Loading the knowledge graph…"}
              </div>
            )}
          </div>
          <QueryBar />
        </section>
        <AnswerPanel />
      </main>

      <AccessGate />
    </div>
  );
}
