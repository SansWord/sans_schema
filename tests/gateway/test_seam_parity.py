from gateway.connectors.base import schema_version
from gateway.connectors.fake import FakeConnector
from gateway.contracts import CanonicalQueryIR, ResolvedField

IR = CanonicalQueryIR(
    select=[ResolvedField("t", "books_view.title", 0.9),
            ResolvedField("g", "books_view.category", 0.9)],
    predicate={"op": "and", "clauses": [
        {"op": "eq", "field": "books_view.category", "value": "Science Fiction"},
        {"op": "gte", "field": "books_view.price", "value": 20}]},
    where_confidence=0.9, where_raw="expensive sci-fi")

def test_introspected_schema_matches_the_fake_mirror(pg_connector):
    pg = pg_connector.describe()
    fake = FakeConnector().describe()
    assert {f.path for f in pg.fields} == {f.path for f in fake.fields}
    # spec §11 tier-2: the introspected schema must *equal* the fake mirror, not
    # merely share column names. schema_version folds path|type|description, so an
    # equal hash proves seed.sql and rows.py have not drifted on type or description.
    assert schema_version(pg) == schema_version(fake)

def test_same_ir_selects_the_same_rows(pg_connector):
    pg_rows = pg_connector.execute(IR, limit=100)
    fake_rows = FakeConnector().execute(IR)
    key = lambda rows: frozenset((r["books_view.title"], r["books_view.category"]) for r in rows)
    assert key(pg_rows) == key(fake_rows)          # order not guaranteed without ORDER BY
    assert key(pg_rows) == {("The Long Orbit", "Science Fiction"),
                            ("Orbit of Dreams", "Science Fiction")}
