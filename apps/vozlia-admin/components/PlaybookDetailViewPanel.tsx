import { useState } from "react";

type PlaybookDetail = {
  id: string;
  name?: string;
  status?: string;
  steps?: Array<Record<string, unknown>>;
  metadata?: Record<string, unknown>;
  [k: string]: unknown;
};

type Props = {
  selectedPlaybookId?: string;
};

function pretty(v: unknown): string {
  try {
    return JSON.stringify(v, null, 2);
  } catch {
    return String(v);
  }
}

export default function PlaybookDetailViewPanel({ selectedPlaybookId }: Props) {
  const [tenantId, setTenantId] = useState("");
  const [playbookId, setPlaybookId] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [detail, setDetail] = useState<PlaybookDetail | null>(null);

  const effectivePlaybookId = (selectedPlaybookId || playbookId || "").trim();

  async function loadDetail() {
    if (!tenantId.trim()) {
      setError("tenant_id is required");
      return;
    }
    if (!effectivePlaybookId) {
      setError("playbook_id is required");
      return;
    }

    setLoading(true);
    setError(null);
    try {
      const qs = new URLSearchParams({ tenant_id: tenantId.trim() });
      const res = await fetch(`/api/admin/playbooks/${encodeURIComponent(effectivePlaybookId)}?${qs.toString()}`);
      const data = (await res.json()) as PlaybookDetail & { error?: string; detail?: string };
      if (!res.ok) throw new Error(data.error || data.detail || "Failed to load playbook detail");
      setDetail(data);
    } catch (e: unknown) {
      setError((e as Error)?.message || String(e));
      setDetail(null);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="panel">
      <div className="panelTitle">Playbook Detail View</div>
      <div className="panelSub">TASK-0258. Read-only detail for selected playbook.</div>

      <div className="form" style={{ marginTop: 12 }}>
        <div className="field">
          <div className="fieldLabel">Tenant ID</div>
          <input className="input mono" value={tenantId} onChange={(e) => setTenantId(e.target.value)} placeholder="tenant_demo" />
        </div>
        <div className="field">
          <div className="fieldLabel">Playbook ID</div>
          <input className="input mono" value={selectedPlaybookId || playbookId} onChange={(e) => setPlaybookId(e.target.value)} placeholder="pb_xxx" />
        </div>
      </div>

      <div className="actions" style={{ marginTop: 10 }}>
        <button type="button" className="btnSecondary" onClick={() => loadDetail().catch(() => null)} disabled={loading || !tenantId.trim() || !effectivePlaybookId}>
          {loading ? "Loading…" : "Load Playbook Detail"}
        </button>
      </div>

      {error ? <div className="alert" style={{ marginTop: 12 }}><div className="alertTitle">Playbook Error</div><div className="alertBody">{error}</div></div> : null}

      {!detail ? (
        <div className="muted" style={{ marginTop: 12 }}>No playbook detail loaded yet.</div>
      ) : (
        <div className="panelInset" style={{ marginTop: 12 }}>
          <div className="field"><div className="fieldLabel">Name</div><div className="fieldHelper">{detail.name || "-"}</div></div>
          <div className="field"><div className="fieldLabel">Status</div><div className="fieldHelper">{String(detail.status || "-")}</div></div>
          <div className="field">
            <div className="fieldLabel">Steps</div>
            <pre className="mono" style={{ margin: 0, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>{pretty(detail.steps || [])}</pre>
          </div>
          <div className="field">
            <div className="fieldLabel">Raw Payload</div>
            <pre className="mono" style={{ margin: 0, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>{pretty(detail)}</pre>
          </div>
        </div>
      )}
    </div>
  );
}
