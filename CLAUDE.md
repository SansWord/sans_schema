# sans_schema — Project Context

A **Semantic Query Gateway**: a client sends `{want, where}` using its *own*
field names + a plain-language filter, against a backend whose schema it doesn't
know. The gateway semantically resolves fields, compiles the NL filter to a
**validated predicate AST**, executes, and returns the response in the client's
own keys. This file is auto-loaded every session — keep it a small **index**
(stable facts + links out), not an encyclopedia.

## Who's working on this

Sansword (solo). Preferences: **clear options with a recommendation** over
open-ended questions; **honest pushback** and root-cause rigor over agreement;
cares about **doc/versioning hygiene**, not just shipping; wants decisions that
are the human's (scope, product framing, model/vendor choice) **surfaced, not
assumed**. _(Edit freely.)_

## Current status

> Not restated here, to avoid drift: **what's shipped** → top row of
> [`docs/devlog.md`](docs/devlog.md); **what's next** → [`todo.md`](todo.md).

Stable facts:
- **Repo:** local git (no remote yet). Not a package — a spike + docs.
- **Spike stack:** Python 3.9; `spike/` (the resolution-accuracy experiment);
  multi-vendor LLM via **LiteLLM** (`spike/requirements.txt`).
- **Gateway (not built yet):** language TBD — leaning TypeScript (GraphQL-Mesh /
  JSON-native) or Python + Ibis. See [`docs/architecture.md`](docs/architecture.md) §Stack.
- **Starting model:** `gemini/gemini-3.1-flash-lite`, behind the `LLM` interface.

## Docs — two tiers

- **Maintained (source of truth; must match code/decisions):**
  - [`docs/architecture.md`](docs/architecture.md) — the current design & rules
    (request contract, hourglass + IR contracts, resolution discipline,
    prompt-cache layout, model & gate). **Read before any design/build choice.
    Update in the same change when a contract/interface/decision below changes.**
- **Historical (allowed to go stale, kept forever — how we got here):**
  - [`docs/specs/`](docs/specs/) — per-milestone specs (the concept + spike write-up).
  - [`docs/devlog.md`](docs/devlog.md) — milestone log, newest-on-top.
  - [`docs/HANDOFF.md`](docs/HANDOFF.md) — one-time primer for the first-build session
    (superseded by this file + devlog + todo once the gateway is underway).

## Locked decisions

> Settled calls — guarding against *silent* drift, not against changing your mind
> on purpose. **Obey when writing a plan / implementing; challenge freely when
> brainstorming or spec'ing.** To change one: update `docs/architecture.md` + this
> line and log the change + reason in `docs/devlog.md`. Detail for each →
> [`docs/architecture.md`](docs/architecture.md).

- **Request contract** — `{want}` = fields in your words (structured, no DSL);
  `{where}` = natural language. Response in the client's own keys + `interpreted` echo.
- **Resolution discipline** — NL → **validated AST** → execute. Never NL → SQL.
  `validate_ast` (operator whitelist + real fields) is the injection boundary.
- **Architecture** — two-sided hourglass: `RequestAdapter → RawQuery → resolver →
  CanonicalQueryIR → Connector`. The novel value is the resolver; the rest is reuse.
- **Scoring semantics** — execution equivalence (do two predicates select the same rows?).
- **Model** — start on `gemini-3.1-flash-lite`, behind the `LLM` interface,
  default-with-escalation to a stronger model on low confidence.
- **Prompt-cache layout** — `system[instructions] + system[schema+cache_control] +
  user[request]` so the per-backend schema caches at ~0.1×.

## Before you plan or build — consult the tree

Read the relevant `docs/*.md` (and the Locked decisions) **before** planning,
brainstorming, or continuing work — then plan against them, and **name the files
you consulted** so it's visible which docs informed the work.

## End of session — close the loop

Before work counts as done: update every maintained `docs/*.md` it touched, add a
newest-on-top entry to [`docs/devlog.md`](docs/devlog.md) (linking that
milestone's spec/plan), and update [`todo.md`](todo.md).

## Conventions

- **Versioning:** three-part semver (`vX.Y.Z`); devlog heading + TL;DR row match.
- **Git staging: explicit paths only — never `git add -A` / `git add .`.**
  (A blanket add already swept run logs into this repo once.) Confirm scope with
  `git diff --name-only` before committing.
- **Comments/docs describe the *current* state** — no "used to be…" breadcrumbs; history lives in git + the devlog.
- **Run logs are gitignored** (`*.log`) — spike output stays local.
- **Scan commits for secrets** (API keys, `.env*`) before pushing anywhere public.
