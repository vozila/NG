import React, { useMemo, useRef, useState } from "react";

type KBSource = {
  file_id: string;
  filename?: string | null;
  content_type?: string | null;
  kind?: string | null;
  chunk_index?: number | null;
  snippet?: string | null;
  score?: number | null;
};

type KBQueryMode = "retrieve" | "answer";

type KBQueryResp = {
  ok?: boolean;
  tenant_id?: string;
  mode?: KBQueryMode;
  retrieval_strategy?: string | null;
  answer?: string | null;
  sources?: KBSource[];
  policy_chars?: number | null;
  context_chars?: number | null;
  model?: string | null;
  latency_ms?: number | null;
  detail?: string;
  error?: string;
};

type ChatMsg =
  | { role: "user"; text: string }
  | { role: "assistant"; text: string; meta?: { retrieval_strategy?: string | null; model?: string | null; latency_ms?: number | null }; sources?: KBSource[] }
  | { role: "system"; text: string };

function safeJsonParse<T>(t: string): T | null {
  try {
    return JSON.parse(t) as T;
  } catch {
    return null;
  }
}

function formatScore(x?: number | null): string {
  if (x === null || x === undefined) return "";
  const v = Math.round(x * 1000) / 1000;
  return String(v);
}

export function KBChatPanel({ tenantId }: { tenantId: string }) {
  const [mode, setMode] = useState<KBQueryMode>("answer");
  const [includePolicy, setIncludePolicy] = useState<boolean>(true);
  const [limit, setLimit] = useState<number>(12);

  const [input, setInput] = useState<string>("");
  const [busy, setBusy] = useState<boolean>(false);
  const [err, setErr] = useState<string>("");

  const [msgs, setMsgs] = useState<ChatMsg[]>([
    {
      role: "system",
      text:
        "Ask questions about uploaded + ingested KB files for this tenant. Answers are grounded in sources returned below each response.",
    },
  ]);

  const canQuery = useMemo(() => !!tenantId && !!tenantId.trim(), [tenantId]);
  const listEndRef = useRef<HTMLDivElement | null>(null);

  function scrollToBottom() {
    try {
      listEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
    } catch {
      // ignore
    }
  }

  async function send() {
    setErr("");
    const q = input.trim();
    if (!q) return;
    if (!canQuery) {
      setErr("Select an email account / tenant_id first (above).");
      return;
    }

    setBusy(true);
    setMsgs((prev) => [...prev, { role: "user", text: q }]);
    setInput("");

    try {
      const r = await fetch("/api/admin/kb/query", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          tenant_id: tenantId.trim(),
          query: q,
          mode,
          limit,
          include_policy: includePolicy,
        }),
      });

      const t = await r.text();
      const j = safeJsonParse<KBQueryResp>(t);

      if (!r.ok) {
        const msg = j?.detail || j?.error || t || `HTTP ${r.status}`;
        throw new Error(msg);
      }
      if (!j?.ok) {
        const msg = j?.detail || j?.error || "Query failed";
        throw new Error(msg);
      }

      if (mode === "retrieve") {
        const n = (j.sources || []).length;
        const text = n
          ? `Retrieved ${n} source chunk${n === 1 ? "" : "s"} (strategy: ${j.retrieval_strategy || "unknown"}).`
          : `No sources found. Try a more specific query, or ensure files are ingested. (strategy: ${j.retrieval_strategy || "unknown"})`;

        setMsgs((prev) => [
          ...prev,
          {
            role: "assistant",
            text,
            meta: { retrieval_strategy: j.retrieval_strategy || null, model: j.model || null, latency_ms: j.latency_ms || null },
            sources: j.sources || [],
          },
        ]);
      } else {
        const answer = (j.answer || "").trim() || "(No answer returned.)";
        setMsgs((prev) => [
          ...prev,
          {
            role: "assistant",
            text: answer,
            meta: { retrieval_strategy: j.retrieval_strategy || null, model: j.model || null, latency_ms: j.latency_ms || null },
            sources: j.sources || [],
          },
        ]);
      }
    } catch (e: any) {
      setErr(e?.message || String(e));
      setMsgs((prev) => [...prev, { role: "assistant", text: "Sorry — I couldn’t complete that KB query. See the error above and try again." }]);
    } finally {
      setBusy(false);
      setTimeout(scrollToBottom, 50);
    }
  }

  return (
    <div className="panel" style={{ marginTop: 16 }}>
      <div className="panelTitle">KB Chat</div>
      <div className="panelSub">
        ChatGPT-style Q&A grounded in the tenant Knowledge Base. Make sure files are <b>ingested</b> (chunked) before expecting answers.
      </div>

      {!canQuery ? (
        <div className="help" style={{ marginTop: 10 }}>
          Select an email account / tenant_id in the KB Files panel above to enable chat.
        </div>
      ) : null}

      <div className="form" style={{ marginTop: 12 }}>
        <div className="grid3" style={{ alignItems: "end" }}>
          <div className="field">
            <label className="label">Mode</label>
            <select className="select" value={mode} onChange={(e) => setMode(e.target.value as KBQueryMode)}>
              <option value="answer">answer (recommended)</option>
              <option value="retrieve">retrieve (debug)</option>
            </select>
          </div>

          <div className="field">
            <label className="label">Limit</label>
            <select className="select" value={String(limit)} onChange={(e) => setLimit(parseInt(e.target.value, 10) || 12)}>
              <option value="6">6</option>
              <option value="8">8</option>
              <option value="12">12</option>
              <option value="16">16</option>
            </select>
          </div>

          <div className="field" style={{ display: "flex", gap: 10, alignItems: "center" }}>
            <label className="label" style={{ marginBottom: 0 }}>
              <input
                type="checkbox"
                checked={includePolicy}
                onChange={(e) => setIncludePolicy(e.target.checked)}
                style={{ marginRight: 8 }}
              />
              include policy docs
            </label>
          </div>
        </div>

        <div style={{ marginTop: 10 }}>
          {err ? <div className="error">{err}</div> : null}
        </div>

        <div
          style={{
            marginTop: 10,
            border: "1px solid rgba(15,23,42,0.12)",
            borderRadius: 10,
            padding: 10,
            maxHeight: 380,
            overflowY: "auto",
            background: "rgba(255,255,255,0.55)",
          }}
        >
          {msgs.map((m, idx) => (
            <div key={idx} style={{ marginBottom: 12 }}>
              <div style={{ fontWeight: 700, marginBottom: 4, opacity: 0.8 }}>
                {m.role === "user" ? "You" : m.role === "assistant" ? "KB Assistant" : "System"}
              </div>
              <div style={{ whiteSpace: "pre-wrap", lineHeight: 1.35 }}>{m.text}</div>

              {"meta" in m && m.meta ? (
                <div className="help" style={{ marginTop: 6 }}>
                  {m.meta.retrieval_strategy ? `strategy: ${m.meta.retrieval_strategy}` : null}
                  {m.meta.model ? ` • model: ${m.meta.model}` : null}
                  {m.meta.latency_ms !== null && m.meta.latency_ms !== undefined ? ` • latency_ms: ${Math.round(m.meta.latency_ms)}` : null}
                </div>
              ) : null}

              {"sources" in m && m.sources && m.sources.length ? (
                <div style={{ marginTop: 8 }}>
                  <div className="help" style={{ fontWeight: 700 }}>
                    Sources
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 6 }}>
                    {m.sources.slice(0, limit).map((s, i) => (
                      <div
                        key={i}
                        style={{
                          border: "1px solid rgba(15,23,42,0.10)",
                          borderRadius: 10,
                          padding: 8,
                          background: "rgba(255,255,255,0.7)",
                        }}
                      >
                        <div style={{ fontWeight: 700 }}>
                          {s.filename || s.file_id}
                          {s.chunk_index !== null && s.chunk_index !== undefined ? ` #${s.chunk_index}` : ""}
                          {s.kind ? ` • ${s.kind}` : ""}
                          {s.score !== null && s.score !== undefined ? ` • score ${formatScore(s.score)}` : ""}
                        </div>
                        <div className="help" style={{ marginTop: 3 }}>
                          {s.content_type || ""}
                        </div>
                        <div style={{ marginTop: 6, whiteSpace: "pre-wrap" }}>{(s.snippet || "").trim()}</div>
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}
            </div>
          ))}
          <div ref={listEndRef} />
        </div>

        <div style={{ marginTop: 10, display: "flex", gap: 10 }}>
          <input
            className="input"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={canQuery ? "Ask a question about this tenant’s KB…" : "Select tenant_id above…"}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send().catch(() => {});
              }
            }}
            disabled={!canQuery || busy}
          />
          <button type="button" className="btnPrimary" onClick={send} disabled={!canQuery || busy || !input.trim()}>
            {busy ? "Asking…" : "Send"}
          </button>
        </div>

        <div className="help" style={{ marginTop: 8 }}>
          Tip: For best results, ask specific questions like “What is the cancellation policy?” or “What’s the service call fee?” and upload a policy doc
          as <span className="mono">kind=policy</span>.
        </div>
      </div>
    </div>
  );
}
