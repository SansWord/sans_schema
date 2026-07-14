import { Debug, Interpreted } from "@/lib/api";

function Confidence({ value }: { value: number | null }) {
  if (value === null) return null;
  const cls = value >= 0.9 ? "conf high" : value >= 0.7 ? "conf mid" : "conf low";
  return <span className={cls}>{Math.round(value * 100)}%</span>;
}

function CacheBadge({ status }: { status?: "hit" | "miss" }) {
  if (!status) return null;
  return status === "hit"
    ? <span className="badge hit">CACHE HIT</span>
    : <span className="badge miss">CACHE MISS → LLM</span>;
}

export default function InterpretedPanel(
  { interpreted, debug }: { interpreted: Interpreted; debug?: Debug },
) {
  const gatePct = debug ? Math.round(debug.gate_threshold * 100) : null;
  return (
    <section className="panel interpreted">
      <h2>{debug ? "What the gateway understood — and did" : "What the gateway understood"}</h2>
      <ul>
        {Object.entries(interpreted.want).map(([key, cell]) => (
          <li key={key}>
            <code className="yours">{key}</code>
            {" → "}
            {cell.field
              ? <code className="theirs">{cell.field}</code>
              : <em>declined (not confident enough)</em>}
            <Confidence value={cell.confidence} />
            <CacheBadge status={debug?.cache.want[key]} />
          </li>
        ))}
      </ul>
      {interpreted.where && (
        <div className="where-echo">
          <p>
            <strong>filter:</strong> “{interpreted.where.raw}”
            <Confidence value={interpreted.where.confidence} />
            {gatePct !== null && <span className="gate-note"> (gate: ≥{gatePct}%)</span>}
            <CacheBadge status={debug?.cache.where} />
          </p>
          {interpreted.where.ast == null
            ? <em>(no filter compiled)</em>
            : <pre>{JSON.stringify(interpreted.where.ast, null, 2)}</pre>}
        </div>
      )}
      {debug?.execution?.sql && (
        <div className="sql-echo">
          <h3>SQL the connector ran — values stay bound parameters</h3>
          <pre className="block">
            {debug.execution.sql}
            {"\n-- params: " + JSON.stringify(debug.execution.params)}
          </pre>
        </div>
      )}
    </section>
  );
}
