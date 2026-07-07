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
- **Repo:** git, remote `origin` on GitHub (`SansWord/sans_schema`, public — run the
  secret scan below before every push). Installable package (`pyproject.toml`,
  `pip install -e ".[dev]"`) — ships `core/` + `gateway/`; `spike/` is eval-only.
- **Stack:** Python 3.9 (spike) / 3.11 (container); `core/` (shared resolver +
  predicate) · `gateway/` (FastAPI `POST /query`, connectors, cache, pipeline) ·
  `spike/` (the frozen resolution-accuracy eval harness that re-measures `core`);
  multi-vendor LLM via **LiteLLM**.
- **Gateway (v0.2.0 built):** the first end-to-end slice — resolve `{want,where}` →
  validated AST → execute on Postgres → rows in client keys. Postgres + fake connectors,
  two-part cache, want+where gates, Docker + quickstart. See the devlog top row +
  [`docs/architecture.md`](docs/architecture.md) + [`gateway/README.md`](gateway/README.md).
- **Starting model:** `gemini/gemini-3.1-flash-lite`, behind the `LLM` interface.

## Docs — two tiers

- **Maintained (source of truth; must match code/decisions):**
  - [`docs/architecture.md`](docs/architecture.md) — the current design & rules
    (request contract, hourglass + IR contracts, resolution discipline,
    prompt-cache layout, model & gate). **Read before any design/build choice.
    Update in the same change when a contract/interface/decision below changes.**
  - [`docs/system-design.md`](docs/system-design.md) — the glanceable component map
    (Mermaid topology + swap-point matrix). Companion to `architecture.md`:
    this = the boxes and how they swap; `architecture.md` = the exact contracts.
- **Historical (allowed to go stale, kept forever — how we got here):**
  - [`docs/specs/`](docs/specs/) — per-milestone specs (the concept + spike write-up).
  - [`docs/plans/`](docs/plans/) — per-milestone implementation plans.
  - [`docs/notes/`](docs/notes/) — pre-spec design notes / open questions (not law).
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
- **Stack** — Gateway = **Python (FastAPI)**; lift the spike resolver into a shared
  `core/` (types + resolver). Demo runs over a real Postgres with **dynamic schema
  detection** (no hardcoded gateway schema). Deploy container-portable.

## Before you plan or build — consult the tree

Read the relevant `docs/*.md` (and the Locked decisions) **before** planning,
brainstorming, or continuing work — then plan against them, and **name the files
you consulted** so it's visible which docs informed the work.

## Workflow — the dev cycle

The loop each milestone runs through (adapt to tooling):

1. **Brainstorm → spec** before building; **plan** once the spec is agreed. Spec +
   plan land in the historical tier (`docs/specs/`, `docs/plans/`) — they may go
   stale later, and that's fine.
2. **Implement** against the plan.
3. **Fold lasting decisions into the maintained docs** ([`docs/architecture.md`](docs/architecture.md)
   + the Locked decisions above) — those, **not** the spec, are the source of
   truth afterward.
4. **Close the loop at end of session** (below): refresh maintained docs + devlog + todo.
5. The next round starts from these docs — so a new idea that diverges from a past
   decision gets surfaced (see Locked decisions).

## End of session — close the loop

Updating the docs is a **gate, not a nicety** — do it before the work counts as
done (before a PR opens), and commit the doc changes **in the same PR** as the code:

1. **Update every maintained `docs/*.md`** the session touched, so it matches the
   shipped state. ("No docs needed" is a claim to justify, not a default.)
2. **Append a newest-on-top entry to [`docs/devlog.md`](docs/devlog.md)**, linking
   this milestone's spec/plan.
3. **Update [`todo.md`](todo.md)** — clear done items, add next steps.

When the user says **"ship it"** / **"raise a PR,"** run this, commit, open the PR —
then **stop** (don't merge; that's the user's call). If the user heads to
push/merge without it, **remind them** to update the docs first.

## Conventions

- **Versioning:** three-part semver (`vX.Y.Z`); devlog heading + TL;DR row match.
- **Git staging: explicit paths only — never `git add -A` / `git add .`.**
  (A blanket add already swept run logs into this repo once.) Confirm scope with
  `git diff --name-only` before committing.
- **Comments/docs describe the *current* state** — no "used to be…" breadcrumbs; history lives in git + the devlog.
- **Run logs are gitignored** (`*.log`) — spike output stays local.

## Before committing

Scan every commit for **secrets / API keys / tokens**, `.env*` files, and private
personal info before pushing anywhere public (this repo will likely get a remote).
This scan is load-bearing, not precautionary.
