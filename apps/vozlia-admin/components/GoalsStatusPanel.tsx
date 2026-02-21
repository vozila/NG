import { useState } from "react";

type GoalRow = {
  id: string;
  name?: string;
  status?: string;
  next_run_at?: string | null;
  last_outcome?: string | null;
  playbook_id?: string | null;
};

type GoalsResponse = {
  items?: GoalRow[];
};

type Props = {
  onSelectPlaybook: (playbookId: string) => void;
};

function fmt(v?: string | null): string {
  if (!v) return "-";
  return v.replace("T", " ").replace("Z", "");
}

export default function GoalsStatusPanel({ onSelectPlaybook }: Props) {
  const [tenantId, setTenantId] = useState("");
  const [loading, setLoading] = useState(false);
  const [actingId, setActingId] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const [rows, setRows] = useState<GoalRow[]>([]);

  async function loadGoals() {
    if (!tenantId.trim()) {
      setError("tenant_id is required");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const qs = new URLSearchParams({ tenant_id: tenantId.trim(), limit: "50" });
      const res = await fetch(`/api/admin/goals?${qs.toString()}`);
      const data = (await res.json()) as GoalsResponse & { error?: string; detail?: string };
      if (!res.ok) throw new Error(data.error || data.detail || "Failed to load goals");
      setRows(Array.isArray(data.items) ? data.items : []);
    } catch (e: unknown) {
      setError((e as Error)?.message || String(e));
      setRows([]);
    } finally {
      setLoading(false);
    }
  }

  async function patchGoal(id: string, action: "pause" | "resume") {
    setActingId(id);
    setError(null);
    try {
      const res = await fetch(`/api/admin/goals/${encodeURIComponent(id)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action }),
      });
      const data = (await res.json()) as { error?: string; detail?: string };
      if (!res.ok) throw new Error(data.error || data.detail || `Failed to ${action} goal`);

      setRows((prev) => prev.map((r) => (r.id === id ? { ...r, status: action === "pause" ? "paused" : "active" } : r)));
    } catch (e: unknown) {
      setError((e as Error)?.message || String(e));
    } finally {
      setActingId("");
    }
  }

  return (
    <div className="panel">
      <div className="panelTitle">Goals Page</div>
      <div className="panelSub">TASK-0257. Goal status list with next run and last outcome.</div>

      <div className="field" style={{ marginTop: 12 }}>
        <div className="fieldLabel">Tenant ID</div>
        <input className="input mono" value={tenantId} onChange={(e) => setTenantId(e.target.value)} placeholder="tenant_demo" />
      </div>

      <div className="actions" style={{ marginTop: 10 }}>
        <button type="button" className="btnSecondary" onClick={() => loadGoals().catch(() => null)} disabled={loading || !tenantId.trim()}>
          {loading ? "Loading…" : "Load Goals"}
        </button>
      </div>

      {error ? <div className="alert" style={{ marginTop: 12 }}><div className="alertTitle">Goals Error</div><div className="alertBody">{error}</div></div> : null}

      <div className="list" style={{ marginTop: 12 }}>
        {rows.length === 0 ? <div className="muted">No goals loaded yet.</div> : null}
        {rows.map((g) => (
          <div key={g.id} className="rowCard" style={{ alignItems: "flex-start", gap: 10 }}>
            <div style={{ minWidth: 0, flex: 1 }}>
              <div className="rowTitle">{g.name || g.id}</div>
              <div className="rowSub mono">id: {g.id}</div>
              <div className="rowSub">status: {g.status || "-"}</div>
              <div className="rowSub">next run: {fmt(g.next_run_at)}</div>
              <div className="rowSub">last outcome: {g.last_outcome || "-"}</div>
              <div className="rowSub">playbook: {g.playbook_id || "-"}</div>
            </div>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              <button type="button" className="btnSecondary" disabled={actingId === g.id} onClick={() => patchGoal(g.id, "pause").catch(() => null)}>
                {actingId === g.id ? "Applying…" : "Pause"}
              </button>
              <button type="button" className="btnPrimary" disabled={actingId === g.id} onClick={() => patchGoal(g.id, "resume").catch(() => null)}>
                {actingId === g.id ? "Applying…" : "Resume"}
              </button>
              {g.playbook_id ? (
                <button type="button" className="btnSecondary" onClick={() => onSelectPlaybook(g.playbook_id as string)}>
                  View Playbook
                </button>
              ) : null}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
