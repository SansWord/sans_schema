from core.predicate import matches, select_indices

ROWS = [
    {"category": "Science Fiction", "price": 24.0, "published_at": "2026-05-10"},
    {"category": "Fantasy", "price": 9.99, "published_at": "1968-01-01"},
    {"category": "Science Fiction", "price": 30.0, "published_at": "2025-11-20"},
]

def test_eq_and_numeric_and_date_normalization():
    ast = {"op": "and", "clauses": [
        {"op": "eq", "field": "category", "value": "Science Fiction"},
        {"op": "gte", "field": "price", "value": "20"},          # string vs float
    ]}
    assert select_indices(ast, ROWS) == frozenset({0, 2})

def test_between_dates_and_not():
    ast = {"op": "not", "clause": {"op": "between", "field": "published_at",
                                   "value": ["2026-01-01", "2026-12-31"]}}
    assert select_indices(ast, ROWS) == frozenset({1, 2})

def test_in_and_is_null_and_contains():
    rows = [{"status": None, "name": "Wireless Mouse"}, {"status": "shipped", "name": "Desk Lamp"}]
    assert select_indices({"op": "is_null", "field": "status"}, rows) == frozenset({0})
    assert select_indices({"op": "contains", "field": "name", "value": "mouse"}, rows) == frozenset({0})
    assert matches({"op": "in", "field": "status", "value": ["shipped", "delivered"]}, rows[1])
