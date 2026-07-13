export type Interpreted = {
  want: Record<string, { field: string | null; confidence: number }>;
  where?: { raw: string; ast: unknown; confidence: number | null };
};

export type QueryResponse = {
  rows: Record<string, unknown>[];
  interpreted?: Interpreted;
};

export type QueryError = {
  error: string;
  message: string;
  interpreted?: Interpreted;
};

export type QueryResult =
  | { ok: true; data: QueryResponse }
  | { ok: false; status: number; data: QueryError };

const GATEWAY = process.env.NEXT_PUBLIC_GATEWAY_URL ?? "http://localhost:8000";

export async function runQuery(want: string[], where: string | null): Promise<QueryResult> {
  const res = await fetch(`${GATEWAY}/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ want, where, isVerbose: true }),
  });
  const data = await res.json();
  return res.ok ? { ok: true, data } : { ok: false, status: res.status, data };
}
