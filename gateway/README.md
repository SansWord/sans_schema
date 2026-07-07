# sans_schema Gateway — Quickstart

A **Semantic Query Gateway**. A client sends `{want, where}` using its *own* field
names plus a plain-language filter, against a Postgres backend whose schema it
doesn't know. The gateway resolves the fields, compiles the NL filter to a
**validated predicate AST**, executes, and returns rows in the client's own keys.

This is the first end-to-end slice (v0.2.0). See [`../docs/architecture.md`](../docs/architecture.md)
for the full design.

## 1. Start Postgres and load the demo data

Put Postgres on a shared Docker network so the gateway container can reach it by
name (this avoids host-routing headaches — see the note in step 2):

```bash
docker network create sans
docker run -d --name sans-pg --network sans -e POSTGRES_PASSWORD=pg -p 5432:5432 postgres:16

# Seed the demo dataset (normalized authors/books + the flat books_view).
docker exec -i sans-pg psql -U postgres -d postgres < gateway/demo/seed.sql
```

The `DROP … IF EXISTS` at the top of the seed prints `NOTICE: … does not exist`
on a fresh DB — that's expected (the seed is re-runnable), not an error. Verify it
loaded: `docker exec -i sans-pg psql -U postgres -d postgres -c "SELECT count(*) FROM books_view;"`
should return `6`.

`gateway/demo/seed.sql` is the source of truth for the demo data; the gateway
introspects `books_view` at startup — no schema is hardcoded.

## 2. Configure the environment

Copy the template and fill in your key:

```bash
cp .env.example .env
# then edit .env — set the API key matching your LLM_MODEL
```

| Env var          | Default                          | Purpose                                   |
|------------------|----------------------------------|-------------------------------------------|
| `DATABASE_URL`   | *(required)*                     | Postgres DSN the connector introspects    |
| `LLM_MODEL`      | `gemini/gemini-3.1-flash-lite`   | LiteLLM model id for resolution           |
| `GATE_THRESHOLD` | `0.7`                            | Confidence gate (want-decline / where-422)|
| `RESULT_LIMIT`   | `100`                            | Max rows returned per query               |
| `MAX_WANT_FIELDS`| `50`                             | Max fields one request may ask for        |
| `MAX_FIELD_LEN`  | `200`                            | Max length of a single `want` field name  |
| `MAX_WHERE_LEN`  | `2000`                           | Max length of the NL `where` string       |
| `ENABLE_DEBUG_ENDPOINTS` | `0`                      | Expose `/debug/*` introspection (dev only — see below) |

Plus the API key env var your model's provider expects (e.g. `GEMINI_API_KEY`,
`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`). **`.env` is gitignored — never commit keys.**

> **`DATABASE_URL` host gotcha.** Inside a container, `localhost` is the *container
> itself*, not your machine. With the shared-network setup above, use the Postgres
> **container name** as the host — `.env.example` defaults to
> `postgresql://postgres:pg@sans-pg:5432/postgres`. (Running `uvicorn` locally instead
> of in a container? Then use `localhost:5432`.)

## 3. Run the gateway

**Container (recommended)** — on the same `sans` network as Postgres:

```bash
docker build -t sans-schema:dev .
docker run -p 8000:8000 --env-file .env --network sans sans-schema:dev
```

**Local (dev)** — set `DATABASE_URL=…@localhost:5432/…` and run:

```bash
pip install -e ".[dev]"
uvicorn gateway.app:app --reload
```

## 4. Query it

```bash
curl -X POST localhost:8000/query \
  -H 'content-type: application/json' \
  -d '{"want": {"title": null, "writer": null},
       "where": "science fiction only",
       "isVerbose": true}'
```

`want` is your field names (an object `{key: null}` or a list `["key", …]`);
`where` is a plain-language filter; `isVerbose` adds the `interpreted` echo.

Expected response shape:

```json
{
  "rows": [
    {"title": "The Long Orbit", "writer": "R. Novak"},
    {"title": "Future Shock 2026", "writer": "SansWord"}
  ],
  "interpreted": {
    "want": {
      "title":  {"field": "title", "confidence": 0.95},
      "writer": {"field": "author_name", "confidence": 0.93}
    },
    "where": {
      "raw": "science fiction only",
      "ast": {"op": "eq", "field": "category", "value": "Science Fiction"},
      "confidence": 0.9
    }
  }
}
```

Rows come back in **your** keys. A field the gateway can't confidently resolve
comes back as a `null` column (not an error); a low-confidence or off-contract
filter returns `422` with the `interpreted` echo so you can see what it understood.

## 5. Debug endpoints (dev only)

To see what the gateway actually sends the model and what it has cached, set
`ENABLE_DEBUG_ENDPOINTS=1` and hit:

| Endpoint | Shows | Discloses |
|---|---|---|
| `GET /debug/prompts` | the static resolver **system** prompts + operator whitelist + prompt-cache layout | nothing (no backend data) |
| `GET /debug/schema` | the introspected **schema prompt** (what the resolver sees) + fields | column names, descriptions, **sample values** |
| `GET /debug/cache` | the resolution cache — cached `want`-field and `where`-phrase resolutions | resolved paths/ASTs + what has been queried |

```bash
curl localhost:8000/debug/prompts     # safe — instructions only
curl localhost:8000/debug/schema      # discloses schema + samples
curl localhost:8000/debug/cache
```

> **Off by default; keep them off in production.** When disabled they return `404`
> (not advertised). `/debug/schema` and `/debug/cache` disclose your schema, sample
> data, and query history — they're a local/dev inspection aid, not a public surface.
> There's no auth yet, so don't expose a debug-enabled gateway to untrusted callers.
