# sans_schema playground

The public demo UI over the gateway's `POST /query`: build a `{want, where}`
request in your own words, see rows come back in *your* keys, and inspect the
`interpreted` echo (resolved field + confidence + predicate AST) — the star of
the demo. Error states render as features: the confidence-gate refusal and both
429 guardrails get friendly panels instead of raw errors.

Live: <https://sans-schema-playground.vercel.app> · slide deck hosted at
[`/slides.html`](https://sans-schema-playground.vercel.app/slides.html).

## 1. Run it locally

Needs Node 18+ (built on Node 24) and a gateway to talk to.

```bash
# terminal 1 — a local gateway that allows the playground's origin
CORS_ORIGINS=http://localhost:3000 \
DATABASE_URL=postgresql://postgres:pg@localhost:5432/postgres \
GEMINI_API_KEY=<your key> \
uvicorn gateway.app:app --port 8000
# (full gateway quickstart incl. seeded Postgres: ../gateway/README.md §1)

# terminal 2
cd playground
npm install
npm run dev            # http://localhost:3000
```

With no config, the browser calls `http://localhost:8000` — the local-dev
default. `npm run build` type-checks and produces the production build.

## 2. Configuration

| Env var | Default | Meaning |
|---|---|---|
| `NEXT_PUBLIC_GATEWAY_URL` | `http://localhost:8000` | Base URL of the gateway the **browser** calls |

Two properties of `NEXT_PUBLIC_*` worth knowing (both bit us):

- **Build-time, not runtime.** The value is inlined into the JS bundle when
  `next build` runs. Changing it on Vercel does nothing until the next
  deployment builds.
- **Empty string ≠ unset.** `"" ?? default` keeps the empty string, so an
  accidentally-empty value makes the browser call `/query` on the playground's
  own origin. Verify a deploy by grepping the built bundle for the gateway URL
  (page chunks live under `_next/static/chunks/app/`).

The gateway must list the playground's origin in its `CORS_ORIGINS` — the
browser talks to it directly; there is no proxy in between.

## 3. Layout

```
app/page.tsx            the playground (client component: state + fetch loop)
app/own-data/page.tsx   three-step "run it on your own data" quickstart
app/layout.tsx          shell + globals.css (hand-rolled CSS, no Tailwind)
components/
  RequestBuilder.tsx    want rows + where textarea + example chips
  ResultsTable.tsx      rows in the client's own keys
  InterpretedPanel.tsx  the interpreted echo (field, confidence, AST)
  StatusPanel.tsx       friendly error states (422 refusal, both 429s, timeout)
lib/api.ts              typed gateway client (30 s timeout, non-JSON-safe errors)
lib/examples.ts         the example chips — ORDER IS THE DEMO SCRIPT
public/slides.html      self-contained 9-slide deck (+ qr.png)
```

- **Chip order is load-bearing:** `docs/demo/script.md` walks the chips top to
  bottom; reorder them and the script desyncs.
- Every request sends `isVerbose: true` so the `interpreted` echo is always
  present.
- Error codes the UI gives friendly copy: `where_low_confidence`,
  `all_want_declined`, `rate_limited`, `demo_budget_exhausted` (plus the
  client-side `timeout` / `network` states). Codes come from the gateway —
  see `gateway/guardrails.py` and `gateway/pipeline.py`.

## 4. Deploy (Vercel)

The runbook lives in [`../gateway/DEPLOY.md`](../gateway/DEPLOY.md) ("Playground
(Vercel)" section): link the project, set `NEXT_PUBLIC_GATEWAY_URL` for
production, `vercel --prod`. One CLI gotcha: recent Vercel CLIs run
non-interactively when driven by tooling — pass the env value with
`--value "<url>"` (piping to stdin silently stores an empty value).

Deploying also publishes the deck: anything in `public/` is served at the site
root, so the repo's single copy of `slides.html` is automatically hosted.
