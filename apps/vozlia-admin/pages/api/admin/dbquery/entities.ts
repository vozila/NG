import type { NextApiRequest, NextApiResponse } from "next";
import { getServerSession } from "next-auth/next";
import { authOptions } from "../../auth/[...nextauth]";

const CONTROL_BASE_URL = process.env.CONTROL_BASE_URL || "http://localhost:8000";

export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  const session = await getServerSession(req, res, authOptions);
  const adminKey = (session?.user as any)?.adminKey;
  if (!adminKey) return res.status(401).json({ detail: "Not authenticated" });

  if (req.method !== "GET") return res.status(405).json({ detail: "Method not allowed" });

  const r = await fetch(`${CONTROL_BASE_URL}/admin/dbquery/entities`, {
    headers: { "x-admin-key": adminKey },
  });
  const body = await r.json().catch(() => ({}));
  return res.status(r.status).json(body);
}
