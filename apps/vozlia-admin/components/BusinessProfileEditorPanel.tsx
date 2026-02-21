import { useState } from "react";

type BusinessProfile = {
  business_name: string;
  phone: string;
  website: string;
  address: string;
  hours: string;
  services_csv: string;
  escalation_phone: string;
  escalation_policy: string;
  voice_tone: string;
};

const EMPTY_PROFILE: BusinessProfile = {
  business_name: "",
  phone: "",
  website: "",
  address: "",
  hours: "",
  services_csv: "",
  escalation_phone: "",
  escalation_policy: "",
  voice_tone: "",
};

type ApiResponse = {
  profile?: Partial<BusinessProfile>;
  services?: string[];
};

export default function BusinessProfileEditorPanel() {
  const [tenantId, setTenantId] = useState("");
  const [profile, setProfile] = useState<BusinessProfile>(EMPTY_PROFILE);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedMsg, setSavedMsg] = useState<string | null>(null);

  function patchProfile(key: keyof BusinessProfile, value: string) {
    setProfile((prev) => ({ ...prev, [key]: value }));
  }

  async function loadProfile() {
    if (!tenantId.trim()) {
      setError("tenant_id is required");
      return;
    }
    setLoading(true);
    setError(null);
    setSavedMsg(null);
    try {
      const res = await fetch(`/api/admin/business-profile?tenant_id=${encodeURIComponent(tenantId.trim())}`);
      const data = (await res.json()) as ApiResponse;
      if (!res.ok) {
        throw new Error((data as { error?: string }).error || "Failed to load business profile");
      }
      const next = data.profile || {};
      const services = Array.isArray(data.services) ? data.services.join(", ") : next.services_csv || "";
      setProfile({
        business_name: next.business_name || "",
        phone: next.phone || "",
        website: next.website || "",
        address: next.address || "",
        hours: next.hours || "",
        services_csv: services,
        escalation_phone: next.escalation_phone || "",
        escalation_policy: next.escalation_policy || "",
        voice_tone: next.voice_tone || "",
      });
    } catch (e: unknown) {
      setError((e as Error)?.message || String(e));
    } finally {
      setLoading(false);
    }
  }

  async function saveProfile() {
    if (!tenantId.trim()) {
      setError("tenant_id is required");
      return;
    }
    setSaving(true);
    setError(null);
    setSavedMsg(null);
    try {
      const services = profile.services_csv
        .split(",")
        .map((v) => v.trim())
        .filter(Boolean);

      const payload = {
        tenant_id: tenantId.trim(),
        profile: {
          business_name: profile.business_name.trim(),
          phone: profile.phone.trim(),
          website: profile.website.trim(),
          address: profile.address.trim(),
          hours: profile.hours.trim(),
          escalation_phone: profile.escalation_phone.trim(),
          escalation_policy: profile.escalation_policy.trim(),
          voice_tone: profile.voice_tone.trim(),
        },
        services,
      };

      const res = await fetch("/api/admin/business-profile", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = (await res.json()) as { error?: string };
      if (!res.ok) {
        throw new Error(data.error || "Failed to save business profile");
      }
      setSavedMsg("Profile saved.");
    } catch (e: unknown) {
      setError((e as Error)?.message || String(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="panel">
      <div className="panelTitle">Business Profile Editor</div>
      <div className="panelSub">TASK-0236. Owner-managed profile used by customer-mode prompts and templates.</div>

      <div className="form" style={{ marginTop: 12 }}>
        <div className="field">
          <div className="fieldLabel">Tenant ID</div>
          <input className="input mono" value={tenantId} onChange={(e) => setTenantId(e.target.value)} placeholder="tenant_demo" />
          <div className="actions" style={{ marginTop: 10 }}>
            <button type="button" className="btnSecondary" onClick={loadProfile} disabled={loading || !tenantId.trim()}>
              {loading ? "Loading…" : "Load Profile"}
            </button>
          </div>
        </div>

        <div className="field">
          <div className="fieldLabel">Business Name</div>
          <input className="input" value={profile.business_name} onChange={(e) => patchProfile("business_name", e.target.value)} />
        </div>

        <div className="field">
          <div className="fieldLabel">Phone</div>
          <input className="input" value={profile.phone} onChange={(e) => patchProfile("phone", e.target.value)} />
        </div>

        <div className="field">
          <div className="fieldLabel">Website</div>
          <input className="input" value={profile.website} onChange={(e) => patchProfile("website", e.target.value)} />
        </div>

        <div className="field">
          <div className="fieldLabel">Address</div>
          <input className="input" value={profile.address} onChange={(e) => patchProfile("address", e.target.value)} />
        </div>

        <div className="field">
          <div className="fieldLabel">Hours</div>
          <textarea className="input" rows={3} value={profile.hours} onChange={(e) => patchProfile("hours", e.target.value)} placeholder="Mon-Fri 9a-6p\nSat 10a-2p" />
        </div>

        <div className="field">
          <div className="fieldLabel">Services (comma-separated)</div>
          <textarea className="input" rows={3} value={profile.services_csv} onChange={(e) => patchProfile("services_csv", e.target.value)} placeholder="Brake repair, Oil change, Tire rotation" />
        </div>

        <div className="field">
          <div className="fieldLabel">Escalation Phone</div>
          <input className="input" value={profile.escalation_phone} onChange={(e) => patchProfile("escalation_phone", e.target.value)} />
        </div>

        <div className="field">
          <div className="fieldLabel">Escalation Policy</div>
          <textarea className="input" rows={2} value={profile.escalation_policy} onChange={(e) => patchProfile("escalation_policy", e.target.value)} placeholder="Escalate billing disputes and legal requests to manager." />
        </div>

        <div className="field">
          <div className="fieldLabel">Voice Tone</div>
          <input className="input" value={profile.voice_tone} onChange={(e) => patchProfile("voice_tone", e.target.value)} placeholder="friendly, concise, no jargon" />
        </div>
      </div>

      {error ? <div className="alert" style={{ marginTop: 12 }}><div className="alertTitle">Business Profile Error</div><div className="alertBody">{error}</div></div> : null}
      {savedMsg ? <div className="muted" style={{ marginTop: 12 }}>{savedMsg}</div> : null}

      <div className="actions" style={{ marginTop: 12 }}>
        <button type="button" className="btnPrimary" onClick={saveProfile} disabled={saving || !tenantId.trim()}>
          {saving ? "Saving…" : "Save Profile"}
        </button>
      </div>

      <div className="panelInset" style={{ marginTop: 12 }}>
        <div className="panelSub">
          API contract assumption: <span className="mono">GET/PATCH /admin/business-profile</span> via portal proxy at <span className="mono">/api/admin/business-profile</span>, with <span className="mono">tenant_id</span> and profile payload.
        </div>
      </div>
    </div>
  );
}
