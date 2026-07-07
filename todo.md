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
- [ ] **Write the implementation plan** (→ `docs/plans/`) — **next, in a fresh session.**
      Reference [`docs/specs/2026-07-first-gateway-slice.md`](docs/specs/2026-07-first-gateway-slice.md).
      Then implement the slice against the plan.

## MVP shape & setup — decide in the first spec

Goal: a **light, easy on-ramp** — a user points the gateway at their DB, gives it
an LLM key, and starts receiving `{want, where}` requests. Decisions to settle:

- [ ] **How to serve / package** (undecided): a **Docker image** (point at a DB +
      set env → running gateway), a runnable process/CLI, a library/framework
      plugin, or serverless. Lean: Docker for the simplest on-ramp — revisit.
- [ ] **Which DB first:** Postgres (matches the connector seam plan); config via a
      standard DSN / env var.
- [ ] **How to talk to the LLM:** LiteLLM (already), key + model via env; default
      `gemini-3.1-flash-lite` (see [`docs/architecture.md`](docs/architecture.md) §5).
- [ ] **Config surface:** how the user declares backend + credentials (env vars vs
      a small config file), and later per-tenant domain hints / field allowlist.
- [ ] **Onboarding flow:** fewest steps from "install" to "first successful query"
      — target a copy-paste quickstart in the README. Deliverable: a
      `gateway/README.md` quickstart (build-time; highest-leverage doc for both
      adoption and a portfolio reviewer who runs it).
- [ ] **Public demo site / playground** — a hosted page where anyone pastes weird
      field names + an NL filter against a demo backend and watches it resolve
      (the enthusiast reviewer's top ask; great for adoption). **Cost is the catch
      (worry about later, but noted):** a public endpoint invites arbitrary LLM
      calls → uncapped spend. Guardrails to design when we build it — a **fixed
      demo dataset** (so schema/prompt caches hit hard), the **cheapest model**
      (flash-lite), **cache common queries**, per-IP/session **rate limits** + a
      **global daily spend cap**, and bot/abuse protection. Keep it a bounded
      sandbox, never an open gateway to a real DB.

**Ambition — the open question:** keep the MVP **dev / prototype grade**, *not* a
production system serving 100+ QPS at a high cache rate? **Lean: yes, keep it
light and defer production scale.** Production scale depends on the unresolved
de-risking items (cache-hit on real traffic, confident-wrong rate, authz) + the
resolution cache — so don't let "could be production" bloat the light MVP; revisit
only after the *Validation & de-risking* section clears.

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
- [ ] **Security:** field allowlist / field-level authz. *(When this gets designed,
      consolidate the scattered security notes — architecture §6, the injection
      boundary, the schema-probing surface — into a maintained `docs/security.md`.)*
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
      the economics.
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
