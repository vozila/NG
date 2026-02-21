import { useMemo, useState } from "react";

type WizardMsg = {
  role: "user" | "assistant";
  text: string;
};

type WizardResponse = {
  reply?: string;
  goal_draft?: {
    name?: string;
    objective?: string;
    cadence?: string;
  };
  preview?: {
    name?: string;
    objective?: string;
    cadence?: string;
  };
  goal_id?: string;
  status?: string;
};

export default function GoalsWizardPanel() {
  const [tenantId, setTenantId] = useState("");
  const [message, setMessage] = useState("");
  const [chat, setChat] = useState<WizardMsg[]>([]);
  const [draft, setDraft] = useState<WizardResponse["goal_draft"] | null>(null);
  const [pendingGoalId, setPendingGoalId] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  const canApprove = useMemo(() => !!tenantId.trim() && (!!pendingGoalId || !!draft), [tenantId, pendingGoalId, draft]);

  async function askWizard() {
    const text = message.trim();
    if (!tenantId.trim()) {
      setError("tenant_id is required");
      return;
    }
    if (!text) return;

    setError(null);
    setInfo(null);
    setLoading(true);
    setChat((prev) => [...prev, { role: "user", text }]);
    setMessage("");

    try {
      const res = await fetch("/api/admin/goals/wizard/turn", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          tenant_id: tenantId.trim(),
          message: text,
          messages: [...chat, { role: "user", text }].map((m) => ({ role: m.role, content: m.text })),
        }),
      });
      const data = (await res.json()) as WizardResponse & { error?: string; detail?: string };
      if (!res.ok) throw new Error(data.error || data.detail || "Wizard request failed");

      setChat((prev) => [...prev, { role: "assistant", text: data.reply || "(no reply)" }]);
      setDraft(data.goal_draft || data.preview || null);
      if (data.goal_id) setPendingGoalId(data.goal_id);
    } catch (e: unknown) {
      setError((e as Error)?.message || String(e));
      setChat((prev) => [...prev, { role: "assistant", text: `Error: ${String((e as Error)?.message || e)}` }]);
    } finally {
      setLoading(false);
    }
  }

  async function approveGoal() {
    if (!tenantId.trim()) {
      setError("tenant_id is required");
      return;
    }

    setLoading(true);
    setError(null);
    setInfo(null);
    try {
      const payload = pendingGoalId
        ? { tenant_id: tenantId.trim(), goal_id: pendingGoalId }
        : { tenant_id: tenantId.trim(), goal_draft: draft };

      const res = await fetch("/api/admin/goals/wizard/approve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = (await res.json()) as { error?: string; goal_id?: string; status?: string };
      if (!res.ok) throw new Error(data.error || "Goal approval failed");
      const gid = data.goal_id || pendingGoalId;
      setPendingGoalId(gid || "");
      setInfo(`Goal approved${gid ? `: ${gid}` : ""}.`);
    } catch (e: unknown) {
      setError((e as Error)?.message || String(e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="panel">
      <div className="panelTitle">Chat Wizard</div>
      <div className="panelSub">TASK-0256. Chat-driven goal drafting and approval flow.</div>

      <div className="field" style={{ marginTop: 12 }}>
        <div className="fieldLabel">Tenant ID</div>
        <input className="input mono" value={tenantId} onChange={(e) => setTenantId(e.target.value)} placeholder="tenant_demo" />
      </div>

      <div className="panelInset" style={{ marginTop: 12 }}>
        <div className="panelTitle">Wizard Chat</div>
        <div className="list" style={{ marginTop: 10 }}>
          {chat.length === 0 ? <div className="muted">Start by describing your goal in plain language.</div> : null}
          {chat.map((m, i) => (
            <div key={`${m.role}-${i}`} className="listItem" style={{ flexDirection: "column", alignItems: "flex-start" }}>
              <div className="fieldLabel">{m.role === "user" ? "You" : "Vozlia"}</div>
              <div className="fieldHelper" style={{ whiteSpace: "pre-wrap" }}>{m.text}</div>
            </div>
          ))}
        </div>

        <div className="field" style={{ marginTop: 10 }}>
          <input
            className="input"
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                askWizard().catch(() => null);
              }
            }}
            placeholder="Example: Create a daily follow-up goal for missed calls at 8:00 AM ET"
          />
        </div>

        <div className="actions" style={{ marginTop: 10 }}>
          <button type="button" className="btnSecondary" onClick={() => askWizard().catch(() => null)} disabled={loading || !message.trim() || !tenantId.trim()}>
            {loading ? "Running…" : "Send"}
          </button>
        </div>
      </div>

      <div className="panelInset" style={{ marginTop: 12 }}>
        <div className="panelTitle">Draft Preview</div>
        {!draft ? (
          <div className="muted" style={{ marginTop: 8 }}>No goal draft yet.</div>
        ) : (
          <div className="form" style={{ marginTop: 8 }}>
            <div className="field"><div className="fieldLabel">Name</div><div className="fieldHelper">{draft.name || "-"}</div></div>
            <div className="field"><div className="fieldLabel">Objective</div><div className="fieldHelper">{draft.objective || "-"}</div></div>
            <div className="field"><div className="fieldLabel">Cadence</div><div className="fieldHelper">{draft.cadence || "-"}</div></div>
          </div>
        )}

        <div className="actions" style={{ marginTop: 10 }}>
          <button type="button" className="btnPrimary" onClick={() => approveGoal().catch(() => null)} disabled={loading || !canApprove}>
            {loading ? "Approving…" : "Approve Goal"}
          </button>
        </div>
      </div>

      {error ? <div className="alert" style={{ marginTop: 12 }}><div className="alertTitle">Wizard Error</div><div className="alertBody">{error}</div></div> : null}
      {info ? <div className="muted" style={{ marginTop: 12 }}>{info}</div> : null}
    </div>
  );
}
