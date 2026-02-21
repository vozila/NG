import { useState } from "react";

type ApptRow = {
  rid: string;
  ts?: number;
  caller?: string;
  preferred_time?: string;
  notes?: string;
  status?: string;
};

type ApptResponse = {
  items?: ApptRow[];
};

function fmtTs(ts?: number): string {
  if (!ts) return "-";
  try {
    return new Date(ts * 1000).toISOString();
  } catch {
    return String(ts);
  }
}

export default function AppointmentRequestsViewPanel() {
  const [tenantId, setTenantId] = useState("");
  const [limit, setLimit] = useState("25");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [rows, setRows] = useState<ApptRow[]>([]);

  async function loadRequests() {
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
      const res = await fetch(`/api/admin/owner-inbox/appt-requests?${qs.toString()}`);
      const data = (await res.json()) as ApptResponse & { error?: string };
      if (!res.ok) throw new Error(data.error || "Failed to load appointment requests");
      setRows(Array.isArray(data.items) ? data.items : []);
    } catch (e: unknown) {
      setError((e as Error)?.message || String(e));
      setRows([]);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="panel">
      <div className="panelTitle">Appointment Request View</div>
      <div className="panelSub">TASK-0248. Owner review list for appointment requests captured from calls.</div>

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
        <button type="button" className="btnSecondary" onClick={loadRequests} disabled={loading || !tenantId.trim()}>
          {loading ? "Loading…" : "Load Appointment Requests"}
        </button>
      </div>

      {error ? (
        <div className="alert" style={{ marginTop: 12 }}>
          <div className="alertTitle">Appointment View Error</div>
          <div className="alertBody">{error}</div>
        </div>
      ) : null}

      <div className="list" style={{ marginTop: 12 }}>
        {rows.length === 0 ? <div className="muted">No appointment requests loaded yet.</div> : null}
        {rows.map((row) => (
          <div key={row.rid} className="rowCard" style={{ alignItems: "flex-start", gap: 10 }}>
            <div style={{ minWidth: 0 }}>
              <div className="rowTitle mono">{row.rid}</div>
              <div className="rowSub">caller: {row.caller || "-"}</div>
              <div className="rowSub">preferred time: {row.preferred_time || "-"}</div>
              <div className="rowSub">status: {row.status || "new"}</div>
              <div className="rowSub">ts: {fmtTs(row.ts)}</div>
              {row.notes ? <div className="rowSub">notes: {row.notes}</div> : null}
            </div>
          </div>
        ))}
      </div>

      <div className="panelInset" style={{ marginTop: 12 }}>
        <div className="panelSub">
          API contract assumption: <span className="mono">GET /owner/inbox/appt_requests</span> (or equivalent) via
          <span className="mono"> /api/admin/owner-inbox/appt-requests</span> proxy.
        </div>
      </div>
    </div>
  );
}
