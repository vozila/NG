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

  const service_id = String(req.query.service_id || "");
  if (!service_id) return res.status(400).json({ error: "missing_service_id", trace });

  const url = new URL(`${baseUrl.replace(/\/$/, "")}/admin/render/logs`);
  for (const [k, v] of Object.entries(req.query || {})) {
    if (typeof v === "string") url.searchParams.set(k, v);
  }

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
      console.log(`[render-proxy][${trace}] GET /logs ${service_id} -> ${upstream.status} ${ms}ms ct=${contentType} body='${preview}'`);
    }

    res.status(upstream.status);
    res.setHeader("content-type", contentType || "application/json");

    if (contentType.includes("application/json")) {
      try {
        const parsed = rawText ? JSON.parse(rawText) : {};
        if (parsed && typeof parsed === "object") return res.json({ ...(parsed as any), trace });
        return res.json({ trace, raw: rawText });
      } catch {
        return res.status(502).json({ error: "bad_upstream_json", trace, preview: rawText.slice(0, 800) });
      }
    }

    return res.send(rawText);
  } catch (err: any) {
    return res.status(502).json({ error: "upstream_fetch_failed", trace, detail: err?.message ?? String(err) });
  }
}
