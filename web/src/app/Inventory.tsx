"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ago, utc } from "@/lib/ago";
import { applyFilters, DEFAULT_FILTERS, type Filters, toCsv, toQuery } from "@/lib/filter";
import { type Cube, KIND_LABELS, type Model, STATUSES } from "@/lib/model";

type Tab = "cubes" | "computers" | "zones" | "activity";
type View = "grid" | "table";
const HOUR = 3600e3;

const kindLabel = (k: string) => KIND_LABELS[k] ?? k;
const statusLabel = (s: string | null) => (s ?? "no record").replace(/_/g, " ");

/** fresh < 1 h, recent < 24 h, stale older, never. */
function freshness(at: string | null | undefined, now: number) {
  if (!at) return "never";
  const age = now - Date.parse(at);
  return age < HOUR ? "fresh" : age < 24 * HOUR ? "recent" : "stale";
}

function Dot({ at, now }: { at: string | null | undefined; now: number }) {
  const f = freshness(at, now);
  return <span className={`dot ${f}`} title={at ? utc(at) : "never seen"} aria-label={f} />;
}

function Time({ at, now }: { at: string | null | undefined; now: number }) {
  if (!at) return <span className="muted">never</span>;
  return <time dateTime={at} title={utc(at)}>{ago(at, now)}</time>;
}

