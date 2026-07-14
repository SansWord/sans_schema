# Demo script — 25-minute session

~8 min slides (`playground/public/slides.html`, hosted at
`https://sans-schema-playground.vercel.app/slides.html`) → ~12 min live demo →
~5 min "now you try it". The playground URL/QR is on screen from slide 1.

The live demo is driven by the playground's example chips, top to bottom
(`playground/lib/examples.ts` — chip order IS the script order).

## Live demo (~12 min)

### 1. Want-only — chip "Just the basics" (~2 min)
Click it. The interpreted panel ("what the gateway understood — and did") comes
first; the rows are at the bottom. Point at the row headers: `book name`,
`writer` — words we made up seconds ago, now column headers. Say: "I never read
this database's schema. The gateway resolved my words to its columns — the
panel on top shows each mapping with its confidence."

### 2. The core trick — chip "Same data, different words" (~2 min)
Click it. Same rows, but the columns are now `headline` / `penned by`. Say:
"Two clients with different vocabularies, zero shared schema, same backend.
That's the pitch in one click."

### 3. Plain-language filter — chip "Sci-fi under $25" (~3 min)
Click it. Walk the interpreted panel slowly: each want field → resolved column
+ confidence; the where phrase → the predicate AST. Emphasize: "the model emits
a constrained AST, code validates it against an operator whitelist and the real
fields, and only then does parameterized SQL run. Natural language never touches
SQL." Then point at the SQL echo at the bottom of the panel — the exact query
the connector ran, values as bound parameters. "This is the proof, not a
diagram — the literal SQL, with every value still a parameter." The request
panel below has the same call as a Copy-curl button and the raw response JSON:
"the playground is just a curl with a UI — nothing here is staged."

### 4. Refusal as a feature — chip "Too vague (watch it refuse)" (~2 min)
Click it. The gateway declines: confidence below threshold → HTTP 422, no rows.
Say: "silently returning plausible-but-wrong rows is the real failure mode.
Refusing to guess is the safety feature." (Phrasing was locked during the dry
run — if it ever resolves confidently, make the filter vaguer live and let it
refuse.)

### 5. The cache — re-click chip "Sci-fi under $25" (~1.5 min)
Instant this time — and the interpreted panel shows it: every badge flips from
CACHE MISS → LLM to CACHE HIT. Say: "resolution is cached per backend schema —
a repeat question skips the LLM entirely. Repeat queries cost approximately
nothing." Cost beat: "this is the first application I've built with an LLM in
the request path, and cost immediately became a design constraint — the
two-part cache, the prompt-cache layout, token caps: all standard AI-app
plumbing you end up needing."

### 6. Invite the room (~1.5 min)
Back to slide 7/8: "the URL is on screen — try your own words while I take
questions. If it says the demo budget ran out, that's a guardrail, not a crash —
the own-data page shows how to run it yourself in three steps."

Extra chips ("Written in French", "Young authors", "中文也通", "草莓族？") are
ammunition for audience suggestions, not scripted. The Mandarin chip ("價格低於
$20, 作者 35 歲以上") is a double demo: the filter language doesn't have to be
English, AND the model does the age→birth-year math itself (verified: compiles
to `price < 20 AND birth_year < 1991` at 0.95). If asked about limits: strictly
"35 歲以上" is `<= 1991`, the model chose `<` — that boundary fuzziness is the
`bind_today` milestone in todo.md.

More typed-live ammunition (verify each in the dry run — model updates can
shift them):

- **"作者是 Z 世代"** (want: `book name`, `writer`, `author's birth year`) —
  world-knowledge resolution: the model knows what Gen-Z means and compiles it
  to a birth-year range. Natural follow-up to the "Young authors" chip.
- **Chip "草莓族？(a misread, refused)"** — the strongest refusal story for a
  Mandarin-speaking room, stronger than plain vagueness: the model doesn't know
  草莓族 names a generation, misreads it as an author's name — but at low
  confidence, so the gate refuses. Say: "the gate catches semantic misreads,
  not just vague phrasing. A wrong guess delivered confidently is the failure
  mode; this is the defense."
- **"出版超過 20 年"** (want: `book name`, `published`) — the prompt carries
  today's date, so the model compiles the correct cutoff date. Segue to the
  what's-next slide: making that date binding symbolic (`bind_today`) is the
  first roadmap item, so the compiled AST survives midnight and caches
  date-independently.

## Dry run — the day before (spec: one full pass on the real deployment)

- [ ] Open the production playground; click every chip once (warms the
      resolution cache AND validates the happy paths).
- [ ] Chip 4 refuses (422, friendly copy). If not: adjust its phrasing in
      `playground/lib/examples.ts`, redeploy, re-verify.
- [ ] "草莓族？" chip also refuses (low-confidence misread → 422). Same fix
      path as chip 4 if it ever resolves confidently.
- [ ] Type the two live-ammunition strings ("作者是 Z 世代", "出版超過 20 年")
      once each — Gen-Z compiles to a birth-year range; the date one compiles
      to the correct cutoff for today's date.
- [ ] Re-click chip 3 — visibly faster (cache hit).
- [ ] `curl -s -o /dev/null -w "%{http_code}" https://sans-schema-demo.fly.dev/debug/schema` → 404.
- [ ] Slides load at `/slides.html`; arrow keys work; QR on slide 1 scans from a
      phone to the playground.
- [ ] `fly.toml` caps are the session values (10/minute, 1000/day) and the
      Gemini quota cap is still set.
- [ ] `/own-data` page: copy-paste the three blocks into a terminal — they run.
- [ ] **Day of, ~10 min before going on stage: re-click every chip once.** The
      day-before warm won't survive the night — `fly.toml` has
      `auto_stop_machines` / `min_machines_running = 0` and the resolution cache
      is in-process, so a machine restart empties it.
