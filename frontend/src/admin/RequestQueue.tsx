import { useState } from "react";
import { adminPost, ago, type PendingRequest } from "./types";

const DURATIONS = [1, 4, 24, 72, 168];

function RequestCard({ req, onError }: { req: PendingRequest; onError: (m: string) => void }) {
  const [hours, setHours] = useState(24);
  const [quota, setQuota] = useState(30);
  const [unlimited, setUnlimited] = useState(false);
  const [busy, setBusy] = useState(false);

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    try {
      await fn();
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <li className="request-card">
      <div className="who">
        <strong>{req.name}</strong>
        <span className="muted small">
          {ago(req.created_at)} · {req.ip ?? "unknown IP"}
        </span>
      </div>
      {req.reason ? <p className="reason">“{req.reason}”</p> : <p className="muted small">No reason given.</p>}
      {req.user_agent && (
        <p className="muted small ua" title={req.user_agent}>
          {req.user_agent}
        </p>
      )}
      <div className="controls">
        <label>
          Duration
          <select value={hours} onChange={(e) => setHours(Number(e.target.value))}>
            {DURATIONS.map((h) => (
              <option key={h} value={h}>
                {h < 24 ? `${h} h` : `${h / 24} d`}
              </option>
            ))}
          </select>
        </label>
        <label>
          Questions
          <input
            type="number"
            min={1}
            max={1000}
            value={quota}
            disabled={unlimited}
            onChange={(e) => setQuota(Number(e.target.value))}
          />
        </label>
        <label className="check">
          <input type="checkbox" checked={unlimited} onChange={(e) => setUnlimited(e.target.checked)} /> Unlimited
        </label>
      </div>
      <div className="actions">
        <button
          type="button"
          className="primary small"
          disabled={busy}
          onClick={() => act(() => adminPost(`/admin/api/requests/${req.id}/approve`, { hours, quota, unlimited }))}
        >
          Approve
        </button>
        <button
          type="button"
          className="secondary small"
          disabled={busy}
          onClick={() => act(() => adminPost(`/admin/api/requests/${req.id}/deny`))}
        >
          Deny
        </button>
      </div>
    </li>
  );
}

export function RequestQueue({ pending, onError }: { pending: PendingRequest[]; onError: (m: string) => void }) {
  if (!pending.length) return <p className="muted">No pending requests.</p>;
  return (
    <ul className="request-list">
      {pending.map((r) => (
        <RequestCard key={r.id} req={r} onError={onError} />
      ))}
    </ul>
  );
}
