import type { NextApiRequest, NextApiResponse } from "next";
import { getServerSession } from "next-auth/next";
import { authOptions } from "../../../auth/[...nextauth]";
import crypto from "crypto";
import { Readable } from "stream";

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

export const config = {
  api: {
    responseLimit: false,
  },
};

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

  const url = new URL(`${baseUrl.replace(/\/$/, "")}/admin/render/logs/export`);
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
      },
    });

    const ms = Date.now() - t0;
    if (debug) {
      console.log(`[render-proxy][${trace}] GET /export -> ${upstream.status} ${ms}ms ct=${upstream.headers.get("content-type")}`);
    }

    res.statusCode = upstream.status;

    const ct = upstream.headers.get("content-type") || "text/plain";
    res.setHeader("content-type", ct);

    const cd = upstream.headers.get("content-disposition");
    if (cd) res.setHeader("content-disposition", cd);

    // Stream body through
    const body = upstream.body as any;
    if (!body) {
      const buf = Buffer.from(await upstream.arrayBuffer());
      res.end(buf);
      return;
    }

    Readable.fromWeb(body).pipe(res);
  } catch (err: any) {
    return res.status(502).json({ error: "upstream_fetch_failed", trace, detail: err?.message ?? String(err) });
  }
}
