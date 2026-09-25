import type { NodeType } from "./types";

/**
 * Node colour groups. Seven per-type hues can't be told apart all-pairs (validated with the
 * dataviz palette checker), so types fold into three validated groups (dark-surface steps of
 * blue / orange / aqua) plus a neutral for papers. The exact type is always shown in text.
 */
export type ColorGroup = "paper" | "approach" | "evaluation" | "idea";

export const GROUPS: { id: ColorGroup; label: string; color: string; types: NodeType[] }[] = [
  { id: "paper", label: "Papers", color: "#e8ecf5", types: ["Paper"] },
  { id: "approach", label: "Methods & models", color: "#3987e5", types: ["Method", "Model"] },
  { id: "evaluation", label: "Datasets, tasks & metrics", color: "#d95926", types: ["Dataset", "Task", "Metric"] },
  { id: "idea", label: "Concepts & fields", color: "#199e70", types: ["Concept", "Field"] },
];

const BY_TYPE = new Map<NodeType, (typeof GROUPS)[number]>(GROUPS.flatMap((g) => g.types.map((t) => [t, g] as const)));

export function groupOf(type: NodeType): ColorGroup {
  return BY_TYPE.get(type)?.id ?? "idea";
}

export function colorOf(type: NodeType): string {
  return BY_TYPE.get(type)?.color ?? "#199e70";
}
