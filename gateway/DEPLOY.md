# Public demo deployment — runbook

Gateway + tiny Postgres on Fly.io, playground on Vercel. Config lives in
`fly.toml` (guardrails on: 10/min per IP, 1000/day global, CORS allowlist,
`Fly-Client-IP` as the rate-limit key). Railway/Render are drop-in fallbacks —
but set `CLIENT_IP_HEADER` only to a header the platform itself sets/overwrites
(e.g. `CF-Connecting-IP` or `True-Client-IP` behind Cloudflare); a
client-appendable `X-Forwarded-For` lets visitors mint fresh rate-limit
buckets and defeats per-IP limiting.

## One-time setup

```bash
fly auth login
fly apps create sans-schema-demo

# Tiny Postgres + attach (attach sets the DATABASE_URL secret on the app)
fly postgres create --name sans-schema-demo-db --region nrt \
    --initial-cluster-size 1 --vm-size shared-cpu-1x --volume-size 1
fly postgres attach sans-schema-demo-db -a sans-schema-demo
# ^ prints a connection string — save it for seeding below.

# Seed once (proxy the DB locally; use the credentials attach printed)
fly proxy 15432:5432 -a sans-schema-demo-db
# in a second terminal (fly proxy blocks)
psql "<attach-connection-string, host swapped to localhost:15432>" \
    < gateway/demo/seed.sql

# LLM key
fly secrets set GEMINI_API_KEY=<key> -a sans-schema-demo

fly deploy
```

## Vendor backstop — the money stop (operator action, load-bearing)

Set a **quota limit** (requests/day) on the Gemini API key's Google Cloud
project: Console → APIs & Services → Generative Language API → Quotas →
requests per day → cap it (e.g. 2000/day). A billing *budget* only alerts;
the *quota* cap is what actually stops spend if every other guardrail fails.

## Verify after deploy

```bash
BASE=https://sans-schema-demo.fly.dev
# happy path → 200 with rows in the made-up keys
curl -s $BASE/query -H 'Content-Type: application/json' \
  -d '{"want": ["book name", "writer"], "isVerbose": true}'
# debug endpoints must be dark → 404
curl -s -o /dev/null -w "%{http_code}\n" $BASE/debug/schema
# per-IP limit → 429 {"error":"rate_limited"} after ~10 rapid requests
for i in $(seq 1 12); do curl -s -o /dev/null -w "%{http_code} " \
  -X POST $BASE/query -H 'Content-Type: application/json' \
  -d '{"want":["book name"]}'; done; echo
```

The 429 drill consumes the daily budget — do it before the session day, or bump
`DAILY_REQUEST_CAP` temporarily.

## Playground (Vercel)

Playground doc (local dev, config, layout): [`../playground/README.md`](../playground/README.md).

```bash
cd playground
vercel link --yes --project sans-schema-playground
# --value is required under tooling: recent CLIs run non-interactively and a
# piped/prompted value silently stores an EMPTY string (see playground/README.md §2)
vercel env add NEXT_PUBLIC_GATEWAY_URL production \
  --value "https://sans-schema-demo.fly.dev" --force
vercel --prod
```

Verify the build actually baked the URL in (an empty env var fails silently —
the browser then calls the playground's own origin):

```bash
curl -s https://sans-schema-playground.vercel.app | grep -oE '/_next/static/chunks/[A-Za-z0-9./_-]+\.js' \
  | while read -r c; do curl -s "https://sans-schema-playground.vercel.app$c"; done \
  | grep -c "sans-schema-demo.fly.dev"   # must be ≥ 1
```

If the production URL differs from `https://sans-schema-playground.vercel.app`,
update `CORS_ORIGINS` in `fly.toml` and `fly deploy` again.

## Operator introspection

Never enable `ENABLE_DEBUG_ENDPOINTS` on the public deploy (`/debug/schema` and
`/debug/cache` disclose data). Inspect via `fly ssh console -a sans-schema-demo`
or a local deploy instead.

## Teardown

```bash
fly apps destroy sans-schema-demo
fly apps destroy sans-schema-demo-db
```
