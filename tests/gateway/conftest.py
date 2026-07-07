import os
from pathlib import Path
import pytest

SEED = Path(__file__).resolve().parents[2] / "gateway" / "demo" / "seed.sql"


@pytest.fixture
def pg_connector():
    dsn = os.environ.get("TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("set TEST_DATABASE_URL to run Postgres-backed tests")
    import psycopg
    from gateway.connectors.postgres import PostgresConnector
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(SEED.read_text())
    return PostgresConnector(dsn, view="books_view")
