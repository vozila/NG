import { useMemo, useState } from "react";

type OcrResponse = {
  job_id?: string;
  status?: string;
  extracted?: Record<string, unknown>;
  review_required?: boolean;
};

function asPretty(v: unknown): string {
  if (v == null) return "";
  if (typeof v === "string") return v;
  try {
    return JSON.stringify(v, null, 2);
  } catch {
    return String(v);
  }
}

export default function OcrUploadReviewPanel() {
  const [tenantId, setTenantId] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<OcrResponse | null>(null);

  const extractedRows = useMemo(() => {
    if (!result?.extracted) return [];
    return Object.entries(result.extracted);
  }, [result]);

  async function toBase64(input: File): Promise<string> {
    const reader = new FileReader();
    return await new Promise((resolve, reject) => {
      reader.onerror = () => reject(reader.error || new Error("Failed to read file"));
      reader.onload = () => {
        const raw = String(reader.result || "");
        const marker = "base64,";
        const idx = raw.indexOf(marker);
        if (idx < 0) {
          reject(new Error("Could not parse base64 payload"));
          return;
        }
        resolve(raw.slice(idx + marker.length));
      };
      reader.readAsDataURL(input);
    });
  }

  async function submitFile() {
    if (!tenantId.trim()) {
      setError("tenant_id is required");
      return;
    }
    if (!file) {
      setError("Select an image or PDF first");
      return;
    }

    setUploading(true);
    setError(null);
    setResult(null);

    try {
      const contentBase64 = await toBase64(file);
      const res = await fetch("/api/admin/ocr-ingest", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          tenant_id: tenantId.trim(),
          filename: file.name,
          content_type: file.type || "application/octet-stream",
          content_base64: contentBase64,
        }),
      });

      const data = (await res.json()) as OcrResponse & { error?: string };
      if (!res.ok) {
        throw new Error(data.error || "OCR ingest failed");
      }
      setResult(data);
    } catch (e: unknown) {
      setError((e as Error)?.message || String(e));
    } finally {
      setUploading(false);
    }
  }

  return (
    <div className="panel">
      <div className="panelTitle">OCR Upload + Review</div>
      <div className="panelSub">TASK-0238. Upload business docs, run OCR ingest, and review extracted fields before operator acceptance.</div>

      <div className="form" style={{ marginTop: 12 }}>
        <div className="field">
          <div className="fieldLabel">Tenant ID</div>
          <input className="input mono" value={tenantId} onChange={(e) => setTenantId(e.target.value)} placeholder="tenant_demo" />
        </div>

        <div className="field">
          <div className="fieldLabel">Document File</div>
          <input className="input" type="file" accept="image/*,.pdf" onChange={(e) => setFile(e.target.files?.[0] || null)} />
          <div className="fieldHelper">Accepted: images and PDF. File is base64-encoded and sent to the portal OCR proxy.</div>
        </div>
      </div>

      <div className="actions" style={{ marginTop: 12 }}>
        <button type="button" className="btnPrimary" onClick={submitFile} disabled={uploading || !tenantId.trim() || !file}>
          {uploading ? "Uploading…" : "Run OCR Ingest"}
        </button>
      </div>

      {error ? <div className="alert" style={{ marginTop: 12 }}><div className="alertTitle">OCR Error</div><div className="alertBody">{error}</div></div> : null}

      {result ? (
        <div className="panelInset" style={{ marginTop: 12 }}>
          <div className="panelTitle">Review Result</div>
          <div className="fieldHelper" style={{ marginTop: 6 }}>
            <span className="mono">job_id={result.job_id || "(none)"}</span> · <span className="mono">status={result.status || "(unknown)"}</span> · review_required=
            <span className="mono">{String(!!result.review_required)}</span>
          </div>

          {extractedRows.length === 0 ? (
            <div className="muted" style={{ marginTop: 10 }}>No extracted fields returned.</div>
          ) : (
            <div className="list" style={{ marginTop: 10 }}>
              {extractedRows.map(([key, value]) => (
                <div key={key} className="listItem" style={{ alignItems: "flex-start", flexDirection: "column" }}>
                  <div className="fieldLabel">{key}</div>
                  <pre className="mono" style={{ margin: 0, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>{asPretty(value)}</pre>
                </div>
              ))}
            </div>
          )}
        </div>
      ) : null}

      <div className="panelInset" style={{ marginTop: 12 }}>
        <div className="panelSub">
          API contract assumption: <span className="mono">POST /admin/ocr-ingest</span> via proxy <span className="mono">/api/admin/ocr-ingest</span> with
          <span className="mono"> tenant_id, filename, content_type, content_base64</span>.
        </div>
      </div>
    </div>
  );
}
