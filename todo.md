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
- [ ] Re-validate resolution on a **larger/messier case set** before quoting an SLA.
- [ ] Freedom-to-operate check on patent **US 12045656** if commercializing.
