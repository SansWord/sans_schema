import pytest
from core.resolver import type_check_ast, validate_ast
from core.schemas import Schema, Field

SCHEMA = Schema("demo", [
    Field("t.id", "integer", "id"),
    Field("t.price", "numeric", "price"),
    Field("t.name", "text", "name"),
    Field("t.active", "boolean", "flag"),
    Field("t.made_on", "date", "release date"),
    Field("t.blob", "jsonb", "an unmapped type"),
])

def _both(ast):
    validate_ast(ast, SCHEMA)
    type_check_ast(ast, SCHEMA)

def test_valid_typed_ast_passes():
    _both({"op": "and", "clauses": [
        {"op": "eq", "field": "t.name", "value": "Wireless Mouse"},
        {"op": "gte", "field": "t.price", "value": 20},
        {"op": "eq", "field": "t.active", "value": True},
        {"op": "lt", "field": "t.made_on", "value": "2026-01-01"},
        {"op": "in", "field": "t.id", "value": [1, 2, 3]},
        {"op": "contains", "field": "t.name", "value": "mouse"},
    ]})

def test_numeric_string_on_number_is_coercible():
    type_check_ast({"op": "gte", "field": "t.price", "value": "20"}, SCHEMA)  # no raise

def test_non_numeric_value_on_int_rejected():
    with pytest.raises(ValueError):
        type_check_ast({"op": "in", "field": "t.id", "value": ["select 1"]}, SCHEMA)

def test_bad_date_rejected():
    with pytest.raises(ValueError):
        type_check_ast({"op": "gt", "field": "t.made_on", "value": "not-a-date"}, SCHEMA)

def test_non_bool_on_bool_rejected():
    with pytest.raises(ValueError):
        type_check_ast({"op": "eq", "field": "t.active", "value": "yes"}, SCHEMA)

def test_contains_on_non_text_rejected():
    with pytest.raises(ValueError):
        type_check_ast({"op": "contains", "field": "t.id", "value": "5"}, SCHEMA)

def test_number_on_text_rejected():
    with pytest.raises(ValueError):
        type_check_ast({"op": "eq", "field": "t.name", "value": 123}, SCHEMA)

def test_dict_value_rejected():
    with pytest.raises(ValueError):
        type_check_ast({"op": "eq", "field": "t.price", "value": {"x": 1}}, SCHEMA)

def test_unknown_column_type_is_skipped():
    # jsonb isn't in the kind map → no type check, no raise even for a wild value
    type_check_ast({"op": "eq", "field": "t.blob", "value": 123}, SCHEMA)
