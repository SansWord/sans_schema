# sans_schema

**A semantic query gateway — query your data without knowing its schema.**

> `sans` (French: *without*) + `schema` → *without schema*. That's the promise:
> ask for data using your **own** field names and a plain-language filter, and the
> gateway figures out the rest.

## What it does

You send a request shaped the way *you* want it — the field names you'd naturally
use, and a filter in plain English:

```json
POST /query
{
  "want":  { "title": null, "writer": null, "releaseDate": null },
  "where": "published this year, sci-fi only"
}
```

You don't need to know the backend's schema, and there's no query language to
learn. The gateway:

1. **Resolves your field names** onto the real backend columns — *semantically*,
   so `writer` finds `author` and `releaseDate` finds `published_at`, even though
   you never saw those names.
2. **Compiles your plain-language filter** into a validated query — never raw SQL
   straight from text (a safety boundary).
3. **Runs it** and **returns the data in your own keys**, plus an `interpreted`
   echo so you can see exactly what it did:

```json
{
  "interpreted": {
    "want":  { "writer": "→ author", "releaseDate": "→ published_at" },
    "where": "published_at >= 2026-01-01 AND category = 'Science Fiction'",
    "confidence": 0.94
  },
  "data": [ { "title": "…", "writer": "SansWord", "releaseDate": "2026-03-01" } ]
}
```

The payoff: **clients never need the schema**, and **different clients can use
their own vocabulary** against the same backend — while queries stay safe,
structured, and (once cached) cheap.

### Same backend, different vocabularies

The backend (which no client ever sees) stores columns like `author.name`,
`book.title`, `book.category`, `book.published_at`, `book.price`. Two different
clients can hit it with **their own field names and their own filters** — and each
gets its answer back in the keys it asked with.

**Client A — a reading app.** Wants recent non-fiction:

```json
{ "want":  { "bookTitle": null, "authorName": null, "topic": null, "publishedOn": null },
  "where": "non-fiction added since 2024" }
```

*Resolves `bookTitle→book.title`, `authorName→author.name`, `topic→book.category`,
`publishedOn→book.published_at`; filter → `category = 'Non-Fiction' AND published_at >= 2024-01-01`. Response:*

```json
{ "data": [
  { "bookTitle": "Silent Fields", "authorName": "M. Ito", "topic": "Non-Fiction", "publishedOn": "2026-01-15" }
] }
```

**Client B — an AI agent.** Same backend, different words, a different filter
(other category, other time window, plus a price cap):

```json
{ "want":  { "name": null, "penName": null, "kind": null, "year": null, "price": null },
  "where": "fantasy from before 2020 under $15" }
```

*Resolves `name→book.title`, `penName→author.name`, `kind→book.category`,
`year→book.published_at`, `price→book.price`; filter → `category = 'Fantasy' AND published_at < 2020-01-01 AND price < 15`. Response:*

```json
{ "data": [
  { "name": "A Wizard of Earthsea", "penName": "Ursula K. Le Guin", "kind": "Fantasy", "year": "1968-01-01", "price": 9.99 }
] }
```

Same data, same backend, zero shared schema knowledge — the gateway meets each
client in its own vocabulary.

## Why

Auto-generating an API from a database, natural-language-to-SQL, semantic layers,
data federation — all of these exist. What doesn't: a plain REST gateway that does
**runtime, client-driven resolution over an *unknown* backend**, so the caller
brings its own field names and gets its own shape back. That's the gap sans_schema
fills — aimed first at **AI agents and rapidly-built frontends** that invent field
names on the fly.

## Status

**Early / pre-build.** The hard, load-bearing part — semantic resolution — has been
**validated by a spike**: across 3 vendors / 9 LLMs it resolved fields and compiled
filters at ~100% on a 52-case benchmark. The gateway itself is in design; usage
instructions will land here once the first implementation exists.

- **Current state** → [`docs/devlog.md`](docs/devlog.md) (top row)
- **What's next** → [`todo.md`](todo.md)
- **Design & rules** → [`docs/architecture.md`](docs/architecture.md)
- **Full concept + spike results** → [`docs/specs/2026-07-concept-and-spike.md`](docs/specs/2026-07-concept-and-spike.md)
- **The accuracy experiment** → [`spike/`](spike/)

## Repo layout

```
README.md   ← you are here (the pitch)
CLAUDE.md   ← agent context / doc-tree index
docs/       ← architecture (maintained) · devlog · specs/ · plans/
spike/      ← the resolution-accuracy experiment (Python)
todo.md     ← what's next
```
