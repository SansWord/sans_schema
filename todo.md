# TODO

The single home for "what's next" — the root `CLAUDE.md` points here instead of
restating it. Keep current as part of the end-of-session checklist.

## Now

- [x] **Brainstorm + spec the first gateway slice** — landed
      [`docs/specs/2026-07-first-gateway-slice.md`](docs/specs/2026-07-first-gateway-slice.md).
      Language locked **Python/FastAPI**; `RawQuery`/`CanonicalQueryIR` contracts;
      denormalized-view connector (no joins in v1) + fake-connector seam; two-part
      resolution cache; gates on both `want` and `where`. `docs/HANDOFF.md` removed
      (superseded by `CLAUDE.md` + the tree + the spec). Added maintained
      [`docs/system-design.md`](docs/system-design.md) (topology + swap matrix).
- [x] **Review + fold.** Spec approved 2026-07-06; settled decisions folded into the
      maintained law — `docs/architecture.md` §2 (where-confidence) + §7 (Python/FastAPI)
      and `CLAUDE.md` (status + Locked decisions). Demo refined to a **real Postgres +
      dynamic schema detection** (`BOOKS`/etc. stay `spike/`-only eval fixtures).
- [x] **Write the implementation plan + build the slice** — plan landed
      [`docs/plans/2026-07-first-gateway-slice.md`](docs/plans/2026-07-first-gateway-slice.md);
      **built as v0.2.0** (see the devlog top row). `core/` + `gateway/`, Postgres + fake
      connectors, seam parity verified against real Postgres 16, Docker + quickstart shipped.
- [x] **Re-ran the spike eval** (`spike.score --models gemini/gemini-3.1-flash-lite`, 2026-07-07)
      to confirm the where-confidence prompt change didn't regress: **WANT 100%, WHERE 98%** —
      identical to the v0.1.0 baseline. Numbers recorded in the devlog v0.2.0 entry.
- [x] **Demo session (v0.3.0)** — guardrails + playground + deploy config + deck/script
      built and reviewed (see the devlog top row). Remaining **operator steps** before the
      session:
  - [x] **Deploy the gateway on Fly.io** — live at `https://sans-schema-demo.fly.dev`
        (`nrt`, single machine — `fly deploy` adds an HA second machine by default,
        scaled back to 1; seeded Postgres attached; verify block passed 2026-07-13).
  - [x] **Gemini quota cap** — set 2026-07-13: Generative Language API →
        "Request limit per model per day for a project" (the Tier-1 daily row)
        capped at 2000 (≈ $1.40/day worst case at flash-lite prices).
  - [x] **Deploy the playground on Vercel** — live at
        `https://sans-schema-playground.vercel.app` (gateway URL verified baked into
        the bundle; CORS verified allow+deny).
  - [x] **Dry run** — production pass 2026-07-13; re-run the checklist at the bottom of
        [`docs/demo/script.md`](docs/demo/script.md) the day before the session (and
        re-click the chips ~10 min before stage — in-process cache empties on restart).

**Demo improvements (wanted for this demo, post-v0.3.0):**

- [x] **Extend the demo data — more books, real data.** Built as **v0.4.0** (see the
      devlog top row): 380 real books / 71 curated authors from Open Library + Wikidata,
      `books.json` as source of truth, `gender` column added, chip-coverage tests.
      Remaining **operator step**:
  - [x] **Re-seed the deployed Fly Postgres** — done 2026-07-13 (381 rows verified,
        app restarted for the memoized schema, live-verified: gender query + sci-fi
        + Mandarin chips all return rows; Taiwan Travelogue in production).
        Re-click the chips ~10 min before the demo session as usual (in-process
        cache empties on restart).
- [x] **Playground request-transparency panel ("what did the gateway actually do?").**
      Built as **v0.5.0** (see the devlog top row): `isDebug` + `ENABLE_QUERY_DEBUG`
      debug block (SQL, cache hit/miss, gate threshold) rendered in the playground panel.
  - [x] **Deploy** — done 2026-07-14: `fly deploy --ha=false` (1 machine,
        `ENABLE_QUERY_DEBUG` live) + Vercel production redeploy (bundle verified
        sending `isDebug`); tagged `v0.5.0`. Live-verified: same query twice →
        parameterized SQL + all-miss then all-hit, `/debug/*` still 404.
        Demo-day note: re-click chips ~10 min before stage (in-process cache
        empties on restart), and the `today` stamp keys the where cache, so
        chips warmed before UTC midnight miss again after it (08:00 Taiwan time).

