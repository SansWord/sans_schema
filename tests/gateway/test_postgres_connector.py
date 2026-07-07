from gateway.contracts import CanonicalQueryIR, ResolvedField

def test_describe_introspects_view_columns(pg_connector):
    schema = pg_connector.describe()
    by_path = {f.path: f for f in schema.fields}
    assert {"title", "category", "price", "author_name"} <= set(by_path)
    assert by_path["category"].description == "genre / subject classification"
    assert "Science Fiction" in by_path["category"].samples

def test_execute_compiles_ast_and_keys_by_path(pg_connector):
    ir = CanonicalQueryIR(
        select=[ResolvedField("t", "title", 0.9), ResolvedField("g", "category", 0.9)],
        predicate={"op": "and", "clauses": [
            {"op": "eq", "field": "category", "value": "Science Fiction"},
            {"op": "gte", "field": "price", "value": 20}]},
        where_confidence=0.9, where_raw="expensive sci-fi")
    rows = pg_connector.execute(ir, limit=100)
    assert {r["title"] for r in rows} == {"The Long Orbit", "Orbit of Dreams"}
    assert set(rows[0]) == {"title", "category"}

def test_limit_is_enforced(pg_connector):
    ir = CanonicalQueryIR(select=[ResolvedField("t", "title", 0.9)],
                          predicate=None, where_confidence=None, where_raw=None)
    assert len(pg_connector.execute(ir, limit=2)) == 2
