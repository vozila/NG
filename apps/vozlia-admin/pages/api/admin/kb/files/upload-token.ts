import type { NextApiRequest, NextApiResponse } from "next";
import { getServerSession } from "next-auth/next";
import { authOptions } from "../../../auth/[...nextauth]";

function mustEnv(name: string): string {
  const v = process.env[name];
  if (!v) throw new Error(`Missing env var: ${name}`);
  return v;
}

export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  try {
    const session = await getServerSession(req, res, authOptions);
    if (!session?.user?.email) return res.status(401).json({ error: "Unauthorized" });

    if (req.method !== "POST") return res.status(405).json({ error: "Method not allowed" });

    const { tenant_id, filename, content_type, kind } = (req.body ?? {}) as Record<string, unknown>;

    if (!tenant_id || typeof tenant_id !== "string" || !tenant_id.trim()) {
      return res.status(400).json({ error: "Missing tenant_id" });
    }
    if (!filename || typeof filename !== "string" || !filename.trim()) {
      return res.status(400).json({ error: "Missing filename" });
    }
    if (!content_type || typeof content_type !== "string" || !content_type.trim()) {
      return res.status(400).json({ error: "Missing content_type" });
    }
    if (!kind || typeof kind !== "string" || !kind.trim()) {
      return res.status(400).json({ error: "Missing kind" });
    }

    const CONTROL_BASE = mustEnv("VOZLIA_CONTROL_BASE_URL");
    const ADMIN_KEY = mustEnv("VOZLIA_ADMIN_KEY");

    const upstream = await fetch(`${CONTROL_BASE}/admin/kb/files/upload-token`, {
      method: "POST",
      headers: {
        "X-Vozlia-Admin-Key": ADMIN_KEY,
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify({
        tenant_id: tenant_id.trim(),
        filename: filename.trim(),
        content_type: content_type.trim(),
        kind: kind.trim(),
      }),
    });

    const text = await upstream.text();
    res.status(upstream.status);
    res.setHeader("content-type", upstream.headers.get("content-type") || "application/json");
    return res.send(text);
  } catch (err: any) {
    return res.status(502).json({ error: "proxy_failed", detail: String(err?.message || err) });
  }
}
