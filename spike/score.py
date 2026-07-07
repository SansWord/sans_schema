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
from core.llm import LiteLLM, LLM
from core.prompts import want_system, want_user, where_system, where_user
from core.resolver import resolve_want, validate_ast, where_ast
from core.predicate import select_indices as _selected, score_where
from .schemas import ALL_SCHEMAS

# Adjust to whatever your keys support. LiteLLM model identifiers.
# Cross-vendor examples (pass via --models, or edit this list):
#   Anthropic (ANTHROPIC_API_KEY): anthropic/claude-haiku-4-5 | -sonnet-4-6 | -opus-4-8
#   OpenAI    (OPENAI_API_KEY):    openai/gpt-5.5 | openai/gpt-5.4 | openai/gpt-5.4-mini
#     current line is GPT-5.x (Jul 2026); gpt-4o / gpt-4.1 / o3 are legacy/deprecated
#   Google    (GEMINI_API_KEY):    gemini/gemini-pro-latest | gemini/gemini-flash-latest
#     current stable ids (Jul 2026): gemini-3.5-flash, gemini-3.1-flash-lite,
#       gemini-2.5-pro, gemini-2.5-flash. The *-latest aliases auto-track the
#       newest Pro/Flash. Gemini 2.0 and 1.x are shut down (404). Google AI
#       Studio provider — Vertex is vertex_ai/gemini-... instead.
# Curated chat/reasoning tiers per provider (cheap -> strong). Pass a provider
# keyword to --models to run its whole set, e.g. `--models gemini`. "all" runs
# every provider. ("All models" literally would include image/embedding models
# that aren't chat models, so these are the resolver-relevant tiers.)
PROVIDER_SETS = {
    "anthropic": [
        "anthropic/claude-haiku-4-5",
        "anthropic/claude-sonnet-4-6",
        "anthropic/claude-opus-4-8",
    ],
    "gemini": [
        "gemini/gemini-3.1-flash-lite",
        "gemini/gemini-3.5-flash",
        "gemini/gemini-pro-latest",
    ],
    "openai": [
        "openai/gpt-5.4-mini",
        "openai/gpt-5.4",
        "openai/gpt-5.5",
    ],
}

DEFAULT_MODELS = PROVIDER_SETS["anthropic"]


def expand_models(tokens: List[str]) -> List[str]:
    """Expand provider keywords ('gemini', 'all') to model lists; pass other
    tokens (explicit LiteLLM ids) through. De-dupes, preserving order."""
    out: List[str] = []
    for t in tokens:
        if t == "all":
            for v in PROVIDER_SETS.values():
                out += v
        elif t in PROVIDER_SETS:
            out += PROVIDER_SETS[t]
        else:
            out.append(t)
    seen = set()
    return [m for m in out if not (m in seen or seen.add(m))]


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
            got_where = where_ast(llm, schema, case.where or "", TODAY) if case.where else None
        except Exception as e:  # noqa: BLE001 — LLM/JSON failure, no raw available
            result["where"] = {"error": f"llm/parse: {e}"}
        else:
            # validate separately so the raw output is captured even on a
            # contract violation (e.g. a where node with no "op").
            try:
                if got_where is not None:
                    validate_ast(got_where, schema)
                result["where"] = {"pass": score_where(case.expect_where, got_where, schema.rows),
                                   "raw": got_where}
            except Exception as e:  # noqa: BLE001
                result["where"] = {"error": str(e), "raw": got_where}
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


def want_misses(case: Case, mapping: Dict[str, Any]):
    """Return (key, expected, got_field, confidence) for each mismatched key."""
    out = []
    for key, exp in case.expect_want.items():
        cell = (mapping or {}).get(key) or {}
        gf = cell.get("field")
        conf = cell.get("confidence", 0)
        declined = gf is None or (isinstance(conf, (int, float)) and conf < 0.5)
        ok = declined if exp is None else (gf == exp)
        if not ok:
            out.append((key, exp, gf, conf))
    return out


def where_debug(case: Case, got_ast, rows):
    """Expected/got ASTs plus the rows each selects — the execution-equivalence
    diff that explains a WHERE failure."""
    exp = case.expect_where
    exp_rows = sorted(_selected(exp, rows)) if exp is not None else None
    try:
        got_rows = sorted(_selected(got_ast, rows)) if got_ast is not None else None
    except Exception as e:  # noqa: BLE001
        got_rows = f"<eval error: {e}>"
    return exp, got_ast, exp_rows, got_rows


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", default=DEFAULT_MODELS,
                    help="LiteLLM model ids, and/or a provider keyword "
                         "(anthropic | gemini | openai | all) to run that "
                         "provider's whole tier set. e.g. --models gemini")
    ap.add_argument("--verbose", action="store_true",
                    help="also print raw resolver output for PASSING cases "
                         "(failures always print expected/got + row diff)")
    ap.add_argument("--show-prompts", action="store_true",
                    help="print the exact assembled prompts and exit (no API calls)")
    args = ap.parse_args(argv)

    if args.show_prompts:
        return show_prompts()

    models = expand_models(args.models)

    for model in models:
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
                # always show which keys missed — paste-ready for debugging
                if w["correct"] < w["total"]:
                    for key, exp, gf, conf in want_misses(case, w.get("raw")):
                        print(f"       want MISS {key!r}: expected {exp}  got {gf} (conf {conf})")
                if args.verbose:
                    print("       want raw:", json.dumps(w.get("raw")))
            if "where" in r:
                wh = r["where"]
                where_total += 1
                if "error" in wh:
                    print(f"     where ERROR: {wh['error']}")
                    print(f"       nl:       {case.where!r}")
                    if "raw" in wh:
                        print(f"       got raw:  {json.dumps(wh['raw'])}")
                    print(f"       expected: {json.dumps(case.expect_where)}")
                else:
                    passed = wh["pass"]
                    where_pass += 1 if passed else 0
                    print(f"     where {'PASS' if passed else 'FAIL'}")
                    if not passed:
                        exp, got, er, gr = where_debug(case, wh.get("raw"),
                                                       ALL_SCHEMAS[case.schema].rows)
                        print(f"       nl:       {case.where!r}")
                        print(f"       expected: {json.dumps(exp)}  -> rows {er}")
                        print(f"       got:      {json.dumps(got)}  -> rows {gr}")
                        if isinstance(er, list) and isinstance(gr, list):
                            print(f"       row diff: only-in-expected {sorted(set(er) - set(gr))}"
                                  f"  only-in-got {sorted(set(gr) - set(er))}")
                    elif args.verbose:
                        print("       where raw:", json.dumps(wh.get("raw")))

        wp = 100 * want_correct / want_total if want_total else 0
        hp = 100 * where_pass / where_total if where_total else 0
        print(f"\n  WANT resolution: {want_correct}/{want_total} = {wp:.0f}%")
        print(f"  WHERE -> AST:    {where_pass}/{where_total} = {hp:.0f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
