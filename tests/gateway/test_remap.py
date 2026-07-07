from gateway.pipeline import remap_row
from gateway.contracts import ResolvedField

def test_remap_uses_client_keys_and_nulls_declined_fields():
    select = [ResolvedField("book_title", "title", 0.9),
              ResolvedField("genre", "category", 0.9),
              ResolvedField("mystery", None, 0.2)]   # declined → null column
    row = {"title": "The Long Orbit", "category": "Science Fiction"}
    assert remap_row(row, select) == {
        "book_title": "The Long Orbit", "genre": "Science Fiction", "mystery": None}
