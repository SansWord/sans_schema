from core.resolver import where_resolve, where_ast, WhereResult
from core.schemas import Schema, Field
from tests.fakes import FakeLLM

SCHEMA = Schema("demo", [Field("book.category", "text", "genre", ["Science Fiction"])])
CANNED = {"where": {"op": "eq", "field": "book.category", "value": "Science Fiction"},
          "confidence": 0.88}

def test_where_resolve_returns_ast_and_confidence():
    r = where_resolve(FakeLLM(where=CANNED), SCHEMA, "sci-fi only", "2026-07-06")
    assert isinstance(r, WhereResult)
    assert r.ast == CANNED["where"]
    assert r.confidence == 0.88

def test_where_ast_still_returns_bare_ast():
    ast = where_ast(FakeLLM(where=CANNED), SCHEMA, "sci-fi only", "2026-07-06")
    assert ast == CANNED["where"]

def test_missing_confidence_defaults_to_none():
    r = where_resolve(FakeLLM(where={"where": None}), SCHEMA, "x", "2026-07-06")
    assert r.ast is None and r.confidence is None
