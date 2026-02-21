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

    if (req.method !== "GET") return res.status(405).json({ error: "Method not allowed" });

    const url = new URL(`${getBackendBaseUrl()}/kb/docs`);
    url.searchParams.set("tenant_email", session.user.email);

    const upstream = await fetch(url.toString(), {
      method: "GET",
      headers: {
        "X-Vozlia-Admin-Key": getAdminKey(),
        Accept: "application/json",
      },
    });

    const text = await upstream.text();
    res.status(upstream.status).send(text);
  } catch (e: any) {
    res.status(500).json({ error: e?.message || "Internal error" });
  }
}