**Next milestone after the demo session: undecided.** Strong candidates — the two demo
improvements above, `bind_today` (below), and the security milestone (field-level authz +
endpoint auth + data-borne prompt injection). Pick one to start the next session.

- [ ] **Symbolic / relative dates (`bind_today`)** — a leading fast-follow candidate (detail
      under *Later*). Compile `where` to a date-independent AST → date-independent where cache
      + removes LLM date-math errors. Re-run the spike eval to confirm no regression.

## MVP shape & setup — settled in the v0.2.0 slice

Goal: a **light, easy on-ramp** — a user points the gateway at their DB, gives it
an LLM key, and starts receiving `{want, where}` requests. Settled decisions:

- [x] **How to serve / package:** a **Docker image** (`Dockerfile` ships `core/`+`gateway/`;
      `docker run -p 8000:8000 --env-file .env`). `uvicorn gateway.app:app` for local dev.
- [x] **Which DB first:** Postgres, via a standard DSN in `DATABASE_URL`
      (`gateway/connectors/postgres.py` introspects a denormalized view).
- [x] **How to talk to the LLM:** LiteLLM, key + model via env; default
      `gemini-3.1-flash-lite` (`LLM_MODEL`).
- [x] **Config surface:** env-driven `Settings` (`gateway/config.py`) — `DATABASE_URL`,
      `LLM_MODEL`, `GATE_THRESHOLD`, `RESULT_LIMIT`. Per-tenant domain hints / field allowlist
      still deferred.
- [x] **Onboarding flow:** copy-paste quickstart shipped at
      [`gateway/README.md`](gateway/README.md) (Postgres + seed → env → `docker run` → `curl`).
