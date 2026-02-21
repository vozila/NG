import type { NextApiRequest, NextApiResponse } from "next";
import { getServerSession } from "next-auth/next";
import { authOptions } from "../../auth/[...nextauth]";

function mustEnv(name: string): string {
  const v = process.env[name];
  if (!v) throw new Error(`Missing env var: ${name}`);
  return v;
}

function controlBase(): string {
  return mustEnv("VOZLIA_CONTROL_BASE_URL").replace(/\/+$/, "");
}

function adminKey(): string {
  return mustEnv("VOZLIA_ADMIN_KEY");
}

export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  const session = await getServerSession(req, res, authOptions);
  if (!session) return res.status(401).json({ error: "unauthorized" });

  if (req.method !== "POST") return res.status(405).json({ error: "method_not_allowed" });

  const url = `${controlBase()}/admin/websearch/search`;

  try {
    const upstream = await fetch(url, {
      method: "POST",
      headers: {
        "X-Vozlia-Admin-Key": adminKey(),
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify(req.body ?? {}),
    });

    const text = await upstream.text();
    res.status(upstream.status);
    res.setHeader("content-type", upstream.headers.get("content-type") || "application/json");
    try {
      return res.json(text ? JSON.parse(text) : {});
    } catch {
      return res.send(text);
    }
  } catch (err: any) {
    return res.status(502).json({ detail: "Upstream request failed", error: err?.message ?? String(err) });
  }
}
