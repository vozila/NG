import { useState, type ReactNode } from "react";

export type DragPayload =
  | { type: "skill"; key: string }
  | { type: "playbook"; id: string };

export function safeParseDragPayload(raw: string): DragPayload | null {
  try {
    const obj = JSON.parse(raw) as Record<string, unknown>;
    const type = obj["type"];
    if (type === "skill") {
      const key = obj["key"];
      if (typeof key === "string" && key.length > 0) return { type: "skill", key };
      return null;
    }
    if (type === "playbook") {
      const id = obj["id"];
      if (typeof id === "string" && id.length > 0) return { type: "playbook", id };
      return null;
    }
    return null;
  } catch {
    return null;
  }
}

export function SectionRow({
  title,
  subtitle,
  open,
  onToggle,
  children,
  rightSlot,
}: {
  title: string;
  subtitle: string;
  open: boolean;
  onToggle: () => void;
  children: ReactNode;
  rightSlot?: ReactNode;
}) {
  return (
    <div className="sectionShell">
      <button type="button" className="sectionHeader" onClick={onToggle}>
        <span className="plus">{open ? "–" : "+"}</span>
        <div className="sectionText">
          <div className="sectionTitle">{title}</div>
          <div className="sectionSub">{subtitle}</div>
        </div>
        {rightSlot ? <div className="sectionRight">{rightSlot}</div> : null}
      </button>
      {open ? <div className="sectionBody">{children}</div> : null}
    </div>
  );
}

export function Switch({
  checked,
  onChange,
  label,
  helper,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
  helper?: string;
}) {
  return (
    <div className="switchRow">
      <div className="switchText">
        <div className="switchLabel">{label}</div>
        {helper ? <div className="switchHelper">{helper}</div> : null}
      </div>
      <button type="button" className={`switch ${checked ? "on" : "off"}`} onClick={() => onChange(!checked)} aria-pressed={checked}>
        <span className="knob" />
      </button>
    </div>
  );
}

export function TextField({
  label,
  value,
  onChange,
  placeholder,
  helper,
  multiline,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  helper?: string;
  multiline?: boolean;
}) {
  return (
    <div className="field">
      <div className="fieldLabel">{label}</div>
      {helper ? <div className="fieldHelper">{helper}</div> : null}
      {multiline ? (
        <textarea className="input" rows={4} value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} />
      ) : (
        <input className="input" value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} />
      )}
    </div>
  );
}

export function SkillTile({
  title,
  desc,
  enabled,
  active,
  onClick,
  draggableKey,
}: {
  title: string;
  desc: string;
  enabled: boolean;
  active: boolean;
  onClick: () => void;
  draggableKey: string;
}) {
  return (
    <button
      type="button"
      className={`tile ${active ? "active" : ""}`}
      onClick={onClick}
      draggable
      onDragStart={(e) => {
        const payload: DragPayload = { type: "skill", key: draggableKey };
        e.dataTransfer.setData("application/json", JSON.stringify(payload));
        e.dataTransfer.effectAllowed = "copyMove";
      }}
    >
      <div className="tileTop">
        <div className="tileTitle">{title}</div>
        <span className={`pill ${enabled ? "pillOn" : "pillOff"}`}>{enabled ? "Enabled" : "Disabled"}</span>
      </div>
      <div className="tileDesc">{desc}</div>
    </button>
  );
}

export function DropZone({
  title,
  subtitle,
  onDropPayload,
  children,
}: {
  title: string;
  subtitle: string;
  onDropPayload: (p: DragPayload) => void;
  children: ReactNode;
}) {
  const [over, setOver] = useState(false);
  return (
    <div
      className={`dropZone ${over ? "over" : ""}`}
      onDragOver={(e) => {
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setOver(false);
        const raw = e.dataTransfer.getData("application/json");
        const payload = safeParseDragPayload(raw);
        if (payload) onDropPayload(payload);
      }}
    >
      <div className="dropHead">
        <div>
          <div className="dropTitle">{title}</div>
          <div className="dropSub">{subtitle}</div>
        </div>
      </div>
      <div className="dropBody">{children}</div>
    </div>
  );
}
