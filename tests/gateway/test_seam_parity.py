from gateway.connectors.fake import FakeConnector
from gateway.contracts import CanonicalQueryIR, ResolvedField

IR = CanonicalQueryIR(
    select=[ResolvedField("t", "title", 0.9), ResolvedField("g", "category", 0.9)],
    predicate={"op": "and", "clauses": [
        {"op": "eq", "field": "category", "value": "Science Fiction"},
        {"op": "gte", "field": "price", "value": 20}]},
    where_confidence=0.9, where_raw="expensive sci-fi")

def _rowset(rows):
    return frozenset((r["t"] if "t" in r else r["title"],) for r in rows)  # keyed by field_path

def test_introspected_schema_matches_the_fake_mirror(pg_connector):
    pg_paths = {f.path for f in pg_connector.describe().fields}
    fake_paths = {f.path for f in FakeConnector().describe().fields}
    assert pg_paths == fake_paths

def test_same_ir_selects_the_same_rows(pg_connector):
    pg_rows = pg_connector.execute(IR, limit=100)
    fake_rows = FakeConnector().execute(IR)
    key = lambda rows: frozenset((r["title"], r["category"]) for r in rows)
    assert key(pg_rows) == key(fake_rows)          # order not guaranteed without ORDER BY
    assert key(pg_rows) == {("The Long Orbit", "Science Fiction"),
                            ("Orbit of Dreams", "Science Fiction")}
