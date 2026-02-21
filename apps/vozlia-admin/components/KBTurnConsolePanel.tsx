import React, { useEffect, useMemo, useRef, useState } from "react";

type CallThread = {
  call_sid: string;
  caller_id?: string | null;
  first_at: string;
  last_at: string;
  turns: number;
};

type TurnSource = {
  file_id?: string | null;
  filename?: string | null;
  kind?: string | null;
  chunk_index?: number | null;
  score?: number | null;
};

type TurnEvent = {
  id: string;
  created_at: string;
  role: "user" | "assistant" | "system" | string;
  text: string;
  call_sid?: string | null;
  sources?: TurnSource[] | null;
  data_json?: any;
};

type CallsResp = { items?: CallThread[] };
type TurnsResp = { items?: TurnEvent[]; has_more?: boolean; next_since_ms?: number | null };

function fmtDt(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleString();
  } catch {
    return iso;
  }
}

function bubbleStyle(role: string): React.CSSProperties {
  const isAssistant = role === "assistant";
  return {
    alignSelf: isAssistant ? "flex-end" : "flex-start",
    maxWidth: "85%",
    padding: "10px 12px",
    borderRadius: 10,
    border: "1px solid rgba(0,0,0,0.12)",
    background: isAssistant ? "rgba(0, 120, 255, 0.06)" : "rgba(0,0,0,0.04)",
    whiteSpace: "pre-wrap",
    overflowWrap: "anywhere",
  };
}

