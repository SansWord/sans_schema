# sans_schema — resolution-accuracy spike

Throwaway experiment to answer the one question the whole product rests on:

> When a client sends `{want, where}` using **its own vocabulary** against an
> **unknown backend schema**, how reliably can an LLM (a) map the requested
> fields to real columns, and (b) compile a natural-language filter into a
> validated predicate AST?

Everything else in the design (protocol adapters, connectors, caching) is
commodity we reuse. This layer is the only novel part — so we measure it
before building anything.

## What it measures

For each `(model, schema, case)`:

1. **`want` resolution accuracy** — top-1 field mapping (`writer → author`,
   `genre → category`, …), plus how often the confidence gate correctly flags
   a miss.
2. **NL-`where` → AST accuracy** — does the compiled predicate tree match the
   expected canonical AST (field paths, operators, normalized values like
   "this year" → `2026-01-01`)?

Read the result like this:

- **≥95% top-1 on both, gate catches the misses** → real product, go build.
- **~80–90%** → viable only for agent/prototype use with a clarify/retry loop.
- **<80% or bad AST silently passes** → a demo, not a product. Stop.

## Vendor-agnostic

The LLM is injected behind two tiny interfaces (`LLM.complete`, `Embed.embed`)
so you can benchmark the SAME test set across models/vendors. Default impl uses
[LiteLLM](https://docs.litellm.ai/) (100+ providers, one interface).

## Run

```bash
pip install -r requirements.txt

# set whichever provider key(s) you want to benchmark
export ANTHROPIC_API_KEY=...        # for anthropic/claude-* models
export OPENAI_API_KEY=...           # for openai/gpt-* models
export GEMINI_API_KEY=...           # for gemini/* models (Google AI Studio)

# benchmark the default model set (Anthropic tiers)
python -m spike.score

# a specific model
python -m spike.score --models anthropic/claude-haiku-4-5

# a whole provider's tier set (provider keyword expands to its chat tiers)
python -m spike.score --models gemini          # all Gemini tiers
python -m spike.score --models anthropic        # all Anthropic tiers
python -m spike.score --models all              # every provider

# mix keywords and explicit ids freely (de-duped)
python -m spike.score --models \
  anthropic \
  openai/gpt-4o \
  gemini/gemini-pro-latest
```

Provider keywords (`anthropic` | `gemini` | `openai` | `all`) expand to the
curated chat/reasoning tiers in `PROVIDER_SETS` (in `score.py`) — edit that dict
to change which models a keyword runs. "All models" literally would include a
provider's image/embedding/video models, which aren't chat models; the keyword
runs the resolver-relevant tiers instead.

Model strings are LiteLLM identifiers — any provider LiteLLM supports works:
- **Anthropic**: `anthropic/claude-opus-4-8`, `-sonnet-4-6`, `-haiku-4-5`
- **OpenAI**: `openai/gpt-4o`, `openai/gpt-4o-mini`
- **Google Gemini** (`GEMINI_API_KEY`, Google AI Studio) — current as of Jul 2026:
  - `gemini/gemini-pro-latest` / `gemini/gemini-flash-latest` — auto-track the newest Pro / Flash
  - stable ids: `gemini/gemini-3.5-flash`, `gemini/gemini-3.1-flash-lite`,
    `gemini/gemini-2.5-pro`, `gemini/gemini-2.5-flash`
  - Gemini 2.0 and 1.x are **shut down** (404). For Vertex use `vertex_ai/gemini-...`.

To mirror the three Claude tiers (cheap → strong):
`gemini/gemini-3.1-flash-lite`, `gemini/gemini-3.5-flash`, `gemini/gemini-pro-latest`.

Use whatever model ids your keys have access to. Edit `DEFAULT_MODELS` in
`score.py` or pass `--models`. The `LiteLLM` wrapper requests JSON output and
falls back gracefully for providers that reject `response_format`, so Gemini /
OpenAI / Anthropic all work through the same code path.

## Files

| File | Role |
|---|---|
| `llm.py` | `LLM` / `Embed` interfaces + LiteLLM-backed impl (swap by config) |
| `prompts.py` | The LLM-facing prompts, layered (contract / schema / domain hints / request) |
| `schemas.py` | Sample backend schemas (books, ecommerce) — the "unknown" backends |
| `cases.py` | Test cases: client `{want, where}` + expected resolution/AST |
| `resolver.py` | The layer under test: want-resolution + NL-where → AST |
| `score.py` | Harness: runs `{models} × {cases}`, scores, prints a report |

## Seeing (and tuning) the prompts

Prompts are not buried in logic — they live in `prompts.py`, split into layers so
the safe, high-value knob (domain hints: synonyms, glossary, rules, few-shot
examples) is separate from the contract (operator whitelist, AST shape) that must
stay in sync with `validate_ast()`.

Inspect exactly what gets sent, no API key or spend required:

```bash
python -m spike.score --show-prompts
```

To A/B a prompt change: edit `prompts.py`, commit, re-run `python -m spike.score`,
and diff the scores against the previous commit. Because prompts are their own
file, a prompt tweak shows up as its own git diff — attributable separately from
case-set changes.

Per-tenant customization (product direction) slots into `DomainHints` without
touching the contract; injection safety always lives in `validate_ast()`, never
in the prompt.
