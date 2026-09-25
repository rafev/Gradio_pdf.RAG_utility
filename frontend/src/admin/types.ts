export interface PendingRequest {
  id: string;
  name: string;
  reason: string;
  ip: string | null;
  user_agent: string | null;
  created_at: number;
}

export interface SessionRow {
  id: string;
  name: string;
  ip: string | null;
  created_at: number;
  expires_at: number;
  quota: number | null;
  questions_used: number;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cache_write_tokens: number;
  cost_usd: number;
  revoked: number;
  is_admin: number;
  last_used_at: number | null;
  active: boolean;
}

export interface AdminSnapshot {
  paused: boolean;
  pending: PendingRequest[];
  recent: { id: string; name: string; status: string; decided_at: number | null }[];
  sessions: SessionRow[];
  now: number;
}

export async function adminPost<T = unknown>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method: "POST",
    credentials: "same-origin",
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    let msg = `${res.status}`;
    try {
      const j = await res.json();
      msg = j.message ?? j.detail ?? msg;
    } catch {
      /* ignore */
    }
    throw new Error(msg);
  }
  return (await res.json()) as T;
}

export const ago = (ts: number, now = Date.now() / 1000) => {
  const s = Math.max(0, Math.round(now - ts));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  return `${Math.round(s / 3600)}h ago`;
};

export const until = (ts: number, now = Date.now() / 1000) => {
  const s = Math.round(ts - now);
  if (s <= 0) return "expired";
  if (s < 3600) return `${Math.round(s / 60)}m left`;
  return `${Math.round(s / 3600)}h left`;
};