export function KBTurnConsolePanel({ tenantId }: { tenantId: string }) {
  const [calls, setCalls] = useState<CallThread[]>([]);
  const [selectedCall, setSelectedCall] = useState<string>("");
  const [events, setEvents] = useState<TurnEvent[]>([]);
  const [sinceMs, setSinceMs] = useState<number | null>(null);
  const [polling, setPolling] = useState<boolean>(true);
  const [loading, setLoading] = useState<boolean>(false);
  const [err, setErr] = useState<string>("");

  const scrollerRef = useRef<HTMLDivElement | null>(null);

  const canUse = (tenantId || "").trim().length > 0;
  const debugEnabled = (process.env.NEXT_PUBLIC_DEBUG_UI || "0") === "1";

  const pollMs = Math.max(500, parseInt(process.env.NEXT_PUBLIC_MEMORY_TURNS_POLL_MS || "3000", 10) || 3000);

  // Load recent calls for this tenant
  useEffect(() => {
    let cancelled = false;
    async function run() {
      if (!debugEnabled) return;
      if (!canUse) {
        setCalls([]);
        setSelectedCall("");
        setEvents([]);
        setSinceMs(null);
        return;
      }
      setErr("");
      try {
        const r = await fetch(`/api/admin/memory/calls?tenant_id=${encodeURIComponent(tenantId)}&limit=50`);
        const t = await r.text();
        if (!r.ok) throw new Error(t || `HTTP ${r.status}`);
        const data: CallsResp = JSON.parse(t);
        const items = (data.items || []).filter((c) => !!c.call_sid);
        if (cancelled) return;
        setCalls(items);
        // If nothing selected, auto-select latest
        if (!selectedCall && items.length) setSelectedCall(items[0].call_sid);
      } catch (e: any) {
        if (cancelled) return;
        setErr(e?.message || String(e));
      }
    }
    run();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tenantId, debugEnabled, canUse]);

  // Reset transcript when call changes
  useEffect(() => {
    setEvents([]);
    setSinceMs(null);
  }, [selectedCall]);

  // Poll turns
  useEffect(() => {
    if (!debugEnabled) return;
    if (!canUse || !selectedCall) return;

    let cancelled = false;
    let timer: any = null;

    async function tick() {
      if (cancelled) return;
      if (!polling) return;

      setLoading(true);
      setErr("");
      try {
        const qs = new URLSearchParams();
        qs.set("tenant_id", tenantId);
        qs.set("call_sid", selectedCall);
        qs.set("limit", "200");
        if (sinceMs !== null) qs.set("since_ms", String(sinceMs));

        const r = await fetch(`/api/admin/memory/turns?${qs.toString()}`);
        const t = await r.text();
        if (!r.ok) throw new Error(t || `HTTP ${r.status}`);

        const data: TurnsResp = JSON.parse(t);
        const newItems = data.items || [];
        if (!cancelled && newItems.length) {
          setEvents((prev) => {
            const seen = new Set(prev.map((x) => x.id));
            const merged = [...prev];
            for (const it of newItems) if (!seen.has(it.id)) merged.push(it);
            return merged;
          });
        }
        if (!cancelled && data.next_since_ms !== undefined) setSinceMs(data.next_since_ms ?? null);
      } catch (e: any) {
        if (!cancelled) setErr(e?.message || String(e));
      } finally {
        if (!cancelled) setLoading(false);
        if (!cancelled) timer = setTimeout(tick, pollMs);
      }
    }

    // start polling
    timer = setTimeout(tick, 250);

    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [tenantId, selectedCall, sinceMs, polling, pollMs, debugEnabled, canUse]);

  // Scroll to bottom on new events
  useEffect(() => {
    const el = scrollerRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [events.length]);

  if (!debugEnabled) return null;

  return (
    <div style={{ marginTop: 18, paddingTop: 12, borderTop: "1px solid rgba(0,0,0,0.08)" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, marginBottom: 10 }}>
        <div>
          <div style={{ fontWeight: 700 }}>Console Chat (Debug/Demo)</div>
          <div style={{ fontSize: 12, opacity: 0.7 }}>DB-backed turn feed (tenant-scoped). No impact on call hot path.</div>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <label style={{ fontSize: 12, display: "flex", alignItems: "center", gap: 6 }}>
            <input type="checkbox" checked={polling} onChange={(e) => setPolling(e.target.checked)} />
            Follow live
          </label>
        </div>
      </div>

      {!canUse ? (
        <div style={{ fontSize: 12, opacity: 0.75 }}>Select an email account (tenant) to view calls.</div>
      ) : (
        <>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10, flexWrap: "wrap" }}>
            <label style={{ fontSize: 12, fontWeight: 600 }}>Call:</label>
            <select
              value={selectedCall}
              onChange={(e) => setSelectedCall(e.target.value)}
              style={{ minWidth: 360, padding: "6px 8px", borderRadius: 6 }}
            >
              <option value="">Select a call…</option>
              {calls.map((c) => (
                <option key={c.call_sid} value={c.call_sid}>
                  {c.call_sid} • {c.turns} turns • {fmtDt(c.last_at)}
                </option>
              ))}
            </select>

            <button
              type="button"
              onClick={() => {
                setEvents([]);
                setSinceMs(null);
              }}
              style={{ padding: "6px 10px", borderRadius: 6 }}
              disabled={!selectedCall}
            >
              Reload
            </button>

            <div style={{ fontSize: 12, opacity: 0.75 }}>{loading ? "Updating…" : ""}</div>
          </div>

          {err ? (
            <div style={{ fontSize: 12, color: "crimson", whiteSpace: "pre-wrap" }}>{err}</div>
          ) : null}

          <div
            ref={scrollerRef}
            style={{
              border: "1px solid rgba(0,0,0,0.12)",
              borderRadius: 10,
              padding: 12,
              height: 360,
              overflowY: "auto",
              background: "rgba(255,255,255,0.65)",
            }}
          >
            {!selectedCall ? (
              <div style={{ fontSize: 12, opacity: 0.7 }}>Pick a call to view the transcript.</div>
            ) : events.length === 0 ? (
              <div style={{ fontSize: 12, opacity: 0.7 }}>No turn events yet for this call.</div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                {events.map((ev) => (
                  <div key={ev.id} style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                    <div style={{ fontSize: 11, opacity: 0.6 }}>
                      {ev.role.toUpperCase()} • {fmtDt(ev.created_at)}
                    </div>

                    <div style={bubbleStyle(ev.role)}>{ev.text}</div>

                    {ev.sources && ev.sources.length ? (
                      <div style={{ fontSize: 12, opacity: 0.8 }}>
                        <div style={{ fontWeight: 600, marginBottom: 4 }}>Sources</div>
                        <ul style={{ margin: 0, paddingLeft: 18 }}>
                          {ev.sources.map((s, idx) => (
                            <li key={idx}>
                              {(s.filename || s.file_id || "source") + (s.chunk_index !== undefined && s.chunk_index !== null ? `#chunk${s.chunk_index}` : "")}
                            </li>
                          ))}
                        </ul>
                      </div>
                    ) : null}
                  </div>
                ))}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
