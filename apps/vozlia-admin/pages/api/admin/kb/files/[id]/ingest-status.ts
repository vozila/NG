import type { NextApiRequest, NextApiResponse } from "next";
import { getServerSession } from "next-auth/next";
import { authOptions } from "../../../../auth/[...nextauth]";

function mustEnv(name: string): string {
  const v = process.env[name];
  if (!v) throw new Error(`Missing env var: ${name}`);
  return v;
}

function appendQuery(url: string, query: NextApiRequest["query"]): string {
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(query || {})) {
    if (Array.isArray(v)) {
      for (const vv of v) params.append(k, String(vv));
    } else if (v !== undefined) {
      params.append(k, String(v));
    }
  }
  const qs = params.toString();
  return qs ? `${url}?${qs}` : url;
}

export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  try {
    const session = await getServerSession(req, res, authOptions);
    if (!session?.user?.email) return res.status(401).json({ error: "Unauthorized" });

    if (req.method !== "GET") return res.status(405).json({ error: "Method not allowed" });

    const id = req.query.id;
    if (!id || typeof id !== "string") return res.status(400).json({ error: "Missing id" });

    const tenantId = req.query.tenant_id;
    if (!tenantId || typeof tenantId !== "string" || !tenantId.trim()) {
      return res.status(400).json({ error: "tenant_id is required" });
    }

    const CONTROL_BASE = mustEnv("VOZLIA_CONTROL_BASE_URL");
    const ADMIN_KEY = mustEnv("VOZLIA_ADMIN_KEY");

    const url = appendQuery(`${CONTROL_BASE}/admin/kb/files/${encodeURIComponent(id)}/ingest-status`, {
      tenant_id: tenantId.trim(),
    });

    const upstream = await fetch(url, {
      method: "GET",
      headers: {
        "X-Vozlia-Admin-Key": ADMIN_KEY,
        Accept: "application/json",
      },
    });

    const text = await upstream.text();
    res.status(upstream.status);
    res.setHeader("content-type", upstream.headers.get("content-type") || "application/json");
    return res.send(text);
  } catch (err: any) {
    return res.status(502).json({ error: "proxy_failed", detail: String(err?.message || err) });
  }
}
