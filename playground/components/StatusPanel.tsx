import { QueryError } from "@/lib/api";

const FRIENDLY: Record<string, string> = {
  where_low_confidence:
    "The gateway wasn't confident enough about what this filter means, so it " +
    "refused instead of returning possibly-wrong rows. The refusal is the safety " +
    "feature. Try a more specific filter.",
  all_want_declined:
    "None of the field names resolved confidently, so the gateway declined the " +
    "whole request rather than guess.",
  rate_limited:
    "You're sending requests a little fast — wait a minute and try again.",
  demo_budget_exhausted:
    "The public demo's daily budget is used up. The gateway is open source — " +
    "run it against your own data below.",
};

export default function StatusPanel({ status, error }: { status: number; error: QueryError }) {
  const friendly = FRIENDLY[error.error];
  const budget = error.error === "demo_budget_exhausted";
  const title = status === 429 ? "Demo limits"
    : status === 422 ? "The gateway declined"
    : `Error ${status || "— network"}`;
  return (
    <section className={budget ? "panel status budget" : "panel status"}>
      <h2>{title}</h2>
      <p>{friendly ?? error.message}</p>
      {friendly && <p className="raw">({error.error}: {error.message})</p>}
      {budget && <p><a href="/own-data">→ Run it with your own data</a></p>}
    </section>
  );
}
