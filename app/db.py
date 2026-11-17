"""Database connection pool for the Dash app.

Copied verbatim from competitive-shelf-intelligence/app/db.py.
ThreadedConnectionPool keyed by PID, DEC2FLOAT adapter, 30s statement
timeout, get_conn() context manager.
"""

from __future__ import annotations

import os
from contextlib import contextmanager

import psycopg2
import psycopg2.extensions
import psycopg2.pool

DEC2FLOAT = psycopg2.extensions.new_type(
    psycopg2.extensions.DECIMAL.values,
    "DEC2FLOAT",
    lambda value, curs: float(value) if value is not None else None,
)


def _register_dec2float() -> None:
    psycopg2.extensions.register_type(DEC2FLOAT)


_pools: dict[int, psycopg2.pool.ThreadedConnectionPool] = {}


def get_pool() -> psycopg2.pool.ThreadedConnectionPool:
    pid = os.getpid()
    pool = _pools.get(pid)
    if pool is None:
        _register_dec2float()
        url = os.environ.get("DATABASE_URL")
        if not url:
            raise RuntimeError("DATABASE_URL is not set.")
        pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=1,
            maxconn=10,
            dsn=url,
            # production_demand_forecast first: the snapshot tables are read
            # unqualified, so they resolve in this repo's schema after the U19a
            # move and in copack before it (the code may deploy before or after
            # the owner runs the move).
            options=("-c statement_timeout=90000 "
                     "-c search_path=production_demand_forecast,copack,raw,public"),
            connect_timeout=5,
        )
        _pools[pid] = pool
    return pool


@contextmanager
def get_conn():
    pool = get_pool()
    conn = pool.getconn()
    conn.autocommit = True
    try:
        yield conn
    finally:
        pool.putconn(conn)
