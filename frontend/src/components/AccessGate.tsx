import { useEffect, useState } from "react";
import { api, ApiError } from "../lib/api";
import { useStore } from "../state/store";

const STORAGE_KEY = "paper-atlas-access-request";

interface Pending {
  requestId: string;
  secret: string;
  name: string;
}

function loadPending(): Pending | null {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as Pending) : null;
  } catch {
    return null;
  }
}

function savePending(p: Pending | null) {
  try {
    if (p) sessionStorage.setItem(STORAGE_KEY, JSON.stringify(p));
    else sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    /* storage unavailable: polling still works for this page load */
  }
}

const REASONS: Record<string, string> = {
  revoked: "Your access was revoked by the admin.",
  expired: "Your access has expired.",
  paused: "Public access is paused right now.",
};

export function AccessGate() {
  const access = useStore((s) => s.access);
  const loadAccess = useStore((s) => s.loadAccess);
  const loadGraph = useStore((s) => s.loadGraph);
  const [name, setName] = useState("");
  const [reason, setReason] = useState("");
  const [pending, setPending] = useState<Pending | null>(loadPending);
  const [status, setStatus] = useState<string>(pending ? "pending" : "idle");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!pending) return;
    let stopped = false;
    const poll = async () => {
      try {
        const { status } = await api.accessStatus(pending.requestId, pending.secret);
        if (stopped) return;
        setStatus(status);
        if (status === "approved") {
          savePending(null);
          await loadAccess();
          await loadGraph();
          return;
        }
        if (status !== "pending") {
          savePending(null);
          setPending(null);
          return;
        }
      } catch (e) {
        if (e instanceof ApiError && e.status === 404) {
          savePending(null);
          setPending(null);
          setStatus("idle");
          return;
        }
      }
      if (!stopped) timer = window.setTimeout(poll, 3000);
    };
    let timer = window.setTimeout(poll, 500);
    return () => {
      stopped = true;
      window.clearTimeout(timer);
    };
  }, [pending, loadAccess, loadGraph]);

  if (!access?.gated || access.authorized) return null;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      const r = await api.requestAccess(name, reason);
      const p = { requestId: r.request_id, secret: r.claim_secret, name };
      savePending(p);
      setPending(p);
      setStatus("pending");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <div className="gate-backdrop">
      <div className="gate" role="dialog" aria-modal="true" aria-labelledby="gate-title">
        <h2 id="gate-title">Request access</h2>
        {status === "pending" && pending ? (
          <>
            <p>
              Thanks, {pending.name}. Your request is waiting for the admin's approval. Keep this tab open. It will unlock
              automatically.
            </p>
            <div className="waiting">
              <span className="spinner" aria-hidden /> Waiting for approval…
            </div>
          </>
        ) : (
          <form onSubmit={submit}>
            {status === "denied" && <p className="error-text">Your request was declined.</p>}
            {status === "expired" && <p className="error-text">Your request expired. You can send a new one.</p>}
            {access.reason && REASONS[access.reason] && <p className="error-text">{REASONS[access.reason]}</p>}
            <p className="muted">
              This research assistant runs on a paid API, so each visitor is approved by hand. Tell the admin who you are.
            </p>
            <label>
              Name
              <input value={name} onChange={(e) => setName(e.target.value)} maxLength={80} required autoFocus />
            </label>
            <label>
              <span>
                Why you'd like access <span className="muted">(optional)</span>
              </span>
              <textarea value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} rows={3} />
            </label>
            {error && <p className="error-text">{error}</p>}
            <button type="submit" className="primary" disabled={!name.trim() || access.paused}>
              Request access
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
