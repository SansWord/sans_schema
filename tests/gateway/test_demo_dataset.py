"""Invariants over the frozen demo snapshot (spec 2026-07-13, §Tests).
If one of these fails, fix the dataset (authors.json / build script + re-run
the build), never the assertion."""
import json
from pathlib import Path

from gateway.demo.build_dataset import emit_seed_sql
from gateway.demo.rows import VIEW_ROWS

DEMO = Path(__file__).resolve().parents[2] / "gateway" / "demo"


def test_size_is_in_the_spec_range():
    assert 300 <= len(VIEW_ROWS) <= 500


def test_required_taiwanese_authors_survived_the_drop_policy():
    names = {r["author_name"] for r in VIEW_ROWS}
    assert "Yang Shuang-zi" in names
    assert "Kevin Chen" in names


def test_chip_scifi_under_25_returns_several_rows():
    hits = [r for r in VIEW_ROWS
            if r["category"] == "Science Fiction" and r["price"] < 25]
    assert len(hits) >= 5


def test_chip_written_in_french_returns_rows():
    assert any(r["language"] == "fr" for r in VIEW_ROWS)


def test_chip_young_authors_returns_rows():
    assert any(r["birth_year"] > 1980 for r in VIEW_ROWS)


def test_chip_mandarin_price_and_age_returns_rows():
    # 價格低於 $20, 作者 35 歲以上 — born 1985 or earlier keeps the chip true
    # for years without hardcoding "today".
    assert any(r["price"] < 20 and r["birth_year"] <= 1985 for r in VIEW_ROWS)


def test_gender_field_has_both_male_and_female_rows():
    genders = {r["gender"] for r in VIEW_ROWS}
    assert {"male", "female"} <= genders


def test_committed_seed_sql_matches_the_snapshot():
    snapshot = json.loads((DEMO / "books.json").read_text("utf-8"))
    assert emit_seed_sql(snapshot) == (DEMO / "seed.sql").read_text("utf-8")
