from gateway.contracts import CanonicalQueryIR, ResolvedField

def test_describe_introspects_view_columns(pg_connector):
    schema = pg_connector.describe()
    by_path = {f.path: f for f in schema.fields}
    assert {"books_view.title", "books_view.category",
            "books_view.price", "books_view.author_name"} <= set(by_path)
    assert by_path["books_view.category"].description == "genre / subject classification"
    assert "Science Fiction" in by_path["books_view.category"].samples

def test_execute_compiles_ast_and_keys_by_path(pg_connector):
    ir = CanonicalQueryIR(
        select=[ResolvedField("t", "books_view.title", 0.9),
                ResolvedField("g", "books_view.category", 0.9)],
        predicate={"op": "and", "clauses": [
            {"op": "eq", "field": "books_view.category", "value": "Science Fiction"},
            {"op": "gte", "field": "books_view.price", "value": 20}]},
        where_confidence=0.9, where_raw="expensive sci-fi")
    rows = pg_connector.execute(ir, limit=100)
    assert {r["books_view.title"] for r in rows} == {"The Long Orbit", "Orbit of Dreams"}
    assert set(rows[0]) == {"books_view.title", "books_view.category"}

def test_limit_is_enforced(pg_connector):
    ir = CanonicalQueryIR(select=[ResolvedField("t", "books_view.title", 0.9)],
                          predicate=None, where_confidence=None, where_raw=None)
    assert len(pg_connector.execute(ir, limit=2)) == 2
