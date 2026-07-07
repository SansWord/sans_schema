from gateway.gate import GateConfig, gate_want, where_passes

MAPPING = {
    "writer": {"field": "author.name", "confidence": 0.95},
    "genre":  {"field": "book.category", "confidence": 0.60},   # below 0.7 → declined
    "bogus":  {"field": None, "confidence": 0.0},
}

def test_gate_want_preserves_order_and_declines_low_confidence():
    cfg = GateConfig(threshold=0.7)
    got = gate_want(["writer", "genre", "bogus"], MAPPING, cfg)
    assert [f.client_key for f in got] == ["writer", "genre", "bogus"]
    assert got[0].field_path == "author.name"
    assert got[1].field_path is None and got[1].confidence == 0.60   # confidence retained
    assert got[2].field_path is None

def test_missing_key_becomes_declined_zero_confidence():
    got = gate_want(["ghost"], {}, GateConfig())
    assert got[0].field_path is None and got[0].confidence == 0.0

def test_gate_want_declines_a_non_schema_path():
    # a confident resolution to a field that isn't a real schema path is dropped
    # (SELECT-side mirror of validate_ast) — defends against a hijacked/mis-resolved want.
    mapping = {"good": {"field": "author.name", "confidence": 0.99},
               "bad":  {"field": "author.ghost", "confidence": 0.99}}
    got = gate_want(["good", "bad"], mapping, GateConfig(0.7),
                    valid_fields={"author.name", "book.category"})
    assert got[0].field_path == "author.name"
    assert got[1].field_path is None and got[1].confidence == 0.99   # confidence retained

def test_where_passes():
    cfg = GateConfig(threshold=0.7)
    assert where_passes(0.88, cfg) is True
    assert where_passes(0.60, cfg) is False
    assert where_passes(None, cfg) is False
