import React, { useEffect, useMemo, useState } from "react";
import { KBTurnConsolePanel } from "./KBTurnConsolePanel";

type KBKind = "knowledge" | "policy";

type KBFileRow = {
  id: string;
  tenant_id: string;
  kind: string;
  status: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  sha256: string;
  storage_bucket?: string | null;
  storage_key?: string | null;
  uploaded_by?: string | null;
  created_at: string;
};

type EmailAccount = {
  id: string;
  provider_type: string;
  oauth_provider?: string | null;
  email_address?: string | null;
  display_name?: string | null;
  is_primary: boolean;
  is_active: boolean;

  // Depending on Control Plane schema, tenant mapping may appear in one of these fields.
  tenant_id?: string | null;
  tenantId?: string | null;

  // Current deployed behavior: email accounts include user_id; in Vozlia today, user_id is the tenant UUID.
  user_id?: string | null;
  userId?: string | null;
};

type ListResp = { items: KBFileRow[]; has_more?: boolean; next_offset?: number | null };

type UploadTokenResp = { upload_url: string; upload_token: string; expires_in_s: number };

type DownloadTokenResp = { download_url: string; download_token: string; expires_in_s: number };

const DEFAULT_LIMIT = 50;

function formatBytes(n: number): string {
  if (!Number.isFinite(n)) return String(n);
  if (n < 1024) return `${n} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let x = n;
  let u = 0;
  while (x >= 1024 && u < units.length - 1) {
    x /= 1024;
    u += 1;
  }
  return `${x.toFixed(x >= 10 ? 1 : 2)} ${units[u]}`;
}

function safeJsonParse<T>(text: string): T | null {
  try {
    return JSON.parse(text) as T;
  } catch {
    return null;
  }
}

const LS_TENANT_KEY = "vozlia.kb.tenant_id";
const LS_EMAIL_ACCOUNT_KEY = "vozlia.kb.email_account_id";

export function KBUploadPanel() {
  const [accounts, setAccounts] = useState<EmailAccount[]>([]);
  const [accountsLoading, setAccountsLoading] = useState(false);
  const [accountsErr, setAccountsErr] = useState("");

  const [selectedEmailAccountId, setSelectedEmailAccountId] = useState<string>("");

  // tenantId is editable as a fallback (if tenant mapping isn't returned by /email-accounts).
  const [tenantId, setTenantId] = useState<string>("");

  const [kind, setKind] = useState<KBKind>("knowledge");
  const [q, setQ] = useState<string>("");

  const [items, setItems] = useState<KBFileRow[]>([]);
  const [listBusy, setListBusy] = useState(false);
  const [listErr, setListErr] = useState<string>("");

  const [file, setFile] = useState<File | null>(null);
  const [uploadBusy, setUploadBusy] = useState(false);
  const [uploadErr, setUploadErr] = useState<string>("");
  const [uploadOk, setUploadOk] = useState<string>("");

  const canQuery = useMemo(() => !!tenantId.trim(), [tenantId]);

  const selectedAccount = useMemo(
    () => accounts.find((a) => a.id === selectedEmailAccountId) || null,
    [accounts, selectedEmailAccountId],
  );

  function tenantFromAccount(a: EmailAccount | null): string {
    if (!a) return "";
    // Prefer explicit tenant_id fields, then fallback to user_id (current model behavior).
    return ((a.tenant_id || a.tenantId || a.user_id || a.userId || "") as string).toString().trim();
  }

  async function copyValue(label: string, value: string) {
    if (!value) return;
    try {
      await navigator.clipboard.writeText(value);
      setUploadOk(`Copied ${label}.`);
      setUploadErr("");
    } catch {
      // Fallback for environments where clipboard API is blocked
      window.prompt(`Copy ${label}:`, value);
    }
  }

  async function loadAccounts() {
    setAccountsLoading(true);
    setAccountsErr("");
    try {
      const r = await fetch("/api/admin/email-accounts?include_inactive=true", { method: "GET" });
      const t = await r.text();
      if (!r.ok) throw new Error(t || `HTTP ${r.status}`);

      const data = safeJsonParse<any>(t);
      const rows: EmailAccount[] = Array.isArray(data) ? data : [];
      setAccounts(rows);

      // Default selection: localStorage -> primary active -> first active -> first
      let prev = "";
      try {
        prev = window.localStorage.getItem(LS_EMAIL_ACCOUNT_KEY) || "";
      } catch {}

      const isActive = (x: EmailAccount) => x.is_active !== false;
      const byId = prev ? rows.find((x) => x.id === prev) : null;
      const primaryActive = rows.find((x) => x.is_primary && isActive(x));
      const firstActive = rows.find((x) => isActive(x));
      const chosen = (byId && isActive(byId) ? byId : null) || primaryActive || firstActive || rows[0] || null;

      if (chosen && !selectedEmailAccountId) setSelectedEmailAccountId(chosen.id);
      if (chosen && !tenantId.trim()) {
        const tid = tenantFromAccount(chosen);
        if (tid) setTenantId(tid);
      }
    } catch (e: any) {
      setAccountsErr(e?.message || String(e));
      setAccounts([]);
    } finally {
      setAccountsLoading(false);
    }
  }

  async function refresh() {
    setListErr("");
    setUploadOk("");
    setUploadErr("");

    if (!tenantId.trim()) {
      setItems([]);
      return;
    }

    setListBusy(true);
    try {
      const url = new URL("/api/admin/kb/files", window.location.origin);
      url.searchParams.set("tenant_id", tenantId.trim());
      if (q.trim()) url.searchParams.set("q", q.trim());
      url.searchParams.set("limit", String(DEFAULT_LIMIT));
      url.searchParams.set("offset", "0");

      const r = await fetch(url.toString(), { method: "GET" });
      const t = await r.text();
      if (!r.ok) throw new Error(t || `HTTP ${r.status}`);

      const json = safeJsonParse<ListResp>(t);
      if (!json) throw new Error("Invalid JSON from /api/admin/kb/files");
      setItems(json.items || []);
    } catch (e: any) {
      setItems([]);
      setListErr(e?.message || String(e));
    } finally {
      setListBusy(false);
    }
  }

  async function upload() {
    setUploadErr("");
    setUploadOk("");

    if (!tenantId.trim()) {
      setUploadErr("Select an email account / tenant first.");
      return;
    }
    if (!file) {
      setUploadErr("Choose a file first.");
      return;
    }

    setUploadBusy(true);
    try {
      const tokenRes = await fetch("/api/admin/kb/files/upload-token", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          tenant_id: tenantId.trim(),
          filename: file.name,
          content_type: file.type || "application/octet-stream",
          kind,
        }),
      });

      const tokenText = await tokenRes.text();
      if (!tokenRes.ok) throw new Error(tokenText || `HTTP ${tokenRes.status}`);
      const tokenJson = safeJsonParse<UploadTokenResp>(tokenText);
      if (!tokenJson) throw new Error("Invalid JSON from /api/admin/kb/files/upload-token");

      const fd = new FormData();
      fd.append("file", file, file.name);

      const r = await fetch(tokenJson.upload_url, {
        method: "POST",
        headers: { "X-Vozlia-Upload-Token": tokenJson.upload_token },
        body: fd,
      });

      const t = await r.text();
      if (!r.ok) throw new Error(t || `HTTP ${r.status}`);

      setUploadOk("Uploaded.");
      setFile(null);
      await refresh();
    } catch (e: any) {
      setUploadErr(e?.message || String(e));
    } finally {
      setUploadBusy(false);
    }
  }

  async function requestDownload(fileId: string) {
    setUploadErr("");
    setUploadOk("");

    if (!tenantId.trim()) {
      setUploadErr("Select an email account / tenant first.");
      return;
    }

    try {
      const url = new URL(`/api/admin/kb/files/${fileId}/download-token`, window.location.origin);
      url.searchParams.set("tenant_id", tenantId.trim());

      const r = await fetch(url.toString(), { method: "GET" });
      const t = await r.text();
      if (!r.ok) throw new Error(t || `HTTP ${r.status}`);

      const json = safeJsonParse<DownloadTokenResp>(t);
      if (!json) throw new Error("Invalid JSON from /api/admin/kb/files/{id}/download-token");

      window.open(json.download_url, "_blank", "noopener,noreferrer");
    } catch (e: any) {
      setUploadErr(e?.message || String(e));
    }
  }

  async function deleteFile(fileId: string) {
    setUploadErr("");
    setUploadOk("");

    if (!tenantId.trim()) {
      setUploadErr("Select an email account / tenant first.");
      return;
    }

    const ok = confirm("Delete this KB file? This removes the object and metadata.");
    if (!ok) return;

    try {
      const url = new URL(`/api/admin/kb/files/${fileId}`, window.location.origin);
      url.searchParams.set("tenant_id", tenantId.trim());

      const r = await fetch(url.toString(), { method: "DELETE" });
      const t = await r.text();
      if (!r.ok) throw new Error(t || `HTTP ${r.status}`);

      setUploadOk("Deleted.");
      await refresh();
    } catch (e: any) {
      setUploadErr(e?.message || String(e));
    }
  }

  // Init: restore last selection for debug UX, then load accounts
  useEffect(() => {
    try {
      const prevTenant = window.localStorage.getItem(LS_TENANT_KEY) || "";
      if (prevTenant) setTenantId(prevTenant);

      const prevEmail = window.localStorage.getItem(LS_EMAIL_ACCOUNT_KEY) || "";
      if (prevEmail) setSelectedEmailAccountId(prevEmail);
    } catch {
      // ignore
    }
    loadAccounts().catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Persist for convenience
  useEffect(() => {
    try {
      if (tenantId.trim()) window.localStorage.setItem(LS_TENANT_KEY, tenantId.trim());
    } catch {}
  }, [tenantId]);

  useEffect(() => {
    try {
      if (selectedEmailAccountId) window.localStorage.setItem(LS_EMAIL_ACCOUNT_KEY, selectedEmailAccountId);
    } catch {}
  }, [selectedEmailAccountId]);

  // When email selection changes, auto-fill tenantId if mapping exists.
  useEffect(() => {
    const tid = tenantFromAccount(selectedAccount);
    if (tid) setTenantId(tid);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedEmailAccountId]);

  // Load list once tenant becomes available
  useEffect(() => {
    if (!tenantId.trim()) return;
    refresh().catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tenantId]);

  return (
    <div className="panel" style={{ marginTop: 14 }}>
      <div className="panelTitle">KB Files</div>
      <div className="panelSub">
        Upload tenant KB documents (knowledge) and tenant policy/rules documents (policy). Uploads go WebUI → Control Plane.
      </div>

      <div className="form" style={{ marginTop: 12 }}>
        <div className="grid2">
          <div className="field">
            <label className="label">Email account</label>
            <select
              className="input"
              value={selectedEmailAccountId}
              onChange={(e) => setSelectedEmailAccountId(e.target.value)}
              disabled={accountsLoading}
            >
              <option value="">{accountsLoading ? "(loading…)" : "(select email)"}</option>
              {accounts.map((a) => {
                const email = a.email_address || a.display_name || a.id;
                const flags = [a.is_primary ? "primary" : "", !a.is_active ? "inactive" : ""].filter(Boolean).join(", ");
                const tid = tenantFromAccount(a);
                return (
                  <option key={a.id} value={a.id}>
                    {email}
                    {a.provider_type ? ` (${a.provider_type})` : ""}
                    {flags ? ` — ${flags}` : ""}
                    {tid ? ` — tenant ${tid}` : " — (no tenant mapping)"}
                  </option>
                );
              })}
            </select>
            <div className="help">
              This maps to tenant_id for KB operations. If tenant mapping is missing, paste tenant_id manually on the right.
            </div>
            {accountsErr ? <div className="error" style={{ marginTop: 8 }}>{accountsErr}</div> : null}
          </div>

          <div className="field">
            <label className="label">tenant_id</label>
            <input
              className="input mono"
              value={tenantId}
              onChange={(e) => setTenantId(e.target.value)}
              placeholder="TENANT_UUID"
              spellCheck={false}
              autoCapitalize="none"
              autoCorrect="off"
            />
            <div className="help">Required. All KB operations are tenant-scoped.</div>
          </div>
        </div>

        <div className="grid2" style={{ alignItems: "end" }}>
          <div className="field">
            <label className="label">Kind</label>
            <select className="input" value={kind} onChange={(e) => setKind(e.target.value as KBKind)}>
              <option value="knowledge">knowledge</option>
              <option value="policy">policy</option>
            </select>
            <div className="help">policy docs will later become high-priority instructions; knowledge docs become retrieval context.</div>
          </div>

          <div className="field">
            <label className="label">Search</label>
            <input className="input" value={q} onChange={(e) => setQ(e.target.value)} placeholder="filename contains…" />
            <div className="help">Optional. Search is filename-based (q=).</div>
          </div>
        </div>

        <div className="grid2" style={{ alignItems: "end" }}>
          <div className="field">
            <label className="label">File</label>
            <input className="input" type="file" onChange={(e) => setFile(e.target.files?.[0] ?? null)} disabled={uploadBusy} />
            <div className="help">
              {file ? (
                <>
                  Selected: <b>{file.name}</b> ({formatBytes(file.size)}) {file.type ? `• ${file.type}` : ""}
                </>
              ) : (
                "Choose a file to upload."
              )}
            </div>
          </div>

          <div className="actions">
            <button type="button" className="btnPrimary" onClick={upload} disabled={!canQuery || uploadBusy || !file}>
              {uploadBusy ? "Uploading…" : "Upload"}
            </button>

            <button type="button" className="btnSecondary" onClick={refresh} disabled={!canQuery || listBusy}>
              {listBusy ? "Refreshing…" : "Refresh"}
            </button>

            <button type="button" className="btnSecondary" onClick={loadAccounts} disabled={accountsLoading} style={{ marginLeft: 8 }}>
              {accountsLoading ? "Loading…" : "Reload"}
            </button>
          </div>
        </div>

        {(uploadErr || listErr || uploadOk) && (
          <div style={{ marginTop: 10 }}>
            {uploadErr ? <div className="error">{uploadErr}</div> : null}
            {listErr ? <div className="error" style={{ marginTop: 8 }}>{listErr}</div> : null}
            {uploadOk ? <div className="success" style={{ marginTop: 8 }}>{uploadOk}</div> : null}
          </div>
        )}

        <div style={{ marginTop: 8, overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th style={{ textAlign: "left", padding: 6, borderBottom: "1px solid rgba(15,23,42,0.12)" }}>Filename</th>
                <th style={{ textAlign: "left", padding: 6, borderBottom: "1px solid rgba(15,23,42,0.12)" }}>Kind</th>
                <th style={{ textAlign: "left", padding: 6, borderBottom: "1px solid rgba(15,23,42,0.12)" }}>Status</th>
                <th style={{ textAlign: "left", padding: 6, borderBottom: "1px solid rgba(15,23,42,0.12)" }}>Size</th>
                <th style={{ textAlign: "left", padding: 6, borderBottom: "1px solid rgba(15,23,42,0.12)" }}>Created</th>
                <th style={{ textAlign: "right", padding: 6, borderBottom: "1px solid rgba(15,23,42,0.12)" }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {items.map((it) => (
                <tr key={it.id}>
                  <td style={{ padding: 6, borderBottom: "1px solid rgba(15,23,42,0.08)" }}>
                    <div style={{ fontWeight: 600 }}>{it.filename}</div>
                    <div className="help" style={{ marginTop: 2 }}>
                      {it.content_type} {it.sha256 ? `• sha256 ${it.sha256.slice(0, 10)}…` : ""}
                    </div>
                    <div className="help" style={{ marginTop: 2, display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                      <span>
                        File ID: <span className="mono">{it.id}</span>
                      </span>
                      <button type="button" className="btnSecondary" onClick={() => copyValue("file id", it.id)}>
                        Copy ID
                      </button>
                    </div>
                  </td>
                  <td style={{ padding: 6, borderBottom: "1px solid rgba(15,23,42,0.08)" }}>{it.kind}</td>
                  <td style={{ padding: 6, borderBottom: "1px solid rgba(15,23,42,0.08)" }}>{it.status}</td>
                  <td style={{ padding: 6, borderBottom: "1px solid rgba(15,23,42,0.08)" }}>{formatBytes(it.size_bytes)}</td>
                  <td style={{ padding: 6, borderBottom: "1px solid rgba(15,23,42,0.08)" }}>{it.created_at ? new Date(it.created_at).toLocaleString() : ""}</td>
                  <td style={{ padding: 6, borderBottom: "1px solid rgba(15,23,42,0.08)", textAlign: "right" }}>
                    <button type="button" className="btnSecondary" onClick={() => requestDownload(it.id)} style={{ marginRight: 8 }}>
                      Download
                    </button>
                    <button type="button" className="btnSecondary" onClick={() => deleteFile(it.id)}>
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
              {!items.length ? (
                <tr>
                  <td colSpan={6} style={{ padding: 10, opacity: 0.75 }}>
                    {tenantId.trim() ? "No KB files yet." : "Select an email account (or enter a tenant_id) to list KB files."}
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
        <KBTurnConsolePanel tenantId={tenantId.trim()} />
</div>
    </div>
  );
}