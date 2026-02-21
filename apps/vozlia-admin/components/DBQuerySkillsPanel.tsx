/**
 * PURPOSE
 * -------
 * Provide a simple WebUI panel for managing DBQuery dynamic skills:
 * - list skills created via Voice AI / Wizard
 * - run a skill
 * - create/update/disable a daily schedule (channel/destination/time/timezone)
 * - delete a skill
 *
 * This intentionally mirrors the existing WebSearch MVP panel patterns so
 * all dynamic skills are manageable from the WebUI.
 */
"use client";

import React, { useEffect, useMemo, useState } from "react";

type DeliveryChannel = "email" | "sms" | "whatsapp" | "call";

type DBQuerySkill = {
  id: string;
  name: string;
  entity: string;
  enabled: boolean;
  triggers: string[];
  spec: any;
};

type DBQuerySchedule = {
  id: string;
  db_query_skill_id: string;
  time_of_day: string; // "HH:MM"
  timezone: string;
  channel: DeliveryChannel;
  destination: string;
  enabled: boolean;
  last_run_at?: string | null;
  next_run_at?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
};

function safeTimeParts(timeOfDay: string | undefined | null): { hour: number; minute: number } {
  const raw = (timeOfDay || "").trim();
  const m = raw.match(/^(\d{1,2}):(\d{2})$/);
  if (!m) return { hour: 9, minute: 0 };
  const hour = Math.max(0, Math.min(23, parseInt(m[1], 10)));
  const minute = Math.max(0, Math.min(59, parseInt(m[2], 10)));
  return { hour, minute };
}

function fmt(ts?: string | null) {
  if (!ts) return "";
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return ts;
  return d.toLocaleString();
}

