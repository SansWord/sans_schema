def test_core_exports_resolver_and_types():
    from core.resolver import resolve_want, where_ast, parse_where, validate_ast
    from core.schemas import Schema, Field
    from core.llm import LLM, LiteLLM
    from core.prompts import want_system, where_system, OPS
    assert "eq" in OPS


def test_spike_still_imports_and_reuses_core_types():
    from spike.schemas import BOOKS, ALL_SCHEMAS
    from core.schemas import Schema
    assert isinstance(BOOKS, Schema)
    assert set(ALL_SCHEMAS) == {"library", "shop", "hr", "streaming"}
