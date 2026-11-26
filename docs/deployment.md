# Deployment

openscope ships as one Docker image (API + dashboard). It listens on `$PORT` (default 8000),
so it runs on any container host.

## Public demo on Render (free)

The public demo runs at https://openscope-xi6p.onrender.com/overview.

The repository contains a [`render.yaml`](../render.yaml) Blueprint:

1. Sign in at [render.com](https://render.com) with GitHub, and let Render access this repository.
2. **New → Blueprint**, pick the repository, **Apply**.
3. Render builds the Dockerfile and serves the app at `https://<service-name>.onrender.com`.
   Every push to `main` redeploys.

The Blueprint sets `OPENSCOPE_PUBLIC_DEMO=1`. This loads the demo data at startup, shows a
banner telling visitors that data is public and temporary, and keeps Claude classification
off (it is enabled only with `OPENSCOPE_LLM=1`). Public-demo mode also protects the service:

* deleting inventories is disabled (HTTP 403);
* uploads are limited to 1 MB;
* each visitor may make 30 changes (uploads, reviews, exports) per 10 minutes (HTTP 429 with
  `Retry-After`). The limit is in memory, per instance;
* only the 25 newest visitor inventories and ledger runs are kept; older visitor uploads are
  removed first, and the demo data is never removed;
* names starting with `Demo:` are reserved for the demo data.

Every deployment sends security headers: a strict Content-Security-Policy (no inline
scripts; a relaxed policy only for the Swagger UI at `/docs`), `X-Frame-Options: DENY`,
`X-Content-Type-Options: nosniff`, `Referrer-Policy` and `Permissions-Policy`.

Free-plan behaviour to expect:

* The service sleeps after ~15 minutes without traffic. The next visit takes 30–60 seconds
  while it wakes up.
* There is no persistent disk. Visitor uploads and reviews disappear when the service sleeps
  or redeploys, and the demo data is loaded again.

## Self-hosting

```bash
docker build -t openscope .
docker run -p 8000:8000 -v openscope-data:/data openscope
```

Data persists in the `openscope-data` volume. For production, use PostgreSQL
(`OPENSCOPE_DB_URL=postgresql+psycopg://…`, plus a driver in the image) and put the service
behind authentication: v0.4 has no user accounts. All settings are listed in
[`src/openscope/api/settings.py`](../src/openscope/api/settings.py).
