import { ago, utc } from "@/lib/ago";
import { DEFAULT_DATASET } from "@/lib/http";
import { snapshot } from "@/lib/inventory";
import { getStore } from "@/lib/store";

export const dynamic = "force-dynamic";

type Row = {
  mac: string; role: string; cube_id?: number | null; uid?: string | null; pending_uid?: string | null;
  status?: string; detail?: string; updated_at?: string;
};

export default async function DevicesPage() {
  const store = getStore();
  const [doc, seen] = await Promise.all([snapshot(store, DEFAULT_DATASET), store.presence(DEFAULT_DATASET).catch(() => [])]);
  const now = Date.now();
  const computers = seen.sort((a, b) => b.at.localeCompare(a.at));
  const records = Object.values(doc.records)
    .map((r) => ({ ...(r.record as Row), from: r.updated_from, webAt: r.updated_at }))
    .sort((a, b) => (a.cube_id ?? Infinity) - (b.cube_id ?? Infinity) || a.mac.localeCompare(b.mac));
  const last = doc.changes[0]?.at;
  return (
    <main>
      <header>
        <h1>NCT / DEVICE INVENTORY</h1>
        <form method="post" action="/api/session">
          <button className="linkish" name="action" value="logout">Sign out</button>
        </form>
      </header>
      <div className="card">
        <span className="status">Dataset {DEFAULT_DATASET}</span>
        <span className="muted"> · revision {doc.revision} · {records.length} records
          {last && ` · last change ${ago(last, now)} (${utc(last)})`}</span>
        <p className="muted" style={{ marginBottom: 0 }}>
          Read-only view. Edit devices in the pairing app, then run Web Sync (inventory_web) on that computer.
        </p>
      </div>
      <h2>Last seen</h2>
      {computers.length === 0 ? (
        <p className="muted">No computer has contacted the web inventory yet.</p>
      ) : (
        <div className="seen-grid">
          {computers.map((c) => {
            const age = now - Date.parse(c.at);
            const [host, app] = c.client.split(" · ");
            return (
              <div key={c.client} className={`seen ${age < 15 * 60e3 ? "fresh" : age < 24 * 3600e3 ? "recent" : ""}`} title={utc(c.at)}>
                <div className="who">{host}</div>
                <div className="muted">{app ?? ""}</div>
                <div className="ago">{ago(c.at, now)}</div>
                <div className="muted">{c.action} · {utc(c.at)}{c.ip ? ` · ${c.ip}` : ""}</div>
              </div>
            );
          })}
        </div>
      )}
      <h2>Devices</h2>
      <div className="table-wrap">
        <table>
          <thead>
            <tr><th>#</th><th>MAC</th><th>NFC tag</th><th>Status</th><th>Role</th><th>Detail</th><th>Last changed</th></tr>
          </thead>
          <tbody>
            {records.map((r) => (
              <tr key={r.mac}>
                <td>{r.cube_id ?? "—"}</td>
                <td className="mono">{r.mac}</td>
                <td className="mono">{r.uid ?? "—"}{r.pending_uid ? <span className="warn"> → {r.pending_uid}</span> : null}</td>
                <td className={r.status === "acknowledged" ? "ok" : r.status ? "warn" : "muted"}>{r.status ?? "—"}</td>
                <td>{r.role}</td>
                <td className="muted">{r.detail ?? ""}</td>
                <td className="muted" title={r.updated_at ? `Changed on the device record ${utc(r.updated_at)}` : ""}>
                  {r.updated_at ? ago(r.updated_at, now) : "—"}
                  {r.from && <div className="small">uploaded by {r.from.split(" · ")[0]}, {ago(r.webAt, now)}</div>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <h2>Recent changes</h2>
      <div className="table-wrap">
        <table>
          <thead><tr><th>Rev</th><th>When</th><th>MAC</th><th>Change</th><th>From</th></tr></thead>
          <tbody>
            {doc.changes.slice(0, 50).map((c, i) => {
              const before = c.before as Row | null;
              const after = c.after as Row;
              const fields = ["cube_id", "uid", "pending_uid", "status", "role"] as const;
              const diff = before
                ? fields.filter((f) => before[f] !== after[f]).map((f) => `${f}: ${before[f] ?? "—"} → ${after[f] ?? "—"}`).join(", ") || "detail/timestamp"
                : "added";
              return (
                <tr key={`${c.revision}-${c.mac}-${i}`}>
                  <td>{c.revision}</td>
                  <td className="muted" title={utc(c.at)}>{ago(c.at, now)}</td>
                  <td className="mono">{c.mac}</td>
                  <td>{diff}</td>
                  <td className="muted">{c.client}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </main>
  );
}
