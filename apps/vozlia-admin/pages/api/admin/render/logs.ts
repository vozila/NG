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

function asString(v: unknown): string | null {
  return typeof v === "string" && v.length ? v : null;
}

export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  const session = await getServerSession(req, res, authOptions);
  if (!session) return res.status(401).json({ error: "unauthorized" });

  if (req.method !== "GET") return res.status(405).json({ error: "method_not_allowed" });

  const service_id = asString(req.query.service_id);
  const start_ms = asString(req.query.start_ms);
  const end_ms = asString(req.query.end_ms);

  if (!service_id || !start_ms || !end_ms) {
    return res.status(400).json({ error: "missing_required_query_params", required: ["service_id", "start_ms", "end_ms"] });
  }

  const qs = new URLSearchParams({ service_id, start_ms, end_ms });
  const instance_id = asString(req.query.instance_id);
  const limit = asString(req.query.limit);
  const q = asString(req.query.q);
  if (instance_id) qs.set("instance_id", instance_id);
  if (limit) qs.set("limit", limit);
  if (q) qs.set("q", q);

  const url = `${controlBase()}/admin/render/logs?${qs.toString()}`;

  try {
    const upstream = await fetch(url, {
      method: "GET",
      headers: { "X-Vozlia-Admin-Key": adminKey(), Accept: "application/json" },
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
