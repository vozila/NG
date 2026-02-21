import type { GetServerSidePropsContext } from "next";
import { useEffect, useMemo, useRef, useState } from "react";
import { useSession, signIn, signOut } from "next-auth/react";
import { RenderLogsPanel } from "../components/RenderLogsPanel";
import StatusBadgePanel from "../components/StatusBadgePanel";
import { KBUploadPanel } from "../components/KBUploadPanel";
import AgentLongTermMemoryTable from "../components/AgentLongTermMemoryTable";
import WebSearchMvpPanel from "../components/WebSearchMvpPanel";
import DBQuerySkillsPanel from "../components/DBQuerySkillsPanel";
import BusinessProfileEditorPanel from "../components/BusinessProfileEditorPanel";
import TemplateSelectionPreviewPanel from "../components/TemplateSelectionPreviewPanel";
import OcrUploadReviewPanel from "../components/OcrUploadReviewPanel";
import InboxActionsPanel from "../components/InboxActionsPanel";
import NotificationSettingsPanel from "../components/NotificationSettingsPanel";
import AppointmentRequestsViewPanel from "../components/AppointmentRequestsViewPanel";
import GoalsWizardPanel from "../components/GoalsWizardPanel";
import GoalsStatusPanel from "../components/GoalsStatusPanel";
import PlaybookDetailViewPanel from "../components/PlaybookDetailViewPanel";
import { SectionRow, Switch, TextField, SkillTile, DropZone, safeParseDragPayload, type DragPayload } from "../components/admin/AdminUi";

const SKILL_KEYS = ["gmail_summaries", "sms", "calendar", "web_search", "weather", "investment_reporting"] as const;
type SkillKey = (typeof SKILL_KEYS)[number];

function isSkillKey(v: string): v is SkillKey {
  return (SKILL_KEYS as readonly string[]).includes(v);
}

type EmailAccount = {
  id: string;
  provider_type: string;
  email_address?: string | null;
  display_name?: string | null;
  is_active: boolean;
  // Some providers support a 'primary' notion (e.g., Gmail default account).
  // Control plane may omit this field for non-applicable providers.
  is_primary?: boolean;
};

type Playbook = {
  id: string;
  name: string;
  enabled: boolean;
  steps: SkillKey[];
};

type TemplateItem =
  | { kind: "playbook"; id: string }
  | { kind: "skill"; key: SkillKey };

type Template = {
  id: string;
  name: string;
  enabled: boolean;
  sequence: TemplateItem[];
};

type WebSearchSkill = {
  id: string;
  skill_key: string;
  name: string;
  query: string;
  triggers?: string[];
  enabled: boolean;
};


/**
 * Mapping between UI "skill keys" and the Control Plane / Backend skill IDs used in settings.skills_config.
 * IMPORTANT: Keep these stable; they are persisted in DB config.
 */
const SKILL_ID_BY_KEY: Record<SkillKey, string> = {
  gmail_summaries: "gmail_summary",
  sms: "sms",
  calendar: "calendar",
  web_search: "web_search",
  weather: "weather",
  investment_reporting: "investment_reporting",
};

const KEY_BY_SKILL_ID: Record<string, SkillKey> = Object.fromEntries(
  (Object.keys(SKILL_ID_BY_KEY) as SkillKey[]).map((k) => [SKILL_ID_BY_KEY[k], k])
) as Record<string, SkillKey>;

/**
 * Default prompt used when Investment Reporting doesn't have a custom llm_prompt configured.
 * (Front-end-only constant; backend still owns the actual behavior.)
 */
const DEFAULT_INVESTMENT_REPORTING_LLM_PROMPT = `
You are Vozlia's investment reporting assistant.
Return a concise report for the requested ticker(s):
- Current price and daily change (if available)
- 3–6 key bullets: notable news, earnings, major risks, and a plain-English outlook
- End with a brief disclaimer: "Not financial advice."
Keep it short and easy to read in voice.
`.trim();

const LEGACY_PANELS_ENABLED = process.env.NEXT_PUBLIC_WEBUI_LEGACY_PANELS === "1";

export default function AdminPage() {
  const { data: session } = useSession();
  const primaryEmail = (session?.user?.email as string | undefined) || "";

  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const [settings, setSettings] = useState<any>({});
  const [accounts, setAccounts] = useState<EmailAccount[]>([]);
  const [accountsLoading, setAccountsLoading] = useState(true);


  const [webSearchSkills, setWebSearchSkills] = useState<WebSearchSkill[]>([]);
  const [webSearchSkillsLoading, setWebSearchSkillsLoading] = useState(false);

  // Concept-only state
  const [open, setOpen] = useState<Record<string, boolean>>({
    skills: false,
    playbooks: false,
    templates: false,
    agentMemory: false,
    chitchat: false,
    logging: false,
    email: false,
    renderLogs: false,
    websearchMvp: false,
    businessKnowledge: false,
    ownerOps: false,
    goalsCenter: false,
  });

  const [selectedGoalPlaybookId, setSelectedGoalPlaybookId] = useState<string>("");

  const [activeSkill, setActiveSkill] = useState<SkillKey | null>(null);
  const configPanelRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!activeSkill) return;
    // Ensure the config panel is visible even if the Saved Web Search Skills list is long.
    // NOTE: double-clicking a tile fires 2 clicks; we keep tiles "select-only" and provide an explicit Close button.
    requestAnimationFrame(() => {
      configPanelRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }, [activeSkill]);


  // Skill config (concept fields)
  type SkillCfgState = {
    enabled: boolean;
    addToGreeting: boolean;
    autoExecuteAfterGreeting: boolean;
    engagementPrompt: string;
    llmPrompt: string;
    tickers: string;
  };

  const [skillCfg, setSkillCfg] = useState<Record<SkillKey, SkillCfgState>>({
    gmail_summaries: { enabled: false, addToGreeting: false, autoExecuteAfterGreeting: false, engagementPrompt: "", llmPrompt: "", tickers: "" },
    sms: { enabled: false, addToGreeting: false, autoExecuteAfterGreeting: false, engagementPrompt: "", llmPrompt: "", tickers: "" },
    calendar: { enabled: false, addToGreeting: false, autoExecuteAfterGreeting: false, engagementPrompt: "", llmPrompt: "", tickers: "" },
    web_search: { enabled: false, addToGreeting: false, autoExecuteAfterGreeting: false, engagementPrompt: "", llmPrompt: "", tickers: "" },
    weather: { enabled: false, addToGreeting: false, autoExecuteAfterGreeting: false, engagementPrompt: "", llmPrompt: "", tickers: "" },
    investment_reporting: { enabled: false, addToGreeting: false, autoExecuteAfterGreeting: false, engagementPrompt: "", llmPrompt: "", tickers: "" },
  });

  // Greeting priority list (admin configurable)
  const [greetingPriority, setGreetingPriority] = useState<SkillKey[]>([
    "gmail_summaries",
    "sms",
    "calendar",
    "web_search",
    "weather",
    "investment_reporting",
  ]);

  // Playbooks/Templates concept models
  const [playbooks, setPlaybooks] = useState<Playbook[]>([
    { id: "pb-1", name: "New Lead Intake", enabled: true, steps: ["gmail_summaries"] },
    { id: "pb-2", name: "After-hours Info", enabled: true, steps: ["weather"] },
  ]);
  const [selectedPlaybookId, setSelectedPlaybookId] = useState<string>("pb-1");

  const [templates, setTemplates] = useState<Template[]>([
    { id: "tpl-1", name: "Default Agent Program", enabled: true, sequence: [{ kind: "playbook", id: "pb-1" }] },
  ]);
  const [selectedTemplateId, setSelectedTemplateId] = useState<string>("tpl-1");

