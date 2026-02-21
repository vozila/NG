import type { NextApiRequest, NextApiResponse } from "next";
import { getServerSession } from "next-auth/next";
import { authOptions } from "../../auth/[...nextauth]";

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

function parseCookies(req: NextApiRequest): Record<string, string> {
  const cookie = req.headers.cookie || "";
  const out: Record<string, string> = {};
  cookie.split(";").forEach((kv) => {
    const idx = kv.indexOf("=");
    if (idx > -1) {
      const k = kv.slice(0, idx).trim();
      const v = kv.slice(idx + 1).trim();
      if (k) out[k] = decodeURIComponent(v);
    }
  });
  return out;
}

export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  const session = await getServerSession(req, res, authOptions);
  if (!session) return res.redirect(`/api/auth/signin?callbackUrl=${encodeURIComponent("/admin")}`);

  const clientId = process.env.GMAIL_OAUTH_CLIENT_ID || process.env.GOOGLE_CLIENT_ID;
  const clientSecret = process.env.GMAIL_OAUTH_CLIENT_SECRET || process.env.GOOGLE_CLIENT_SECRET;
  if (!clientId || !clientSecret) {
    return res.status(500).json({ error: "missing_google_oauth_env" });
  }

  const code = typeof req.query.code === "string" ? req.query.code : null;
  const state = typeof req.query.state === "string" ? req.query.state : null;
  if (!code) return res.status(400).json({ error: "missing_code" });

  const cookies = parseCookies(req);
  const expectedState = cookies["gmail_oauth_state"];
  if (!state || !expectedState || state !== expectedState) {
    return res.status(400).json({ error: "state_mismatch" });
  }

  const redirectUri = process.env.GMAIL_OAUTH_REDIRECT_URI || `${getBaseUrl(req)}/api/admin/gmail/callback`;

  // Exchange code for tokens
  const tokenResp = await fetch("https://oauth2.googleapis.com/token", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      code,
      client_id: clientId,
      client_secret: clientSecret,
      redirect_uri: redirectUri,
      grant_type: "authorization_code",
    }),
  });

  const tokenJson = await tokenResp.json().catch(() => ({} as any));
  if (!tokenResp.ok) {
    return res.status(502).json({ error: "token_exchange_failed", detail: tokenJson });
  }

  const accessToken = tokenJson.access_token as string | undefined;
  const refreshToken = tokenJson.refresh_token as string | undefined;
  const expiresIn = tokenJson.expires_in as number | undefined;

  if (!accessToken) {
    return res.status(502).json({ error: "missing_access_token", detail: tokenJson });
  }

  // Fetch Gmail profile to get email address
  const profileResp = await fetch("https://gmail.googleapis.com/gmail/v1/users/me/profile", {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  const profileJson = await profileResp.json().catch(() => ({} as any));
  if (!profileResp.ok) {
    return res.status(502).json({ error: "gmail_profile_failed", detail: profileJson });
  }

  const emailAddress = (profileJson.emailAddress as string | undefined) || "";
  if (!emailAddress) {
    return res.status(502).json({ error: "missing_email_address", detail: profileJson });
  }

  // Upsert into Vozlia Control
  const CONTROL_BASE = mustEnv("VOZLIA_CONTROL_BASE_URL").replace(/\/+$/, "");
  const ADMIN_KEY = mustEnv("VOZLIA_ADMIN_KEY");

  const upsertResp = await fetch(`${CONTROL_BASE}/admin/email-accounts/gmail/upsert`, {
    method: "POST",
    headers: {
      "X-Vozlia-Admin-Key": ADMIN_KEY,
      "Content-Type": "application/json",
      Accept: "application/json",
    },
    body: JSON.stringify({
      email_address: emailAddress,
      display_name: emailAddress,
      oauth_access_token: accessToken,
      oauth_refresh_token: refreshToken ?? null,
      expires_in: expiresIn ?? null,
    }),
  });

  const upsertText = await upsertResp.text();
  if (!upsertResp.ok) {
    return res.status(502).json({ error: "control_upsert_failed", status: upsertResp.status, detail: upsertText });
  }

  // Clear state cookie
  res.setHeader("Set-Cookie", `gmail_oauth_state=; HttpOnly; Path=/; Max-Age=0; SameSite=Lax; Secure`);

  return res.redirect("/admin?gmail=connected");
}
