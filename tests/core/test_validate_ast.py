import pytest
from core.resolver import validate_ast
from core.schemas import Schema, Field

SCHEMA = Schema("demo", [Field("category", "text", "genre"),
                         Field("price", "numeric", "price")])

def test_valid_ast_passes():
    validate_ast({"op": "and", "clauses": [
        {"op": "between", "field": "price", "value": [10, 20]},
        {"op": "in", "field": "category", "value": ["a", "b"]},
        {"op": "not", "clause": {"op": "eq", "field": "category", "value": "x"}},
    ]}, SCHEMA)  # no raise

def test_not_missing_clause_raises_valueerror():
    with pytest.raises(ValueError):
        validate_ast({"op": "not"}, SCHEMA)

def test_between_requires_two_element_list():
    with pytest.raises(ValueError):
        validate_ast({"op": "between", "field": "price", "value": 20}, SCHEMA)
    with pytest.raises(ValueError):
        validate_ast({"op": "between", "field": "price", "value": [1, 2, 3]}, SCHEMA)

def test_in_requires_a_list():
    with pytest.raises(ValueError):
        validate_ast({"op": "in", "field": "category", "value": "x"}, SCHEMA)

def test_and_needs_a_clauses_list():
    with pytest.raises(ValueError):
        validate_ast({"op": "and", "clauses": {"op": "eq"}}, SCHEMA)

def test_unknown_field_and_op_still_rejected():
    with pytest.raises(ValueError):
        validate_ast({"op": "eq", "field": "nope", "value": 1}, SCHEMA)
    with pytest.raises(ValueError):
        validate_ast({"op": "regex", "field": "category", "value": "x"}, SCHEMA)
