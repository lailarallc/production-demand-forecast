"""Pre-compute forecast snapshots to database tables.

Runs the full S&OP pipeline once and writes results to:
  copack.forecast_snapshot  — one row per SKU (S&OP summary)
  copack.doom_loop_snapshot — one row per (SKU, week) (OOS aggregates)
  copack.snapshot_meta      — generation metadata

The script uses the same analytics functions from app/analytics/ — no
duplicated logic. Import and call them directly.

Usage:
    python db/precompute_forecast.py

Requires DATABASE_URL in environment (or .env in project root).
"""

from __future__ import annotations

import logging
import os
import pathlib
import sys

_project_root = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))

from dotenv import load_dotenv

load_dotenv(_project_root / ".env")

import pandas as pd
import prod_guard
import psycopg2

from app.analytics.capacity import (
    compute_decision_deadline,
    compute_stockout_date,
    detect_shared_line_conflicts,
)
from app.analytics.forecast import build_rolling_forecast
from app.analytics.oos_correction import correct_velocity, detect_oos_periods

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    sys.exit("ERROR: DATABASE_URL is not set.")

_DEMO_AS_OF_DATE = "2025-11-01"
_HISTORY_WEEKS = 78
_AGGREGATE_STORES = frozenset({"UNFI-AGG", "KEHE-AGG", "DTC-AGG"})

# ---------------------------------------------------------------
# DDL — idempotent, copack schema (survives raw schema reseeds)
# ---------------------------------------------------------------

_DDL = """\
CREATE TABLE IF NOT EXISTS copack.forecast_snapshot (
    sku TEXT PRIMARY KEY,
    product_name TEXT,
    product_line TEXT,
    weekly_forecast_mean REAL,
    current_inventory REAL,
    stockout_date DATE,
    decision_deadline DATE,
    days_until_deadline INTEGER,
    deadline_flag TEXT,
    lead_time_weeks INTEGER,
    shared_line_conflict BOOLEAN,
    conflict_skus TEXT,
    median_store_velocity REAL,
    snapshot_generated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS copack.forecast_week_snapshot (
    sku TEXT,
    week_ending DATE,
    forecast_units REAL,
    snapshot_generated_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (sku, week_ending)
);

CREATE TABLE IF NOT EXISTS copack.doom_loop_snapshot (
    sku TEXT,
    week_ending DATE,
    observed_units REAL,
    corrected_units REAL,
    stores_dark INTEGER,
    weekly_hidden_units REAL,
    cumulative_hidden_units REAL,
    snapshot_generated_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (sku, week_ending)
);

CREATE TABLE IF NOT EXISTS copack.snapshot_meta (
    id SERIAL PRIMARY KEY,
    as_of_date DATE,
    generated_at TIMESTAMPTZ DEFAULT NOW(),
    sku_count INTEGER,
    status TEXT DEFAULT 'complete'
);
"""


# ---------------------------------------------------------------
# Data queries (standalone — no Flask app context needed)
# ---------------------------------------------------------------

def _query_df(conn, sql, params=None):
    cur = conn.cursor()
    cur.execute(sql, params or {})
    cols = [desc[0] for desc in cur.description]
    return pd.DataFrame(cur.fetchall(), columns=cols)


def _get_scan_data(conn):
    history_start = str(
        (pd.Timestamp(_DEMO_AS_OF_DATE) - pd.Timedelta(weeks=_HISTORY_WEEKS)).date()
    )
    return _query_df(conn, """
        WITH promo_flag AS (
            SELECT DISTINCT sub.sku, sub.week_ending
            FROM (
                SELECT DISTINCT sku, week_ending
                FROM scan_data
                WHERE week_ending <= %(as_of)s
                  AND week_ending >  %(history_start)s
            ) sub
            JOIN promotions p
                ON p.sku = sub.sku
                AND sub.week_ending BETWEEN p.start_week AND p.end_week
        )
        SELECT
            s.sku, s.store_id, s.week_ending, s.units_sold,
            CASE
                WHEN d.sku IS NOT NULL
                     AND d.authorized_date  <= s.week_ending
                     AND (d.deauthorized_date IS NULL
                          OR d.deauthorized_date > s.week_ending)
                THEN TRUE ELSE FALSE
            END AS is_authorized,
            CASE WHEN pf.sku IS NOT NULL THEN TRUE ELSE FALSE
            END AS is_promo
        FROM scan_data s
        LEFT JOIN distribution_log d
            ON d.sku = s.sku AND d.store_id = s.store_id
        LEFT JOIN promo_flag pf
            ON pf.sku = s.sku AND pf.week_ending = s.week_ending
        WHERE s.week_ending <= %(as_of)s
          AND s.week_ending >  %(history_start)s
        ORDER BY s.sku, s.store_id, s.week_ending
    """, {"as_of": _DEMO_AS_OF_DATE, "history_start": history_start})


