import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Run it on your own data — sans_schema",
};

const STEP1 = `git clone https://github.com/SansWord/sans_schema.git
cd sans_schema
docker build -t sans-schema .`;

const STEP2 = `docker run -p 8000:8000 \\
  -e DATABASE_URL="postgresql://user:pass@host:5432/yourdb" \\
  -e DB_VIEW="your_flat_view" \\
  -e LLM_MODEL="gemini/gemini-3.1-flash-lite" \\
  -e GEMINI_API_KEY="<your key>" \\
  sans-schema`;

const STEP3 = `curl -s localhost:8000/query \\
  -H 'Content-Type: application/json' \\
  -d '{"want": ["any field, in your words"],
       "where": "a plain-language filter",
       "isVerbose": true}'`;

export default function OwnData() {
  return (
    <main>
      <header>
        <h1>Run it on your own data</h1>
        <p>
          Three steps: build the gateway, point it at your Postgres with your own
          LLM key, and query it in your own words.
        </p>
      </header>
      <section className="panel">
        <ol className="steps">
          <li>
            <strong>Build the image</strong>
            <pre className="block">{STEP1}</pre>
          </li>
          <li>
            <strong>Run it against your database</strong>
            <p>
              The gateway introspects one flat (denormalized) view — point{" "}
              <code>DB_VIEW</code> at yours. Column comments improve resolution.
              Any LiteLLM model id works; set the matching provider key.
            </p>
            <pre className="block">{STEP2}</pre>
          </li>
          <li>
            <strong>Query it in your own words</strong>
            <pre className="block">{STEP3}</pre>
          </li>
        </ol>
        <p>
          Full quickstart (local Postgres, seed data, every env var):{" "}
          <a href="https://github.com/SansWord/sans_schema/blob/main/gateway/README.md">
            gateway/README.md
          </a>
        </p>
      </section>
      <footer>
        <a href="/">← Back to the playground</a>
      </footer>
    </main>
  );
}
