from gateway.contracts import RawQuery, ResolvedField, CanonicalQueryIR

def test_rawquery_defaults():
    q = RawQuery(want=["title", "writer"], where="sci-fi", today="2026-07-06")
    assert q.verbose is False and q.want == ["title", "writer"]

def test_ir_carries_select_and_predicate():
    ir = CanonicalQueryIR(
        select=[ResolvedField("writer", "author.name", 0.95),
                ResolvedField("bogus", None, 0.10)],
        predicate={"op": "eq", "field": "book.category", "value": "Science Fiction"},
        where_confidence=0.88, where_raw="sci-fi only")
    assert ir.select[1].field_path is None
    assert ir.where_confidence == 0.88
