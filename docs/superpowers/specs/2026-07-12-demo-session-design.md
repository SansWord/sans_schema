# Demo Session Design — 25-Minute Intro + Public Playground

**Date:** 2026-07-12
**Status:** approved design (brainstorm output)
**Docs consulted:** `CLAUDE.md`, `todo.md`, `docs/devlog.md` (v0.2.0–v0.2.4),
`gateway/config.py`, `gateway/app.py`

## Goal

A 25-minute demo session introducing sans_schema to a **mixed / general tech
audience**, centered on a **public playground** viewers can use during and after
the talk, plus clear instructions to run the gateway against **their own data
and API key**. Build window: **1–3 sessions**.

## Session structure (Approach A — demo-centered)

- **~8 min slides** — problem, the `{want, where}` idea, one internals slide,
  eval numbers.
- **~12 min scripted live demo** in the playground (script below).
- **~5 min "now you try it"** — playground QR/link shown from slide 1;
  close on the own-data quickstart.

## Deliverables (build order)

### 1. Gateway demo-hardening (small, first)

Guardrails for public exposure. Plug in, don't build:

- **CORS** — Starlette's built-in `CORSMiddleware`; allowlist the Vercel
  playground origin + localhost. Zero custom code.
- **Per-IP rate limit** — **slowapi**, in-memory storage (single replica, no
  Redis). Decorator on `POST /query`, e.g. `10/minute` per IP.
- **Global daily cap** — a second slowapi limit with a constant key function
  (e.g. `1000/day` keyed to `"global"`). Request-count only — no spend
  accounting (the vendor quota cap is the money backstop).
- **Friendly 429s** — custom handler returning
  `{"error": "rate_limited" | "demo_budget_exhausted", "message": ...}` so the
  frontend renders "demo budget exhausted — run it locally, here's how."
- **Config** — new env-driven `Settings` fields (e.g. `RATE_LIMIT_PER_IP`,
  `DAILY_REQUEST_CAP`, `CORS_ORIGINS`); **all off/empty by default** so local
  dev and existing tests are unchanged.
- **Proxy gotcha (load-bearing):** behind a PaaS proxy `request.client` is the
  proxy, not the visitor — slowapi's default key would throttle everyone as one
  IP. Use a key function reading the platform's client-IP header
  (`Fly-Client-IP` on Fly; `X-Forwarded-For` on Render/Railway). Unit-tested.
- **Vendor backstop (operator action, not code):** a **quota limit**
  (requests/day) on the Gemini API key/project — a hard stop that bounds
  worst-case dollar exposure. A billing *budget* only alerts; the *quota* cap
  is what stops spend. Documented in the deploy notes.

### 2. Playground frontend (the bulk)

Next.js on Vercel; gateway URL via env var; browser calls the gateway directly
(CORS) — no proxy layer. One page, three zones:

- **Request builder** — textarea for `where` (plain language), dynamic
  add/remove rows for `want` (fields in *the viewer's* words), **Run** button.
  **Example query chips** (4–6 pre-written `{want, where}` combos): one click
  fills and runs. Chips double as the live-demo script and as cache-warmed
  cheap queries.
- **Results table** — rows keyed by the client's own field names; the viewer's
  made-up words visibly become the column headers.
- **`interpreted` echo (the star)** — alongside the table: what each `want`
  field and the `where` filter resolved to (resolved column, confidence, the
  predicate AST rendered readably). Visually emphasized, not a collapsed
  debug pane.
- **Field discovery: none.** No known-fields hint and no schema exposure. A
  one-line framing instead: *"This is a database of books. Ask for fields in
  your own words — the backend's real column names are hidden."* Guessing
  fields **is** the product pitch; the example chips implicitly teach the shape.
- **Error states as features** — gate refusals (low confidence) rendered as a
  friendly "the gateway wasn't confident enough to guess" explanation; 422s and
  the two 429 messages rendered clearly.
- **"Try with your own data"** — a section/page with the 3-step quickstart as
  copy-paste blocks (`docker run` with `DATABASE_URL` + LLM key/`LLM_MODEL`,
  then a `curl`), linking to `gateway/README.md` for depth. QR-friendly URL.

### 3. Deployment

- **Gateway + tiny Postgres on a container PaaS** — Fly.io first pick;
  Railway/Render drop-in fallbacks. Seed once from `gateway/demo/seed.sql`.
- `ENABLE_DEBUG_ENDPOINTS` **off** in the public deploy (`/debug/schema` and
  `/debug/cache` disclose data). Operator introspection via local/private
  deploy or `fly ssh`, never the public URL.
- LLM key + `DATABASE_URL` as PaaS secrets. Model: `gemini/gemini-3.1-flash-lite`.
- **Frontend on Vercel**, pointed at the gateway URL.

### 4. HTML slide deck + demo script (last)

Self-contained HTML deck (arrow-key navigation), lives in the repo, hostable
next to the playground. Nine slides for ~8 minutes:

1. **Title** — "query a database you've never seen, in your own words" +
   playground QR/link (up from minute 0).
2. **The problem** — every client hardcodes someone else's schema; every rename
   breaks every consumer (`author_name` vs `writer` vs `author.full_name`).
3. **The idea** — `{want, where}`: your words + a plain-language filter →
   response in your keys. One real request/response JSON pair.
4. **How it stays safe** (the internals slide) — NL → **validated predicate
   AST** → execute; never NL → SQL. Operator whitelist + real-fields check as
   the injection boundary. One hourglass diagram.
5. **Does it work?** — WANT 100% / WHERE 98% across 9 models, 3 vendors;
   the confidence gate refuses instead of guessing.
6. **Live demo** — the playground URL, big. (The ~12 minutes happen here.)
7. **Try it with your own data** — 3-step quickstart + QR to the instructions
   page.
8. **What's deliberately not solved yet** — authz, messy schemas, agent-traffic
   cache economics. Stated limits build trust.
9. **Thanks / links** — repo, playground, contact.

**Demo script** (driven by the example chips, in order):

1. Want-only query — made-up field names come back as column headers.
2. Same data, *different* field names — the core trick made visible.
3. Add a plain-language `where` — walk the `interpreted` echo (column,
   confidence, AST).
4. A deliberately ambiguous request — the gate refuses; refusal-over-guessing
   framed as a safety feature.
5. Re-run an earlier query — instant; explain the resolution cache (repeat
   queries cost ~nothing).
6. Invite the room to the URL.

## Stretch goal (only if sessions 1–3 leave room)

**Richer demo dataset** (~50–100 real books, fixed snapshot from Open Library /
Gutendex; synthesize `price`). Its own scoped task — it moves
`gateway/demo/rows.py`, the seam-parity test, and row-specific unit tests.
With 6 books most filters match nearly everything; more rows make viewer
queries feel real. Core playground ships first regardless.

## Testing

- Guardrail middleware: unit tests — per-IP limit, global daily cap, CORS
  headers, proxy-header key function, friendly 429 bodies, and
  defaults-off (existing 65-test suite stays green untouched).
- Playground: manual pass against the deployed gateway — happy path, gate
  refusal, both 429s.
- Demo script: one full dry run on the real deployment before the session.

## Out of scope

- Bot/abuse detection (Turnstile etc.) — the hard caps bound worst-case spend.
- Endpoint auth / field-level authz (separate security milestone).
- Windowed cache metrics, spend accounting, multi-replica rate limiting.
- Any `bind_today` / derived-fields work.
