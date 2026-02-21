import { useState } from "react";

type NotificationSettings = {
  sms_enabled: boolean;
  email_enabled: boolean;
  call_enabled: boolean;
  whatsapp_enabled: boolean;
  sms_to: string;
  email_to: string;
  call_to: string;
  whatsapp_to: string;
  dry_run: boolean;
};

const DEFAULTS: NotificationSettings = {
  sms_enabled: false,
  email_enabled: false,
  call_enabled: false,
  whatsapp_enabled: false,
  sms_to: "",
  email_to: "",
  call_to: "",
  whatsapp_to: "",
  dry_run: true,
};

export default function NotificationSettingsPanel() {
  const [tenantId, setTenantId] = useState("");
  const [settings, setSettings] = useState<NotificationSettings>(DEFAULTS);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  function patch<K extends keyof NotificationSettings>(key: K, value: NotificationSettings[K]) {
    setSettings((prev) => ({ ...prev, [key]: value }));
  }

  async function loadSettings() {
    if (!tenantId.trim()) {
      setError("tenant_id is required");
      return;
    }
    setLoading(true);
    setError(null);
    setInfo(null);
    try {
      const res = await fetch("/api/admin/settings");
      const data = (await res.json()) as {
        notification_settings?: Partial<NotificationSettings>;
        notify?: Partial<NotificationSettings>;
        error?: string;
      };
      if (!res.ok) throw new Error(data.error || "Failed to load settings");
      const incoming = data.notification_settings || data.notify || {};
      setSettings((prev) => ({ ...prev, ...incoming }));
    } catch (e: unknown) {
      setError((e as Error)?.message || String(e));
    } finally {
      setLoading(false);
    }
  }

  async function saveSettings() {
    if (!tenantId.trim()) {
      setError("tenant_id is required");
      return;
    }
    setSaving(true);
    setError(null);
    setInfo(null);
    try {
      const payload = {
        tenant_id: tenantId.trim(),
        notification_settings: settings,
      };
      const res = await fetch("/api/admin/settings", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = (await res.json()) as { error?: string };
      if (!res.ok) throw new Error(data.error || "Failed to save notification settings");
      setInfo("Notification settings saved.");
    } catch (e: unknown) {
      setError((e as Error)?.message || String(e));
    } finally {
      setSaving(false);
    }
  }

  async function sendTest(channel: "sms" | "email" | "call" | "whatsapp") {
    if (!tenantId.trim()) {
      setError("tenant_id is required");
      return;
    }
    setError(null);
    setInfo(null);
    try {
      const to =
        channel === "sms"
          ? settings.sms_to
          : channel === "email"
            ? settings.email_to
            : channel === "call"
              ? settings.call_to
              : settings.whatsapp_to;

      const res = await fetch(`/api/admin/notify/${channel}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          tenant_id: tenantId.trim(),
          to,
          dry_run: settings.dry_run,
          message: `[B003 test] ${channel} notification from owner settings panel`,
        }),
      });
      const data = (await res.json()) as { error?: string; status?: string; ok?: boolean };
      if (!res.ok) throw new Error(data.error || `Failed to send ${channel} test`);
      setInfo(`${channel} test sent (or planned dry_run).`);
    } catch (e: unknown) {
      setError((e as Error)?.message || String(e));
    }
  }

  return (
    <div className="panel">
      <div className="panelTitle">Notification Settings</div>
      <div className="panelSub">TASK-0247. Owner-level notification preferences and channel test actions.</div>

      <div className="form" style={{ marginTop: 12 }}>
        <div className="field">
          <div className="fieldLabel">Tenant ID</div>
          <input className="input mono" value={tenantId} onChange={(e) => setTenantId(e.target.value)} placeholder="tenant_demo" />
        </div>
      </div>

      <div className="actions" style={{ marginTop: 8 }}>
        <button type="button" className="btnSecondary" onClick={loadSettings} disabled={loading || !tenantId.trim()}>
          {loading ? "Loading…" : "Load Current Settings"}
        </button>
      </div>

      <div className="form" style={{ marginTop: 12 }}>
        <label className="checkRow"><input type="checkbox" checked={settings.sms_enabled} onChange={(e) => patch("sms_enabled", e.target.checked)} /> <span className="checkText">Enable SMS</span></label>
        <div className="field"><div className="fieldLabel">SMS To</div><input className="input" value={settings.sms_to} onChange={(e) => patch("sms_to", e.target.value)} placeholder="+15551234567" /></div>

        <label className="checkRow"><input type="checkbox" checked={settings.email_enabled} onChange={(e) => patch("email_enabled", e.target.checked)} /> <span className="checkText">Enable Email</span></label>
        <div className="field"><div className="fieldLabel">Email To</div><input className="input" value={settings.email_to} onChange={(e) => patch("email_to", e.target.value)} placeholder="owner@example.com" /></div>

        <label className="checkRow"><input type="checkbox" checked={settings.call_enabled} onChange={(e) => patch("call_enabled", e.target.checked)} /> <span className="checkText">Enable Call</span></label>
        <div className="field"><div className="fieldLabel">Call To</div><input className="input" value={settings.call_to} onChange={(e) => patch("call_to", e.target.value)} placeholder="+15551234567" /></div>

        <label className="checkRow"><input type="checkbox" checked={settings.whatsapp_enabled} onChange={(e) => patch("whatsapp_enabled", e.target.checked)} /> <span className="checkText">Enable WhatsApp</span></label>
        <div className="field"><div className="fieldLabel">WhatsApp To</div><input className="input" value={settings.whatsapp_to} onChange={(e) => patch("whatsapp_to", e.target.value)} placeholder="+15551234567" /></div>

        <label className="checkRow"><input type="checkbox" checked={settings.dry_run} onChange={(e) => patch("dry_run", e.target.checked)} /> <span className="checkText">Dry Run</span></label>
      </div>

      <div className="actions" style={{ marginTop: 12, flexWrap: "wrap" }}>
        <button type="button" className="btnPrimary" onClick={saveSettings} disabled={saving || !tenantId.trim()}>
          {saving ? "Saving…" : "Save Notification Settings"}
        </button>
        <button type="button" className="btnSecondary" onClick={() => sendTest("sms")} disabled={!tenantId.trim()}>Test SMS</button>
        <button type="button" className="btnSecondary" onClick={() => sendTest("email")} disabled={!tenantId.trim()}>Test Email</button>
        <button type="button" className="btnSecondary" onClick={() => sendTest("call")} disabled={!tenantId.trim()}>Test Call</button>
        <button type="button" className="btnSecondary" onClick={() => sendTest("whatsapp")} disabled={!tenantId.trim()}>Test WhatsApp</button>
      </div>

      {error ? (
        <div className="alert" style={{ marginTop: 12 }}>
          <div className="alertTitle">Notification Error</div>
          <div className="alertBody">{error}</div>
        </div>
      ) : null}
      {info ? <div className="muted" style={{ marginTop: 12 }}>{info}</div> : null}

      <div className="panelInset" style={{ marginTop: 12 }}>
        <div className="panelSub">
          API contract assumption: settings read/write via <span className="mono">/api/admin/settings</span>, channel dry-run tests via
          <span className="mono"> /api/admin/notify/{"{sms|email|call|whatsapp}"}</span>.
        </div>
      </div>
    </div>
  );
}
