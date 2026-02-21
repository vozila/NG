import type { NextApiRequest, NextApiResponse } from "next";
import { getServerSession } from "next-auth/next";
import { authOptions } from "../../auth/[...nextauth]";

function getEnv(name: string): string | undefined {
  const v = process.env[name];
  return v && v.trim() ? v.trim() : undefined;
}

function mustEnv(name: string): string {
  const v = getEnv(name);
  if (!v) throw new Error(`Missing env var: ${name}`);
  return v;
}

function getAdminKey(): string {
  return mustEnv("VOZLIA_ADMIN_KEY");
}

function getBackendBaseUrl(): string {
  return mustEnv("VOZLIA_BACKEND_BASE_URL");
}

export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  try {
    const session = await getServerSession(req, res, authOptions);
    if (!session?.user?.email) return res.status(401).json({ error: "Unauthorized" });

    if (req.method !== "POST") return res.status(405).json({ error: "Method not allowed" });

    const { to_number, note } = req.body ?? {};
    if (!to_number || typeof to_number !== "string") {
      return res.status(400).json({ error: "Missing to_number" });
    }

    const upstream = await fetch(`${getBackendBaseUrl()}/kb/link/send`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Vozlia-Admin-Key": getAdminKey(),
        Accept: "application/json",
      },
      body: JSON.stringify({
        to_number,
        tenant_email: session.user.email,
        note: typeof note === "string" ? note : undefined,
      }),
    });

    const text = await upstream.text();
    res.status(upstream.status).send(text);
  } catch (e: any) {
    res.status(500).json({ error: e?.message || "Internal error" });
  }
}
