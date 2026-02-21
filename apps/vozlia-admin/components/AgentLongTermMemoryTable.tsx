import { useEffect, useMemo, useState } from "react";


const LS_MEMORY_BANK_OPEN = "vozlia.admin.memoryBank.open";

type MemoryRow = {
  id: string;
  created_at?: string;
  tenant_id?: string;
  caller_id?: string;
  call_sid?: string | null;
  kind?: string;
  skill_key?: string;
  text?: string;
  data_json?: any;
  tags_json?: any;
};

type ListPayload =
  | MemoryRow[]
  | {
      items?: MemoryRow[];
      rows?: MemoryRow[];
      data?: MemoryRow[];
      total?: number;
      next_offset?: number | null;
      offset?: number;
      limit?: number;
    };

// IMPORTANT: nextOffset is ALWAYS present (number|null), never undefined.
function normalizeList(payload: ListPayload): { rows: MemoryRow[]; total?: number; nextOffset: number | null } {
  if (Array.isArray(payload)) return { rows: payload, nextOffset: null };

  const anyPayload = payload as any;
  const rows =
    (Array.isArray(anyPayload?.items) && anyPayload.items) ||
    (Array.isArray(anyPayload?.rows) && anyPayload.rows) ||
    (Array.isArray(anyPayload?.data) && anyPayload.data) ||
    [];

  const total = typeof anyPayload?.total === "number" ? anyPayload.total : undefined;
  const nextOffset = typeof anyPayload?.next_offset === "number" ? anyPayload.next_offset : null;

  return { rows, total, nextOffset };
}

async function fetchJsonOrThrow<T = any>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  const text = await res.text();

  let data: any = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = null;
    }
  }

  if (!res.ok) {
    const msg =
      (data && (data.error || data.detail || data.message)) ||
      (text ? text.slice(0, 800) : res.statusText) ||
      `HTTP ${res.status}`;
    throw new Error(`${url} failed (${res.status}): ${typeof msg === "string" ? msg : JSON.stringify(msg)}`);
  }

  if (data === null) {
    // some successful endpoints might return empty body; treat as empty object
    if (!text) return {} as T;
    throw new Error(`${url} returned non-JSON (HTTP ${res.status}). First bytes:\n${text.slice(0, 800)}`);
  }

  return data as T;
}

function formatEST(input?: string): string {
  if (!input) return "—";
  const d = new Date(input);
  if (Number.isNaN(d.getTime())) return input;

  try {
    return new Intl.DateTimeFormat("en-US", {
      timeZone: "America/New_York",
      year: "numeric",
      month: "numeric",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
      second: "2-digit",
      timeZoneName: "short",
    }).format(d);
  } catch {
    // If the runtime doesn't support timeZone (rare), fall back to local.
    return d.toLocaleString();
  }
}

