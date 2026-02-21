# Vozlia Admin Portal (Vercel)

This is a small Next.js portal that **does not** talk to the backend DB directly.
Instead, it calls the `vozlia-control` service (Render) via server-side API routes.

## Local dev

```bash
cp .env.example .env.local
# edit .env.local
npm install
npm run dev
```

Open http://localhost:3000/admin

## Deploy (Vercel)

Set these Environment Variables in Vercel (Project → Settings → Environment Variables):

- `VOZLIA_CONTROL_BASE_URL`
- `VOZLIA_ADMIN_KEY`

Then redeploy.

## Endpoints

- `GET /api/admin/settings`
- `PATCH /api/admin/settings`
