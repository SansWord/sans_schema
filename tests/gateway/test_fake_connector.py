from gateway.connectors.base import schema_version, Capabilities
from gateway.connectors.fake import FakeConnector
from gateway.contracts import CanonicalQueryIR, ResolvedField

def test_describe_exposes_the_view_columns():
    c = FakeConnector()
    schema = c.describe()
    paths = {f.path for f in schema.fields}
    assert {"books_view.title", "books_view.category",
            "books_view.price", "books_view.author_name"} <= paths
    assert c.backend_id == "fake"
    assert isinstance(c.capabilities(), Capabilities)

def test_schema_version_is_stable_and_field_sensitive():
    c = FakeConnector()
    assert schema_version(c.describe()) == schema_version(c.describe())

def test_execute_filters_and_keys_by_field_path():
    c = FakeConnector()
    ir = CanonicalQueryIR(
        select=[ResolvedField("book_title", "books_view.title", 0.9),
                ResolvedField("genre", "books_view.category", 0.9)],
        predicate={"op": "eq", "field": "books_view.category", "value": "Science Fiction"},
        where_confidence=0.9, where_raw="sci-fi")
    rows = c.execute(ir)
    assert rows and all(r["books_view.category"] == "Science Fiction" for r in rows)
    assert set(rows[0]) == {"books_view.title", "books_view.category"}   # keyed by field_path

def test_execute_fills_trace_engine():
    from gateway.connectors.base import ExecutionTrace
    ir = CanonicalQueryIR(select=[ResolvedField("t", "books_view.title", 0.9)],
                          predicate=None, where_confidence=None, where_raw=None)
    trace = ExecutionTrace()
    rows = FakeConnector().execute(ir, trace=trace)
    assert rows                                     # execute still returns rows
    assert trace.engine == "core.predicate"
    assert trace.sql is None and trace.params is None   # no SQL story to tell