// Agent Memory (wired)
const [memoryEngagementPrompt, setMemoryEngagementPrompt] = useState<string>("");


// Chit-Chat (concept)
const [chitchatDelaySec, setChitchatDelaySec] = useState<string>("2.0");

// Logging toggles (concept)
const [logToggles, setLogToggles] = useState<Record<string, boolean>>({
  REALTIME_LOG_STATS: true,
  REALTIME_LOG_DELTAS: false,
  REALTIME_LOG_TEXT: false,
  REALTIME_LOG_ALL_EVENTS: false,
  OBS_ENABLED: false,
  OBS_LOG_JSON: false,
});

  // Wired loading
  async function loadSettings() {
    const res = await fetch("/api/admin/settings");
    const data = await res.json();

    // Defensive defaults so older control-plane deployments don't break UI
    const skills = (data && typeof data === "object" && data.skills_config && typeof data.skills_config === "object")
      ? data.skills_config
      : {};

    const gmailSkill = (skills as any).gmail_summary || {};

    // Greeting priority order (skill IDs from control plane)
    const prio = Array.isArray((data as any).skills_priority_order) ? ((data as any).skills_priority_order as string[]) : [];
    if (prio.length) {
      const mapped: SkillKey[] = [];
      for (const sid of prio) {
        const k = KEY_BY_SKILL_ID[sid];
        if (k) mapped.push(k);
      }
      // Append any missing skills (stable)
      const all: SkillKey[] = ["gmail_summaries", "sms", "calendar", "web_search", "weather", "investment_reporting"];
      const finalOrder = [...mapped, ...all.filter((k) => !mapped.includes(k))];
      setGreetingPriority(finalOrder);
    }

    setSettings({
      ...data,
      shortterm_memory_enabled: !!data.shortterm_memory_enabled,
      longterm_memory_enabled: !!data.longterm_memory_enabled,
    });

    // Wire skill fields into the Skill Config panel (multi-skill; safe defaults)
    setSkillCfg((cur) => {
      const next: any = { ...cur };
      const skillsObj: any = skills || {};

      for (const key of Object.keys(SKILL_ID_BY_KEY) as SkillKey[]) {
        const sid = SKILL_ID_BY_KEY[key];
        const cfg = skillsObj[sid] || {};
        const tickersRaw = typeof cfg.tickers_raw === "string" ? cfg.tickers_raw : "";
        const tickersList = Array.isArray(cfg.tickers) ? cfg.tickers.map((t: any) => String(t || "").trim()).filter(Boolean) : [];
        next[key] = {
          ...next[key],
          enabled: key === "gmail_summaries" ? !!(data as any).gmail_summary_enabled : !!cfg.enabled,
          addToGreeting: !!cfg.add_to_greeting,
          autoExecuteAfterGreeting: !!cfg.auto_execute_after_greeting,
          engagementPrompt:
            Array.isArray(cfg.engagement_phrases)
              ? cfg.engagement_phrases.join("\n")
              : key === "investment_reporting"
                ? "stock report"
                : "",
          llmPrompt:
            typeof cfg.llm_prompt === "string" && cfg.llm_prompt.trim()
              ? cfg.llm_prompt
              : key === "investment_reporting"
                ? DEFAULT_INVESTMENT_REPORTING_LLM_PROMPT
                : "",
          tickers: tickersRaw || (tickersList.length ? tickersList.join(", ") : ""),
        };
      }
      return next;
    });
    // Wire memory engagement phrases (one per line in UI)
    setMemoryEngagementPrompt(Array.isArray(data.memory_engagement_phrases) ? data.memory_engagement_phrases.join("\n") : "");
  }


  async function loadAccounts() {
    setAccountsLoading(true);
    const res = await fetch("/api/admin/email-accounts");
    const data = await res.json();
    setAccounts(Array.isArray(data) ? data : []);
    setAccountsLoading(false);
  }

  
  async function loadWebSearchSkills() {
    setWebSearchSkillsLoading(true);
    try {
      const res = await fetch("/api/admin/websearch/skills", { method: "GET" });
      const data = await res.json().catch(() => []);
      if (res.ok) setWebSearchSkills(Array.isArray(data) ? data : []);
    } finally {
      setWebSearchSkillsLoading(false);
    }
  }

  async function deleteWebSearchSkill(id: string, name?: string) {
    const label = name ? `"${name}"` : id;
    if (!confirm(`Delete Web Search skill ${label}? This cannot be undone.`)) return;

    setError(null);
    try {
      const res = await fetch(`/api/admin/websearch/skills/${encodeURIComponent(id)}`, { method: "DELETE" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data?.detail || data?.error || "Delete failed");
      await loadWebSearchSkills();
    } catch (e: any) {
      setError(String(e?.message ?? e));
    }
  }

useEffect(() => {
    if (!LEGACY_PANELS_ENABLED) return;
    loadSettings().catch((e: unknown) => setError(String((e as any)?.message ?? e)));
    loadAccounts().catch((e: unknown) => setError(String((e as any)?.message ?? e)));
    loadWebSearchSkills().catch((e: unknown) => setError(String((e as any)?.message ?? e)));
  }, []);

  const gmailAccounts = useMemo(() => accounts.filter((a) => a.provider_type === "gmail"), [accounts]);
  const gmailActiveAccounts = useMemo(() => gmailAccounts.filter((a) => a.is_active), [gmailAccounts]);

  const selectedPlaybook = useMemo(() => playbooks.find((p) => p.id === selectedPlaybookId) ?? playbooks[0], [playbooks, selectedPlaybookId]);
  const selectedTemplate = useMemo(() => templates.find((t) => t.id === selectedTemplateId) ?? templates[0], [templates, selectedTemplateId]);

  async function saveWiredSettings() {
    setSaving(true);
    setError(null);

    // Normalize phrase lists from textarea inputs (one phrase per line)
    const gmailEngagementPhrases = (skillCfg.gmail_summaries.engagementPrompt || "")
      .split("\n")
      .map((s) => s.trim())
      .filter(Boolean);

    const memoryPhrases = (memoryEngagementPrompt || "")
      .split("\n")
      .map((s) => s.trim())
      .filter(Boolean);

    // Control-plane PATCH payload (modular skills_config + memory toggles)
    const payload = {
      agent_greeting: settings.agent_greeting,
      realtime_prompt_addendum: settings.realtime_prompt_addendum,

      // Existing wired Gmail toggles + inbox selection
      gmail_summary_enabled: settings.gmail_summary_enabled,
      gmail_account_id: settings.gmail_account_id,
      gmail_enabled_account_ids: settings.gmail_enabled_account_ids,

      // NEW: Modular per-skill config (all skills; backend may choose to use subset)
      skills_config: (() => {
        const base: any =
          settings && typeof settings === "object" && (settings as any).skills_config && typeof (settings as any).skills_config === "object" && !Array.isArray((settings as any).skills_config)
            ? { ...((settings as any).skills_config as any) }
            : {};
        const out: any = { ...base };
        const parseLines = (v: string) =>
          (v || "")
            .split("\n")
            .map((s) => s.trim())
            .filter(Boolean);

        (Object.keys(SKILL_ID_BY_KEY) as SkillKey[]).forEach((key) => {
          const sid = SKILL_ID_BY_KEY[key];
          const cfg = (skillCfg as any)[key] || {};
          out[sid] = {
            enabled: !!cfg.enabled,
            add_to_greeting: !!cfg.addToGreeting,
            auto_execute_after_greeting: !!cfg.autoExecuteAfterGreeting,
            engagement_phrases: parseLines(cfg.engagementPrompt || ""),
            llm_prompt: cfg.llmPrompt || "",
            ...(key === "investment_reporting"
              ? (() => {
                  const raw = String(cfg.tickers || "").trim();
                  const tickers = raw
                    .split(",")
                    .map((s: string) => s.trim().toUpperCase())
                    .filter(Boolean);
                  return { tickers_raw: raw, tickers };
                })()
              : {}),
          };
        });

        // Mirror legacy gmail_summary_enabled into the skill as well
        out.gmail_summary = {
          ...(out.gmail_summary || {}),
          enabled: !!settings.gmail_summary_enabled,
        };

        return out;
      })(),

      // NEW: Greeting priority order (skill IDs)
      skills_priority_order: (() => {
        const known = greetingPriority.map((k) => SKILL_ID_BY_KEY[k]);
        const baseOrder = Array.isArray((settings as any).skills_priority_order) ? ((settings as any).skills_priority_order as string[]) : [];
        const unknown = baseOrder.filter((sid) => !known.includes(sid));
        return [...known, ...unknown];
      })(),
      // NEW: Memory wiring
      shortterm_memory_enabled: !!settings.shortterm_memory_enabled,
      longterm_memory_enabled: !!settings.longterm_memory_enabled,
      memory_engagement_phrases: memoryPhrases,
    };

    try {
      const res = await fetch("/api/admin/settings", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      const data = await res.json();
      if (!res.ok) throw new Error(data?.error || "Failed to save settings");

      setSettings(data);

      // Re-sync Gmail skill fields from server (defensive: supports older responses)
      const skills =
        data && typeof data === "object" && data.skills_config && typeof data.skills_config === "object"
          ? data.skills_config
          : {};
      const gmailSkill = (skills as any).gmail_summary || {};

      setSkillCfg((cur) => ({
        ...cur,
        gmail_summaries: {
          ...cur.gmail_summaries,
          enabled: !!data.gmail_summary_enabled,
          addToGreeting: !!gmailSkill.add_to_greeting,
          autoExecuteAfterGreeting: !!gmailSkill.auto_execute_after_greeting,
          engagementPrompt: Array.isArray(gmailSkill.engagement_phrases) ? gmailSkill.engagement_phrases.join("\n") : "",
          llmPrompt: typeof gmailSkill.llm_prompt === "string" ? gmailSkill.llm_prompt : "",
        },
      }));

      setMemoryEngagementPrompt(Array.isArray(data.memory_engagement_phrases) ? data.memory_engagement_phrases.join("\n") : "");
    } catch (e: unknown) {
      setError(String((e as any)?.message ?? e));
    } finally {
      setSaving(false);
    }
  }


  async function patchAccount(id: string, patch: Partial<EmailAccount>) {
    setError(null);
    try {
      const res = await fetch(`/api/admin/email-accounts/${encodeURIComponent(id)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data?.error || "Failed to update email account");
      await loadAccounts();
    } catch (e: any) {
      setError(e?.message || String(e));
    }
  }

  async function setPrimaryAccount(id: string) {
    const updates = accounts
      .filter((a) => a.provider_type === "gmail")
      .map((a) => patchAccount(a.id, { is_primary: a.id === id }));
    await Promise.all(updates);
  }

  async function toggleAccountActive(id: string, nextActive: boolean) {
    await patchAccount(id, { is_active: nextActive });
  }

  function appendToGreetingNote(key: SkillKey): string {
    if (skillCfg[key].autoExecuteAfterGreeting) return "Auto-exec after greeting";
    if (skillCfg[key].addToGreeting) return "Announced in greeting";
    return "Runs on demand";
  }

  return (
    <div className="page">
      <div className="bg" />
      <div className="wrap">
        <header className="top">
          <div>
            <div className="brand">Vozlia</div>
            <div className="subtitle">Admin Portal</div>
          </div>

          <div className="who">
            <div>
              <div className="muted">Signed in as</div>
              <div className="mono">{primaryEmail || "admin"}</div>
            </div>

            <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
              <button type="button" className="btnSecondary" onClick={() => signIn(undefined, { callbackUrl: "/admin" })}>
                Refresh Session
              </button>
              <button type="button" className="btnSecondary" onClick={() => signOut({ callbackUrl: "/" })}>
                Logout
              </button>
            </div>
          </div>
        </header>

        {error ? (
          <div className="alert">
            <div className="alertTitle">Error</div>
            <div className="alertBody">{error}</div>
          </div>
        ) : null}

        <div className="stack">
          {LEGACY_PANELS_ENABLED ? (
            <>
          <SectionRow
            title="Skills"
            subtitle="Capabilities/tools. Click a tile to configure. Drag tiles into Playbooks/Templates."
            open={open.skills}
            onToggle={() => setOpen((p) => ({ ...p, skills: !p.skills }))}
            rightSlot={<span className="pill pillOn">{skillCfg.gmail_summaries.enabled ? "Gmail enabled" : "Gmail disabled"}</span>}
          >
            <div className="grid2">
              <div className="tiles">
                <SkillTile
                  title="Gmail Summaries"
                  desc={appendToGreetingNote("gmail_summaries")}
                  enabled={skillCfg.gmail_summaries.enabled}
                  active={activeSkill === "gmail_summaries"}
                  onClick={() => setActiveSkill("gmail_summaries")}
                  draggableKey="gmail_summaries"
                />
                <SkillTile
                  title="SMS"
                  desc={appendToGreetingNote("sms")}
                  enabled={skillCfg.sms.enabled}
                  active={activeSkill === "sms"}
                  onClick={() => setActiveSkill("sms")}
                  draggableKey="sms"
                />
                <SkillTile
                  title="Calendar"
                  desc={appendToGreetingNote("calendar")}
                  enabled={skillCfg.calendar.enabled}
                  active={activeSkill === "calendar"}
                  onClick={() => setActiveSkill("calendar")}
                  draggableKey="calendar"
                />
                <SkillTile
                  title="Web Search"
                  desc={appendToGreetingNote("web_search")}
                  enabled={skillCfg.web_search.enabled}
                  active={activeSkill === "web_search"}
                  onClick={() => setActiveSkill("web_search")}
                  draggableKey="web_search"
                />
                <SkillTile
                  title="Weather"
                  desc={appendToGreetingNote("weather")}
                  enabled={skillCfg.weather.enabled}
                  active={activeSkill === "weather"}
                  onClick={() => setActiveSkill("weather")}
                  draggableKey="weather"
                />
                <SkillTile
                  title="Investment Reporting"
                  desc={appendToGreetingNote("investment_reporting")}
                  enabled={skillCfg.investment_reporting.enabled}
                  active={activeSkill === "investment_reporting"}
                  onClick={() => setActiveSkill("investment_reporting")}
                  draggableKey="investment_reporting"
                />
              </div>

              <div className="panel">
                <div className="panelTitle">Greeting Skill Priority</div>
                <div className="panelSub">Drag skills to reorder. When multiple skills have “Add to greeting” enabled, the topmost runs first.</div>

                <DropZone
                  title="Priority List"
                  subtitle="Drop a skill tile here to move it to the top."
                  onDropPayload={(p) => {
                    if (p.type !== "skill") return;
                    if (!isSkillKey(p.key)) return;
                    const key = p.key;
                    setGreetingPriority((cur) => [key, ...cur.filter((k) => k !== key)]);
                  }}
                >
                  <div className="list">
                    {greetingPriority.map((k) => (
                      <div key={k} className="listItem">
                        <span className="mono">{k}</span>
                        <span className={`pill ${skillCfg[k].addToGreeting ? "pillOn" : "pillOff"}`}>{skillCfg[k].addToGreeting ? "Add to greeting" : "Off"}</span>
                      </div>
                    ))}
                  </div>
                </DropZone>
              </div>
            </div>


            <div className="panel" style={{ marginTop: 14 }}>
              <div className="panelTitle">Saved Web Search Skills</div>
              <div className="panelSub">
                Skills created in the Configuration Wizard. These are independent from the built-in “Web Search” skill tile above.
              </div>

              <div className="actions" style={{ marginTop: 10 }}>
                <button type="button" className="btnSecondary" disabled={webSearchSkillsLoading} onClick={() => loadWebSearchSkills().catch(() => null)}>
                  {webSearchSkillsLoading ? "Refreshing…" : "Refresh"}
                </button>
                <button type="button" className="btnSecondary" onClick={() => setOpen((p) => ({ ...p, websearchMvp: true }))}>
                  Open Configuration Wizard
                </button>
              </div>

              {webSearchSkills.length === 0 ? (
                <div className="muted" style={{ marginTop: 10 }}>
                  No saved Web Search skills yet. Create one in the Configuration Wizard.
                </div>
              ) : (
                <div className="list" style={{ marginTop: 10 }}>
                  {webSearchSkills.map((s) => (
                    <div key={s.id} className="listSelect" style={{ cursor: "default" }}>
                      <div className="row">
                        <div className="rowMain">
                          <div className="rowTitle">{s.name}</div>
                          <div className="rowSub mono">{s.id}</div>
                          <div className="rowSub">{s.query}</div>
                          {s.triggers?.length ? <div className="rowSub">Triggers: {s.triggers.join(", ")}</div> : null}
                        </div>
                        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                          <span className={`pill ${s.enabled ? "pillOn" : "pillOff"}`}>{s.enabled ? "Enabled" : "Disabled"}</span>
                          <button type="button" className="btnSecondary" onClick={() => deleteWebSearchSkill(s.id, s.name)}>
                            Delete
                          </button>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {activeSkill ? (
              <div ref={configPanelRef} className="panel" style={{ marginTop: 14 }}>
                <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12 }}>
                  <div>
                    <div className="panelTitle">Configure: {activeSkill}</div>
                    <div className="panelSub">Concept controls (we’ll wire these to the control plane next).</div>
                  </div>
                  <button type="button" className="btnSecondary" onClick={() => setActiveSkill(null)}>
                    Close
                  </button>
                </div>

                <div className="form">
                  {/* Gmail enable is wired to current settings; others are concept */}
                  {activeSkill === "gmail_summaries" ? (
                    <Switch
                      checked={!!settings.gmail_summary_enabled}
                      onChange={(v) => {
                        setSettings((p: any) => ({ ...p, gmail_summary_enabled: v }));
                        setSkillCfg((cur) => ({ ...cur, gmail_summaries: { ...cur.gmail_summaries, enabled: v } }));
                      }}
                      label="Enable / Disable"
                      helper="Wired to gmail_summary_enabled"
                    />
                  ) : (
                    <Switch
                      checked={skillCfg[activeSkill].enabled}
                      onChange={(v) => setSkillCfg((cur) => ({ ...cur, [activeSkill]: { ...cur[activeSkill], enabled: v } }))}
                      label="Enable / Disable"
                      helper="Concept (not wired yet)"
                    />
                  )}

                  <Switch
                    checked={skillCfg[activeSkill].addToGreeting}
                    onChange={(v) =>
                      setSkillCfg((cur) => ({
                        ...cur,
                        [activeSkill]: { ...cur[activeSkill], addToGreeting: v },
                      }))
                    }
                    label="Add to greeting"
                    helper="When enabled, the agent announces this skill in the greeting (discovery only)."
                  />

                  <Switch
                    checked={skillCfg[activeSkill].autoExecuteAfterGreeting}
                    onChange={(v) =>
                      setSkillCfg((cur) => ({
                        ...cur,
                        [activeSkill]: { ...cur[activeSkill], autoExecuteAfterGreeting: v },
                      }))
                    }
                    label="Auto-execute after greeting"
                    helper="When enabled, Vozlia will execute this skill automatically right after the greeting (in priority order)."
                  />


                  <TextField
                    label="Engagement Prompt (phrases)"
                    value={skillCfg[activeSkill].engagementPrompt}
                    onChange={(v) => setSkillCfg((cur) => ({ ...cur, [activeSkill]: { ...cur[activeSkill], engagementPrompt: v } }))}
                    placeholder={"One phrase per line, e.g.\nemail summaries\nsummarize my inbox"}
                    helper={activeSkill === "gmail_summaries" ? "Wired: phrases that trigger routing to Gmail Summaries." : "Concept (not wired yet)"}
                    multiline
                  />

                  <TextField
                    label="LLM Prompt"
                    value={skillCfg[activeSkill].llmPrompt}
                    onChange={(v) => setSkillCfg((cur) => ({ ...cur, [activeSkill]: { ...cur[activeSkill], llmPrompt: v } }))}
                    placeholder="Full prompt text used when this skill runs."
                    helper="Concept"
                    multiline
                  />

                  {activeSkill === "investment_reporting" ? (
                    <TextField
                      label="Tickers (comma-separated)"
                      value={skillCfg.investment_reporting.tickers}
                      onChange={(v) => setSkillCfg((cur) => ({ ...cur, investment_reporting: { ...cur.investment_reporting, tickers: v } }))}
                      placeholder="AAPL, MSFT, TSLA"
                      helper="Wired: stored in skills_config.investment_reporting.tickers"
                    />
                  ) : null}


                  {activeSkill === "gmail_summaries" ? (
                    <div className="panelInset">
                      <div className="panelTitle">Gmail Inbox Selection</div>
                      <div className="panelSub">These determine which inbox Gmail Summaries uses.</div>

                      <div className="form">
                        <div className="field">
                          <div className="fieldLabel">Default Inbox</div>
                          <div className="fieldHelper">Maps to gmail_account_id (wired)</div>
                          <select
                            className="input"
                            value={settings.gmail_account_id || ""}
                            onChange={(e) => setSettings((p: any) => ({ ...p, gmail_account_id: e.target.value }))}
                          >
                            <option value="">(not set)</option>
                            {gmailActiveAccounts.map((a) => (
                              <option key={a.id} value={a.id}>
                                {(a.email_address || a.display_name || a.id) + (a.is_primary ? " (primary)" : "")}
                              </option>
                            ))}
                          </select>
                        </div>

                        <div className="field">
                          <div className="fieldLabel">Enabled Inboxes</div>
                          <div className="fieldHelper">Maps to gmail_enabled_account_ids (wired)</div>
                          <div className="checkGrid">
                            {gmailActiveAccounts.map((a) => {
                              const enabled: string[] = Array.isArray(settings.gmail_enabled_account_ids) ? settings.gmail_enabled_account_ids : [];
                              const checked = enabled.includes(a.id);
                              return (
                                <label key={a.id} className="checkRow">
                                  <input
                                    type="checkbox"
                                    checked={checked}
                                    onChange={() => {
                                      const next = checked ? enabled.filter((x) => x !== a.id) : [...enabled, a.id];
                                      setSettings((p: any) => ({ ...p, gmail_enabled_account_ids: next }));
                                    }}
                                  />
                                  <span className="checkText">{a.email_address || a.display_name || a.id}</span>
                                </label>
                              );
                            })}
                          </div>
                        </div>
                      </div>
                    </div>
                  ) : null}
                <div className="actions" style={{ marginTop: 12 }}>
                  <button type="button" className="btnPrimary" disabled={saving} onClick={saveWiredSettings}>
                    {saving ? "Saving…" : "Save Skill Settings"}
                  </button>
                </div>

                </div>
              </div>
            ) : null}
          </SectionRow>

          <SectionRow
            title="Configuration Wizard"
            subtitle="ChatGPT-style wizard to answer questions and (optionally) turn them into skills with schedules + notifications. (Currently: Web Search.)"
            open={open.websearchMvp}
            onToggle={() => setOpen((p) => ({ ...p, websearchMvp: !p.websearchMvp }))}
          >
            <WebSearchMvpPanel />

          <div className="mt-6">
            <DBQuerySkillsPanel />
          </div>
          </SectionRow>

          <SectionRow
            title="Playbooks"
            subtitle="Reusable workflows. Build by dragging enabled skill tiles into a playbook container."
            open={open.playbooks}
            onToggle={() => setOpen((p) => ({ ...p, playbooks: !p.playbooks }))}
          >
            <div className="grid2">
              <div className="panel">
                <div className="panelTitle">Playbooks</div>
                <div className="panelSub">Concept UI (not wired yet).</div>

                <div className="list">
                  {playbooks.map((pb) => (
                    <button
                      key={pb.id}
                      type="button"
                      className={`listSelect ${pb.id === selectedPlaybookId ? "active" : ""}`}
                      onClick={() => setSelectedPlaybookId(pb.id)}
                      draggable
                      onDragStart={(e) => {
                        const payload: DragPayload = { type: "playbook", id: pb.id };
                        e.dataTransfer.setData("application/json", JSON.stringify(payload));
                        e.dataTransfer.effectAllowed = "copyMove";
                      }}
                    >
                      <div className="row">
                        <div className="rowMain">
                          <div className="rowTitle">{pb.name}</div>
                          <div className="rowSub mono">{pb.id}</div>
                        </div>
                        <span className={`pill ${pb.enabled ? "pillOn" : "pillOff"}`}>{pb.enabled ? "Enabled" : "Disabled"}</span>
                      </div>
                    </button>
                  ))}
                </div>
              </div>

              <div className="panel">
                <div className="panelTitle">Build: {selectedPlaybook?.name ?? "Playbook"}</div>
                <div className="panelSub">Drop skills into the container. Order = execution order.</div>

                <Switch
                  checked={!!selectedPlaybook?.enabled}
                  onChange={(v) => {
                    setPlaybooks((cur) => cur.map((p) => (p.id === selectedPlaybookId ? { ...p, enabled: v } : p)));
                  }}
                  label="Enable Playbook"
                />

                <DropZone
                  title="Playbook Steps"
                  subtitle="Drop a skill tile here to append it."
                  onDropPayload={(p) => {
                    if (p.type !== "skill") return;
                    if (!isSkillKey(p.key)) return;
                    const key = p.key;
                    setPlaybooks((cur) =>
                      cur.map((pb) => {
                        if (pb.id !== selectedPlaybookId) return pb;
                        const exists = pb.steps.includes(key);
                        return exists ? pb : { ...pb, steps: [...pb.steps, key] };
                      })
                    );
                  }}
                >
                  <div className="chips">
                    {(selectedPlaybook?.steps ?? []).map((k, idx) => (
                      <div key={`${k}-${idx}`} className="chip">
                        <span className="mono">{k}</span>
                        <button
                          type="button"
                          className="chipX"
                          onClick={() => {
                            setPlaybooks((cur) =>
                              cur.map((pb) => {
                                if (pb.id !== selectedPlaybookId) return pb;
                                return { ...pb, steps: pb.steps.filter((x, i) => !(i === idx && x === k)) };
                              })
                            );
                          }}
                        >
                          ×
                        </button>
                      </div>
                    ))}
                    {(selectedPlaybook?.steps ?? []).length === 0 ? <div className="muted">No steps yet. Drag a skill tile in.</div> : null}
                  </div>
                </DropZone>
              </div>
            </div>
          </SectionRow>

          <SectionRow
            title="Templates"
            subtitle="Tenant agent programs. Build by dragging playbooks and/or skills into a template container."
            open={open.templates}
            onToggle={() => setOpen((p) => ({ ...p, templates: !p.templates }))}
          >
            <div className="grid2">
              <div className="panel">
                <div className="panelTitle">Templates</div>
                <div className="panelSub">Concept UI (not wired yet).</div>

                <div className="list">
                  {templates.map((tpl) => (
                    <button
                      key={tpl.id}
                      type="button"
                      className={`listSelect ${tpl.id === selectedTemplateId ? "active" : ""}`}
                      onClick={() => setSelectedTemplateId(tpl.id)}
                    >
                      <div className="row">
                        <div className="rowMain">
                          <div className="rowTitle">{tpl.name}</div>
                          <div className="rowSub mono">{tpl.id}</div>
                        </div>
                        <span className={`pill ${tpl.enabled ? "pillOn" : "pillOff"}`}>{tpl.enabled ? "Enabled" : "Disabled"}</span>
                      </div>
                    </button>
                  ))}
                </div>
              </div>

              <div className="panel">
                <div className="panelTitle">Build: {selectedTemplate?.name ?? "Template"}</div>
                <div className="panelSub">Drop playbooks (from list) or skills (from Skills tiles) into the container. Order = execution order.</div>

                <Switch
                  checked={!!selectedTemplate?.enabled}
                  onChange={(v) => setTemplates((cur) => cur.map((t) => (t.id === selectedTemplateId ? { ...t, enabled: v } : t)))}
                  label="Enable Template"
                />

                <DropZone
                  title="Template Sequence"
                  subtitle="Drop a playbook or skill to append it."
                  onDropPayload={(p) => {
                    let item: TemplateItem | null = null;
                    if (p.type === "playbook") {
                      item = { kind: "playbook", id: p.id };
                    } else if (p.type === "skill") {
                      if (!isSkillKey(p.key)) return;
                      item = { kind: "skill", key: p.key };
                    }

                    if (!item) return;

                    setTemplates((cur) =>
                      cur.map((t) => {
                        if (t.id !== selectedTemplateId) return t;

                        const exists =
                          item.kind === "playbook"
                            ? t.sequence.some((x) => x.kind === "playbook" && x.id === item.id)
                            : t.sequence.some((x) => x.kind === "skill" && x.key === item.key);

                        return exists ? t : { ...t, sequence: [...t.sequence, item] };
                      })
                    );
                  }}
                >
                  <div className="chips">
                    {(selectedTemplate?.sequence ?? []).map((it, idx) => (
                      <div key={`${it.kind}-${"id" in it ? it.id : it.key}-${idx}`} className="chip">
                        <span className="mono">
                          {it.kind}:{it.kind === "playbook" ? it.id : it.key}
                        </span>
                        <button
                          type="button"
                          className="chipX"
                          onClick={() => {
                            setTemplates((cur) =>
                              cur.map((t) => {
                                if (t.id !== selectedTemplateId) return t;
                                return { ...t, sequence: t.sequence.filter((_, i) => i !== idx) };
                              })
                            );
                          }}
                        >
                          ×
                        </button>
                      </div>
                    ))}
                    {(selectedTemplate?.sequence ?? []).length === 0 ? <div className="muted">No items yet. Drag a playbook or skill in.</div> : null}
                  </div>
                </DropZone>
              </div>
            </div>
          </SectionRow>
            </>
          ) : (
            <div className="panel">
              <div className="panelTitle">Legacy Panels Hidden</div>
              <div className="panelSub">Set <span className="mono">NEXT_PUBLIC_WEBUI_LEGACY_PANELS=1</span> to re-enable legacy Skills/Wizard/Playbooks/Templates sections.</div>
            </div>
          )}

          <SectionRow
            title="Business Knowledge Setup"
            subtitle="Business profile, template selection/preview, and OCR review workflow for customer-mode context."
            open={open.businessKnowledge}
            onToggle={() => setOpen((p) => ({ ...p, businessKnowledge: !p.businessKnowledge }))}
          >
            <BusinessProfileEditorPanel />
            <div style={{ marginTop: 14 }}>
              <TemplateSelectionPreviewPanel />
            </div>
            <div style={{ marginTop: 14 }}>
              <OcrUploadReviewPanel />
            </div>
          </SectionRow>

          <SectionRow
            title="Owner Inbox \+ Notifications"
            subtitle="Inbox actions, notification settings, and appointment request review."
            open={open.ownerOps}
            onToggle={() => setOpen((p) => ({ ...p, ownerOps: !p.ownerOps }))}
          >
            <InboxActionsPanel />
            <div style={{ marginTop: 14 }}>
              <NotificationSettingsPanel />
            </div>
            <div style={{ marginTop: 14 }}>
              <AppointmentRequestsViewPanel />
            </div>
          </SectionRow>
          <SectionRow
            title="Goals + Playbooks"
            subtitle="Chat wizard, goal status, and read-only playbook detail."
            open={open.goalsCenter}
            onToggle={() => setOpen((p) => ({ ...p, goalsCenter: !p.goalsCenter }))}
          >
            <GoalsWizardPanel />
            <div style={{ marginTop: 14 }}>
              <GoalsStatusPanel onSelectPlaybook={setSelectedGoalPlaybookId} />
            </div>
            <div style={{ marginTop: 14 }}>
              <PlaybookDetailViewPanel selectedPlaybookId={selectedGoalPlaybookId} />
            </div>
          </SectionRow>
          {LEGACY_PANELS_ENABLED ? (
            <>
          <SectionRow
  title="Agent Memory"
  subtitle="Short-term + long-term toggles and engagement phrases (wired). Memory Bank is wired via Control Plane for debugging."

  open={open.agentMemory}
  onToggle={() => setOpen((p) => ({ ...p, agentMemory: !p.agentMemory }))}
>
  <div className="panel">
    <div className="panelTitle">Memory</div>
    <div className="panelSub">
      These controls are wired to the control plane. Save to apply them at runtime.
    </div>

    <div className="form" style={{ marginTop: 12 }}>
      <Switch
        checked={!!settings.shortterm_memory_enabled}
        onChange={(v) => setSettings((p: any) => ({ ...p, shortterm_memory_enabled: v }))}
        label="Enable Short-Term Memory"
        helper="Wired: stored in control-plane settings."
      />

      <Switch
        checked={!!settings.longterm_memory_enabled}
        onChange={(v) => setSettings((p: any) => ({ ...p, longterm_memory_enabled: v }))}
        label="Enable Long-Term Memory"
        helper="Wired: stored in control-plane settings."
      />

      <TextField
        label="Engagement Prompt (phrases)"
        value={memoryEngagementPrompt}
        onChange={setMemoryEngagementPrompt}
        placeholder={"One phrase per line, e.g.\nremember this\nstore that in memory"}
        helper="Wired: phrases that will trigger the FSM/router to consult memory."
        multiline
      />
    </div>

    <div className="actions" style={{ marginTop: 12 }}>
      <button type="button" className="btnPrimary" disabled={saving} onClick={saveWiredSettings}>
        {saving ? "Saving…" : "Save Memory Settings"}
      </button>
    </div>
  </div>

  <div className="panel" style={{ marginTop: 14 }}>
    <div className="panelTitle">Memory Bank</div>
    <div className="panelSub">Search and browse long-term memory entries (wired via Control Plane).</div>

    <div style={{ marginTop: 12 }}>
      <AgentLongTermMemoryTable />
    </div>
  </div>

  <KBUploadPanel />
</SectionRow>
<SectionRow
  title="Chit-Chat"
  subtitle="Controls for chitchat behavior (dead air response delay)."
  open={open.chitchat}
  onToggle={() => setOpen((p) => ({ ...p, chitchat: !p.chitchat }))}
>
  <div className="panel">
    <div className="panelTitle">Chit-Chat</div>
    <div className="panelSub">Concept UI — we will wire these settings to the control plane next.</div>

    <div className="form" style={{ marginTop: 12 }}>
      <TextField
        label="Response Delay Time"
        value={chitchatDelaySec}
        onChange={setChitchatDelaySec}
        placeholder="2.0"
        helper="Time of dead air (seconds) before Vozlia responds in chitchat mode. (Concept)"
      />
    </div>
  </div>
</SectionRow>

<SectionRow
  title="Logging"
  subtitle="Toggle logging verbosity. Keep hot-path logging minimal in production."
  open={open.logging}
  onToggle={() => setOpen((p) => ({ ...p, logging: !p.logging }))}
>
  <div className="panel">
    <div className="panelTitle">Logging</div>
    <div className="panelSub">
      Concept UI. We’ll wire these toggles to env/config and propagate to the backend. Prefer realtime stats only (avoid per-frame deltas).
    </div>

    <div className="form" style={{ marginTop: 12 }}>
      {Object.keys(logToggles).map((k) => (
        <Switch
          key={k}
          checked={!!logToggles[k]}
          onChange={(v) => setLogToggles((cur) => ({ ...cur, [k]: v }))}
          label={k}
          helper={k === "REALTIME_LOG_DELTAS" ? "Avoid in production; can impact hot path." : undefined}
        />
      ))}
    </div>
  </div>
</SectionRow>

<SectionRow
  title="Email Accounts"
  subtitle="Connected Gmail accounts + controls for which inbox Gmail Summaries uses."
  open={open.email}
  onToggle={() => setOpen((p) => ({ ...p, email: !p.email }))}
>
  <div className="panel">
    <div className="panelTitle">Gmail Summaries Inbox Selection (wired)</div>
    <div className="panelSub">
      These two settings determine which email Gmail Summaries uses. This section duplicates the controls in the Gmail skill tile so it’s easy to find.
    </div>

    <div className="form" style={{ marginTop: 12 }}>
      <div className="field">
        <div className="fieldLabel">Default Inbox</div>
        <div className="fieldHelper">
          Maps to <span className="mono">gmail_account_id</span>. Used as the default inbox for summaries.
        </div>
        <select
          className="input"
          value={settings.gmail_account_id || ""}
          onChange={(e) => setSettings((p: any) => ({ ...p, gmail_account_id: e.target.value }))}
          disabled={accountsLoading}
        >
          <option value="">(not set)</option>
          {gmailActiveAccounts.map((a) => (
            <option key={a.id} value={a.id}>
              {(a.email_address || a.display_name || a.id) + (a.is_primary ? " (primary)" : "")}
            </option>
          ))}
        </select>

        <div style={{ marginTop: 10, display: "flex", gap: 10, flexWrap: "wrap" }}>
          <button
            type="button"
            className="btnSecondary"
            onClick={() => {
              const primary = gmailAccounts.find((a) => a.is_primary && a.is_active);
              if (primary) setSettings((p: any) => ({ ...p, gmail_account_id: primary.id }));
            }}
            disabled={accountsLoading}
          >
            Use Primary Inbox as Default
          </button>
          <button
            type="button"
            className="btnSecondary"
            onClick={() => {
              window.location.href = "/api/admin/gmail/connect";
            }}
            disabled={accountsLoading}
          >
            Reconnect Gmail (refresh token)
          </button>

          <button type="button" className="btnPrimary" disabled={saving} onClick={saveWiredSettings}>
            {saving ? "Saving…" : "Save Inbox Settings"}
          </button>
        </div>
      </div>

      <div className="field">
        <div className="fieldLabel">Enabled Inboxes (multi-inbox)</div>
        <div className="fieldHelper">
          Maps to <span className="mono">gmail_enabled_account_ids</span>. You can enable multiple inboxes to include in summaries.
        </div>

        <div className="checkGrid">
          {gmailActiveAccounts.map((a) => {
            const enabled: string[] = Array.isArray(settings.gmail_enabled_account_ids)
              ? settings.gmail_enabled_account_ids
              : [];
            const checked = enabled.includes(a.id);
            return (
              <label key={a.id} className="checkRow">
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={() => {
                    const next = checked ? enabled.filter((x) => x !== a.id) : [...enabled, a.id];
                    setSettings((p: any) => ({ ...p, gmail_enabled_account_ids: next }));
                  }}
                />
                <span className="checkText">
                  {a.email_address || a.display_name || a.id}{" "}
                  <span className="muted mono" style={{ marginLeft: 6 }}>
                    {a.id}
                  </span>
                </span>
              </label>
            );
          })}
          {gmailActiveAccounts.length === 0 ? <div className="muted">No active Gmail accounts found.</div> : null}
        </div>
      </div>
    </div>
  </div>

  <div className="panel" style={{ marginTop: 14 }}>
    <div className="panelTitle">Connected Gmail Accounts</div>
    <div className="panelSub">
      Primary/Active flags are stored on the email account records. Primary does not automatically change Gmail Summaries default inbox unless you set it above.
    </div>

    <div style={{ marginTop: 12 }}>
      {accountsLoading ? (
        <div className="muted">Loading…</div>
      ) : gmailAccounts.length === 0 ? (
        <div className="muted">No Gmail accounts found.</div>
      ) : (
        <div className="list">
          {gmailAccounts.map((a) => (
            <div key={a.id} className="rowCard">
              <div style={{ minWidth: 0 }}>
                <div className="rowTitle">{a.email_address || a.display_name || a.id}</div>
                <div className="rowSub">
                  <span className="mono">{a.id}</span> · {a.is_primary ? "Primary" : "Secondary"} ·{" "}
                  {a.is_active ? "Active" : "Inactive"}
                </div>
              </div>

              <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap", justifyContent: "flex-end" }}>
                <span className={`pill ${a.is_active ? "pillOn" : "pillOff"}`}>{a.is_active ? "Active" : "Inactive"}</span>

                <button
                  className={a.is_primary ? "btnPrimary" : "btnSecondary"}
                  type="button"
                  onClick={() => setPrimaryAccount(a.id)}
                  disabled={accountsLoading}
                >
                  {a.is_primary ? "Primary" : "Make Primary"}
                </button>

                <button
                  className="btnSecondary"
                  type="button"
                  onClick={() => toggleAccountActive(a.id, !a.is_active)}
                  disabled={accountsLoading}
                >
                  {a.is_active ? "Disable" : "Enable"}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>

    <div className="actions" style={{ marginTop: 12 }}>
      <button
        className="btnSecondary"
        type="button"
        onClick={async () => {
          try {
            setError(null);
            await Promise.all([loadSettings(), loadAccounts()]);
          } catch (e: any) {
            setError(e?.message || String(e));
          }
        }}
      >
        Refresh
      </button>
    </div>
  </div>
</SectionRow>
          <SectionRow
            title="Render Logs"
            subtitle="Live logs fetched from Render."
            open={open.renderLogs}
            onToggle={() => setOpen((p) => ({ ...p, renderLogs: !p.renderLogs }))}
          >
            <div className="panel" style={{ padding: 0 }}>
              <div style={{ padding: 14 }}>
                <div className="panelTitle">Render Logs</div>
                <div className="panelSub">Existing panel embedded near the bottom.</div>
              </div>
              <div style={{ padding: 14, paddingTop: 0 }}>
        <StatusBadgePanel />
        <RenderLogsPanel />
              </div>
            </div>
          </SectionRow>
            </>
          ) : null}
        </div>

        <footer className="foot">
          <div className="muted">
            Concept UI: Skills, Playbooks, Templates are not wired yet. Gmail Summaries enable + inbox selection remains wired.
          </div>
        </footer>
      </div>

      <style jsx global>{`
        :root{
          --bg:#F6F9FF;
          --card:#FFFFFF;
          --border:#E6ECF5;
          --text:#0F172A;
          --muted:#64748B;
          --accent:#06B6D4;
          --accentSoft: rgba(6,182,212,0.12);
          --shadow: 0 10px 30px rgba(15,23,42,0.08);
        }

        html,body{ margin:0; padding:0; background:var(--bg); color:var(--text); font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial; }
        .page{ min-height:100vh; position:relative; overflow-x:hidden; }
        .bg{
          position: fixed; inset:0;
          background-image:url("/circuit-watermark.jpg");
          background-size:cover; background-position:center;
          opacity:0.045; pointer-events:none;
        }
        .wrap{ position:relative; z-index:1; max-width:1080px; margin:0 auto; padding:22px 18px 50px; }

        .top{
          display:flex; justify-content:space-between; gap:16px; align-items:flex-start;
          background: var(--card);
          border:1px solid var(--border);
          border-radius:18px;
          padding:18px;
          box-shadow: var(--shadow);
        }
        .brand{ font-size:22px; font-weight:900; letter-spacing:-0.02em; }
        .subtitle{ margin-top:4px; color:var(--muted); font-size:13px; }
        .who{ text-align:right; min-width:220px; }
        .muted{ color:var(--muted); font-size:12px; }
        .mono{ font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }

        .alert{
          margin-top:14px; padding:14px 16px;
          border-radius:16px;
          border:1px solid rgba(239,68,68,0.35);
          background: rgba(239,68,68,0.08);
          box-shadow: var(--shadow);
        }
        .alertTitle{ font-weight:900; }
        .alertBody{ margin-top:6px; white-space:pre-wrap; font-size:13px; }

        .stack{ margin-top:16px; display:grid; gap:14px; }

        .sectionShell{
          border-radius:18px;
          background: var(--card);
          border:1px solid var(--border);
          box-shadow: var(--shadow);
          overflow:hidden;
        }
        .sectionHeader{
          width:100%; display:flex; align-items:center; gap:12px;
          padding:16px;
          background:transparent; border:none;
          cursor:pointer; text-align:left;
        }
        .plus{
          width:22px; height:22px; border-radius:8px;
          display:inline-flex; align-items:center; justify-content:center;
          border:1px solid var(--border);
          background: rgba(15,23,42,0.02);
          font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
          font-size:16px;
        }
        .sectionText{ flex:1; min-width:0; }
        .sectionTitle{ font-weight:900; }
        .sectionSub{ margin-top:4px; color:var(--muted); font-size:13px; line-height:1.35; }
        .sectionRight{ flex:0 0 auto; }
        .sectionBody{ padding:16px; padding-top:0; }
        .sectionBody::before{ content:""; display:block; height:1px; background:var(--border); margin-bottom:16px; }

        .panel{
          background: var(--card);
          border:1px solid var(--border);
          border-radius:18px;
          padding:14px;
          box-shadow: var(--shadow);
        }
        .panelInset{
          background: rgba(6,182,212,0.03);
          border:1px solid rgba(6,182,212,0.18);
          border-radius:16px;
          padding:14px;
        }
        .panelTitle{ font-weight:900; font-size:14px; }
        .panelSub{ margin-top:4px; color:var(--muted); font-size:12px; line-height:1.35; }

        .grid2{ display:grid; grid-template-columns: 1.25fr 1fr; gap:14px; }
        @media (max-width: 980px){ .grid2{ grid-template-columns: 1fr; } }

        .tiles{
          display:grid;
          grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
          gap:14px;
        }
        .tile{
          text-align:left;
          border-radius:16px;
          border:1px solid var(--border);
          background: var(--card);
          padding:14px;
          cursor:pointer;
          box-shadow: var(--shadow);
        }
        .tile.active{
          border:1px solid rgba(6,182,212,0.6);
          box-shadow: 0 12px 34px rgba(6,182,212,0.10);
        }
        .tileTop{ display:flex; justify-content:space-between; align-items:center; gap:10px; }
        .tileTitle{ font-weight:900; }
        .tileDesc{ margin-top:6px; font-size:13px; color:var(--muted); line-height:1.35; }

        .pill{
          font-size:12px;
          padding:4px 10px;
          border-radius:999px;
          border:1px solid var(--border);
          font-weight:800;
          white-space:nowrap;
        }
        .pillOn{ background: var(--accentSoft); color: #0e7490; border-color: rgba(6,182,212,0.28); }
        .pillOff{ background: rgba(100,116,139,0.08); color: #475569; }

        .form{ margin-top:14px; display:grid; gap:14px; }
        .field{ display:grid; gap:6px; }
        .fieldLabel{ font-weight:800; }
        .fieldHelper{ color:var(--muted); font-size:12px; }
        .input{
          width:100%;
          padding:12px;
          border-radius:12px;
          border:1px solid var(--border);
          background: #ffffff;
          color: var(--text);
          outline:none;
          box-shadow: 0 6px 18px rgba(15,23,42,0.05);
        }

        .switchRow{ display:flex; align-items:center; justify-content:space-between; gap:14px; }
        .switchText{ min-width:0; }
        .switchLabel{ font-weight:800; }
        .switchHelper{ margin-top:4px; color:var(--muted); font-size:12px; line-height:1.35; }
        .switch{
          width:44px; height:26px;
          border-radius:999px;
          border:1px solid var(--border);
          background: #f1f5f9;
          position:relative;
          cursor:pointer;
          box-shadow: 0 6px 18px rgba(15,23,42,0.06);
          flex: 0 0 auto;
        }
        .switch.on{ background: rgba(6,182,212,0.18); border-color: rgba(6,182,212,0.28); }
        .knob{
          position:absolute; top:3px; left:3px;
          width:20px; height:20px; border-radius:999px;
          background:#fff;
          border:1px solid rgba(15,23,42,0.10);
          transition: left 120ms ease;
        }
        .switch.on .knob{ left:21px; background:#06B6D4; border-color: rgba(6,182,212,0.35); }

        .actions{ display:flex; gap:10px; flex-wrap:wrap; }
        .btnPrimary{
          padding:10px 14px;
          border-radius:12px;
          border:1px solid rgba(6,182,212,0.45);
          background: rgba(6,182,212,0.16);
          color:#0b4f5f;
          font-weight:900;
          cursor:pointer;
        }

.btnSecondary{
  padding:10px 14px;
  border-radius:14px;
  border:1px solid var(--border);
  background:#fff;
  color:var(--text);
  font-weight:800;
  cursor:pointer;
  box-shadow: var(--shadow);
}
.btnSecondary:hover{ border-color: rgba(6,182,212,0.35); background: rgba(6,182,212,0.04); }

.table{
  width:100%;
  border-collapse:separate;
  border-spacing:0;
  font-size:13px;
}
.table th, .table td{
  padding:10px 12px;
  border-bottom:1px solid var(--border);
  text-align:left;
  vertical-align:top;
  background:#fff;
}
.table th{
  position:sticky;
  top:0;
  background: rgba(246,249,255,0.9);
  backdrop-filter: blur(6px);
  font-size:12px;
  letter-spacing:0.02em;
  text-transform:uppercase;
  color: var(--muted);
}

        .dropZone{
          margin-top:12px;
          border-radius:16px;
          border:1px dashed rgba(6,182,212,0.35);
          background: rgba(6,182,212,0.03);
          padding:12px;
        }
        .dropZone.over{
          border-color: rgba(6,182,212,0.70);
          background: rgba(6,182,212,0.06);
        }
        .dropHead{ display:flex; justify-content:space-between; gap:10px; padding-bottom:10px; }
        .dropTitle{ font-weight:900; }
        .dropSub{ color:var(--muted); font-size:12px; margin-top:4px; }
        .dropBody{ padding-top:8px; }

        .list{ display:grid; gap:10px; margin-top:12px; }
        .listItem{
          display:flex; align-items:center; justify-content:space-between; gap:12px;
          padding:10px 12px;
          border-radius:14px;
          border:1px solid var(--border);
          background: #ffffff;
        }
        .listSelect{
          border:1px solid var(--border);
          background:#fff;
          border-radius:14px;
          padding:10px 12px;
          cursor:pointer;
          text-align:left;
          box-shadow: 0 6px 18px rgba(15,23,42,0.05);
        }
        .listSelect.active{ border-color: rgba(6,182,212,0.55); background: rgba(6,182,212,0.06); }
        .row{ display:flex; justify-content:space-between; align-items:center; gap:12px; }
        .rowMain{ min-width:0; }
        .rowTitle{ font-weight:900; }
        .rowSub{ margin-top:4px; color:var(--muted); font-size:12px; }

        .rowCard{
          display:flex; justify-content:space-between; align-items:center; gap:12px;
          padding:12px;
          border-radius:14px;
          border:1px solid var(--border);
          background:#fff;
        }

        .chips{ display:flex; gap:10px; flex-wrap:wrap; padding-top:6px; }
        .chip{
          display:flex; align-items:center; gap:10px;
          padding:8px 10px;
          border-radius:999px;
          border:1px solid var(--border);
          background:#fff;
        }
        .chipX{
          border:none;
          background: rgba(239,68,68,0.10);
          color:#b91c1c;
          border-radius:999px;
          width:22px;
          height:22px;
          cursor:pointer;
          font-weight:900;
        }

        .checkGrid{ display:grid; gap:8px; padding-top:6px; }
        .checkRow{ display:flex; align-items:center; gap:10px; }
        .checkText{ color: var(--text); font-size:13px; }

        .foot{ margin-top:18px; padding: 6px 4px 0; }
      `}</style>
    </div>
  );
}

export async function getServerSideProps(ctx: GetServerSidePropsContext) {
  const { getServerSession } = await import("next-auth/next");
  const { authOptions } = await import("./api/auth/[...nextauth]");
  const session = await getServerSession(ctx.req, ctx.res, authOptions);

  if (!session) {
    return {
      redirect: {
        destination: `/api/auth/signin?callbackUrl=${encodeURIComponent("/admin")}`,
        permanent: false,
      },
    };
  }
  return { props: { session } };
}