function csvEscape(v: any): string {
  if (v === null || v === undefined) return "";
  const s = typeof v === "string" ? v : JSON.stringify(v);
  // If it contains quotes, commas, or newlines, quote it per RFC 4180.
  if (/[",\n\r]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
  return s;
}

function rowsToCsv(rows: MemoryRow[]): string {
  const headers = [
    "created_at_est",
    "created_at_raw",
    "tenant_id",
    "caller_id",
    "call_sid",
    "skill_key",
    "kind",
    "text",
    "id",
    "tags_json",
    "data_json",
  ];

  const lines: string[] = [];
  lines.push(headers.join(","));

  for (const r of rows) {
    const createdRaw = r.created_at || "";
    const createdEst = formatEST(r.created_at);

    const line = [
      csvEscape(createdEst),
      csvEscape(createdRaw),
      csvEscape(r.tenant_id || ""),
      csvEscape(r.caller_id || ""),
      csvEscape(r.call_sid || ""),
      csvEscape(r.skill_key || ""),
      csvEscape(r.kind || ""),
      csvEscape(r.text || ""),
      csvEscape(r.id),
      csvEscape(r.tags_json),
      csvEscape(r.data_json),
    ].join(",");
    lines.push(line);
  }

  // Add UTF-8 BOM for Excel compatibility.
  return "\uFEFF" + lines.join("\n");
}

function downloadTextFile(text: string, filename: string, mime = "text/plain;charset=utf-8") {
  const blob = new Blob([text], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2500);
}

export default function AgentLongTermMemoryTable() {
  const [q, setQ] = useState("");
  const [limit, setLimit] = useState(50);
  const [offset, setOffset] = useState(0);

  // Collapsible: Memory Bank can be heavy to render and expensive to load.
  // Default is collapsed so KB Files panel is reachable without long scrolling.
  const [bankOpen, setBankOpen] = useState(false);

  useEffect(() => {
    try {
      const v = window.localStorage.getItem(LS_MEMORY_BANK_OPEN);
      if (v === "1") setBankOpen(true);
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => {
    try {
      window.localStorage.setItem(LS_MEMORY_BANK_OPEN, bankOpen ? "1" : "0");
    } catch {
      // ignore
    }
  }, [bankOpen]);


  const [rows, setRows] = useState<MemoryRow[]>([]);
  const [total, setTotal] = useState<number | undefined>(undefined);
  const [nextOffset, setNextOffset] = useState<number | null>(null);

  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());

  const [loading, setLoading] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [bulkDeleting, setBulkDeleting] = useState(false);
  const [bulkStatus, setBulkStatus] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  const [exportStatus, setExportStatus] = useState<string | null>(null);

  const [error, setError] = useState<string | null>(null);

  // Debounce search so we don't spam the API.
  const debouncedQ = useMemo(() => q.trim(), [q]);

  const pageIds = useMemo(() => rows.map((r) => r.id), [rows]);
  const allSelectedOnPage = useMemo(
    () => pageIds.length > 0 && pageIds.every((id) => selectedIds.has(id)),
    [pageIds, selectedIds]
  );

  // Clear selections when paging/filtering changes (selection is page-scoped).
  useEffect(() => {
    if (!bankOpen) return;
    setSelectedIds(new Set());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bankOpen, offset, limit, debouncedQ]);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      params.set("limit", String(limit));
      params.set("offset", String(offset));
      if (debouncedQ) params.set("q", debouncedQ);

      const payload = await fetchJsonOrThrow<ListPayload>(`/api/admin/memory/longterm?${params.toString()}`);
      const norm = normalizeList(payload);

      setRows(norm.rows);
      setTotal(norm.total);
      setNextOffset(norm.nextOffset);
    } catch (e: any) {
      setError(e?.message || String(e));
      setRows([]);
      setTotal(undefined);
      setNextOffset(null);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (!bankOpen) return;
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bankOpen, offset, limit, debouncedQ]);

  async function onDelete(id: string) {
    const ok = window.confirm("Delete this long-term memory row? This cannot be undone.");
    if (!ok) return;

    setDeletingId(id);
    setError(null);
    try {
      await fetchJsonOrThrow(`/api/admin/memory/longterm/${encodeURIComponent(id)}`, { method: "DELETE" });
      // If it was selected, remove it from selection
      setSelectedIds((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
      await load();
    } catch (e: any) {
      setError(e?.message || String(e));
    } finally {
      setDeletingId(null);
    }
  }

  async function onBulkDeleteSelected() {
    const ids = Array.from(selectedIds);
    if (ids.length === 0) return;

    const ok = window.confirm(`Delete ${ids.length} long-term memory row(s)? This cannot be undone.`);
    if (!ok) return;

    setBulkDeleting(true);
    setBulkStatus(null);
    setError(null);

    try {
      // To keep this deployment safe, we use the existing per-row DELETE endpoint.
      // (Optional server-side bulk delete can be added later, and the UI can switch to it.)
      const BATCH = 5;
      for (let i = 0; i < ids.length; i += BATCH) {
        const batch = ids.slice(i, i + BATCH);
        setBulkStatus(`Deleting ${Math.min(i + batch.length, ids.length)} / ${ids.length}…`);
        await Promise.all(
          batch.map((id) => fetchJsonOrThrow(`/api/admin/memory/longterm/${encodeURIComponent(id)}`, { method: "DELETE" }))
        );
      }

      setSelectedIds(new Set());
      setBulkStatus(`Deleted ${ids.length} row(s).`);
      await load();
    } catch (e: any) {
      setError(e?.message || String(e));
    } finally {
      setBulkDeleting(false);
      setTimeout(() => setBulkStatus(null), 2500);
    }
  }

  async function onExportCsv() {
    setExporting(true);
    setExportStatus(null);
    setError(null);

    try {
      let exportRows: MemoryRow[] = [];

      const selected = Array.from(selectedIds);
      if (selected.length > 0) {
        exportRows = rows.filter((r) => selectedIds.has(r.id));
      } else {
        // Export *matching* rows (up to a safe cap) by paging through the existing API.
        const MAX_EXPORT_ROWS = 5000;
        const PAGE = 200;

        let off = 0;
        while (exportRows.length < MAX_EXPORT_ROWS) {
          const remaining = MAX_EXPORT_ROWS - exportRows.length;
          const take = Math.min(PAGE, remaining);

          const params = new URLSearchParams();
          params.set("limit", String(take));
          params.set("offset", String(off));
          if (debouncedQ) params.set("q", debouncedQ);

          setExportStatus(`Fetching ${exportRows.length}…`);
          const payload = await fetchJsonOrThrow<ListPayload>(`/api/admin/memory/longterm?${params.toString()}`);
          const norm = normalizeList(payload);

          if (!norm.rows.length) break;
          exportRows.push(...norm.rows);

          // Prefer server-provided nextOffset; otherwise stop to avoid loops.
          if (norm.nextOffset === null) break;
          off = norm.nextOffset;

          if (norm.rows.length < take) break;
        }
      }

      const csv = rowsToCsv(exportRows);
      const dateTag = new Date().toISOString().slice(0, 10);
      const fileName =
        selectedIds.size > 0
          ? `vozlia_longterm_memory_selected_${dateTag}.csv`
          : `vozlia_longterm_memory_export_${dateTag}.csv`;

      downloadTextFile(csv, fileName, "text/csv;charset=utf-8");
      setExportStatus(`Exported ${exportRows.length} row(s).`);
    } catch (e: any) {
      setError(e?.message || String(e));
    } finally {
      setExporting(false);
      setTimeout(() => setExportStatus(null), 2500);
    }
  }

  function toggleRow(id: string, checked: boolean) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (checked) next.add(id);
      else next.delete(id);
      return next;
    });
  }

  function toggleAllOnPage(checked: boolean) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      for (const id of pageIds) {
        if (checked) next.add(id);
        else next.delete(id);
      }
      return next;
    });
  }

  return (
    <div>
      <div style={{ display: "flex", gap: 12, alignItems: "center", justifyContent: "space-between", flexWrap: "wrap" }}>
        <div className="muted">{bankOpen ? "Memory Bank expanded." : "Memory Bank collapsed (click Expand to load)."}</div>
        <button type="button" className="btnSecondary" onClick={() => setBankOpen((v) => !v)}>
          {bankOpen ? "Collapse" : "Expand"}
        </button>
      </div>

      {!bankOpen ? (
        <div className="muted" style={{ marginTop: 10 }}>
          Memory Bank is collapsed to reduce scrolling and avoid loading large tables. Click &quot;Expand&quot; to load entries.
        </div>
      ) : (
        <>
          {error ? (
            <div className="alert" style={{ marginTop: 12 }}>
              <div className="alertTitle">Memory Bank Error</div>
              <div className="alertBody">{error}</div>
            </div>
          ) : null}

          <div className="form" style={{ marginTop: 12 }}>
            <div className="field">
              <div className="fieldLabel">Search</div>
              <div className="fieldHelper">Searches across row fields (server-side if supported).</div>
              <input className="input" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search memories…" />
            </div>

            <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
              <button type="button" className="btnSecondary" onClick={() => load()} disabled={loading}>
                {loading ? "Refreshing…" : "Refresh"}
              </button>

              <button
                type="button"
                className="btnSecondary"
                onClick={() => {
                  setQ("");
                  setOffset(0);
                }}
                disabled={loading || (!q && offset === 0)}
              >
                Clear
              </button>

              <button
                type="button"
                className="btnSecondary"
                onClick={onExportCsv}
                disabled={loading || exporting || rows.length === 0}
                title={selectedIds.size > 0 ? "Exports selected rows on this page" : "Exports up to 5000 matching rows"}
              >
                {exporting ? "Exporting…" : "Export CSV"}
              </button>

              <button
                type="button"
                className="btnSecondary"
                onClick={onBulkDeleteSelected}
                disabled={loading || bulkDeleting || selectedIds.size === 0}
                title="Deletes selected rows on this page"
              >
                {bulkDeleting ? "Deleting…" : `Delete Selected (${selectedIds.size})`}
              </button>

              <div className="field" style={{ margin: 0, minWidth: 140 }}>
                <div className="fieldLabel">Rows</div>
                <select
                  className="select"
                  value={limit}
                  onChange={(e) => {
                    setLimit(Number(e.target.value));
                    setOffset(0);
                  }}
                  disabled={loading}
                >
                  <option value={25}>25</option>
                  <option value={50}>50</option>
                  <option value={100}>100</option>
                  <option value={200}>200</option>
                </select>
              </div>

              <div className="muted" style={{ paddingTop: 18 }}>
                {typeof total === "number" ? `Total: ${total}` : rows.length ? `Showing: ${rows.length}` : null}
                {selectedIds.size ? ` · Selected: ${selectedIds.size}` : null}
                {exportStatus ? ` · ${exportStatus}` : null}
                {bulkStatus ? ` · ${bulkStatus}` : null}
              </div>
            </div>
          </div>

          <div style={{ marginTop: 12, overflowX: "auto" }}>
            <table className="table">
              <thead>
                <tr>
                  <th style={{ width: 44 }}>
                    <input
                      type="checkbox"
                      checked={allSelectedOnPage}
                      onChange={(e) => toggleAllOnPage(e.target.checked)}
                      disabled={rows.length === 0}
                      aria-label="Select all rows on this page"
                    />
                  </th>
                  <th style={{ minWidth: 180 }}>Created (EST)</th>
                  <th style={{ minWidth: 220 }}>Tenant / Caller</th>
                  <th style={{ minWidth: 140 }}>Skill / Kind</th>
                  <th style={{ minWidth: 520 }}>Text</th>
                  <th style={{ minWidth: 140 }}>Actions</th>
                </tr>
              </thead>

              <tbody>
                {loading && rows.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="muted" style={{ padding: 12 }}>
                      Loading…
                    </td>
                  </tr>
                ) : rows.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="muted" style={{ padding: 12 }}>
                      No memory rows found.
                    </td>
                  </tr>
                ) : (
                  rows.map((r) => (
                    <tr key={r.id}>
                      <td>
                        <input
                          type="checkbox"
                          checked={selectedIds.has(r.id)}
                          onChange={(e) => toggleRow(r.id, e.target.checked)}
                          aria-label={`Select row ${r.id}`}
                        />
                      </td>

                      <td title={r.created_at || ""}>{formatEST(r.created_at)}</td>

                      <td>
                        <div className="mono" style={{ whiteSpace: "nowrap" }}>
                          {r.tenant_id || "—"}
                        </div>
                        <div className="mono" style={{ whiteSpace: "nowrap", marginTop: 4 }}>
                          {r.caller_id || "—"}
                        </div>
                        {r.call_sid ? (
                          <div className="muted mono" style={{ marginTop: 4 }}>
                            SID: {r.call_sid}
                          </div>
                        ) : null}
                      </td>

                      <td>
                        <div className="mono" style={{ whiteSpace: "nowrap" }}>
                          {r.skill_key || "—"}
                        </div>
                        <div className="muted" style={{ marginTop: 4 }}>
                          {r.kind || "—"}
                        </div>
                      </td>

                      {/* FIX: no truncation — wrap and show full text */}
                      <td style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere", wordBreak: "break-word" }}>
                        {r.text || "—"}
                        {r.tags_json || r.data_json ? (
                          <details style={{ marginTop: 8 }}>
                            <summary className="muted" style={{ cursor: "pointer" }}>
                              meta
                            </summary>
                            <pre style={{ marginTop: 8, fontSize: 12, whiteSpace: "pre-wrap" }}>
                              {JSON.stringify({ tags_json: r.tags_json, data_json: r.data_json }, null, 2)}
                            </pre>
                          </details>
                        ) : null}
                      </td>

                      <td>
                        <button
                          type="button"
                          className="btnSecondary"
                          onClick={() => onDelete(r.id)}
                          disabled={deletingId === r.id || bulkDeleting}
                        >
                          {deletingId === r.id ? "Deleting…" : "Delete"}
                        </button>
                        <div className="muted mono" style={{ marginTop: 6 }}>
                          {r.id}
                        </div>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginTop: 12, alignItems: "center" }}>
            <button
              type="button"
              className="btnSecondary"
              onClick={() => setOffset((o) => Math.max(0, o - limit))}
              disabled={loading || offset === 0}
            >
              Prev
            </button>

            <button
              type="button"
              className="btnSecondary"
              onClick={() => setOffset((o) => o + limit)}
              disabled={loading || (rows.length < limit && nextOffset === null)}
            >
              Next
            </button>

            <div className="muted">Offset: {offset}</div>
          </div>
        </>
      )}
    </div>
  );
}
