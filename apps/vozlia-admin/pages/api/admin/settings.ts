import type { NextApiRequest, NextApiResponse } from "next";
import { getServerSession } from "next-auth/next";
import { authOptions } from "../auth/[...nextauth]";

function mustEnv(name: string): string {
  const v = process.env[name];
  if (!v) throw new Error(`Missing env var: ${name}`);
  return v;
}

/**
 * Vercel API Route: /api/admin/settings
 *
 * Server-side proxy to the Render "vozlia-control" service.
 * - avoids CORS issues
 * - keeps admin key secret (never exposed to the browser)
 *
 * Required env vars:
 * - VOZLIA_CONTROL_BASE_URL   (e.g. https://vozlia-control.onrender.com)
 * - VOZLIA_ADMIN_KEY          (your X-Vozlia-Admin-Key for the control service)
 */
export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  const session = await getServerSession(req, res, authOptions);
  if (!session) return res.status(401).json({ error: "unauthorized" });

  const CONTROL_BASE = mustEnv("VOZLIA_CONTROL_BASE_URL").replace(/\/+$/, "");
  const ADMIN_KEY = mustEnv("VOZLIA_ADMIN_KEY");

  const url = `${CONTROL_BASE}/admin/settings`;

  try {
    let upstream: Response;

    if (req.method === "GET") {
      upstream = await fetch(url, {
        method: "GET",
        headers: {
          "X-Vozlia-Admin-Key": ADMIN_KEY,
          Accept: "application/json",
        },
      });
    } else if (req.method === "PATCH") {
      upstream = await fetch(url, {
        method: "PATCH",
        headers: {
          "X-Vozlia-Admin-Key": ADMIN_KEY,
          "Content-Type": "application/json",
          Accept: "application/json",
        },
        body: JSON.stringify(req.body ?? {}),
      });
    } else {
      return res.status(405).json({ error: "method_not_allowed" });
    }

    const text = await upstream.text();
    res.status(upstream.status);
    res.setHeader("content-type", upstream.headers.get("content-type") || "application/json");

    // Try JSON first, but don't die if upstream sends plain-text.
    try {
      const json = text ? JSON.parse(text) : {};
      return res.json(json);
    } catch {
      return res.send(text);
    }
  } catch (err: any) {
    return res.status(502).json({
      detail: "Upstream request failed",
      error: err?.message ?? String(err),
    });
  }
}
