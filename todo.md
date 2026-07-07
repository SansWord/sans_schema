# TODO

The single home for "what's next" — the root `CLAUDE.md` points here instead of
restating it. Keep current as part of the end-of-session checklist.

## Now

- [ ] **Brainstorm + spec the first gateway implementation** — the thin
      end-to-end vertical slice (see [`docs/HANDOFF.md`](docs/HANDOFF.md)):
      one JSON `{want, where}` adapter → resolver lifted from the spike →
      minimal `RawQuery`/`CanonicalQueryIR` → a Postgres connector with a
      fake-connector seam test → response in the client's own keys.
      **Start by pinning the `RawQuery` and `CanonicalQueryIR` shapes.**
  - When that spec lands, close the loop and `git rm docs/HANDOFF.md` — it's a
    one-time bridge primer, superseded by `CLAUDE.md` + the tree + the new spec.

## Later

- [ ] Connector interface (`describe`/`capabilities`/`execute`) + the seam test.
- [ ] **Resolution cache** (the primary cost lever): key ≈ `tenant + schema-version
      + normalized(want-key | where-phrase)`; invalidate on schema drift.
- [ ] Enforce **structured output** (lock the AST shape; rescues small models).
- [ ] Raise the **confidence gate** to ~0.7 + add the low-confidence
      **clarify / escalate-to-stronger-model** path.
- [ ] **Value resolution** step (enum fuzzing) as its own stage.
- [ ] **Security:** field allowlist / field-level authz.
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
