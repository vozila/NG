import type { NextApiRequest, NextApiResponse } from "next";
import { getServerSession } from "next-auth/next";
import { authOptions } from "../../auth/[...nextauth]";

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
      params.set(k, String(v));
    }
  }
  const qs = params.toString();
  return qs ? `${url}?${qs}` : url;
}

/**
 * Vercel API Route: GET /api/admin/memory/turns
 * Server-side proxy to Control Plane: GET /admin/memory/turns
 */
export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  const session = await getServerSession(req, res, authOptions);
  if (!session) return res.status(401).json({ error: "unauthorized" });

  if (req.method !== "GET") {
    res.setHeader("Allow", "GET");
    return res.status(405).json({ error: "method_not_allowed" });
  }

  const CONTROL_BASE = mustEnv("VOZLIA_CONTROL_BASE_URL").replace(/\/+$/, "");
  const ADMIN_KEY = mustEnv("VOZLIA_ADMIN_KEY");

  const url = appendQuery(`${CONTROL_BASE}/admin/memory/turns`, req.query);

  const upstream = await fetch(url, {
    method: "GET",
    headers: {
      "X-Vozlia-Admin-Key": ADMIN_KEY,
      "Accept": "application/json",
    },
  });

  const text = await upstream.text();
  res.status(upstream.status);
  res.setHeader("Content-Type", upstream.headers.get("content-type") || "application/json");
  return res.send(text);
}
