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


def test_demo_snapshot_ships_as_package_data():
    from importlib.resources import files
    snapshot = files("gateway.demo").joinpath("books.json")
    assert snapshot.is_file()
    from gateway.demo.rows import VIEW_ROWS, VIEW_FIELDS
    assert len(VIEW_ROWS) >= 300
    assert any(name == "gender" for (name, _t, _d, _s) in VIEW_FIELDS)
