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
