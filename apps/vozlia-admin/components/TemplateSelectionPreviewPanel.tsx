import { useMemo, useState } from "react";

type TemplateItem = {
  id: string;
  name: string;
  summary?: string;
  customer_opening?: string;
  handoff_policy?: string;
  tone?: string;
};

type TemplatesResponse = {
  templates?: TemplateItem[];
  selected_template_id?: string;
};

const FALLBACK_TEMPLATES: TemplateItem[] = [
  {
    id: "default-customer",
    name: "Default Customer Intake",
    summary: "General-purpose customer intake with concise lead capture.",
    customer_opening: "Thanks for calling. I can help with services, pricing, and booking requests.",
    handoff_policy: "Escalate billing disputes or legal/compliance requests.",
    tone: "friendly and concise",
  },
  {
    id: "appointments-first",
    name: "Appointments First",
    summary: "Prioritizes booking intent and availability collection.",
    customer_opening: "I can help schedule your visit quickly.",
    handoff_policy: "Escalate if customer asks for manager or urgent exception.",
    tone: "fast and direct",
  },
];

export default function TemplateSelectionPreviewPanel() {
  const [tenantId, setTenantId] = useState("");
  const [templates, setTemplates] = useState<TemplateItem[]>([]);
  const [selectedTemplateId, setSelectedTemplateId] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  const selected = useMemo(() => templates.find((t) => t.id === selectedTemplateId), [templates, selectedTemplateId]);

  async function loadTemplates() {
    if (!tenantId.trim()) {
      setError("tenant_id is required");
      return;
    }
    setLoading(true);
    setError(null);
    setInfo(null);
    try {
      const res = await fetch(`/api/admin/business-templates?tenant_id=${encodeURIComponent(tenantId.trim())}`);
      const data = (await res.json()) as TemplatesResponse & { error?: string };
      if (!res.ok) {
        throw new Error(data.error || "Failed to load templates");
      }

      const list = Array.isArray(data.templates) && data.templates.length ? data.templates : FALLBACK_TEMPLATES;
      setTemplates(list);
      const nextSelected = data.selected_template_id || list[0]?.id || "";
      setSelectedTemplateId(nextSelected);
      if (!Array.isArray(data.templates) || data.templates.length === 0) {
        setInfo("Loaded fallback preview templates because backend template list was empty.");
      }
    } catch (e: unknown) {
      setTemplates(FALLBACK_TEMPLATES);
      setSelectedTemplateId(FALLBACK_TEMPLATES[0].id);
      setError((e as Error)?.message || String(e));
      setInfo("Using fallback preview templates. Backend list fetch failed.");
    } finally {
      setLoading(false);
    }
  }

  async function saveSelection() {
    if (!tenantId.trim() || !selectedTemplateId) {
      setError("tenant_id and selected template are required");
      return;
    }
    setSaving(true);
    setError(null);
    setInfo(null);
    try {
      const res = await fetch("/api/admin/business-templates", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tenant_id: tenantId.trim(), selected_template_id: selectedTemplateId }),
      });
      const data = (await res.json()) as { error?: string };
      if (!res.ok) {
        throw new Error(data.error || "Failed to save template selection");
      }
      setInfo("Template selection saved.");
    } catch (e: unknown) {
      setError((e as Error)?.message || String(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="panel">
      <div className="panelTitle">Template Selection + Preview</div>
      <div className="panelSub">TASK-0237. Select customer-mode template and preview prompt behavior before saving.</div>

      <div className="field" style={{ marginTop: 12 }}>
        <div className="fieldLabel">Tenant ID</div>
        <input className="input mono" value={tenantId} onChange={(e) => setTenantId(e.target.value)} placeholder="tenant_demo" />
        <div className="actions" style={{ marginTop: 10 }}>
          <button type="button" className="btnSecondary" onClick={loadTemplates} disabled={loading || !tenantId.trim()}>
            {loading ? "Loading…" : "Load Templates"}
          </button>
        </div>
      </div>

      <div className="field" style={{ marginTop: 12 }}>
        <div className="fieldLabel">Template</div>
        <select className="input" value={selectedTemplateId} onChange={(e) => setSelectedTemplateId(e.target.value)}>
          {templates.map((tpl) => (
            <option key={tpl.id} value={tpl.id}>
              {tpl.name} ({tpl.id})
            </option>
          ))}
        </select>
      </div>

      <div className="panelInset" style={{ marginTop: 12 }}>
        <div className="panelTitle">Preview</div>
        {selected ? (
          <div className="form" style={{ marginTop: 8 }}>
            <div className="field">
              <div className="fieldLabel">Summary</div>
              <div className="fieldHelper">{selected.summary || "No summary provided"}</div>
            </div>
            <div className="field">
              <div className="fieldLabel">Customer Opening</div>
              <div className="fieldHelper">{selected.customer_opening || "Not provided"}</div>
            </div>
            <div className="field">
              <div className="fieldLabel">Handoff Policy</div>
              <div className="fieldHelper">{selected.handoff_policy || "Not provided"}</div>
            </div>
            <div className="field">
              <div className="fieldLabel">Tone</div>
              <div className="fieldHelper">{selected.tone || "Not provided"}</div>
            </div>
          </div>
        ) : (
          <div className="muted">Load templates to preview.</div>
        )}
      </div>

      {error ? <div className="alert" style={{ marginTop: 12 }}><div className="alertTitle">Template Error</div><div className="alertBody">{error}</div></div> : null}
      {info ? <div className="muted" style={{ marginTop: 12 }}>{info}</div> : null}

      <div className="actions" style={{ marginTop: 12 }}>
        <button type="button" className="btnPrimary" onClick={saveSelection} disabled={saving || !tenantId.trim() || !selectedTemplateId}>
          {saving ? "Saving…" : "Save Template Selection"}
        </button>
      </div>

      <div className="panelInset" style={{ marginTop: 12 }}>
        <div className="panelSub">
          API contract assumption: <span className="mono">GET/PATCH /admin/business-templates</span> via proxy <span className="mono">/api/admin/business-templates</span> with <span className="mono">tenant_id</span> and <span className="mono">selected_template_id</span>.
        </div>
      </div>
    </div>
  );
}
