export default function ResultsTable({ rows }: { rows: Record<string, unknown>[] }) {
  if (rows.length === 0) return <p className="empty">No rows matched.</p>;
  const cols = Object.keys(rows[0]);
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>{cols.map((c) => <th key={c}>{c}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i}>
              {cols.map((c) => (
                <td key={c}>
                  {row[c] === null
                    ? "—"
                    : typeof row[c] === "object"
                      ? JSON.stringify(row[c])
                      : String(row[c])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
