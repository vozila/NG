import { useEffect, useMemo, useRef, useState } from "react";

type RenderService = {
  id: string;
  name?: string;
  type?: string;
  region?: string;
  service_details?: any;
};

type RenderInstance = {
  id: string;
  name?: string;
};

type RenderLogRow = {
  ts: string | null;
  level: string | null;
  msg: string | null;
  raw?: string | null;
};

type RenderLogsOut = {
  service_id: string;
  instance_id: string | null;
  start_ms: number;
  end_ms: number;
  rows: RenderLogRow[];
  has_more: boolean;
  next_start_ms?: number | null;
  next_end_ms?: number | null;
};

function safeJsonParse(text: string): any {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

function fmtTs(ts: string | null | undefined): string {
  // Control plane returns America/New_York-formatted timestamps like:
  // "2026-02-06 08:17:00 EST" which is NOT reliably parseable by Date().
  // Treat as display string.
  return (ts || "").trim();
}

function fmtLevel(level: string | null | undefined): string {
  return (level || "").toUpperCase().padEnd(5, " ");
}

export function RenderLogsPanel() {
  const [services, setServices] = useState<RenderService[]>([]);
  const [serviceId, setServiceId] = useState<string>("");

  const [instances, setInstances] = useState<RenderInstance[]>([]);
  const [instanceId, setInstanceId] = useState<string>("");

  const [minutes, setMinutes] = useState<number>(15);
  const [limit, setLimit] = useState<number>(500);
  const [q, setQ] = useState<string>("");

  const [autoRefresh, setAutoRefresh] = useState<boolean>(false);
  const [loading, setLoading] = useState<boolean>(false);
  const [loadingOlder, setLoadingOlder] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [logs, setLogs] = useState<RenderLogsOut | null>(null);

  const timerRef = useRef<any>(null);

  const timeRange = useMemo(() => {
    const end = Date.now();
    const start = end - Math.max(1, minutes) * 60_000;
    return { start, end };
  }, [minutes]);

  async function loadServices() {
    setError(null);
    try {
      const r = await fetch(`/api/admin/render/services`, { method: "GET" });
      const text = await r.text();
      const j = safeJsonParse(text);

      if (!r.ok) throw new Error(`HTTP ${r.status}: ${text.slice(0, 400)}`);

      const list: RenderService[] = Array.isArray(j) ? j : (j?.services ?? []);
      setServices(list);

      if (!serviceId && list.length) {
        // Prefer vozlia services if present
        const preferred =
          list.find((s) => (s.name || "").includes("vozlia-backend")) ??
          list.find((s) => (s.name || "").includes("vozlia-control")) ??
          list[0];
        setServiceId(preferred.id);
      }
    } catch (e: any) {
      setError(e?.message ?? String(e));
    }
  }

  async function loadInstances(sid?: string) {
    const useSid = sid ?? serviceId;
    if (!useSid) {
      setInstances([]);
      setInstanceId("");
      return;
    }

    try {
      const r = await fetch(`/api/admin/render/services/${useSid}/instances`, { method: "GET" });
      const text = await r.text();
      const j = safeJsonParse(text);

      if (!r.ok) throw new Error(`HTTP ${r.status}: ${text.slice(0, 400)}`);

      const list: RenderInstance[] = Array.isArray(j) ? j : (j?.instances ?? []);
      setInstances(list);

      // If current instanceId no longer exists, reset to "all".
      if (instanceId && !list.find((x) => x.id === instanceId)) setInstanceId("");
    } catch (e: any) {
      // Don't hard-fail the panel if instance listing fails.
      setInstances([]);
    }
  }

  async function loadLogs(opts?: { start?: number; end?: number; append?: boolean }) {
    const sid = serviceId;
    if (!sid) return;

    const start = opts?.start ?? timeRange.start;
    const end = opts?.end ?? timeRange.end;
    const append = Boolean(opts?.append);

    if (append) setLoadingOlder(true);
    else setLoading(true);

    setError(null);

    try {
      const qs = new URLSearchParams({
        service_id: sid,
        start_ms: String(start),
        end_ms: String(end),
        limit: String(Math.max(50, limit)),
      });
      if (instanceId) qs.set("instance_id", instanceId);
      if (q.trim()) qs.set("q", q.trim());

      const r = await fetch(`/api/admin/render/logs?${qs.toString()}`, { method: "GET" });
      const text = await r.text();
      const j = safeJsonParse(text);

      if (!r.ok) throw new Error(`HTTP ${r.status}: ${text.slice(0, 800)}`);

      const out = j as RenderLogsOut;

      if (!append) {
        setLogs(out);
      } else {
        setLogs((prev) => {
          if (!prev) return out;
          const prevRows = prev.rows || [];
          const nextRows = out.rows || [];
          return {
            ...out,
            rows: [...prevRows, ...nextRows],
          };
        });
      }
    } catch (e: any) {
      setError(e?.message ?? String(e));
    } finally {
      if (append) setLoadingOlder(false);
      else setLoading(false);
    }
  }

  function exportUrl(format: "csv" | "text" | "ndjson"): string {
    const sid = serviceId;
    const start = timeRange.start;
    const end = timeRange.end;
    const qs = new URLSearchParams({
      service_id: sid,
      start_ms: String(start),
      end_ms: String(end),
      format,
    });
    if (instanceId) qs.set("instance_id", instanceId);
    if (q.trim()) qs.set("q", q.trim());
    return `/api/admin/render/logs/export?${qs.toString()}`;
  }

  useEffect(() => {
    loadServices();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!serviceId) return;
    loadInstances(serviceId);
    loadLogs();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serviceId]);

  useEffect(() => {
    // Load logs whenever the time window changes (and service is selected)
    if (serviceId) loadLogs();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [timeRange.start, timeRange.end, limit, instanceId]);

  useEffect(() => {
    if (timerRef.current) clearInterval(timerRef.current);
    if (!autoRefresh) return;

    timerRef.current = setInterval(() => loadLogs(), 10_000);

    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoRefresh, serviceId, timeRange.start, timeRange.end, limit, instanceId, q]);

  const rows = logs?.rows ?? [];

  const canLoadOlder = Boolean(logs?.has_more && logs?.next_start_ms && logs?.next_end_ms);

  return (
    <div style={{ border: "1px solid #333", borderRadius: 8, padding: 12, marginTop: 12 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
        <div style={{ fontWeight: 700 }}>Render Logs</div>

        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <label style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span>Service</span>
            <select
              value={serviceId}
              onChange={(e) => {
                setServiceId(e.target.value);
                setInstanceId("");
              }}
              style={{ minWidth: 240 }}
            >
              <option value="" disabled>
                Select…
              </option>
              {services.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name ?? s.id}
                </option>
              ))}
            </select>
          </label>

          <label style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span>Instance</span>
            <select value={instanceId} onChange={(e) => setInstanceId(e.target.value)} style={{ minWidth: 220 }}>
              <option value="">All</option>
              {instances.map((i) => (
                <option key={i.id} value={i.id}>
                  {i.name ?? i.id}
                </option>
              ))}
            </select>
          </label>

          <label style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span>Window</span>
            <input
              type="number"
              value={minutes}
              min={1}
              max={240}
              onChange={(e) => setMinutes(Number(e.target.value))}
              style={{ width: 80 }}
            />
            <span>min</span>
          </label>

          <label style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span>Limit</span>
            <input
              type="number"
              value={limit}
              min={50}
              max={2000}
              onChange={(e) => setLimit(Number(e.target.value))}
              style={{ width: 90 }}
            />
          </label>

          <label style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span>Search</span>
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="text filter"
              style={{ width: 220 }}
            />
          </label>

          <button onClick={() => loadLogs()} disabled={!serviceId || loading} style={{ padding: "6px 10px" }}>
            {loading ? "Refreshing…" : "Refresh"}
          </button>

          <button onClick={() => loadServices()} style={{ padding: "6px 10px" }}>
            Reload services
          </button>

          <label style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <input type="checkbox" checked={autoRefresh} onChange={(e) => setAutoRefresh(e.target.checked)} />
            <span>Auto refresh</span>
          </label>

          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span>Export</span>
            <a href={exportUrl("csv")} target="_blank" rel="noreferrer" style={{ textDecoration: "underline" }}>
              CSV
            </a>
            <a href={exportUrl("text")} target="_blank" rel="noreferrer" style={{ textDecoration: "underline" }}>
              Text
            </a>
            <a href={exportUrl("ndjson")} target="_blank" rel="noreferrer" style={{ textDecoration: "underline" }}>
              NDJSON
            </a>
          </div>
        </div>
      </div>

      {error ? (
        <div style={{ marginTop: 10, color: "#ff6b6b", whiteSpace: "pre-wrap" }}>{error}</div>
      ) : null}

      <div style={{ marginTop: 10, fontSize: 12, opacity: 0.85, display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <div>
          Showing {rows.length} log rows{logs?.has_more ? " (more available)" : ""}.
        </div>
        {canLoadOlder ? (
          <button
            onClick={() => loadLogs({ start: logs!.next_start_ms!, end: logs!.next_end_ms!, append: true })}
            disabled={loadingOlder}
            style={{ padding: "4px 8px" }}
          >
            {loadingOlder ? "Loading older…" : "Load older"}
          </button>
        ) : null}
      </div>

      <pre
        style={{
          marginTop: 10,
          maxHeight: 520,
          overflow: "auto",
          background: "#0b0b0b",
          color: "#e5e7eb",
          border: "1px solid #222",
          borderRadius: 8,
          padding: 10,
          fontSize: 12,
          fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace',
          lineHeight: 1.35,
          whiteSpace: "pre-wrap",
          wordBreak: "break-word",
        }}
      >
        {rows.length
          ? rows
              .map((r) => {
                const ts = fmtTs(r.ts);
                const lvl = fmtLevel(r.level);
                const msg = r.msg || r.raw || "";
                return `${ts} ${lvl} ${msg}`.trimEnd();
              })
              .join("\n")
          : "No logs in the selected window."}
      </pre>
    </div>
  );
}