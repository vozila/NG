import type { NextApiRequest, NextApiResponse } from "next";

function mustEnv(name: string): string {
  const v = process.env[name];
  if (!v || !v.trim()) throw new Error(`Missing env var: ${name}`);
  return v.trim();
}

export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  try {
    if (req.method !== "POST") return res.status(405).json({ error: "Method not allowed" });

    const { token } = req.body ?? {};
    if (!token || typeof token !== "string") return res.status(400).json({ error: "Missing token" });

    const upstream = await fetch(`${mustEnv("VOZLIA_BACKEND_BASE_URL")}/kb/upload/complete`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ token }),
    });

    const text = await upstream.text();
    res.status(upstream.status).send(text);
  } catch (e: any) {
    res.status(500).json({ error: e?.message || "Internal error" });
  }
}
