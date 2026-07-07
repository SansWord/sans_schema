from gateway.cache import ResolutionCache, normalize_key, normalize_phrase

def test_normalization_collapses_case_and_whitespace():
    assert normalize_key("  Release   Date ") == "release date"
    assert normalize_phrase("Sci-Fi   ONLY") == "sci-fi only"

def test_field_cache_hit_and_miss():
    c = ResolutionCache()
    assert c.get_field("pg", "v1", "writer") is None
    c.set_field("pg", "v1", "writer", {"field": "author.name", "confidence": 0.9})
    assert c.get_field("pg", "v1", "Writer") == {"field": "author.name", "confidence": 0.9}
    assert c.get_field("pg", "v2", "writer") is None          # schema_version scopes the key
    assert c.get_field("other", "v1", "writer") is None       # backend scopes the key

def test_stats_counts_hits_and_misses():
    c = ResolutionCache()
    c.get_field("pg", "v1", "writer")          # miss
    c.set_field("pg", "v1", "writer", {"field": "author.name", "confidence": 0.9})
    c.get_field("pg", "v1", "writer")          # hit
    c.get_field("pg", "v1", "other")           # miss
    field = c.stats()["field"]
    assert field["hits"] == 1 and field["misses"] == 2 and field["lookups"] == 3
    assert field["hit_rate"] == 1 / 3
    combined = c.stats()["combined"]
    assert combined["lookups"] == 3 and combined["hit_rate"] == 1 / 3   # where had 0 lookups

def test_stats_hit_rate_none_before_any_lookup():
    assert ResolutionCache().stats()["combined"]["hit_rate"] is None

def test_where_cache_keys_on_today():
    c = ResolutionCache()
    c.set_where("pg", "v1", "published this year", "2026-07-06",
                {"ast": {"op": "eq"}, "confidence": 0.8})
    assert c.get_where("pg", "v1", "published this year", "2026-07-06")["confidence"] == 0.8
    assert c.get_where("pg", "v1", "published this year", "2026-07-07") is None   # next day misses
