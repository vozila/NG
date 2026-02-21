import { useMemo, useState } from "react";

type LeadRow = {
  rid: string;
  ts?: number;
  caller?: string;
  summary?: string;
  status?: string;
  score?: number;
  appt_requested?: boolean;
};

type LeadsResponse = {
  items?: LeadRow[];
};

function fmtTs(ts?: number): string {
  if (!ts) return "-";
  try {
    return new Date(ts * 1000).toISOString();
  } catch {
    return String(ts);
  }
}

export default function InboxActionsPanel() {
  const [tenantId, setTenantId] = useState("");
  const [limit, setLimit] = useState("25");
  const [loading, setLoading] = useState(false);
  const [savingRid, setSavingRid] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [rows, setRows] = useState<LeadRow[]>([]);

  const hasRows = useMemo(() => rows.length > 0, [rows]);

  async function loadLeads() {
    if (!tenantId.trim()) {
      setError("tenant_id is required");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const qs = new URLSearchParams({
        tenant_id: tenantId.trim(),
        limit: String(Number(limit) > 0 ? Number(limit) : 25),
      });
      const res = await fetch(`/api/admin/owner-inbox/leads?${qs.toString()}`);
      const data = (await res.json()) as LeadsResponse & { error?: string };
      if (!res.ok) throw new Error(data.error || "Failed to load leads");
      setRows(Array.isArray(data.items) ? data.items : []);
    } catch (e: unknown) {
      setError((e as Error)?.message || String(e));
      setRows([]);
    } finally {
      setLoading(false);
    }
  }

  async function applyAction(rid: string, action: "mark_handled" | "qualify") {
    setSavingRid(rid);
    setError(null);
    try {
      const body =
        action === "qualify"
          ? { tenant_id: tenantId.trim(), rid, action, payload: { score: 90, notes: "qualified from admin UI" } }
          : { tenant_id: tenantId.trim(), rid, action, payload: { handled: true, handled_by: "owner_ui" } };

      const res = await fetch("/api/admin/owner-inbox/actions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = (await res.json()) as { error?: string };
      if (!res.ok) throw new Error(data.error || `Failed action: ${action}`);

      setRows((prev) =>
        prev.map((row) => {
          if (row.rid !== rid) return row;
          if (action === "mark_handled") return { ...row, status: "handled" };
          return { ...row, status: "qualified", score: row.score ?? 90 };
        })
      );
    } catch (e: unknown) {
      setError((e as Error)?.message || String(e));
    } finally {
      setSavingRid(null);
    }
  }

  return (
    <div className="panel">
      <div className="panelTitle">Inbox Actions</div>
      <div className="panelSub">TASK-0246. Review leads and apply handled/qualified actions from owner inbox workflows.</div>

      <div className="form" style={{ marginTop: 12 }}>
        <div className="field">
          <div className="fieldLabel">Tenant ID</div>
          <input className="input mono" value={tenantId} onChange={(e) => setTenantId(e.target.value)} placeholder="tenant_demo" />
        </div>
        <div className="field">
          <div className="fieldLabel">Limit</div>
          <input className="input" value={limit} onChange={(e) => setLimit(e.target.value)} placeholder="25" />
        </div>
      </div>

      <div className="actions" style={{ marginTop: 12 }}>
        <button type="button" className="btnSecondary" onClick={loadLeads} disabled={loading || !tenantId.trim()}>
          {loading ? "Loading…" : "Load Leads"}
        </button>
      </div>

      {error ? (
        <div className="alert" style={{ marginTop: 12 }}>
          <div className="alertTitle">Inbox Action Error</div>
          <div className="alertBody">{error}</div>
        </div>
      ) : null}

      <div className="list" style={{ marginTop: 12 }}>
        {!hasRows ? <div className="muted">No leads loaded yet.</div> : null}
        {rows.map((row) => (
          <div key={row.rid} className="rowCard" style={{ alignItems: "flex-start", gap: 12 }}>
            <div style={{ minWidth: 0, flex: 1 }}>
              <div className="rowTitle mono">{row.rid}</div>
              <div className="rowSub">caller: {row.caller || "-"}</div>
              <div className="rowSub">status: {row.status || "new"}</div>
              <div className="rowSub">score: {row.score ?? "-"}</div>
              <div className="rowSub">appointment requested: {String(!!row.appt_requested)}</div>
              <div className="rowSub">ts: {fmtTs(row.ts)}</div>
              {row.summary ? <div className="rowSub">summary: {row.summary}</div> : null}
            </div>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              <button
                type="button"
                className="btnSecondary"
                disabled={savingRid === row.rid}
                onClick={() => applyAction(row.rid, "qualify")}
              >
                {savingRid === row.rid ? "Saving…" : "Qualify"}
              </button>
              <button
                type="button"
                className="btnPrimary"
                disabled={savingRid === row.rid}
                onClick={() => applyAction(row.rid, "mark_handled")}
              >
                {savingRid === row.rid ? "Saving…" : "Mark Handled"}
              </button>
            </div>
          </div>
        ))}
      </div>

      <div className="panelInset" style={{ marginTop: 12 }}>
        <div className="panelSub">
          API contract assumption: <span className="mono">GET /owner/inbox/leads</span> and <span className="mono">POST /owner/inbox/actions</span> via
          <span className="mono"> /api/admin/owner-inbox/*</span> proxies.
        </div>
      </div>
    </div>
  );
}
