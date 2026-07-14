from gateway.contracts import CanonicalQueryIR, ResolvedField

def test_describe_introspects_view_columns(pg_connector):
    schema = pg_connector.describe()
    by_path = {f.path: f for f in schema.fields}
    assert {"books_view.title", "books_view.category",
            "books_view.price", "books_view.author_name"} <= set(by_path)
    assert by_path["books_view.category"].description == "genre / subject classification"
    # _samples() is DISTINCT ... LIMIT 5 with no ORDER BY — membership of one
    # specific value is not guaranteed, so assert against the whole vocabulary.
    vocab = {"Science Fiction", "Fantasy", "Mystery", "Romance", "History",
             "Non-Fiction", "Literary Fiction"}
    samples = by_path["books_view.category"].samples
    assert samples and set(samples) <= vocab

def test_execute_compiles_ast_and_keys_by_path(pg_connector):
    ir = CanonicalQueryIR(
        select=[ResolvedField("t", "books_view.title", 0.9),
                ResolvedField("g", "books_view.category", 0.9)],
        predicate={"op": "and", "clauses": [
            {"op": "eq", "field": "books_view.author_name", "value": "Yang Shuang-zi"},
            {"op": "lt", "field": "books_view.price", "value": 30}]},
        where_confidence=0.9, where_raw="cheap books by Yang Shuang-zi")
    rows = pg_connector.execute(ir, limit=100)
    assert {r["books_view.title"] for r in rows} == {"我家住在張日興隆隔壁",
                                                     "Taiwan Travelogue"}
    assert set(rows[0]) == {"books_view.title", "books_view.category"}

def test_limit_is_enforced(pg_connector):
    ir = CanonicalQueryIR(select=[ResolvedField("t", "books_view.title", 0.9)],
                          predicate=None, where_confidence=None, where_raw=None)
    assert len(pg_connector.execute(ir, limit=2)) == 2

def test_execute_fills_trace_with_parameterized_sql(pg_connector):
    from gateway.connectors.base import ExecutionTrace
    ir = CanonicalQueryIR(
        select=[ResolvedField("t", "books_view.title", 0.9)],
        predicate={"op": "lt", "field": "books_view.price", "value": 30},
        where_confidence=0.9, where_raw="under $30")
    trace = ExecutionTrace()
    pg_connector.execute(ir, limit=5, trace=trace)
    assert trace.engine == "postgres"
    assert trace.sql == 'SELECT "title" FROM "books_view" WHERE "price" < %s LIMIT %s'
    assert trace.params == [30, 5]              # values stay bound, never inlined
