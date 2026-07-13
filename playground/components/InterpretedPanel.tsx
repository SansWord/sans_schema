import { Interpreted } from "@/lib/api";

function Confidence({ value }: { value: number | null }) {
  if (value === null) return null;
  const cls = value >= 0.9 ? "conf high" : value >= 0.7 ? "conf mid" : "conf low";
  return <span className={cls}>{Math.round(value * 100)}%</span>;
}

export default function InterpretedPanel({ interpreted }: { interpreted: Interpreted }) {
  return (
    <section className="panel interpreted">
      <h2>What the gateway understood</h2>
      <ul>
        {Object.entries(interpreted.want).map(([key, cell]) => (
          <li key={key}>
            <code className="yours">{key}</code>
            {" → "}
            {cell.field
              ? <code className="theirs">{cell.field}</code>
              : <em>declined (not confident enough)</em>}
            <Confidence value={cell.confidence} />
          </li>
        ))}
      </ul>
      {interpreted.where && (
        <div className="where-echo">
          <p>
            <strong>filter:</strong> “{interpreted.where.raw}”
            <Confidence value={interpreted.where.confidence} />
          </p>
          <pre>{JSON.stringify(interpreted.where.ast, null, 2)}</pre>
        </div>
      )}
    </section>
  );
}
