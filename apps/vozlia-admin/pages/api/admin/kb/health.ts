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

    if (req.method !== "GET") return res.status(405).json({ error: "Method not allowed" });

    const CONTROL_BASE = mustEnv("VOZLIA_CONTROL_BASE_URL");
    const ADMIN_KEY = mustEnv("VOZLIA_ADMIN_KEY");

    const upstream = await fetch(`${CONTROL_BASE}/admin/kb/health`, {
      method: "GET",
      headers: { "X-Vozlia-Admin-Key": ADMIN_KEY, Accept: "application/json" },
    });

    const text = await upstream.text();
    res.status(upstream.status);
    res.setHeader("content-type", upstream.headers.get("content-type") || "application/json");
    return res.send(text);
  } catch (err: any) {
    return res.status(502).json({ error: "proxy_failed", detail: String(err?.message || err) });
  }
}
