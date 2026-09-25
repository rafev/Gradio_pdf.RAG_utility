import { useEffect, useRef, useState } from "react";
import { RequestQueue } from "./RequestQueue";
import { SessionTable } from "./SessionTable";
import { adminPost, ago, type AdminSnapshot } from "./types";

function beep() {
  try {
    const ctx = new AudioContext();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.frequency.value = 880;
    gain.gain.setValueAtTime(0.08, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.35);
    osc.connect(gain).connect(ctx.destination);
    osc.start();
    osc.stop(ctx.currentTime + 0.35);
  } catch {
    /* audio unavailable */
  }
}

export function AdminApp() {
  const [snap, setSnap] = useState<AdminSnapshot | null>(null);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [alerts, setAlerts] = useState(typeof Notification !== "undefined" && Notification.permission === "granted");
  const seenPending = useRef<Set<string> | null>(null);

  useEffect(() => {
    const es = new EventSource("/admin/api/events");
    es.addEventListener("snapshot", (ev) => {
      const data = JSON.parse((ev as MessageEvent).data) as AdminSnapshot;
      setSnap(data);
      setConnected(true);
      const ids = new Set(data.pending.map((p) => p.id));
      if (seenPending.current) {
        const fresh = data.pending.filter((p) => !seenPending.current!.has(p.id));
        if (fresh.length) {
          beep();
          if (typeof Notification !== "undefined" && Notification.permission === "granted")
            for (const p of fresh) new Notification("Access request", { body: `${p.name}${p.reason ? `: ${p.reason}` : ""}` });
        }
      }
      seenPending.current = ids;
    });
    es.onerror = () => setConnected(false);
    return () => es.close();
  }, []);

  useEffect(() => {
    document.title = snap?.pending.length ? `(${snap.pending.length}) Paper Atlas Admin` : "Paper Atlas Admin";
  }, [snap?.pending.length]);

  const openApp = async () => {
    try {
      const { url } = await adminPost<{ url: string }>("/admin/api/app-session");
      window.open(url, "_blank", "noopener");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div className="admin">
      <header className="topbar">
        <div className="brand">
          <span className="logo" aria-hidden /> Paper Atlas <span className="muted">· admin</span>
        </div>
        <div className="admin-actions">
          <span className={`conn ${connected ? "ok" : ""}`}>{connected ? "live" : "reconnecting…"}</span>
          {!alerts && typeof Notification !== "undefined" && (
            <button
              type="button"
              className="ghost"
              onClick={() => Notification.requestPermission().then((p) => setAlerts(p === "granted"))}
            >
              Enable alerts
            </button>
          )}
          <button type="button" className="ghost" onClick={openApp}>
            Open app as admin
          </button>
          {snap && (
            <button
              type="button"
              className={snap.paused ? "primary small" : "secondary small"}
              onClick={() => adminPost("/admin/api/pause", { paused: !snap.paused }).catch((e) => setError(String(e.message)))}
            >
              {snap.paused ? "Resume public access" : "Pause public access"}
            </button>
          )}
        </div>
      </header>

      <main className="admin-main">
        {error && (
          <p className="error-text" role="alert">
            {error}{" "}
            <button type="button" className="icon" onClick={() => setError(null)} aria-label="Dismiss">
              ×
            </button>
          </p>
        )}
        {snap?.paused && <div className="banner">Public access is paused. New requests and visitor chats are blocked.</div>}

        <section>
          <h2>
            Pending requests {snap && snap.pending.length > 0 && <span className="count">{snap.pending.length}</span>}
          </h2>
          {snap ? <RequestQueue pending={snap.pending} onError={setError} /> : <p className="muted">Connecting…</p>}
        </section>

        <section>
          <h2>Sessions</h2>
          {snap && <SessionTable sessions={snap.sessions} now={snap.now} onError={setError} />}
        </section>

        {snap && snap.recent.length > 0 && (
          <section>
            <h2>Recent decisions</h2>
            <ul className="recent">
              {snap.recent.map((r) => (
                <li key={r.id}>
                  <strong>{r.name}</strong> <span className={`status ${r.status}`}>{r.status}</span>
                  {r.decided_at && <span className="muted small"> · {ago(r.decided_at, snap.now)}</span>}
                </li>
              ))}
            </ul>
          </section>
        )}
      </main>
    </div>
  );
}
