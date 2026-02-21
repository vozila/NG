import type { NextApiRequest, NextApiResponse } from "next";
import { getServerSession } from "next-auth/next";
import { authOptions } from "../../auth/[...nextauth]";

function mustEnv(name: string): string {
  const v = process.env[name];
  if (!v) throw new Error(`Missing env var: ${name}`);
  return v;
}

export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  const session = await getServerSession(req, res, authOptions);
  if (!session) return res.status(401).json({ error: "unauthorized" });

  const CONTROL_BASE = mustEnv("VOZLIA_CONTROL_BASE_URL").replace(/\/+$/, "");
  const ADMIN_KEY = mustEnv("VOZLIA_ADMIN_KEY");

  const { id } = req.query;
  if (!id || typeof id !== "string") return res.status(400).json({ error: "missing_id" });

  const url = `${CONTROL_BASE}/admin/email-accounts/${encodeURIComponent(id)}`;

  try {
    if (req.method === "PATCH") {
      const upstream = await fetch(url, {
        method: "PATCH",
        headers: {
          "X-Vozlia-Admin-Key": ADMIN_KEY,
          "Content-Type": "application/json",
          Accept: "application/json",
        },
        body: JSON.stringify(req.body ?? {}),
      });

      const text = await upstream.text();
      res.status(upstream.status);
      res.setHeader("content-type", upstream.headers.get("content-type") || "application/json");
      return res.send(text);
    }

    if (req.method === "DELETE") {
      const hard = typeof req.query.hard === "string" ? req.query.hard : undefined;
      const delUrl = hard ? `${url}?hard=${encodeURIComponent(hard)}` : url;

      const upstream = await fetch(delUrl, {
        method: "DELETE",
        headers: {
          "X-Vozlia-Admin-Key": ADMIN_KEY,
          Accept: "application/json",
        },
      });

      const text = await upstream.text();
      res.status(upstream.status);
      res.setHeader("content-type", upstream.headers.get("content-type") || "application/json");
      return res.send(text);
    }

    return res.status(405).json({ error: "method_not_allowed" });
  } catch (err: any) {
    return res.status(500).json({ error: "proxy_failed", detail: String(err?.message || err) });
  }
}
