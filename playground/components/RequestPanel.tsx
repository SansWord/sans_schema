"use client";
import { useState } from "react";
import { asCurl } from "@/lib/api";

export default function RequestPanel(
  { want, where, response }: { want: string[]; where: string | null; response?: unknown },
) {
  const [copied, setCopied] = useState(false);
  const curl = asCurl(want, where);
  async function copy() {
    await navigator.clipboard.writeText(curl);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }
  return (
    <section className="panel">
      <div className="panel-head">
        <h2>The request — this is the whole API</h2>
        <button className="copy" onClick={() => void copy()}>
          {copied ? "Copied!" : "Copy curl"}
        </button>
      </div>
      <pre className="block">{curl}</pre>
      {response !== undefined && (
        <details className="response-json">
          <summary>Response JSON</summary>
          <pre className="block">{JSON.stringify(response, null, 2)}</pre>
        </details>
      )}
    </section>
  );
}
