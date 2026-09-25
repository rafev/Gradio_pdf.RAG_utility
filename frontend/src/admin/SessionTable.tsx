import { adminPost, ago, until, type SessionRow } from "./types";

export function SessionTable({ sessions, now, onError }: { sessions: SessionRow[]; now: number; onError: (m: string) => void }) {
  if (!sessions.length) return <p className="muted">No sessions yet.</p>;
  const total = sessions.reduce((sum, s) => sum + s.cost_usd, 0);
  return (
    <div className="table-wrap">
      <table className="sessions">
        <thead>
          <tr>
            <th>Who</th>
            <th>Status</th>
            <th className="num">Questions</th>
            <th className="num">Tokens in / out</th>
            <th className="num">Est. cost</th>
            <th>Last used</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {sessions.map((s) => (
            <tr key={s.id} className={s.active ? "" : "inactive"}>
              <td>
                {s.name}
                {s.is_admin ? <span className="tag">admin</span> : null}
                <div className="muted small">{s.ip ?? ""}</div>
              </td>
              <td>{s.revoked ? "revoked" : until(s.expires_at, now)}</td>
              <td className="num">
                {s.questions_used}
                {s.quota != null ? ` / ${s.quota}` : ""}
              </td>
              <td className="num">
                {(s.input_tokens + s.cache_read_tokens + s.cache_write_tokens).toLocaleString()} /{" "}
                {s.output_tokens.toLocaleString()}
              </td>
              <td className="num">${s.cost_usd.toFixed(3)}</td>
              <td className="muted small">{s.last_used_at ? ago(s.last_used_at, now) : "never"}</td>
              <td>
                {s.active && (
                  <button
                    type="button"
                    className="ghost danger"
                    onClick={() =>
                      adminPost(`/admin/api/sessions/${s.id}/revoke`).catch((e) => onError(String(e.message ?? e)))
                    }
                  >
                    Revoke
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr>
            <td colSpan={4} className="muted small">
              Cost is an estimate from token counts and list prices.
            </td>
            <td className="num">${total.toFixed(3)}</td>
            <td colSpan={2} />
          </tr>
        </tfoot>
      </table>
    </div>
  );
}