export default function Inventory({ model, initial }: {
  model: Model; initial: { filters: Filters; tab: Tab; cube: string | null; activity: string };
}) {
  const router = useRouter();
  const [filters, setFilters] = useState<Filters>(initial.filters);
  const [tab, setTab] = useState<Tab>(initial.tab);
  const [view, setView] = useState<View>("grid");
  const [selected, setSelected] = useState<string | null>(initial.cube);
  const [activityQuery, setActivityQuery] = useState(initial.activity);
  const [now, setNow] = useState(() => Date.parse(model.generatedAt));
  const [refreshing, setRefreshing] = useState(false);
  const search = useRef<HTMLInputElement>(null);

  // Remembered view, live clock, and a quiet refresh every minute.
  useEffect(() => {
    try {
      const saved = localStorage.getItem("nct-inventory-view");
      if (saved === "grid" || saved === "table") setView(saved);
    } catch { /* storage unavailable: keep default */ }
    setNow(Date.now());
    const clock = setInterval(() => setNow(Date.now()), 20_000);
    const refresh = setInterval(() => router.refresh(), 60_000);
    return () => { clearInterval(clock); clearInterval(refresh); };
  }, [router]);
  useEffect(() => { setRefreshing(false); setNow(Date.now()); }, [model.generatedAt]);

  const chooseView = (v: View) => {
    setView(v);
    try { localStorage.setItem("nct-inventory-view", v); } catch { /* ignore */ }
  };

  // Shareable URL: filters, tab, open cube.
  useEffect(() => {
    const extra: Record<string, string> = {};
    if (tab !== "cubes") extra.tab = tab;
    if (selected) extra.cube = selected;
    if (activityQuery) extra.activity = activityQuery;
    window.history.replaceState(null, "", window.location.pathname + toQuery(filters, extra));
  }, [filters, tab, selected, activityQuery]);

  // Keyboard: "/" focuses search, Escape closes the drawer.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setSelected(null);
      if (e.key === "/" && document.activeElement?.tagName !== "INPUT") {
        e.preventDefault(); setTab("cubes"); search.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const visible = useMemo(() => applyFilters(model.cubes, filters, now), [model.cubes, filters, now]);
  const set = <K extends keyof Filters>(k: K, v: Filters[K]) => setFilters((f) => ({ ...f, [k]: v }));
  const cubesByMac = useMemo(() => new Map(model.cubes.map((c) => [c.mac, c])), [model.cubes]);
  const open = selected ? cubesByMac.get(selected) ?? null : null;
  const filtered = JSON.stringify(filters) !== JSON.stringify(DEFAULT_FILTERS);

  const counts = useMemo(() => {
    const c = model.cubes;
    return {
      total: c.length,
      numbered: c.filter((x) => x.number != null).length,
      tagged: c.filter((x) => x.uid).length,
      acknowledged: c.filter((x) => x.status === "acknowledged").length,
      pending: c.filter((x) => x.status === "pending" || x.status === "unconfirmed" || x.pendingUid).length,
      seen24: c.filter((x) => x.lastSeen && now - Date.parse(x.lastSeen.at) < 24 * HOUR).length,
      never: c.filter((x) => !x.lastSeen).length,
    };
  }, [model.cubes, now]);

  const tile = (label: string, value: number, patch: Partial<Filters>, tone = "") => (
    <button className={`stat ${tone}`} onClick={() => { setTab("cubes"); setFilters({ ...DEFAULT_FILTERS, ...patch }); }}>
      <span className="stat-value">{value}</span>
      <span className="stat-label">{label}</span>
    </button>
  );

  const exportCsv = () => {
    const blob = new Blob([toCsv(visible)], { type: "text/csv" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `nct-inventory-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  const refresh = useCallback(() => { setRefreshing(true); router.refresh(); }, [router]);

  const activity = useMemo(() => {
    const q = activityQuery.trim().toLowerCase();
    if (!q) return model.changes;
    return model.changes.filter((c) => {
      const cube = cubesByMac.get(c.mac);
      return [c.mac, c.client, c.summary, cube?.number != null ? `#${cube.number}` : ""].join(" ").toLowerCase().includes(q);
    });
  }, [activityQuery, model.changes, cubesByMac]);

  return (
    <div className="app">
      <header className="topbar">
        <div>
          <h1>NCT / DEVICE INVENTORY</h1>
          <div className="muted small">
            {model.dataset} · revision {model.revision}
            {model.lastChange && <> · last change <Time at={model.lastChange} now={now} /></>}
            {" · "}page updated <Time at={model.generatedAt} now={now} />
          </div>
        </div>
        <div className="topbar-actions">
          <button onClick={refresh} disabled={refreshing}>{refreshing ? "Refreshing…" : "Refresh"}</button>
          <form method="post" action="/api/session">
            <button className="linkish" name="action" value="logout">Sign out</button>
          </form>
        </div>
      </header>

      <section className="stats" aria-label="Summary">
        {tile("devices", counts.total, {})}
        {tile("numbered", counts.numbered, { numbered: "yes" })}
        {tile("NFC tagged", counts.tagged, { tagged: "yes" })}
        {tile("acknowledged", counts.acknowledged, { status: "acknowledged" }, "ok")}
        {tile("pending / unconfirmed", counts.pending, { status: "pending_any" }, counts.pending ? "warn" : "")}
        {tile("seen in 24 h", counts.seen24, { seen: "24h", sort: "lastSeen" }, "ok")}
        {tile("never seen", counts.never, { seen: "never" }, counts.never ? "muted-tone" : "")}
      </section>

      <nav className="tabs" role="tablist">
        {([["cubes", `Cubes · ${model.cubes.length}`], ["computers", `Computers · ${model.computers.length}`],
          ["zones", `Zones · ${model.zones.length}`], ["activity", "Activity"]] as [Tab, string][]).map(([t, label]) => (
          <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? "active" : ""} onClick={() => setTab(t)}>{label}</button>
        ))}
      </nav>

      {tab === "cubes" && (
        <section>
          <div className="toolbar">
            <input ref={search} type="search" className="search" placeholder="Search number, MAC, NFC, detail, computer…  ( / )"
              value={filters.q} onChange={(e) => set("q", e.target.value)} />
            <select value={filters.status} onChange={(e) => set("status", e.target.value)} aria-label="Status">
              <option value="">Any status</option>
              <option value="pending_any">Pending / unconfirmed</option>
              {STATUSES.map((s) => <option key={s} value={s}>{statusLabel(s)}</option>)}
            </select>
            <select value={filters.seen} onChange={(e) => set("seen", e.target.value as Filters["seen"])} aria-label="Last seen">
              <option value="any">Seen any time</option>
              <option value="1h">Seen in 1 h</option>
              <option value="24h">Seen in 24 h</option>
              <option value="7d">Seen in 7 days</option>
              <option value="older">Not seen for 7+ days</option>
              <option value="never">Never seen</option>
            </select>
            <select value={filters.role} onChange={(e) => set("role", e.target.value)} aria-label="Role">
              <option value="">Any role</option>
              <option value="auto">auto</option>
              <option value="led">LED module</option>
              <option value="excluded">reader / station</option>
            </select>
            <select value={filters.numbered} onChange={(e) => set("numbered", e.target.value as Filters["numbered"])} aria-label="Number">
              <option value="any">Numbered or not</option>
              <option value="yes">Has number</option>
              <option value="no">No number</option>
            </select>
            <select value={filters.tagged} onChange={(e) => set("tagged", e.target.value as Filters["tagged"])} aria-label="NFC">
              <option value="any">Tagged or not</option>
              <option value="yes">Has NFC tag</option>
              <option value="no">No NFC tag</option>
            </select>
            <div className="sort">
              <select value={filters.sort} onChange={(e) => set("sort", e.target.value as Filters["sort"])} aria-label="Sort">
                <option value="number">Sort: number</option>
                <option value="lastSeen">Sort: last seen</option>
                <option value="changed">Sort: last changed</option>
                <option value="status">Sort: status</option>
                <option value="mac">Sort: MAC</option>
              </select>
              <button className="icon" onClick={() => set("desc", !filters.desc)} title="Reverse order">{filters.desc ? "↑" : "↓"}</button>
            </div>
          </div>
          <div className="toolbar secondary">
            <span className="muted">Showing {visible.length} of {model.cubes.length}</span>
            {filtered && <button className="linkish" onClick={() => setFilters(DEFAULT_FILTERS)}>Clear filters</button>}
            <span className="spacer" />
            <button className="linkish" onClick={exportCsv}>Export CSV</button>
            <div className="segmented" role="group" aria-label="View">
              <button className={view === "grid" ? "active" : ""} onClick={() => chooseView("grid")}>Grid</button>
              <button className={view === "table" ? "active" : ""} onClick={() => chooseView("table")}>Table</button>
            </div>
          </div>

          {visible.length === 0 ? (
            <p className="empty">No cubes match. <button className="linkish" onClick={() => setFilters(DEFAULT_FILTERS)}>Clear filters</button></p>
          ) : view === "grid" ? (
            <div className="cube-grid">
              {visible.map((c) => (
                <button key={c.mac} className={`cube-tile status-${c.status ?? "none"} ${c.role !== "auto" ? "role-" + c.role : ""}`}
                  onClick={() => setSelected(c.mac)} aria-label={`Cube ${c.number ?? c.mac}`}>
                  <span className="tile-top">
                    <span className="tile-number">{c.number ?? "—"}</span>
                    <Dot at={c.lastSeen?.at} now={now} />
                  </span>
                  <span className="tile-mac mono">{c.mac.slice(-8)}</span>
                  <span className="tile-seen">
                    {c.lastSeen ? <><Time at={c.lastSeen.at} now={now} /> · {kindLabel(c.lastSeen.kind)}</> : "never seen"}
                  </span>
                  <span className="tile-foot">
                    <span className="tile-status">{statusLabel(c.status)}</span>
                    {c.role !== "auto" && <span className="badge">{c.role === "excluded" ? "reader" : c.role}</span>}
                    {c.pendingUid && <span className="badge warn">pending tag</span>}
                  </span>
                </button>
              ))}
            </div>
          ) : (
            <div className="table-wrap">
              <table className="cube-table">
                <thead>
                  <tr>
                    {([["number", "#"], ["mac", "MAC"], [null, "NFC"], ["status", "Status"], [null, "Role"],
                      ["lastSeen", "Last seen"], [null, "Via / where"], ["changed", "Last changed"], [null, "Uploaded by"]] as [Filters["sort"] | null, string][]).map(([key, label]) => (
                      <th key={label} className={key ? "sortable" : ""} onClick={key ? () => setFilters((f) => ({ ...f, sort: key, desc: f.sort === key ? !f.desc : false })) : undefined}>
                        {label}{key && filters.sort === key ? (filters.desc ? " ↑" : " ↓") : ""}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {visible.map((c) => (
                    <tr key={c.mac} onClick={() => setSelected(c.mac)} className="clickable">
                      <td className="num">{c.number ?? "—"}</td>
                      <td className="mono">{c.mac}</td>
                      <td className="mono">{c.uid ?? "—"}{c.pendingUid && <span className="warn"> → {c.pendingUid}</span>}</td>
                      <td className={`status-text status-${c.status ?? "none"}`}>{statusLabel(c.status)}</td>
                      <td>{c.role}</td>
                      <td className="nowrap"><Dot at={c.lastSeen?.at} now={now} /> <Time at={c.lastSeen?.at} now={now} /></td>
                      <td className="muted">{c.lastSeen ? `${kindLabel(c.lastSeen.kind)} · ${c.lastSeen.computer}` : ""}</td>
                      <td className="muted nowrap"><Time at={c.updatedAt} now={now} /></td>
                      <td className="muted">{c.uploadedBy}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}

      {tab === "computers" && (
        <section>
          <p className="muted">Computers that used the web inventory. Cube sightings are uploaded by each computer when it runs Web Sync (Check or Sync now).</p>
          {model.computers.length === 0 ? <p className="empty">No computer has contacted the web inventory yet.</p> : (
            <div className="seen-grid">
              {model.computers.map((c) => (
                <div key={c.name} className={`seen ${freshness(c.lastAt, now)}`}>
                  <div className="who">{c.name}</div>
                  <div className="ago"><Time at={c.lastAt} now={now} /></div>
                  <div className="muted small">
                    {c.reportedAt ? <>Reported {c.reportedCubes} cubes <Time at={c.reportedAt} now={now} /></> : "No cube sightings reported yet"}
                  </div>
                  <ul className="apps">
                    {c.apps.map((a) => (
                      <li key={a.client}>
                        <span>{a.client.split(" · ")[1] ?? a.client}</span>
                        <span className="muted">{a.action} · <Time at={a.at} now={now} />{a.ip ? ` · ${a.ip}` : ""}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          )}
        </section>
      )}

      {tab === "zones" && (
        <section>
          {model.zones.length === 0 ? <p className="empty">No zone boards reported yet (they appear after a computer that has seen them runs Web Sync).</p> : (
            <div className="table-wrap">
              <table>
                <thead><tr><th>Zone</th><th>Type</th><th>Point</th><th>Firmware</th><th>DB</th><th>Tags</th><th>Last seen</th><th>MAC</th><th>Reported by</th></tr></thead>
                <tbody>
                  {model.zones.map((z) => (
                    <tr key={z.mac}>
                      <td><strong>{z.name}</strong>{z.profile && z.profile !== z.type && <div className="muted small">{z.profile}</div>}</td>
                      <td><span className={`zone-type ${z.type}`}>{z.type}</span></td>
                      <td>{z.point ?? "—"}</td>
                      <td className="mono">{z.firmware ?? "—"}</td>
                      <td>{z.dbVersion != null ? `v${z.dbVersion}` : "—"}</td>
                      <td>{z.tags ?? "—"}</td>
                      <td><Dot at={z.lastSeen} now={now} /> <Time at={z.lastSeen} now={now} /></td>
                      <td className="mono muted">{z.mac}</td>
                      <td className="muted">{z.reporter}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}

      {tab === "activity" && (
        <section>
          <div className="toolbar">
            <input type="search" className="search" placeholder="Filter changes by #number, MAC, computer or text…"
              value={activityQuery} onChange={(e) => setActivityQuery(e.target.value)} />
            <span className="muted">{activity.length} change{activity.length === 1 ? "" : "s"}</span>
          </div>
          <ol className="feed">
            {activity.slice(0, 300).map((c, i) => {
              const cube = cubesByMac.get(c.mac);
              return (
                <li key={`${c.revision}-${c.mac}-${i}`}>
                  <Time at={c.at} now={now} />
                  <button className="linkish cube-link" onClick={() => setSelected(c.mac)}>
                    {cube?.number != null ? `#${cube.number}` : c.mac}
                  </button>
                  <span>{c.summary}</span>
                  <span className="muted">rev {c.revision} · {c.client}</span>
                </li>
              );
            })}
          </ol>
        </section>
      )}

      {open && <Drawer cube={open} now={now} onClose={() => setSelected(null)} />}
    </div>
  );
}

function Drawer({ cube, now, onClose }: { cube: Cube; now: number; onClose: () => void }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try { await navigator.clipboard.writeText(cube.mac); setCopied(true); setTimeout(() => setCopied(false), 1500); } catch { /* ignore */ }
  };
  const rows: [string, React.ReactNode][] = [
    ["Number", cube.number ?? "—"],
    ["MAC", <span key="mac" className="mono">{cube.mac} <button className="linkish" onClick={copy}>{copied ? "copied" : "copy"}</button></span>],
    ["NFC tag", <span key="uid" className="mono">{cube.uid ?? "—"}</span>],
    ["Pending tag", <span key="p" className="mono">{cube.pendingUid ?? "—"}</span>],
    ["Status", statusLabel(cube.status)],
    ["Role", cube.role],
    ["First seen via", cube.source ?? "—"],
    ["Detail", cube.detail || "—"],
    ["Record changed", <Time key="u" at={cube.updatedAt} now={now} />],
    ["Uploaded", <span key="up"><Time at={cube.uploadedAt} now={now} /> by {cube.uploadedBy || "—"} (rev {cube.revision})</span>],
  ];
  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <aside className="drawer" onClick={(e) => e.stopPropagation()} aria-label="Cube details">
        <div className="drawer-head">
          <div>
            <div className="drawer-number">{cube.number != null ? `#${cube.number}` : "No number"}</div>
            <div className="muted small">{cube.lastSeen ? <>Last seen <Time at={cube.lastSeen.at} now={now} /> · {kindLabel(cube.lastSeen.kind)}</> : "Never seen"}</div>
          </div>
          <button className="icon" onClick={onClose} aria-label="Close">✕</button>
        </div>
        <dl className="fields">
          {rows.map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}
        </dl>
        <h3>Sightings</h3>
        {cube.seen.length === 0 ? <p className="muted">No computer has reported seeing this cube.</p> : (
          <ul className="sightings">
            {cube.seen.map((s) => (
              <li key={s.kind}>
                <Dot at={s.at} now={now} />
                <div>
                  <div><strong>{kindLabel(s.kind)}</strong> · <Time at={s.at} now={now} /></div>
                  <div className="muted small">{s.detail ? `${s.detail} · ` : ""}{s.computer} · {utc(s.at)}</div>
                </div>
              </li>
            ))}
          </ul>
        )}
        <h3>History</h3>
        {cube.history.length === 0 ? <p className="muted">No changes since the web inventory started.</p> : (
          <ol className="feed compact">
            {cube.history.map((h, i) => (
              <li key={`${h.revision}-${i}`}>
                <Time at={h.at} now={now} />
                <span>{h.summary}</span>
                <span className="muted">rev {h.revision} · {h.client}</span>
              </li>
            ))}
          </ol>
        )}
      </aside>
    </div>
  );
}
