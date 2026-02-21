import type { NextApiRequest, NextApiResponse } from "next";
import { getServerSession } from "next-auth/next";
import { authOptions } from "../../auth/[...nextauth]";

function mustEnv(name: string): string {
  const v = process.env[name];
  if (!v) throw new Error(`Missing env var: ${name}`);
  return v;
}

export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  try {
    const session = await getServerSession(req, res, authOptions);
    if (!session?.user?.email) return res.status(401).json({ error: "Unauthorized" });
    if (req.method !== "PATCH") return res.status(405).json({ error: "Method not allowed" });

    const id = String(req.query.id || "").trim();
    if (!id) return res.status(400).json({ error: "Missing goal id" });

    const CONTROL_BASE = mustEnv("VOZLIA_CONTROL_BASE_URL").replace(/\/+$/, "");
    const ADMIN_KEY = mustEnv("VOZLIA_ADMIN_KEY");

    const primary = `${CONTROL_BASE}/admin/goals/${encodeURIComponent(id)}`;
    const fallback = `${CONTROL_BASE}/owner/goals/${encodeURIComponent(id)}`;

    let upstream = await fetch(primary, {
      method: "PATCH",
      headers: {
        "X-Vozlia-Admin-Key": ADMIN_KEY,
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify(req.body ?? {}),
    });

    if (upstream.status === 404) {
      upstream = await fetch(fallback, {
        method: "PATCH",
        headers: {
          "X-Vozlia-Admin-Key": ADMIN_KEY,
          "Content-Type": "application/json",
          Accept: "application/json",
        },
        body: JSON.stringify(req.body ?? {}),
      });
    }

    const text = await upstream.text();
    res.status(upstream.status);
    res.setHeader("content-type", upstream.headers.get("content-type") || "application/json");
    return res.send(text);
  } catch (err: unknown) {
    return res.status(502).json({ error: "proxy_failed", detail: String((err as Error)?.message || err) });
  }
}
