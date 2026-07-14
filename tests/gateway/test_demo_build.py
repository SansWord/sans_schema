"""Unit tests for the demo dataset build pipeline's PURE parts.
The network-fetching parts are exercised by deliberately running the script."""
from gateway.demo.columns import COLUMNS


def test_columns_carry_the_full_view_including_gender():
    names = [c[0] for c in COLUMNS]
    assert names == ["book_id", "title", "category", "published_at", "price",
                     "page_count", "language", "author_id", "author_name",
                     "birth_year", "country", "gender"]
    by_name = {c[0]: c for c in COLUMNS}
    assert by_name["gender"] == ("gender", "text", "author's gender")
    assert by_name["price"] == ("price", "numeric", "retail price in USD")

from gateway.demo.build_dataset import (
    map_category, synth_price, marc_to_iso, normalize_country, emit_seed_sql,
)


def test_map_category_prefers_specific_over_fallback():
    assert map_category(["Science fiction", "American fiction"]) == "Science Fiction"
    assert map_category(["Fantasy", "Fiction"]) == "Fantasy"
    assert map_category(["Detective and mystery stories"]) == "Mystery"
    assert map_category(["Biography", "History"]) == "Non-Fiction"
    assert map_category(["Fiction"]) == "Literary Fiction"
    assert map_category([]) == "Literary Fiction"


def test_synth_price_is_deterministic_and_bounded():
    a = synth_price("A Wizard of Earthsea", "Fantasy", 205)
    b = synth_price("A Wizard of Earthsea", "Fantasy", 205)
    assert a == b
    for title, cat, pages in [("x", "Fantasy", 100), ("Dune", "Science Fiction", 700),
                              ("y", "History", 900), ("z", "Romance", 50)]:
        p = synth_price(title, cat, pages)
        assert 4.99 <= p <= 49.99
        cents = round(p - int(p), 2)
        assert cents in (0.50, 0.99)


def test_marc_to_iso_maps_known_codes_and_none_for_unknown():
    assert marc_to_iso("eng") == "en"
    assert marc_to_iso("fre") == "fr"
    assert marc_to_iso("chi") == "zh"
    assert marc_to_iso("xxx") is None


def test_normalize_country_shortens_long_forms():
    assert normalize_country("United States of America") == "USA"
    assert normalize_country("United Kingdom") == "UK"
    assert normalize_country("Taiwan") == "Taiwan"
    assert normalize_country("Japan") == "Japan"


TINY_SNAPSHOT = {
    "authors": [{"author_id": 1, "author_name": "Ursula K. Le Guin",
                 "birth_year": 1929, "country": "USA", "gender": "female"}],
    "books": [{"book_id": 1, "title": "A Wizard of Earthsea", "category": "Fantasy",
               "published_at": "1968-01-01", "price": 9.99, "page_count": 205,
               "language": "en", "author_id": 1}],
}


def test_emit_seed_sql_structure_and_escaping():
    sql = emit_seed_sql(TINY_SNAPSHOT)
    assert sql.startswith("-- Demo dataset — GENERATED")
    assert "CREATE TABLE authors" in sql and "gender      text" in sql
    assert "CREATE VIEW books_view AS" in sql
    assert "(1, 'A Wizard of Earthsea', 'Fantasy', '1968-01-01', 9.99, 205, 'en', 1)" in sql
    # every view column gets its comment, single quotes doubled
    # (whitespace-insensitive: the emitter pads column names for alignment)
    normalized = " ".join(sql.split())
    assert "COMMENT ON COLUMN books_view.gender IS 'author''s gender';" in normalized
    assert all(f"books_view.{name}" in sql for (name, _t, _d) in COLUMNS)
    # deterministic: same input, same output
    assert emit_seed_sql(TINY_SNAPSHOT) == sql