def _get_inventory(conn):
    return _query_df(conn, """
        SELECT i.sku, i.on_hand_cases * pm.case_pack_qty AS on_hand_units
        FROM sku_inventory i
        JOIN product_master pm ON pm.sku = i.sku
        ORDER BY i.sku
    """)


def _get_schedule(conn):
    return _query_df(conn, """
        SELECT ps.sku, ps.line_id, ps.scheduled_week,
               ps.quantity_cases * pm.case_pack_qty AS quantity_units,
               ps.status
        FROM production_schedule ps
        JOIN product_master pm ON pm.sku = ps.sku
        WHERE ps.status = 'booked'
        ORDER BY ps.scheduled_week, ps.sku
    """)


def _get_sku_config(conn):
    return _query_df(conn, """
        SELECT c.sku, c.line_id, c.lead_time_weeks, c.min_run_cases,
               pm.product_name, pm.product_line, pm.case_pack_qty
        FROM sku_production_config c
        JOIN product_master pm ON pm.sku = c.sku
        ORDER BY c.sku
    """)


# ---------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------

def _to_date(val):
    if val is None:
        return None
    try:
        if pd.isna(val):
            return None
        return pd.Timestamp(val).date()
    except Exception:
        return None


# ---------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------

def run(conn):
    logger.info("Loading scan data...")
    scan = _get_scan_data(conn)
    logger.info("  %d rows", len(scan))

    logger.info("Running OOS correction...")
    with_oos = detect_oos_periods(scan)
    true_demand = correct_velocity(with_oos)
    logger.info("  %d rows after correction", len(true_demand))

    logger.info("Building baseline forecast...")
    forecast_from = str(pd.to_datetime(true_demand["week_ending"]).max().date())
    forecast = build_rolling_forecast(true_demand, forecast_from_week=forecast_from)
    logger.info("  %d forecast rows", len(forecast))

    # Per-week projected series (the STL seasonal shape) — persisted so the
    # snapshot-mode app draws the seasonal forecast, not a flat mean line.
    forecast_weeks = forecast[forecast["is_projected"]].copy()
    forecast_weeks["week_ending"] = pd.to_datetime(forecast_weeks["week_ending"])
    logger.info("  %d projected forecast-week rows", len(forecast_weeks))

    logger.info("Loading reference data...")
    inventory = _get_inventory(conn)
    schedule = _get_schedule(conn)
    sku_config = _get_sku_config(conn)

    logger.info("Computing stockout dates...")
    sop = compute_stockout_date(forecast, inventory, schedule)

    logger.info("Computing decision deadlines...")
    sop = compute_decision_deadline(
        sop, sku_config, as_of_date=pd.Timestamp(_DEMO_AS_OF_DATE)
    )

    logger.info("Detecting shared-line conflicts...")
    sop = detect_shared_line_conflicts(sop, sku_config)

    meta = sku_config[["sku", "product_name", "product_line", "lead_time_weeks"]].copy()
    sop = sop.merge(meta, on="sku", how="left")

    # Median per-store velocity for new-doors scenario math
    physical = true_demand[~true_demand["store_id"].isin(_AGGREGATE_STORES)]
    store_weekly = physical.groupby(["sku", "store_id"])["true_demand"].mean()
    median_vel = store_weekly.groupby(level="sku").median().rename("median_store_velocity")
    sop = sop.merge(median_vel, on="sku", how="left")
    sop["median_store_velocity"] = sop["median_store_velocity"].fillna(0.0)

    logger.info("  %d SKUs in S&OP summary", len(sop))

    # ── Doom loop: weekly aggregates per SKU ─────────────────────
    logger.info("Building doom loop snapshot...")
    td = true_demand.copy()
    td["week_ending"] = pd.to_datetime(td["week_ending"])

    wk = td.groupby(["sku", "week_ending"]).agg(
        observed_units=("units_sold", "sum"),
        corrected_units=("true_demand", "sum"),
        stores_dark=("is_oos", "sum"),
    )
    weekly_hidden = (
        td[td["is_oos"]]
        .groupby(["sku", "week_ending"])["true_demand"]
        .sum()
        .rename("weekly_hidden_units")
    )
    wk = wk.join(weekly_hidden, how="left")
    wk["weekly_hidden_units"] = wk["weekly_hidden_units"].fillna(0.0)
    wk = wk.reset_index().sort_values(["sku", "week_ending"])
    wk["cumulative_hidden_units"] = wk.groupby("sku")["weekly_hidden_units"].cumsum()

    logger.info("  %d doom-loop rows", len(wk))

    # ── Write to database ────────────────────────────────────────
    cur = conn.cursor()
    cur.execute(_DDL)

    cur.execute("TRUNCATE copack.forecast_snapshot")
    cur.execute("TRUNCATE copack.forecast_week_snapshot")
    cur.execute("TRUNCATE copack.doom_loop_snapshot")

    logger.info("Writing forecast_snapshot...")
    for _, row in sop.iterrows():
        conflict = row.get("conflict_skus")
        if isinstance(conflict, list):
            conflict = ",".join(conflict) if conflict else None

        cur.execute("""
            INSERT INTO copack.forecast_snapshot (
                sku, product_name, product_line, weekly_forecast_mean,
                current_inventory, stockout_date, decision_deadline,
                days_until_deadline, deadline_flag, lead_time_weeks,
                shared_line_conflict, conflict_skus, median_store_velocity
            ) VALUES (
                %(sku)s, %(name)s, %(line)s, %(fcst)s, %(inv)s,
                %(stockout)s, %(deadline)s, %(days)s, %(flag)s, %(lt)s,
                %(conflict)s, %(cskus)s, %(vel)s
            )
        """, {
            "sku": row["sku"],
            "name": row.get("product_name"),
            "line": row.get("product_line"),
            "fcst": float(row.get("weekly_forecast_mean", 0)),
            "inv": float(row.get("current_inventory", 0)),
            "stockout": _to_date(row.get("stockout_date")),
            "deadline": _to_date(row.get("decision_deadline")),
            "days": (int(row["days_until_deadline"])
                     if pd.notna(row.get("days_until_deadline")) else None),
            "flag": row.get("deadline_flag"),
            "lt": (int(row["lead_time_weeks"])
                   if pd.notna(row.get("lead_time_weeks")) else None),
            "conflict": bool(row.get("shared_line_conflict", False)),
            "cskus": conflict,
            "vel": float(row.get("median_store_velocity", 0)),
        })

    logger.info("Writing forecast_week_snapshot...")
    for _, row in forecast_weeks.iterrows():
        cur.execute("""
            INSERT INTO copack.forecast_week_snapshot (
                sku, week_ending, forecast_units
            ) VALUES (
                %(sku)s, %(we)s, %(fcst)s
            )
            ON CONFLICT (sku, week_ending) DO UPDATE
                SET forecast_units = EXCLUDED.forecast_units
        """, {
            "sku": row["sku"],
            "we": row["week_ending"].date(),
            "fcst": float(row["forecast_units"]),
        })

    logger.info("Writing doom_loop_snapshot...")
    for _, row in wk.iterrows():
        cur.execute("""
            INSERT INTO copack.doom_loop_snapshot (
                sku, week_ending, observed_units, corrected_units,
                stores_dark, weekly_hidden_units, cumulative_hidden_units
            ) VALUES (
                %(sku)s, %(we)s, %(obs)s, %(cor)s, %(dark)s, %(wh)s, %(ch)s
            )
        """, {
            "sku": row["sku"],
            "we": row["week_ending"].date(),
            "obs": float(row["observed_units"]),
            "cor": float(row["corrected_units"]),
            "dark": int(row["stores_dark"]),
            "wh": float(row["weekly_hidden_units"]),
            "ch": float(row["cumulative_hidden_units"]),
        })

    cur.execute("""
        INSERT INTO copack.snapshot_meta (as_of_date, sku_count, status)
        VALUES (%(as_of)s, %(count)s, 'complete')
    """, {"as_of": _DEMO_AS_OF_DATE, "count": len(sop)})

    conn.commit()
    logger.info("Snapshot complete — %d SKUs, %d doom-loop rows", len(sop), len(wk))


if __name__ == "__main__":
    prod_guard.check(DATABASE_URL)  # refuses a fly tunnel to production
    with psycopg2.connect(
        DATABASE_URL, options="-c search_path=copack,raw,public"
    ) as conn:
        run(conn)
