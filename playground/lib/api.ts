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
    signal: AbortSignal.timeout(30_000),
  });
  if (res.ok) return { ok: true, data: await res.json() };
  let data: QueryError;
  try {
    data = await res.json();
  } catch {
    data = { error: "http_error", message: `${res.status} ${res.statusText}` };
  }
  return { ok: false, status: res.status, data };
}
