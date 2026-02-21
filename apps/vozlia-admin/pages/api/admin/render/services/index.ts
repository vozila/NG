import type { NextApiRequest, NextApiResponse } from "next";
import { getServerSession } from "next-auth/next";
import { authOptions } from "../../../auth/[...nextauth]";
import crypto from "crypto";

function getEnv(name: string): string | undefined {
  const v = process.env[name];
  return v && v.trim() ? v.trim() : undefined;
}

function getAdminKey(): string | undefined {
  return getEnv("VOZLIA_ADMIN_KEY") || getEnv("VOZLIA_ADMIN_API_KEY");
}

function getBaseUrl(): string | undefined {
  return getEnv("VOZLIA_CONTROL_BASE_URL") || getEnv("VOZLIA_CONTROL_PLANE_URL");
}

function parseLimit(q: unknown): number {
  const raw = Array.isArray(q) ? q[0] : q;
  let n = parseInt(String(raw ?? "100"), 10);
  if (!Number.isFinite(n) || n < 1) n = 100;
  // Render list endpoints: max 100
  if (n > 100) n = 100;
  return n;
}

export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  const session = await getServerSession(req, res, authOptions);
  if (!session) return res.status(401).json({ error: "unauthorized" });

  if (req.method !== "GET") return res.status(405).json({ error: "method_not_allowed" });

  const baseUrl = getBaseUrl();
  const adminKey = getAdminKey();
  if (!baseUrl) return res.status(500).json({ error: "missing_env", name: "VOZLIA_CONTROL_BASE_URL" });
  if (!adminKey) return res.status(500).json({ error: "missing_env", name: "VOZLIA_ADMIN_KEY" });

  const trace = (req.headers["x-vozlia-trace"] as string | undefined) || crypto.randomUUID();
  res.setHeader("x-vozlia-trace", trace);

  const debug = getEnv("VOZLIA_DEBUG_RENDER_LOGS") === "1";

  const limit = parseLimit(req.query.limit);
  const url = new URL(`${baseUrl.replace(/\/$/, "")}/admin/render/services`);
  url.searchParams.set("limit", String(limit));

  const t0 = Date.now();
  try {
    const upstream = await fetch(url.toString(), {
      method: "GET",
      headers: {
        "X-Vozlia-Admin-Key": adminKey,
        "X-Vozlia-Trace": trace,
        Accept: "application/json",
      },
    });

    const ms = Date.now() - t0;
    const contentType = upstream.headers.get("content-type") || "";
    const rawText = await upstream.text();

    if (debug) {
      const preview = rawText.slice(0, 400).replace(/\s+/g, " ");
      console.log(
        `[render-proxy][${trace}] GET /admin/render/services?limit=${limit} -> ${upstream.status} ${ms}ms ct=${contentType} body='${preview}'`
      );
    }

    res.status(upstream.status);
    res.setHeader("content-type", contentType || "application/json");

    if (contentType.includes("application/json")) {
      try {
        const parsed = rawText ? JSON.parse(rawText) : [];
        // Normalize to { services: [...] } so UI can't silently fail
        if (Array.isArray(parsed)) return res.json({ services: parsed, trace });
        if (parsed && typeof parsed === "object") {
          if (Array.isArray((parsed as any).services)) return res.json({ ...(parsed as any), trace });
          if ((parsed as any).id && (parsed as any).name) return res.json({ services: [parsed], trace });
          return res.json({ ...(parsed as any), trace });
        }
        return res.json({ services: [], trace });
      } catch (e: any) {
        return res.status(502).json({ error: "bad_upstream_json", trace, preview: rawText.slice(0, 800) });
      }
    }

    // Non-JSON (shouldn't happen)
    return res.send(rawText);
  } catch (err: any) {
    return res.status(502).json({ error: "upstream_fetch_failed", trace, detail: err?.message ?? String(err) });
  }
}
