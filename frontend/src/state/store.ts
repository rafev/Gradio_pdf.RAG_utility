import { create } from "zustand";
import { api, ApiError, streamChat, type ChatTurnParam } from "../lib/api";
import type { ColorGroup } from "../lib/palette";
import type { AccessInfo, AgentEvent, GraphData, Passage, Usage } from "../lib/types";

export interface Step {
  kind: "tool" | "note";
  id: string;
  name?: string;
  input?: Record<string, unknown>;
  summary?: string;
  isError?: boolean;
  running?: boolean;
  text?: string;
}

export interface Turn {
  id: string;
  question: string;
  answer: string;
  steps: Step[];
  status: "streaming" | "done" | "error";
  statusMessage?: string;
  error?: string;
  passages: Record<string, Passage>;
  usage?: Usage;
  nodeIds: string[];
  linkIds: string[];
}

interface Highlight {
  nodes: Set<string>;
  links: Set<string>;
  pulse: Set<string>; // nodes touched by the most recent tool result
  pulseAt: number;
}

interface FlyTo {
  nodeIds: string[];
  nonce: number;
}

interface State {
  access: AccessInfo | null;
  graph: GraphData | null;
  graphError: string | null;
  turns: Turn[];
  draft: string;
  streaming: boolean;
  highlight: Highlight;
  focusId: string | null;
  flyTo: FlyTo | null;
  hiddenGroups: Set<ColorGroup>;
  minDegree: number;

  loadAccess: () => Promise<void>;
  loadGraph: () => Promise<void>;
  setDraft: (text: string) => void;
  ask: (question: string) => Promise<void>;
  stop: () => void;
  focus: (nodeId: string | null, fly?: boolean) => void;
  fly: (nodeIds: string[]) => void;
  resetView: () => void;
  toggleGroup: (g: ColorGroup) => void;
  setMinDegree: (n: number) => void;
}

const emptyHighlight = (): Highlight => ({ nodes: new Set(), links: new Set(), pulse: new Set(), pulseAt: 0 });
let controller: AbortController | null = null;