- [x] **Demo site / playground — built as v0.3.0** (`playground/`, Next.js; see the devlog
      top row). Request builder + example chips, results in the client's own keys, the
      `interpreted` echo rendered alongside, error states as features, own-data quickstart
      page. Original shape (kept for reference): a page to
      *interactively* test the gateway: a **textarea for `where`** (plain-language filter)
      and a **per-field input row for `want`** (add/remove client field names), a **Run**
      button, and the response rendered as a **table** (rows in the client's own keys). Show
      the **`interpreted` echo** alongside (what each field/filter resolved to + confidence)
      so the resolution is visible, and let the user **edit `where`/`want` and re-run** to see
      how results change. `/debug/schema` can populate a "known fields" hint for the demo
      backend. Doubles as (a) a dev/testing tool and (b) the public adoption playground (the
      enthusiast reviewer's top ask). Stack likely Vercel (Next.js) → the container API.
  - **Public-exposure guardrails — shipped in v0.3.0** (`gateway/guardrails.py`: per-IP
    rate limit, global daily request cap, CORS allowlist, all env-toggled; vendor quota cap
    documented in `gateway/DEPLOY.md` as the money backstop). Still deferred: bot/abuse
    detection, spend (vs request-count) accounting. Keep it a bounded sandbox, never an
    open gateway to a real DB.
- [x] **Richer demo dataset from open data** — built as **v0.4.0**: 380 real books /
      71 curated authors (Open Library + Wikidata, both CC0), frozen
      `gateway/demo/books.json` snapshot as source of truth (generated `seed.sql`,
      JSON-loading `rows.py`), deterministic synthesized prices, nullable `gender`
      column, chip-coverage + seed-determinism tests. See the devlog v0.4.0 entry;
      re-seeding the deployed Fly Postgres is the remaining operator step (tracked
      under *Demo improvements* above).

**Ambition — the open question:** keep the MVP **dev / prototype grade**, *not* a
production system serving 100+ QPS at a high cache rate? **Lean: yes, keep it
light and defer production scale.** Production scale depends on the unresolved
de-risking items (cache-hit on real traffic, confident-wrong rate, authz) + the
resolution cache — so don't let "could be production" bloat the light MVP; revisit
only after the *Validation & de-risking* section clears.

## Open design questions (from live use)

Captured while running the v0.2.0 quickstart — shape + leaning written up in
[`docs/notes/query-api-open-questions.md`](docs/notes/query-api-open-questions.md).
Each needs its own brainstorm → spec before building; both sharpen the de-risking items below.

- [ ] **Derived / computed fields ("tiny calculations")** — `author_age` from `birth_year`,
      currency conversions, a `currency` constant. The gap: `want`/`where` assume one existing
      column per field; computation needs a *validated expression* grammar (kept inside the
      injection boundary + mirrored in the equivalence oracle). Leaning: **declared virtual
      fields** for business-critical/external values (never let the LLM guess an FX rate);
      model-authored expressions only later, for pure date/arithmetic, behind the gate.
      Interacts with `bind_today`.
- [ ] **Field exposure & discovery** — is it safe to expose available fields, and how should a
      client discover them? Leaning: a **curated, authz-filtered capability listing** (NL
      descriptions, no raw paths/samples) over a raw `/schema` dump or `want: "*"` wildcard.
      Prerequisites: field-level authz + sample-stripping (and note the `interpreted` echo is
      already a per-request schema-probing oracle). Sharpens the security / no-schema-probing items.

## Later

- [ ] **Symbolic / relative dates (`bind_today`)** — *first fast-follow after the MVP
      slice.* Compile `where` to a **date-independent** AST that references `today`
      symbolically (e.g. `{rel: "year_start"}`); bind concrete dates deterministically
      at execute time. Two wins: a date-independent where cache (drops `today` from the
      cache key) **and** removing LLM date-math errors. Modifies the risky resolver
      layer → its own measured milestone (re-run the spike eval to confirm no regression).
- [ ] Connector interface (`describe`/`capabilities`/`execute`) + the seam test.
- [ ] **Resolution cache** (the primary cost lever): key ≈ `tenant + schema-version
      + normalized(want-key | where-phrase)`; invalidate on schema drift.
- [ ] Enforce **structured output** (lock the AST shape; rescues small models).
- [ ] Raise the **confidence gate** to ~0.7 + add the low-confidence
      **clarify / escalate-to-stronger-model** path.
- [ ] **Value resolution** step (enum fuzzing) as its own stage.
- [ ] **Security:** field allowlist / field-level authz + **endpoint authentication**
      (`POST /query` is currently unauthenticated) + **data-borne prompt injection**
      (schema comments/samples reach the prompt unsanitized — delimit/label as data).
      *(v0.2.1 security review confirmed no SQLi / no prompt-injection→SQL and hardened the
      robustness gaps — `want`-path validation, 502 containment, ingress size limits. These
      three items are what's left; when designed, consolidate the scattered security notes —
      architecture §6, the injection boundary, the schema-probing surface — into `docs/security.md`.)*
- [ ] Decide the **gateway language** (TS vs Python + Ibis) at build time.
- [ ] Freedom-to-operate check on patent **US 12045656** if commercializing.

## Validation & de-risking (from the 2026-07 persona review)

Three reviewers (AI-app dev, senior engineer, AI-tech enthusiast) agreed: the
spike validated the **clean, small, easy** version of the one thing that matters.
Close these before believing the "go build" signal or quoting an accuracy number.

- [ ] **Fix the spike oracle.** Execution equivalence runs on only ~8 rows/schema
      → two *different* predicates can coincidentally select the same rows (WHERE %
      is inflated). Use large, realistic row sets + boundary/adversarial cases +
      property-based equivalence; freeze the scorer before a run (no post-hoc tuning).
- [ ] **Report a confident-wrong rate**, not just top-1 — the real risk is a
      *confident* mis-resolution (`writer→editor`) returning plausible wrong data
      silently. The gate only catches *low* confidence.
- [ ] **Messy-schema benchmark:** cryptic/legacy/abbreviated names, near-duplicate
      synonyms (`created_at`/`inserted_at`/`dt`), wide tables (100+ cols), ambiguous
      candidates. Report accuracy + confident-wrong there, not on the clean set.
- [ ] **Benchmark value/enum resolution** once built (see Later) — the messy
      value-matching part is currently unmeasured.
- [ ] **Measure cache-hit rate on realistic agent traffic.** The cost model (→ ~0
      per request) assumes a high hit rate, but agents — the wedge — invent novel
      keys/phrasings and have the *lowest* hit rate. Resolve the tension or re-frame
      the economics. *(Instrumentation shipped v0.2.4: field/where/combined hit-miss
      counters + hit_rate, observable at `/debug/cache`. Open work is running realistic
      agent traffic through it — the counters are cumulative-since-start, no windowing yet.)*
- [ ] **Default confirm-before-execute ON for agents** until the confident-wrong
      rate is measured and bounded.
- [ ] **Drift / canary harness:** pin model versions; re-score on model / schema /
      description changes; prove cache invalidation on schema drift. (The `LLM`
      interface prevents API lock-in, not behavioral drift.)
- [ ] **Baseline comparison:** measure value vs a *deterministic* generated-SDK +
      synonym map (cacheable-forever, auditable, authz-clean) — not just vs Hasura.
      The convenience must beat the cheap deterministic option.
- [ ] **Authz without client schema knowledge:** resolve the core tension (dynamic
      resolution vs a per-client column allowlist); a cold request must not let a
      client probe the schema. (Sharpens the Security item above.)
