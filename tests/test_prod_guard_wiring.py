"""The prod guard sits in front of every write path to Postgres.

db/seed_copack.py and db/precompute_forecast.py create, truncate and insert
into copack.* at DATABASE_URL -- localhost:15433 in .env, which is a
`fly proxy` tunnel to production when one is open. These tests fake a flyctl
listener, run each script as __main__, and assert nothing connects.
"""

import pathlib
import runpy
import sys

import dotenv
import psycopg2
import pytest

DB = pathlib.Path(__file__).parent.parent / "db"
sys.path.insert(0, str(DB))

import prod_guard  # noqa: E402  (db/prod_guard.py, as the scripts import it)

SCRIPTS = ["seed_copack.py", "precompute_forecast.py"]


@pytest.fixture
def fly_tunnel(monkeypatch):
    seen = []
    monkeypatch.delenv("ALLOW_PROD_DB", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://u@127.0.0.1:15433/cinderhaven")
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **kw: False)  # keep .env out
    monkeypatch.setattr(prod_guard, "_listener", lambda port: seen.append(port) or "flyctl")
    monkeypatch.setattr(psycopg2, "connect", lambda *a, **kw: pytest.fail("connected"))
    return seen


@pytest.mark.parametrize("script", SCRIPTS)
def test_write_script_refuses_fly_tunnel(fly_tunnel, script):
    with pytest.raises(prod_guard.ProdDatabaseError):
        runpy.run_path(str(DB / script), run_name="__main__")
    assert fly_tunnel == [15433]