export const useStore = create<State>((set, get) => {
  const patchTurn = (id: string, fn: (t: Turn) => Turn) =>
    set((s) => ({ turns: s.turns.map((t) => (t.id === id ? fn(t) : t)) }));

  const handleEvent = (turnId: string, e: AgentEvent) => {
    switch (e.type) {
      case "status":
        patchTurn(turnId, (t) => ({ ...t, statusMessage: e.message }));
        break;
      case "text":
        patchTurn(turnId, (t) => ({ ...t, answer: t.answer + e.delta, statusMessage: undefined }));
        break;
      case "round_end":
        // Text from a round that ended in tool calls is the agent thinking aloud: move it to the trace.
        if (e.has_tools)
          patchTurn(turnId, (t) =>
            t.answer.trim()
              ? { ...t, answer: "", steps: [...t.steps, { kind: "note", id: `note-${e.round}`, text: t.answer.trim() }] }
              : { ...t, answer: "" },
          );
        break;
      case "tool_call":
        patchTurn(turnId, (t) => ({
          ...t,
          statusMessage: undefined,
          steps: [...t.steps, { kind: "tool", id: e.id, name: e.name, input: e.input, running: true }],
        }));
        break;
      case "tool_result": {
        patchTurn(turnId, (t) => ({
          ...t,
          steps: t.steps.map((st) =>
            st.id === e.id ? { ...st, running: false, summary: e.summary, isError: e.is_error } : st,
          ),
        }));
        if (!e.is_error && e.node_ids.length) {
          const h = get().highlight;
          set({
            highlight: {
              nodes: new Set([...h.nodes, ...e.node_ids]),
              links: new Set([...h.links, ...e.link_ids]),
              pulse: new Set(e.node_ids),
              pulseAt: performance.now(),
            },
          });
          get().fly(e.node_ids);
        }
        break;
      }
      case "citations":
        patchTurn(turnId, (t) => ({
          ...t,
          passages: Object.fromEntries(e.passages.map((p) => [p.chunk_id, p])),
        }));
        break;
      case "done":
        patchTurn(turnId, (t) => ({
          ...t,
          status: t.status === "error" ? "error" : "done",
          usage: e.usage,
          nodeIds: e.node_ids,
          linkIds: e.link_ids,
          statusMessage: undefined,
        }));
        if (e.questions_left !== undefined)
          set((s) => ({ access: s.access ? { ...s.access, questions_left: e.questions_left } : s.access }));
        if (e.node_ids.length) get().fly(e.node_ids);
        break;
      case "error":
        patchTurn(turnId, (t) => ({ ...t, status: "error", error: e.message, statusMessage: undefined }));
        break;
    }
  };

  return {
    access: null,
    graph: null,
    graphError: null,
    turns: [],
    draft: "",
    streaming: false,
    highlight: emptyHighlight(),
    focusId: null,
    flyTo: null,
    hiddenGroups: new Set(),
    minDegree: 0,

    loadAccess: async () => {
      try {
        set({ access: await api.accessMe() });
      } catch {
        set({ access: { gated: false, authorized: false, reason: "offline" } });
      }
    },

    loadGraph: async () => {
      try {
        set({ graph: await api.graph(), graphError: null });
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) {
          await get().loadAccess();
          return;
        }
        set({ graphError: err instanceof Error ? err.message : String(err) });
      }
    },

    setDraft: (draft) => set({ draft }),

    ask: async (question) => {
      question = question.trim();
      if (!question || get().streaming) return;
      const history: ChatTurnParam[] = get()
        .turns.filter((t) => t.status === "done" && t.answer)
        .flatMap((t) => [
          { role: "user" as const, content: t.question },
          { role: "assistant" as const, content: t.answer },
        ]);
      const turn: Turn = {
        id: crypto.randomUUID(),
        question,
        answer: "",
        steps: [],
        status: "streaming",
        passages: {},
        nodeIds: [],
        linkIds: [],
      };
      set((s) => ({ turns: [...s.turns, turn], draft: "", streaming: true, highlight: emptyHighlight(), focusId: null }));
      controller = new AbortController();
      try {
        await streamChat(question, history, (e) => handleEvent(turn.id, e), controller.signal);
        patchTurn(turn.id, (t) => (t.status === "streaming" ? { ...t, status: "done" } : t));
      } catch (err) {
        const aborted = err instanceof DOMException && err.name === "AbortError";
        patchTurn(turn.id, (t) => ({
          ...t,
          status: aborted ? "done" : "error",
          error: aborted ? undefined : err instanceof Error ? err.message : String(err),
          answer: aborted && !t.answer ? "_Stopped._" : t.answer,
        }));
        if (err instanceof ApiError && (err.status === 401 || err.status === 429 || err.status === 503))
          void get().loadAccess();
      } finally {
        controller = null;
        set({ streaming: false });
      }
    },

    stop: () => controller?.abort(),

    focus: (nodeId, fly = true) => {
      set({ focusId: nodeId });
      if (nodeId && fly) get().fly([nodeId]);
    },

    fly: (nodeIds) => set((s) => ({ flyTo: { nodeIds, nonce: (s.flyTo?.nonce ?? 0) + 1 } })),

    resetView: () => set((s) => ({ highlight: emptyHighlight(), focusId: null, flyTo: { nodeIds: [], nonce: (s.flyTo?.nonce ?? 0) + 1 } })),

    toggleGroup: (g) =>
      set((s) => {
        const hidden = new Set(s.hiddenGroups);
        if (hidden.has(g)) hidden.delete(g);
        else hidden.add(g);
        return { hiddenGroups: hidden };
      }),

    setMinDegree: (minDegree) => set({ minDegree }),
  };
});
