"use client";
import { useState } from "react";
import RequestBuilder from "@/components/RequestBuilder";
import ResultsTable from "@/components/ResultsTable";
import InterpretedPanel from "@/components/InterpretedPanel";
import StatusPanel from "@/components/StatusPanel";
import { runQuery, QueryError, QueryResponse } from "@/lib/api";
import { Example } from "@/lib/examples";

export default function Home() {
  const [want, setWant] = useState<string[]>(["book name", "writer"]);
  const [where, setWhere] = useState("");
  const [busy, setBusy] = useState(false);
  const [ok, setOk] = useState<QueryResponse | null>(null);
  const [err, setErr] = useState<{ status: number; data: QueryError } | null>(null);

  async function run(w: string[] = want, wh: string = where) {
    setBusy(true);
    setOk(null);
    setErr(null);
    try {
      const fields = w.map((f) => f.trim()).filter(Boolean);
      const res = await runQuery(fields, wh.trim() || null);
      if (res.ok) setOk(res.data);
      else setErr({ status: res.status, data: res.data });
    } catch {
      setErr({ status: 0, data: { error: "network", message: "Could not reach the gateway." } });
    } finally {
      setBusy(false);
    }
  }

  function useExample(ex: Example) {
    setWant([...ex.want]);
    setWhere(ex.where ?? "");
    void run(ex.want, ex.where ?? "");
  }

  return (
    <main>
      <header>
        <h1>sans_schema playground</h1>
        <p>Query a database you&apos;ve never seen, in your own words.</p>
      </header>
      <RequestBuilder want={want} where={where} busy={busy}
                      onWantChange={setWant} onWhereChange={setWhere}
                      onRun={() => void run()} onExample={useExample} />
      {err && (
        <>
          <StatusPanel status={err.status} error={err.data} />
          {err.data.interpreted && <InterpretedPanel interpreted={err.data.interpreted} />}
        </>
      )}
      {ok && (
        <>
          <section className="panel">
            <h2>Rows — in <em>your</em> column names</h2>
            <ResultsTable rows={ok.rows} />
          </section>
          {ok.interpreted && <InterpretedPanel interpreted={ok.interpreted} />}
        </>
      )}
      <footer>
        <a href="/own-data">Try it with your own data →</a>
      </footer>
    </main>
  );
}
