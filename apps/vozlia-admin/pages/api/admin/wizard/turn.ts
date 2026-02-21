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

function looksLikeJson(text: string): boolean {
  const t = (text || "").trim();
  return t.startsWith("{") || t.startsWith("[");
}

export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  const session = await getServerSession(req, res, authOptions);
  if (!session) return res.status(401).json({ error: "unauthorized" });

  if (req.method !== "POST") return res.status(405).json({ error: "method_not_allowed" });

  const url = `${controlBase()}/admin/wizard/turn`;

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

    const status = upstream.status;
    const upstreamContentType = upstream.headers.get("content-type") || "";
    const text = await upstream.text();

    // IMPORTANT: This route should always return JSON so the browser client can safely call res.json().
    // If the upstream returns non-JSON (e.g. plain "Internal Server Error"), wrap it in a JSON envelope.
    let payload: any = {};
    let parsed = false;

    if (upstreamContentType.includes("application/json") || looksLikeJson(text)) {
      try {
        payload = text ? JSON.parse(text) : {};
        parsed = true;
      } catch {
        parsed = false;
      }
    }

    if (!parsed) {
      payload = {
        error: "upstream_non_json_response",
        upstream_status: status,
        upstream_content_type: upstreamContentType,
        upstream_text: (text || "").slice(0, 4000),
      };
    }

    res.status(status);
    res.setHeader("content-type", "application/json");
    return res.json(payload);
  } catch (err: any) {
    return res.status(502).json({
      error: "upstream_request_failed",
      detail: "Upstream request failed",
      message: err?.message ?? String(err),
    });
  }
}
