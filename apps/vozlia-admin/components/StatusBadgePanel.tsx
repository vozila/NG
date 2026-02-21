import { useEffect, useState } from "react";

type Check = {
  name: string;
  ok: boolean;
  ms?: number;
  status?: number;
  detail?: any;
};

type RegressionDiag = {
  ok: boolean;
  ts: string;
  checks: Check[];
};

export default function StatusBadgePanel() {
  const [data, setData] = useState<RegressionDiag | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(false);

  // Poll interval for /admin/diag/regression (seconds).
  // Use NEXT_PUBLIC_REGRESSION_POLL_SECONDS to override (default: 30).
  const pollSecondsRaw = (process.env.NEXT_PUBLIC_REGRESSION_POLL_SECONDS ?? "30").trim();
  const pollSeconds = Math.max(5, Number.parseInt(pollSecondsRaw, 10) || 30);
  const pollMs = pollSeconds * 1000;

  async function refresh() {
    setLoading(true);
    setError(null);
    try {
      const r = await fetch("/api/admin/diag/regression", { method: "GET" });
      const text = await r.text();
      if (!r.ok) throw new Error(`HTTP ${r.status}: ${text.slice(0, 400)}`);
      const j = JSON.parse(text);
      setData(j);
    } catch (e: any) {
      setError(e?.message ?? String(e));
      setData(null);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, pollMs);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const ok = data?.ok ?? false;

  return (
    <div style={{ border: "1px solid #333", borderRadius: 10, padding: 12, marginTop: 12 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{ fontWeight: 700 }}>System Status</div>
          <div
            style={{
              padding: "4px 10px",
              borderRadius: 999,
              border: "1px solid #222",
              background: ok ? "#143d1f" : "#3d1414",
              color: ok ? "#a6f3b9" : "#f3a6a6",
              fontSize: 12,
              fontWeight: 700,
            }}
            title={data?.ts ? `Last checked: ${data.ts}` : "Not checked yet"}
          >
            {loading ? "CHECKING…" : ok ? "OK" : "DEGRADED"}
          </div>
        </div>

        <button onClick={refresh} style={{ padding: "6px 10px" }}>
          Refresh
        </button>
      </div>

      {error ? (
        <div style={{ marginTop: 10, color: "#ff6b6b", whiteSpace: "pre-wrap" }}>{error}</div>
      ) : null}

      {data?.checks?.length ? (
        <div style={{ marginTop: 10, display: "grid", gap: 6 }}>
          {data.checks.map((c) => (
            <div key={c.name} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
              <div style={{ opacity: 0.9 }}>{c.name}</div>
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                {typeof c.ms === "number" ? <div style={{ fontSize: 12, opacity: 0.7 }}>{c.ms.toFixed(0)}ms</div> : null}
                <div
                  style={{
                    width: 10,
                    height: 10,
                    borderRadius: 999,
                    background: c.ok ? "#2ecc71" : "#ff6b6b",
                    border: "1px solid #222",
                  }}
                  title={c.ok ? "OK" : JSON.stringify(c.detail ?? c.status ?? "failed")}
                />
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div style={{ marginTop: 10, fontSize: 12, opacity: 0.75 }}>No checks yet.</div>
      )}
    </div>
  );
}
