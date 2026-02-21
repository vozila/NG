import { useRouter } from "next/router";
import { useMemo, useState } from "react";

type InitResp = {
  doc_id: string;
  upload_url: string;
  storage_key: string;
  bucket: string;
  expires_in_seconds: number;
};

export default function UploadTokenPage() {
  const router = useRouter();
  const token = useMemo(() => {
    const t = router.query.token;
    return Array.isArray(t) ? t[0] : t;
  }, [router.query.token]);

  const [file, setFile] = useState<File | null>(null);
  const [status, setStatus] = useState<string>("");
  const [busy, setBusy] = useState(false);

  async function onUpload() {
    if (!token || typeof token !== "string") return;
    if (!file) return;

    setBusy(true);
    setStatus("Requesting upload slot…");

    try {
      const initRes = await fetch("/api/kb/upload-init", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          token,
          filename: file.name,
          content_type: file.type || "application/octet-stream",
          size_bytes: file.size,
        }),
      });

      const initText = await initRes.text();
      if (!initRes.ok) throw new Error(initText);

      const init: InitResp = JSON.parse(initText);

      setStatus("Uploading…");

      const putRes = await fetch(init.upload_url, {
        method: "PUT",
        headers: {
          "Content-Type": file.type || "application/octet-stream",
        },
        body: file,
      });

      if (!putRes.ok) {
        const t = await putRes.text();
        throw new Error(`Upload failed: ${putRes.status} ${t}`);
      }

      setStatus("Finalizing…");
      const doneRes = await fetch("/api/kb/upload-complete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token }),
      });

      const doneText = await doneRes.text();
      if (!doneRes.ok) throw new Error(doneText);

      setStatus("Upload received. You can close this page.");
    } catch (e: any) {
      setStatus(`Error: ${e?.message || String(e)}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main style={{ maxWidth: 720, margin: "40px auto", padding: 16, fontFamily: "system-ui" }}>
      <h1 style={{ fontSize: 28, marginBottom: 8 }}>Upload a document</h1>
      <p style={{ opacity: 0.8, marginBottom: 16 }}>
        Choose a PDF/DOCX/TXT file. This link expires for security.
      </p>

      <input
        type="file"
        accept=".pdf,.docx,.txt,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain"
        onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        disabled={busy}
      />

      <div style={{ marginTop: 16 }}>
        <button onClick={onUpload} disabled={!file || busy || !token} style={{ padding: "10px 14px" }}>
          {busy ? "Uploading…" : "Upload"}
        </button>
      </div>

      {status ? <pre style={{ whiteSpace: "pre-wrap", marginTop: 16 }}>{status}</pre> : null}
    </main>
  );
}
