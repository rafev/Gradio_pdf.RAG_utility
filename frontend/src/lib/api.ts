import { SSEParser } from "./sse";
import type { AccessInfo, AgentEvent, GraphData, NodeDetail, Passage } from "./types";

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, { credentials: "same-origin", ...init });
  if (!res.ok) throw await toError(res);
  return (await res.json()) as T;
}

async function toError(res: Response): Promise<ApiError> {
  let code = "http_error";
  let message = `${res.status} ${res.statusText}`;
  try {
    const body = await res.json();
    code = body.error ?? code;
    message = body.message ?? body.detail ?? message;
  } catch {
    /* non-JSON body */
  }
  return new ApiError(res.status, code, typeof message === "string" ? message : JSON.stringify(message));
}

export const api = {
  accessMe: () => request<AccessInfo>("/api/access/me"),
  requestAccess: (name: string, reason: string) =>
    request<{ request_id: string; claim_secret: string }>("/api/access/request", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, reason }),
    }),
  accessStatus: (requestId: string, secret: string) =>
    request<{ status: string }>(`/api/access/status/${encodeURIComponent(requestId)}`, {
      headers: { "X-Claim-Secret": secret },
    }),
  graph: () => request<GraphData>("/api/graph"),
  node: (id: string) => request<NodeDetail>(`/api/node/${encodeURIComponent(id)}`),
  passage: (paperId: string, page: number) =>
    request<{ paper_id: string; page: number; title: string; passages: Omit<Passage, "paper_id" | "page">[] }>(
      `/api/passage/${encodeURIComponent(paperId)}/${page}`,
    ),
};

export interface ChatTurnParam {
  role: "user" | "assistant";
  content: string;
}

/** POST /api/chat and dispatch each server-sent event. Resolves when the stream ends. */
export async function streamChat(
  question: string,
  history: ChatTurnParam[],
  onEvent: (e: AgentEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch("/api/chat", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify({ question, history }),
    signal,
  });
  if (!res.ok || !res.body) throw await toError(res);

  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  const parser = new SSEParser();
  const dispatch = (data: string) => {
    try {
      onEvent(JSON.parse(data) as AgentEvent);
    } catch {
      /* ignore malformed event */
    }
  };
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    for (const msg of parser.feed(value)) dispatch(msg.data);
  }
  for (const msg of parser.end()) dispatch(msg.data);
}
