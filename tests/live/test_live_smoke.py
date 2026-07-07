import os
import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_LIVE_LLM") != "1",
    reason="set RUN_LIVE_LLM=1 (and an LLM API key + TEST_DATABASE_URL) to run live")


def test_end_to_end_against_real_llm_and_postgres():
    from pathlib import Path
    import psycopg
    from core.llm import LiteLLM
    from gateway.cache import ResolutionCache
    from gateway.connectors.postgres import PostgresConnector
    from gateway.contracts import RawQuery
    from gateway.gate import GateConfig
    from gateway.pipeline import run_query

    dsn = os.environ["TEST_DATABASE_URL"]
    seed = Path(__file__).resolve().parents[2] / "gateway" / "demo" / "seed.sql"
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(seed.read_text())

    llm = LiteLLM(os.environ.get("LLM_MODEL", "gemini/gemini-3.1-flash-lite"))
    resp = run_query(
        RawQuery(want=["book_title", "writer"], where="science fiction only",
                 today="2026-07-06", verbose=True),
        PostgresConnector(dsn), llm, ResolutionCache(), GateConfig(0.7), limit=100)
    assert resp["rows"]
    assert resp["interpreted"]["want"]["writer"]["field"] in ("author_name", None)
