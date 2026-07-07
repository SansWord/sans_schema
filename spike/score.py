"""Harness: run {models} x {cases}, score want-resolution and NL-where->AST,
print a report.

Usage:
    python -m spike.score
    python -m spike.score --models anthropic/claude-haiku-4-5 openai/gpt-4o
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List, Optional

from .cases import CASES, TODAY, Case
from .llm import LiteLLM, LLM
from .prompts import want_system, want_user, where_system, where_user
from .resolver import parse_where, resolve_want
from .schemas import ALL_SCHEMAS

# Adjust to whatever your keys support. LiteLLM model identifiers.
# Cross-vendor examples (pass via --models, or edit this list):
#   Anthropic (ANTHROPIC_API_KEY): anthropic/claude-haiku-4-5 | -sonnet-4-6 | -opus-4-8
#   OpenAI    (OPENAI_API_KEY):    openai/gpt-4o | openai/gpt-4o-mini
#   Google    (GEMINI_API_KEY):    gemini/gemini-pro-latest | gemini/gemini-flash-latest
#     current stable ids (Jul 2026): gemini-3.5-flash, gemini-3.1-flash-lite,
#       gemini-2.5-pro, gemini-2.5-flash. The *-latest aliases auto-track the
#       newest Pro/Flash. Gemini 2.0 and 1.x are shut down (404). Google AI
#       Studio provider — Vertex is vertex_ai/gemini-... instead.
DEFAULT_MODELS = [
    "anthropic/claude-haiku-4-5",
    "anthropic/claude-sonnet-4-6",
    "anthropic/claude-opus-4-8",
]


# --- scoring ---------------------------------------------------------------

def score_want(expected: Dict[str, Optional[str]], got: Dict[str, Any]):
    """Returns (correct, total, gate_ok) where gate_ok counts unresolvable keys
    the model correctly declined (field null / low confidence)."""
    correct = 0
    gate_ok = 0
    for key, exp_field in expected.items():
        cell = got.get(key) or {}
        got_field = cell.get("field")
        conf = cell.get("confidence", 0.0)
        declined = got_field is None or (isinstance(conf, (int, float)) and conf < 0.5)
        if exp_field is None:
            # should be declined
            if declined:
                gate_ok += 1
                correct += 1
        else:
            if got_field == exp_field:
                correct += 1
    return correct, len(expected), gate_ok


# --- execution equivalence -------------------------------------------------
# Two predicate ASTs are semantically equal iff they select the same rows from
# the schema's sample dataset. This is robust to clause order, gt-vs-gte at a
# non-boundary, open-range-vs-bounded, and date-vs-datetime formatting — the
# exact things that made an AST-shape comparison give false failures.
from datetime import datetime  # noqa: E402


def _parse_dt(s: str):
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s.strip(), fmt)
        except ValueError:
            continue
    return None


def _norm(v: Any) -> Any:
    """Normalize a value so equal-meaning values compare equal regardless of how
    the model chose to represent them (int vs "2026", bool vs "true", date vs
    datetime). Order matters: bool before number (bool is an int subclass)."""
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip()
        dt = _parse_dt(s)
        if dt is not None:
            return dt
        low = s.lower()
        if low in ("true", "false"):
            return low == "true"
        try:
            return float(s)          # numeric string -> number ("2026" == 2026)
        except ValueError:
            return low
    return v


def _match(node: Dict[str, Any], row: Dict[str, Any]) -> bool:
    op = node.get("op")
    if op == "and":
        return all(_match(c, row) for c in node.get("clauses", []))
    if op == "or":
        return any(_match(c, row) for c in node.get("clauses", []))
    if op == "not":
        return not _match(node["clause"], row)

    raw = row.get(node.get("field"))
    val = node.get("value")
    lv = _norm(raw)
    rv = [_norm(x) for x in val] if isinstance(val, list) else _norm(val)

    if op == "eq":
        return lv == rv
    if op == "ne":
        return lv != rv
    if op == "in":
        return lv in rv
    if op == "nin":
        return lv not in rv
    if op == "is_null":
        return raw is None
    if op == "contains":
        return isinstance(lv, str) and isinstance(rv, str) and rv in lv
    if op == "between":
        lo, hi = rv[0], rv[1]
        try:
            return lo <= lv <= hi
        except TypeError:
            return False
    try:
        if op == "gt":
            return lv > rv
        if op == "gte":
            return lv >= rv
        if op == "lt":
            return lv < rv
        if op == "lte":
            return lv <= rv
    except TypeError:
        return False
    return False


def _selected(ast: Dict[str, Any], rows: List[Dict[str, Any]]) -> frozenset:
    return frozenset(i for i, r in enumerate(rows) if _match(ast, r))


def score_where(expected: Optional[Dict[str, Any]], got: Optional[Dict[str, Any]],
                rows: List[Dict[str, Any]]) -> bool:
    if expected is None:
        return got is None
    if got is None:
        return False
    try:
        return _selected(expected, rows) == _selected(got, rows)
    except Exception:  # noqa: BLE001
        return False


# --- run -------------------------------------------------------------------

def run_case(llm: LLM, case: Case) -> Dict[str, Any]:
    schema = ALL_SCHEMAS[case.schema]
    result: Dict[str, Any] = {"note": case.note}
    try:
        got_want = resolve_want(llm, schema, case.want)
        c, t, g = score_want(case.expect_want, got_want)
        result["want"] = {"correct": c, "total": t, "gate_ok": g, "raw": got_want}
    except Exception as e:  # noqa: BLE001
        result["want"] = {"error": str(e)}

    if case.where is not None or case.expect_where is not None:
        try:
            got_where = parse_where(llm, schema, case.where or "", TODAY) if case.where else None
            result["where"] = {"pass": score_where(case.expect_where, got_where, schema.rows),
                               "raw": got_where}
        except Exception as e:  # noqa: BLE001
            result["where"] = {"error": str(e)}
    return result


def show_prompts() -> int:
    """Print the exact prompts we send — no API calls, no key needed."""
    print("=" * 70)
    print("SYSTEM PROMPTS (constant across cases; domain hints would append here)")
    print("=" * 70)
    print("\n[resolve_want / system]\n" + want_system())
    print("\n[parse_where / system]\n" + where_system())
    print("\n" + "=" * 70)
    print("PER-CASE USER PROMPTS (schema context + the actual request)")
    print("=" * 70)
    for i, case in enumerate(CASES):
        sp = ALL_SCHEMAS[case.schema].as_prompt()
        print(f"\n### CASE {i} [{case.schema}] — {case.note}")
        print("\n[resolve_want / user]\n" + want_user(sp, case.want))
        if case.where is not None:
            print("\n[parse_where / user]\n" + where_user(sp, case.where, TODAY))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", default=DEFAULT_MODELS)
    ap.add_argument("--verbose", action="store_true", help="print raw resolver output")
    ap.add_argument("--show-prompts", action="store_true",
                    help="print the exact assembled prompts and exit (no API calls)")
    args = ap.parse_args(argv)

    if args.show_prompts:
        return show_prompts()

    for model in args.models:
        print(f"\n{'='*70}\nMODEL: {model}\n{'='*70}")
        llm = LiteLLM(model)
        want_correct = want_total = 0
        where_pass = where_total = 0
        for i, case in enumerate(CASES):
            r = run_case(llm, case)
            w = r.get("want", {})
            if "error" in w:
                print(f"[{i}] want ERROR: {w['error']}  ({case.note})")
            else:
                want_correct += w["correct"]
                want_total += w["total"]
                print(f"[{i}] want {w['correct']}/{w['total']}  ({case.note})")
            if "where" in r:
                wh = r["where"]
                where_total += 1
                if "error" in wh:
                    print(f"     where ERROR: {wh['error']}")
                else:
                    where_pass += 1 if wh["pass"] else 0
                    print(f"     where {'PASS' if wh['pass'] else 'FAIL'}")
                    if args.verbose and not wh["pass"]:
                        print("       got:", json.dumps(wh.get("raw")))
            if args.verbose:
                print("       want raw:", json.dumps(w.get("raw")))

        wp = 100 * want_correct / want_total if want_total else 0
        hp = 100 * where_pass / where_total if where_total else 0
        print(f"\n  WANT resolution: {want_correct}/{want_total} = {wp:.0f}%")
        print(f"  WHERE -> AST:    {where_pass}/{where_total} = {hp:.0f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
