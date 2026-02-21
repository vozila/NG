import type { NextApiRequest, NextApiResponse } from "next";
import { getServerSession } from "next-auth/next";
import { authOptions } from "../../auth/[...nextauth]";
import crypto from "crypto";

function mustEnv(name: string): string {
  const v = process.env[name];
  if (!v) throw new Error(`Missing env var: ${name}`);
  return v;
}

function getBaseUrl(req: NextApiRequest): string {
  const proto = (req.headers["x-forwarded-proto"] as string) || "https";
  const host = req.headers.host;
  return `${proto}://${host}`;
}

export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  const session = await getServerSession(req, res, authOptions);
  if (!session) return res.redirect(`/api/auth/signin?callbackUrl=${encodeURIComponent("/admin")}`);

  const clientId = process.env.GMAIL_OAUTH_CLIENT_ID || process.env.GOOGLE_CLIENT_ID;
  const clientSecret = process.env.GMAIL_OAUTH_CLIENT_SECRET || process.env.GOOGLE_CLIENT_SECRET;

  if (!clientId || !clientSecret) {
    return res.status(500).json({ error: "missing_google_oauth_env", detail: "Set GMAIL_OAUTH_CLIENT_ID/SECRET (or GOOGLE_CLIENT_ID/SECRET)" });
  }

  const redirectUri = process.env.GMAIL_OAUTH_REDIRECT_URI || `${getBaseUrl(req)}/api/admin/gmail/callback`;

  const scopes = [
    // Gmail
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
    // Calendar
    "https://www.googleapis.com/auth/calendar.events",
  ];

  const state = crypto.randomBytes(16).toString("hex");
  // store state in httpOnly cookie for CSRF protection
  res.setHeader("Set-Cookie", `gmail_oauth_state=${state}; HttpOnly; Path=/; SameSite=Lax; Secure`);

  const params = new URLSearchParams({
    client_id: clientId,
    redirect_uri: redirectUri,
    response_type: "code",
    access_type: "offline",
    prompt: "consent",
    include_granted_scopes: "true",
    state,
    scope: scopes.join(" "),
  });

  const url = `https://accounts.google.com/o/oauth2/v2/auth?${params.toString()}`;
  return res.redirect(url);
}
