"use client";
import { Example, EXAMPLES } from "@/lib/examples";

type Props = {
  want: string[];
  where: string;
  busy: boolean;
  onWantChange: (fields: string[]) => void;
  onWhereChange: (where: string) => void;
  onRun: () => void;
  onExample: (ex: Example) => void;
};

export default function RequestBuilder(
  { want, where, busy, onWantChange, onWhereChange, onRun, onExample }: Props,
) {
  const setField = (i: number, v: string) =>
    onWantChange(want.map((f, j) => (j === i ? v : f)));
  return (
    <section className="panel">
      <p className="framing">
        This is a database of books. Ask for fields <em>in your own words</em> —
        the backend&apos;s real column names are hidden.
      </p>
      <div className="chips">
        {EXAMPLES.map((ex) => (
          <button key={ex.label} className="chip" disabled={busy}
                  onClick={() => onExample(ex)}>
            {ex.label}
          </button>
        ))}
      </div>
      <label className="label">want — the fields, in your words</label>
      {want.map((f, i) => (
        <div key={i} className="want-row">
          <input value={f} placeholder={`field ${i + 1}`}
                 onChange={(e) => setField(i, e.target.value)} />
          <button aria-label="remove field" disabled={want.length === 1}
                  onClick={() => onWantChange(want.filter((_, j) => j !== i))}>
            ×
          </button>
        </div>
      ))}
      <button className="add" onClick={() => onWantChange([...want, ""])}>
        + add field
      </button>
      <label className="label">where — a plain-language filter (optional)</label>
      <textarea value={where} rows={2}
                placeholder="e.g. science fiction under 25 dollars"
                onChange={(e) => onWhereChange(e.target.value)} />
      <button className="run" disabled={busy || want.every((f) => !f.trim())}
              onClick={onRun}>
        {busy ? "Running…" : "Run"}
      </button>
    </section>
  );
}
