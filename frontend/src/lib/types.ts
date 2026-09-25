export type EntityType = "Method" | "Model" | "Dataset" | "Task" | "Metric" | "Concept" | "Field";
export type NodeType = EntityType | "Paper";

export interface GraphNode {
  id: string;
  label: string;
  type: NodeType;
  degree: number;
  paper_id?: string;
  year?: number | null;
  n_papers?: number;
  // added by the force simulation
  x?: number;
  y?: number;
  z?: number;
}

export interface GraphLink {
  id: string;
  source: string | GraphNode; // the simulation replaces ids with node objects
  target: string | GraphNode;
  relation: string;
  papers: string[];
}

export interface GraphData {
  nodes: GraphNode[];
  links: GraphLink[];
  stats: { nodes: number; edges: number; papers: number; node_types: Record<string, number> };
}

export interface Evidence {
  paper_id: string;
  page: number | null;
  quote: string;
}

export interface NodeEdge {
  id: string;
  source: string;
  target: string;
  relation: string;
  source_label: string;
  target_label: string;
  evidence: Evidence[];
}

export interface NodeDetail {
  id: string;
  kind: "paper" | "entity";
  type: NodeType;
  label: string;
  description?: string;
  aliases?: string[];
  paper_ids?: string[];
  paper_id?: string;
  authors?: string[];
  year?: number | null;
  venue?: string | null;
  doi?: string | null;
  abstract?: string;
  summary?: string;
  edges: NodeEdge[];
  papers?: { id: string; paper_id: string; label: string; year?: number | null; relations: string[] }[];
}

export interface Passage {
  chunk_id: string;
  paper_id: string;
  page: number;
  section: string;
  text: string;
}

export interface Usage {
  input_tokens: number;
  output_tokens: number;
  cache_read_input_tokens: number;
  cache_creation_input_tokens: number;
}

export type AgentEvent =
  | { type: "status"; message: string }
  | { type: "text"; delta: string; round: number }
  | { type: "round_end"; round: number; has_tools: boolean }
  | { type: "tool_call"; id: string; name: string; input: Record<string, unknown>; round: number }
  | {
      type: "tool_result";
      id: string;
      name: string;
      summary: string;
      is_error: boolean;
      node_ids: string[];
      link_ids: string[];
    }
  | { type: "citations"; passages: Passage[] }
  | {
      type: "done";
      usage: Usage;
      node_ids: string[];
      link_ids: string[];
      model: string;
      questions_left?: number | null;
    }
  | { type: "error"; message: string };

export interface AccessInfo {
  gated: boolean;
  authorized: boolean;
  reason?: string;
  paused?: boolean;
  name?: string;
  expires_at?: number;
  questions_left?: number | null;
  is_admin?: boolean;
}