export default function DBQuerySkillsPanel() {
  const [skills, setSkills] = useState<DBQuerySkill[]>([]);
  const [schedules, setSchedules] = useState<DBQuerySchedule[]>([]);

  const scheduleBySkillId = useMemo(() => {
    const m = new Map<string, DBQuerySchedule>();
    for (const s of schedules) m.set(s.db_query_skill_id, s);
    return m;
  }, [schedules]);

  const [detailSkillId, setDetailSkillId] = useState<string | null>(null);

  const [schedEnabled, setSchedEnabled] = useState<boolean>(true);
  const [schedTime, setSchedTime] = useState<string>("09:00");
  const [schedTimezone, setSchedTimezone] = useState<string>("America/New_York");
  const [schedChannel, setSchedChannel] = useState<DeliveryChannel>("email");
  const [schedDestination, setSchedDestination] = useState<string>("");

  const [runOut, setRunOut] = useState<any>(null);
  const [runErr, setRunErr] = useState<string>("");

  useEffect(() => {
    refreshLists().catch(() => void 0);
  }, []);

  useEffect(() => {
    if (!detailSkillId) return;

    const sched = scheduleBySkillId.get(detailSkillId);
    if (sched) {
      setSchedEnabled(!!sched.enabled);
      setSchedTime(sched.time_of_day || "09:00");
      setSchedTimezone(sched.timezone || "America/New_York");
      setSchedChannel((sched.channel as DeliveryChannel) || "email");
      setSchedDestination(sched.destination || "");
    } else {
      setSchedEnabled(true);
      setSchedTime("09:00");
      setSchedTimezone("America/New_York");
      setSchedChannel("email");
      setSchedDestination("");
    }
  }, [detailSkillId, scheduleBySkillId]);

  async function refreshLists() {
    const [skillsRes, schedRes] = await Promise.all([
      fetch("/api/admin/dbquery/skills", { method: "GET" }),
      fetch("/api/admin/dbquery/schedules", { method: "GET" }),
    ]);

    const skillsData = await skillsRes.json().catch(() => []);
    const schedData = await schedRes.json().catch(() => []);

    if (skillsRes.ok) setSkills(Array.isArray(skillsData) ? (skillsData as DBQuerySkill[]) : []);
    if (schedRes.ok) setSchedules(Array.isArray(schedData) ? (schedData as DBQuerySchedule[]) : []);
  }

  async function onDeleteSkill(id: string) {
    setRunErr("");
    const res = await fetch(`/api/admin/dbquery/skills/${id}`, { method: "DELETE" });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      setRunErr(body?.detail ? String(body.detail) : `Delete failed (${res.status})`);
      return;
    }
    if (detailSkillId === id) setDetailSkillId(null);
    await refreshLists();
  }

  async function onRunSkill(skill: DBQuerySkill) {
    setRunErr("");
    setRunOut(null);
    const res = await fetch("/api/admin/dbquery/run", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ spec: skill.spec }),
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      setRunErr(body?.detail ? String(body.detail) : `Run failed (${res.status})`);
      return;
    }
    setRunOut(body);
  }

  async function onSaveSchedule(skillId: string) {
    setRunErr("");

    const { hour, minute } = safeTimeParts(schedTime);

    const res = await fetch("/api/admin/dbquery/schedules", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        db_query_skill_id: skillId,
        hour,
        minute,
        timezone: schedTimezone,
        channel: schedChannel,
        destination: schedDestination,
        enabled: schedEnabled,
      }),
    });

    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      setRunErr(body?.detail ? String(body.detail) : `Schedule save failed (${res.status})`);
      return;
    }

    await refreshLists();
  }

  return (
    <div className="border rounded p-3">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">DB Query Skills</h2>
        <button className="px-2 py-1 border rounded" onClick={() => refreshLists()}>
          Refresh
        </button>
      </div>

      {runErr ? (
        <div className="mt-2 p-2 border rounded bg-red-50 text-red-700 text-sm whitespace-pre-wrap">{runErr}</div>
      ) : null}

      {skills.length === 0 ? (
        <div className="mt-2 text-sm text-gray-500">
          No DB query skills found. Create one via Voice AI / Wizard, then refresh.
        </div>
      ) : null}

      <div className="mt-3 space-y-2">
        {skills.map((s) => {
          const sched = scheduleBySkillId.get(s.id);
          const isOpen = detailSkillId === s.id;
          return (
            <div key={s.id} className="border rounded p-2">
              <div className="flex items-center justify-between gap-2">
                <div className="min-w-0">
                  <div className="font-medium truncate">{s.name}</div>
                  <div className="text-xs text-gray-500 truncate">
                    id={s.id} • entity={s.entity} • enabled={String(s.enabled)}
                  </div>
                  {sched ? (
                    <div className="text-xs text-gray-600 mt-1">
                      Schedule: {sched.enabled ? "ON" : "OFF"} • {sched.channel} → {sched.destination} @{" "}
                      {sched.time_of_day} ({sched.timezone})
                    </div>
                  ) : (
                    <div className="text-xs text-gray-600 mt-1">Schedule: (none)</div>
                  )}
                </div>

                <div className="flex items-center gap-2 shrink-0">
                  <button className="px-2 py-1 border rounded" onClick={() => onRunSkill(s)}>
                    Run now
                  </button>
                  <button
                    className="px-2 py-1 border rounded"
                    onClick={() => setDetailSkillId(isOpen ? null : s.id)}
                  >
                    {isOpen ? "Hide" : "Schedule"}
                  </button>
                  <button className="px-2 py-1 border rounded text-red-700" onClick={() => onDeleteSkill(s.id)}>
                    Delete
                  </button>
                </div>
              </div>

              {isOpen ? (
                <div className="mt-3 grid grid-cols-1 md:grid-cols-2 gap-2">
                  <label className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={schedEnabled}
                      onChange={(e) => setSchedEnabled(e.target.checked)}
                    />
                    Enabled
                  </label>

                  <label className="text-sm">
                    Time (HH:MM)
                    <input
                      className="w-full border rounded px-2 py-1"
                      value={schedTime}
                      onChange={(e) => setSchedTime(e.target.value)}
                      placeholder="09:00"
                    />
                  </label>

                  <label className="text-sm">
                    Timezone
                    <input
                      className="w-full border rounded px-2 py-1"
                      value={schedTimezone}
                      onChange={(e) => setSchedTimezone(e.target.value)}
                      placeholder="America/New_York"
                    />
                  </label>

                  <label className="text-sm">
                    Channel
                    <select
                      className="w-full border rounded px-2 py-1"
                      value={schedChannel}
                      onChange={(e) => setSchedChannel(e.target.value as DeliveryChannel)}
                    >
                      <option value="email">email</option>
                      <option value="sms">sms</option>
                      <option value="whatsapp">whatsapp</option>
                      <option value="call">call</option>
                    </select>
                  </label>

                  <label className="text-sm md:col-span-2">
                    Destination
                    <input
                      className="w-full border rounded px-2 py-1"
                      value={schedDestination}
                      onChange={(e) => setSchedDestination(e.target.value)}
                      placeholder="you@example.com / +1..."
                    />
                  </label>

                  <div className="md:col-span-2 flex items-center gap-2">
                    <button className="px-3 py-1 border rounded" onClick={() => onSaveSchedule(s.id)}>
                      Save schedule
                    </button>
                    {sched?.last_run_at ? (
                      <span className="text-xs text-gray-500">Last run: {fmt(sched.last_run_at)}</span>
                    ) : null}
                    {sched?.next_run_at ? (
                      <span className="text-xs text-gray-500">Next: {fmt(sched.next_run_at)}</span>
                    ) : null}
                  </div>
                </div>
              ) : null}
            </div>
          );
        })}
      </div>

      {runOut ? (
        <div className="mt-4">
          <div className="font-semibold">Run output</div>
          <pre className="mt-1 p-2 border rounded bg-gray-50 text-xs overflow-auto max-h-96">
            {JSON.stringify(runOut, null, 2)}
          </pre>
        </div>
      ) : null}
    </div>
  );
}
