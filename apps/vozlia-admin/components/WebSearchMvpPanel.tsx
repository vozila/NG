"use client";

import { useEffect, useMemo, useRef, useState } from "react";

type WebSearchSource = {
  title: string;
  url: string;
  snippet?: string;
};

type WebSearchRunOut = {
  query: string;
  answer: string;
  sources?: WebSearchSource[];
  latency_ms?: number | null;
  model?: string | null;
};

type WebSearchSkill = {
  id: string;
  skill_key: string;
  name: string;
  query: string;
  triggers?: string[];
  enabled: boolean;
};

type WebSearchSchedule = {
  id: string;
  web_search_skill_id: string;
  enabled: boolean;
  cadence: string;
  time_of_day: string; // "HH:MM"
  timezone: string;
  channel: string;
  destination: string;
  next_run_at?: string | null;
  last_run_at?: string | null;
};

type ChatMsg = {
  role: "user" | "assistant";
  text: string;
  meta?: { model?: string | null; latency_ms?: number | null };
  sources?: WebSearchSource[];
};

function parseTriggers(raw: string): string[] {
  return (raw || "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}

function formatWhenIso(iso?: string | null): string {
  if (!iso) return "";
  return iso.replace("T", " ").replace("Z", "");
}

function safeTimeParts(timeOfDay?: string | null): { hour: string; minute: string } {
  const raw = (timeOfDay || "").trim();
  const m = raw.match(/^(\d{1,2}):(\d{2})/);
  if (!m) return { hour: "7", minute: "0" };
  return { hour: String(Number(m[1])), minute: String(Number(m[2])) };
}

function clampText(s: string, max: number): string {
  const t = (s || "").trim();
  if (t.length <= max) return t;
  return t.slice(0, max - 1) + "…";
}

function scheduleSummary(s: WebSearchSchedule | null): string {
  if (!s) return "No schedule yet";
  const enabled = s.enabled ? "On" : "Off";
  const cadence = s.cadence || "daily";
  const when = `${s.time_of_day} ${s.timezone}`;
  const chan = `${s.channel} → ${s.destination}`;
  return `${enabled} · ${cadence} · ${when} · ${chan}`;
}

export default function WebSearchMvpPanel() {
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // Chat input + optional model override.
  const [query, setQuery] = useState("");
  const [model, setModel] = useState("");

  // Most recent backend result (used by "Save as skill").
  const [runOut, setRunOut] = useState<WebSearchRunOut | null>(null);

  // Chat transcript (UI-only; source of truth is backend).
  const [chat, setChat] = useState<ChatMsg[]>([]);
  const chatEndRef = useRef<HTMLDivElement | null>(null);

  // Saved skills + schedules.
  const [skills, setSkills] = useState<WebSearchSkill[]>([]);
  const [schedules, setSchedules] = useState<WebSearchSchedule[]>([]);

  const scheduleBySkillId = useMemo(() => {
    const m = new Map<string, WebSearchSchedule>();
    for (const s of schedules) m.set(s.web_search_skill_id, s);
    return m;
  }, [schedules]);

  // "Save as skill" modal.
  const [saveOpen, setSaveOpen] = useState(false);
  const [saveName, setSaveName] = useState("");
  const [saveTriggers, setSaveTriggers] = useState("");
  const [saveShowTriggers, setSaveShowTriggers] = useState(false);

  // Skill detail modal (schedule editing).
  const [detailSkillId, setDetailSkillId] = useState<string | null>(null);
  const detailSkill = useMemo(() => skills.find((s) => s.id === detailSkillId) || null, [skills, detailSkillId]);
  const detailSchedule = useMemo(() => (detailSkillId ? scheduleBySkillId.get(detailSkillId) || null : null), [detailSkillId, scheduleBySkillId]);

  const [schedHour, setSchedHour] = useState("7");
  const [schedMinute, setSchedMinute] = useState("0");
  const [schedTimezone, setSchedTimezone] = useState("America/New_York");
  const [schedChannel, setSchedChannel] = useState("email");
  const [schedDestination, setSchedDestination] = useState("");

  useEffect(() => {
    // Keep the chat pinned to the latest messages.
    chatEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [chat, loading]);

  useEffect(() => {
    refreshLists().catch(() => null);
  }, []);

  useEffect(() => {
    // When opening a skill, prefill the schedule editor from existing schedule (if any).
    if (!detailSkillId) return;

    const s = scheduleBySkillId.get(detailSkillId) || null;
    if (s) {
      const t = safeTimeParts(s.time_of_day);
      setSchedHour(t.hour);
      setSchedMinute(t.minute);
      setSchedTimezone(s.timezone || "America/New_York");
      setSchedChannel(s.channel || "email");
      setSchedDestination(s.destination || "");
      return;
    }

    // Defaults for a new schedule.
    setSchedHour("7");
    setSchedMinute("0");
    setSchedTimezone("America/New_York");
    setSchedChannel("email");
    setSchedDestination("");
  }, [detailSkillId, scheduleBySkillId]);

  async function refreshLists() {
    const [skillsRes, schedRes] = await Promise.all([
      fetch("/api/admin/websearch/skills", { method: "GET" }),
      fetch("/api/admin/websearch/schedules", { method: "GET" }),
    ]);

    const skillsData = await skillsRes.json().catch(() => []);
    const schedData = await schedRes.json().catch(() => []);

    if (skillsRes.ok) setSkills(Array.isArray(skillsData) ? (skillsData as WebSearchSkill[]) : []);
    if (schedRes.ok) setSchedules(Array.isArray(schedData) ? (schedData as WebSearchSchedule[]) : []);
  }

  async function ask() {
    setErr(null);
    const q = query.trim();
    if (!q) return;

    // Append user's message immediately.
    setChat((prev) => [...prev, { role: "user", text: q }]);
    setQuery("");

    setLoading(true);
    try {
            const history = [...chat, { role: "user" as const, text: q }];
      const res = await fetch("/api/admin/wizard/turn", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: q,
          messages: history.map((m) => ({ role: m.role, content: m.text })),
        }),
      });

      const out = await res.json();
      if (!res.ok) throw new Error(out?.error || "Wizard request failed");

      // If the wizard executed a web search, surface citations (sources) in the UI.
      let sources: any[] = [];
      try {
        for (const a of out?.actions_executed || []) {
          if (a?.type === "websearch_run" && a?.result?.sources) {
            sources = a.result.sources;
            break;
          }
        }
      } catch {}
      const citations = Array.isArray((out as any)?.citations) ? (out as any).citations : [];

      setRunOut({
        query: q,
        answer: out.reply ?? "",
        sources,
        citations,
      } as any);

      // Refresh saved skills/schedules from the wizard response (fallback: keep existing).
      if (Array.isArray(out.websearch_skills)) setSkills(out.websearch_skills);
      if (Array.isArray(out.websearch_schedules)) setSchedules(out.websearch_schedules);

      setChat((prev) => [
        ...prev,
        {
          role: "assistant",
          text: out.reply ?? "",
          sources,
          citations,
        },
      ]);
    } catch (e: any) {
      const msg = String(e?.message ?? e);
      setErr(msg);
      setChat((prev) => [...prev, { role: "assistant", text: `Sorry — I hit an error: ${msg}` }]);
    } finally {
      setLoading(false);
    }
  }

  function openSaveSkill() {
    const q = (runOut?.query || "").trim();
    if (!q) {
      setErr("Ask a question first, then save it as a skill.");
      return;
    }
    setErr(null);
    // Reasonable defaults.
    setSaveName((prev) => prev || `WebSearch: ${clampText(q, 48)}`);
    setSaveTriggers("");
    setSaveShowTriggers(false);
    setSaveOpen(true);
  }

  async function createSkillFromLastQuestion() {
    setErr(null);
    const q = (runOut?.query || "").trim();
    if (!q) {
      setErr("Ask a question first.");
      return;
    }

    const name = (saveName || "").trim() || `WebSearch: ${clampText(q, 48)}`;
    const triggers = parseTriggers(saveTriggers);

    setLoading(true);
    try {
      const res = await fetch("/api/admin/websearch/skills", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, query: q, triggers }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error((data as any)?.detail || (data as any)?.error || "Create skill failed");

      // Refresh and open the detail modal for quick scheduling.
      await refreshLists();
      if (typeof window !== "undefined") window.dispatchEvent(new Event("vozlia:websearch-updated"));

      const createdId = (data as any)?.id as string | undefined;
      setSaveOpen(false);

      // Prefer the returned id, otherwise attempt to find by name+query after refresh.
      if (createdId) setDetailSkillId(createdId);
      else {
        const match = skills.find((s) => s.name === name && s.query === q);
        if (match) setDetailSkillId(match.id);
      }
    } catch (e: any) {
      setErr(String(e?.message ?? e));
    } finally {
      setLoading(false);
    }
  }

  async function upsertScheduleForOpenSkill() {
    setErr(null);
    if (!detailSkillId) return;

    const h = Number(schedHour);
    const m = Number(schedMinute);

    if (!Number.isFinite(h) || h < 0 || h > 23) {
      setErr("Hour must be 0–23.");
      return;
    }
    if (!Number.isFinite(m) || m < 0 || m > 59) {
      setErr("Minute must be 0–59.");
      return;
    }
    if (!schedDestination.trim()) {
      setErr("Destination is required (email or phone number).");
      return;
    }

    setLoading(true);
    try {
      const res = await fetch("/api/admin/websearch/schedules", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          web_search_skill_id: detailSkillId,
          hour: h,
          minute: m,
          timezone: schedTimezone.trim() || "America/New_York",
          channel: schedChannel,
          destination: schedDestination.trim(),
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error((data as any)?.detail || (data as any)?.error || "Schedule failed");

      await refreshLists();
      if (typeof window !== "undefined") window.dispatchEvent(new Event("vozlia:websearch-updated"));
    } catch (e: any) {
      setErr(String(e?.message ?? e));
    } finally {
      setLoading(false);
    }
  }

  async function deleteSkill(id: string) {
    if (!id) return;
    if (!confirm("Delete this skill? This cannot be undone.")) return;

    setErr(null);
    setLoading(true);
    try {
      const res = await fetch(`/api/admin/websearch/skills/${encodeURIComponent(id)}`, { method: "DELETE" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error((data as any)?.detail || (data as any)?.error || "Delete failed");
      await refreshLists();
      if (typeof window !== "undefined") window.dispatchEvent(new Event("vozlia:websearch-updated"));
      setDetailSkillId(null);
    } catch (e: any) {
      setErr(String(e?.message ?? e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="panel">
      <div className="panelTitle">Configuration Wizard</div>
      <div className="panelSub">
        Chat-first setup. Ask a question → get an answer → optionally save it as a skill → click the skill card to schedule delivery.
        <span style={{ opacity: 0.7 }}> (Currently: Web Search.)</span>
      </div>

      {err ? (
        <div className="alert" style={{ marginTop: 12 }}>
          <div className="alertTitle">Error</div>
          <div className="alertBody">{err}</div>
        </div>
      ) : null}

      {/* Chat console */}
      <div className="wizardChatShell" style={{ marginTop: 12 }}>
        <div className="wizardChatHeader">
          <div style={{ fontWeight: 900 }}>Ask Vozlia</div>
          <div className="muted" style={{ fontSize: 13 }}>
            Tip: Ask something like <span className="mono">“Are alternate side parking rules in effect today in NYC?”</span>
          </div>
        </div>

        <div className="wizardChatWindow">
          {chat.length === 0 ? (
            <div style={{ opacity: 0.85, fontSize: 13 }}>
              This is a chat-first wizard. Your legacy toggles and settings still exist elsewhere in the portal.
            </div>
          ) : null}

          {chat.map((m, idx) => (
            <div key={idx} className={`wizardMsg ${m.role === "user" ? "user" : "assistant"}`}>
              <div className="wizardMsgMeta">{m.role === "user" ? "You" : "Vozlia"}</div>
              <div className="wizardMsgBubble">{m.text}</div>

              {m.role === "assistant" && (m.meta?.model || m.meta?.latency_ms != null) ? (
                <div className="wizardMsgFoot">
                  model={m.meta?.model || "(default)"} · latency_ms={m.meta?.latency_ms ?? "?"}
                </div>
              ) : null}

              {m.role === "assistant" && (m.sources || []).length ? (
                <details className="wizardSources">
                  <summary>Sources</summary>
                  <ul>
                    {(m.sources || []).slice(0, 8).map((s, sIdx) => (
                      <li key={sIdx}>
                        <a href={s.url} target="_blank" rel="noreferrer">
                          {s.title || s.url}
                        </a>
                        {s.snippet ? <div className="muted">{s.snippet}</div> : null}
                      </li>
                    ))}
                  </ul>
                </details>
              ) : null}
              {m.role === "assistant" && Array.isArray((m as any).citations) && (m as any).citations.length ? (
                <details className="wizardSources">
                  <summary>Citations ({(m as any).citations.length})</summary>
                  <ul>
                    {(m as any).citations.slice(0, 8).map((c: any, cIdx: number) => (
                      <li key={cIdx}>
                        <pre style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
                          {JSON.stringify(c, null, 2)}
                        </pre>
                      </li>
                    ))}
                  </ul>
                </details>
              ) : null}
            </div>
          ))}

          {loading ? <div style={{ marginTop: 10, opacity: 0.85 }}>Thinking…</div> : null}
          <div ref={chatEndRef} />
        </div>

        <div className="wizardComposer">
          <textarea
            className="input"
            style={{ flex: 1, minHeight: 64, resize: "vertical" }}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Type your question…"
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                ask().catch(() => null);
              }
            }}
          />
          <button className="btnPrimary" type="button" disabled={loading} onClick={() => ask().catch(() => null)}>
            {loading ? "Asking…" : "Send"}
          </button>
        </div>

        <div className="wizardActionBar">
          <div className="muted" style={{ fontSize: 13 }}>
            {runOut?.query ? (
              <>
                Last question saved in memory: <span className="mono">{clampText(runOut.query, 110)}</span>
              </>
            ) : (
              <>Ask a question to enable skill creation.</>
            )}
          </div>

          <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
            <button className="btnSecondary" type="button" disabled={!runOut?.query || loading} onClick={openSaveSkill}>
              Save as Skill
            </button>
            <button className="btnSecondary" type="button" disabled={loading} onClick={() => refreshLists().catch(() => null)}>
              Refresh Skills
            </button>
          </div>
        </div>

        <details style={{ marginTop: 10 }}>
          <summary style={{ cursor: "pointer", opacity: 0.85 }}>Advanced</summary>
          <div className="panelInset" style={{ marginTop: 10 }}>
            <div className="field">
              <div className="fieldLabel">Model override (optional)</div>
              <input
                className="input"
                value={model}
                onChange={(e) => setModel(e.target.value)}
                placeholder="leave blank for backend default"
              />
            </div>
          </div>
        </details>
      </div>

      {/* Skill cards */}
      <div style={{ marginTop: 14 }}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "baseline" }}>
          <div>
            <div style={{ fontWeight: 900 }}>Skills created by the wizard</div>
            <div className="muted" style={{ fontSize: 13, marginTop: 4 }}>
              Click a card to view schedule details and delivery options.
            </div>
          </div>
        </div>

        {skills.length === 0 ? (
          <div className="muted" style={{ marginTop: 10 }}>
            No saved skills yet. Ask a question above, then click <b>Save as Skill</b>.
          </div>
        ) : (
          <div className="wizardGrid" style={{ marginTop: 12 }}>
            {skills.map((s) => {
              const sched = scheduleBySkillId.get(s.id) || null;
              const hasSched = !!sched;
              return (
                <button
                  key={s.id}
                  type="button"
                  className={`tile wizardCard ${hasSched ? "hasSched" : ""}`}
                  onClick={() => setDetailSkillId(s.id)}
                >
                  <div className="wizardCardTop">
                    <div className="wizardCardTitle">{s.name}</div>
                    <span className={`pill ${s.enabled ? "pillOn" : "pillOff"}`}>{s.enabled ? "Enabled" : "Disabled"}</span>
                  </div>

                  <div className="wizardCardLine">{scheduleSummary(sched)}</div>

                  <div className="wizardCardQuery" title={s.query}>
                    {s.query}
                  </div>

                  <div className="wizardCardFoot mono">{clampText(s.skill_key, 34)}</div>
                </button>
              );
            })}
          </div>
        )}
      </div>

      {/* Save as skill modal */}
      {saveOpen ? (
        <div className="wizardModalBackdrop" role="dialog" aria-modal="true">
          <div className="wizardModal">
            <div className="wizardModalHead">
              <div style={{ fontWeight: 900, fontSize: 16 }}>Save as Skill</div>
              <button className="btnSecondary" type="button" onClick={() => setSaveOpen(false)}>
                Close
              </button>
            </div>

            <div className="muted" style={{ fontSize: 13, marginTop: 6 }}>
              This creates a reusable Web Search skill. After saving, click the skill card to schedule delivery.
            </div>

            <div className="field" style={{ marginTop: 12 }}>
              <div className="fieldLabel">Skill name</div>
              <input className="input" value={saveName} onChange={(e) => setSaveName(e.target.value)} />
            </div>

            <div style={{ marginTop: 10 }}>
              <button className="btnSecondary" type="button" onClick={() => setSaveShowTriggers((v) => !v)}>
                {saveShowTriggers ? "Hide triggers" : "Add triggers (optional)"}
              </button>
            </div>

            {saveShowTriggers ? (
              <div className="field" style={{ marginTop: 10 }}>
                <div className="fieldLabel">Trigger phrases (comma-separated)</div>
                <input className="input" value={saveTriggers} onChange={(e) => setSaveTriggers(e.target.value)} placeholder="alternate side parking, ASP rules" />
              </div>
            ) : null}

            <div className="wizardModalActions">
              <button className="btnPrimary" type="button" disabled={loading} onClick={() => createSkillFromLastQuestion().catch(() => null)}>
                {loading ? "Saving…" : "Create Skill"}
              </button>
              <button className="btnSecondary" type="button" disabled={loading} onClick={() => refreshLists().catch(() => null)}>
                Refresh
              </button>
            </div>

            <div className="muted" style={{ fontSize: 12, marginTop: 10 }}>
              Question: <span className="mono">{clampText(runOut?.query || "", 160)}</span>
            </div>
          </div>
        </div>
      ) : null}

      {/* Skill details modal */}
      {detailSkillId && detailSkill ? (
        <div className="wizardModalBackdrop" role="dialog" aria-modal="true">
          <div className="wizardModal">
            <div className="wizardModalHead">
              <div style={{ minWidth: 0 }}>
                <div style={{ fontWeight: 900, fontSize: 16 }}>{detailSkill.name}</div>
                <div className="muted" style={{ fontSize: 13, marginTop: 4 }}>
                  {detailSkill.query}
                </div>
              </div>
              <button className="btnSecondary" type="button" onClick={() => setDetailSkillId(null)}>
                Close
              </button>
            </div>

            <div className="panelInset" style={{ marginTop: 12 }}>
              <div style={{ fontWeight: 900 }}>Schedule</div>
              <div className="muted" style={{ fontSize: 13, marginTop: 6 }}>
                {detailSchedule ? (
                  <>
                    <div>
                      Current: <span className="mono">{scheduleSummary(detailSchedule)}</span>
                    </div>
                    {detailSchedule.next_run_at ? (
                      <div style={{ marginTop: 4 }}>
                        Next run: <span className="mono">{formatWhenIso(detailSchedule.next_run_at)}</span>
                      </div>
                    ) : null}
                    {detailSchedule.last_run_at ? (
                      <div style={{ marginTop: 4 }}>
                        Last run: <span className="mono">{formatWhenIso(detailSchedule.last_run_at)}</span>
                      </div>
                    ) : null}
                  </>
                ) : (
                  <>No schedule yet.</>
                )}
              </div>

              <div className="form" style={{ marginTop: 12 }}>
                <div className="field" style={{ display: "flex", gap: 8 }}>
                  <div style={{ flex: 1 }}>
                    <div className="fieldLabel">Hour (0–23)</div>
                    <input className="input" value={schedHour} onChange={(e) => setSchedHour(e.target.value)} />
                  </div>
                  <div style={{ flex: 1 }}>
                    <div className="fieldLabel">Minute (0–59)</div>
                    <input className="input" value={schedMinute} onChange={(e) => setSchedMinute(e.target.value)} />
                  </div>
                </div>

                <div className="field">
                  <div className="fieldLabel">Timezone</div>
                  <input className="input" value={schedTimezone} onChange={(e) => setSchedTimezone(e.target.value)} />
                </div>

                <div className="field">
                  <div className="fieldLabel">Delivery channel</div>
                  <select className="input" value={schedChannel} onChange={(e) => setSchedChannel(e.target.value)}>
                    <option value="email">email</option>
                    <option value="sms">sms</option>
                    <option value="whatsapp">whatsapp</option>
                    <option value="call">call</option>
                  </select>
                </div>

                <div className="field">
                  <div className="fieldLabel">Destination</div>
                  <input className="input" value={schedDestination} onChange={(e) => setSchedDestination(e.target.value)} placeholder="email or phone number" />
                </div>

                <div className="actions">
                  <button className="btnPrimary" type="button" disabled={loading} onClick={() => upsertScheduleForOpenSkill().catch(() => null)}>
                    {loading ? "Saving…" : "Save Schedule"}
                  </button>
                  <button className="btnSecondary" type="button" disabled={loading} onClick={() => refreshLists().catch(() => null)}>
                    Refresh
                  </button>
                </div>
              </div>
            </div>

            <details style={{ marginTop: 12 }}>
              <summary style={{ cursor: "pointer", opacity: 0.85 }}>Advanced (danger zone)</summary>
              <div className="panelInset" style={{ marginTop: 10 }}>
                <div className="muted" style={{ fontSize: 13 }}>
                  <div>
                    Skill key: <span className="mono">{detailSkill.skill_key}</span>
                  </div>
                  {(detailSkill.triggers || []).length ? (
                    <div style={{ marginTop: 6 }}>
                      Triggers: <span className="mono">{(detailSkill.triggers || []).join(", ")}</span>
                    </div>
                  ) : null}
                </div>

                <div style={{ marginTop: 12, display: "flex", justifyContent: "flex-end" }}>
                  <button
                    className="btnSecondary"
                    type="button"
                    disabled={loading}
                    onClick={() => deleteSkill(detailSkill.id).catch(() => null)}
                    style={{ borderColor: "rgba(239,68,68,0.35)", background: "rgba(239,68,68,0.06)", color: "#b91c1c" }}
                  >
                    Delete skill
                  </button>
                </div>
              </div>
            </details>
          </div>
        </div>
      ) : null}

      <style jsx>{`
        .wizardChatShell {
          border: 1px solid rgba(0, 0, 0, 0.10);
          border-radius: 16px;
          background: rgba(255, 255, 255, 0.75);
          padding: 14px;
        }
        .wizardChatHeader {
          display: flex;
          justify-content: space-between;
          align-items: baseline;
          gap: 12px;
        }
        .wizardChatWindow {
          margin-top: 10px;
          border: 1px solid rgba(0, 0, 0, 0.12);
          border-radius: 14px;
          padding: 12px;
          height: 55vh;
          overflow-y: auto;
          background: rgba(0, 0, 0, 0.02);
        }
        .wizardComposer {
          display: flex;
          gap: 10px;
          margin-top: 10px;
          align-items: flex-start;
        }
        .wizardActionBar {
          display: flex;
          justify-content: space-between;
          align-items: center;
          gap: 12px;
          margin-top: 10px;
        }

        .wizardMsg {
          margin-top: 12px;
        }
        .wizardMsg:first-child {
          margin-top: 0;
        }
        .wizardMsgMeta {
          font-size: 12px;
          opacity: 0.75;
          margin-bottom: 4px;
        }
        .wizardMsgBubble {
          white-space: pre-wrap;
          font-size: 14px;
          padding: 10px 12px;
          border-radius: 12px;
          border: 1px solid rgba(0, 0, 0, 0.10);
          background: rgba(255, 255, 255, 0.75);
        }
        .wizardMsg.user .wizardMsgBubble {
          background: rgba(0, 0, 0, 0.04);
        }
        .wizardMsgFoot {
          font-size: 12px;
          opacity: 0.7;
          margin-top: 6px;
        }
        .wizardSources {
          margin-top: 8px;
        }
        .wizardSources summary {
          cursor: pointer;
          opacity: 0.85;
          font-size: 13px;
        }
        .wizardSources ul {
          margin-top: 8px;
          padding-left: 18px;
        }

        .wizardGrid {
          display: grid;
          /* Smaller square cards so 40–50 skills remain scannable. */
          grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
          gap: 12px;
        }
        @media (max-width: 860px) {
          .wizardGrid {
            grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
          }
        }
        .wizardCard {
          aspect-ratio: 1 / 1;
          display: flex;
          flex-direction: column;
          justify-content: space-between;
          min-height: 180px;
          /* Override .tile padding to keep cards compact. */
          padding: 12px;
        }
        .wizardCardTop {
          display: flex;
          justify-content: space-between;
          align-items: flex-start;
          gap: 10px;
        }
        .wizardCardTitle {
          font-weight: 900;
          line-height: 1.15;
          overflow: hidden;
          display: -webkit-box;
          -webkit-line-clamp: 2;
          -webkit-box-orient: vertical;
        }
        .wizardCardLine {
          margin-top: 10px;
          font-size: 12px;
          color: rgba(15, 23, 42, 0.72);
          overflow: hidden;
          display: -webkit-box;
          -webkit-line-clamp: 2;
          -webkit-box-orient: vertical;
        }
        .wizardCardQuery {
          margin-top: 10px;
          font-size: 13px;
          color: rgba(15, 23, 42, 0.78);
          overflow: hidden;
          display: -webkit-box;
          -webkit-line-clamp: 2;
          -webkit-box-orient: vertical;
        }
        .wizardCardFoot {
          margin-top: 10px;
          font-size: 12px;
          opacity: 0.7;
        }

        .wizardModalBackdrop {
          position: fixed;
          inset: 0;
          background: rgba(15, 23, 42, 0.55);
          display: flex;
          align-items: center;
          justify-content: center;
          padding: 18px;
          z-index: 9999;
        }
        .wizardModal {
          width: min(920px, 96vw);
          max-height: 90vh;
          overflow: auto;
          background: rgba(255, 255, 255, 0.98);
          border-radius: 18px;
          border: 1px solid rgba(0, 0, 0, 0.12);
          box-shadow: 0 18px 48px rgba(15, 23, 42, 0.28);
          padding: 14px;
        }
        .wizardModalHead {
          display: flex;
          justify-content: space-between;
          align-items: flex-start;
          gap: 12px;
        }
        .wizardModalActions {
          display: flex;
          justify-content: flex-end;
          gap: 10px;
          margin-top: 12px;
        }
      `}</style>
    </div>
  );
}
