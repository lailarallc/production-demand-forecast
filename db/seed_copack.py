"""Seed co-packer schema and synthetic data into Cinderhaven Postgres.

Idempotent — runs DDL (CREATE TABLE IF NOT EXISTS) then inserts with
ON CONFLICT DO NOTHING.  Safe to run multiple times.

Usage:
    python db/seed_copack.py

Requires DATABASE_URL in environment (or .env in project root).
"""

from __future__ import annotations

import os
import pathlib
import sys

from dotenv import load_dotenv

load_dotenv(pathlib.Path(__file__).resolve().parent.parent / ".env")

import prod_guard
import psycopg2

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    sys.exit("ERROR: DATABASE_URL is not set.")

# ---------------------------------------------------------------
# Reference data — keyed on the demo scenario date 2025-11-01.
# Week N = the Monday N weeks after 2025-11-03 (first Monday after
# the demo reference date of 2025-11-01).
# ---------------------------------------------------------------

CO_PACKERS = [
    ("COPACK-001", "Midwest Production Partners, LLC", "Racine, WI",
     "Single co-packer for all Cinderhaven product lines in v1"),
]

PRODUCTION_LINES = [
    # Line A: Artisan Sauces + top 5 Specialty Condiments (SHARED)
    # Shared line is the source of the conflict story.
    ("LINE-A", "COPACK-001", "Line A — Wet/Sauce",
     "Artisan Sauces; Specialty Condiments (top 5)",
     "Shared line. Artisan Sauces top 5 SKUs and Condiments top 5 SKUs "
     "compete for the same production window."),

    # Line B: remaining Condiments + all Pantry (DEDICATED)
    ("LINE-B", "COPACK-001", "Line B — Condiments/Dry",
     "Specialty Condiments (remaining); Pantry Staples",
     "Dedicated line. No shared-line conflicts in v1."),
]

# lead_time_weeks, min_run_cases per product line
LINE_A_SAUCE_LEAD    = 10
LINE_A_SAUCE_MIN     = 500
LINE_A_CONDIMENT_LEAD = 8
LINE_A_CONDIMENT_MIN  = 300
LINE_B_CONDIMENT_LEAD = 8
LINE_B_CONDIMENT_MIN  = 300
LINE_B_PANTRY_LEAD    = 12
LINE_B_PANTRY_MIN     = 400
LINE_B_DRY_LEAD       = 10
LINE_B_DRY_MIN        = 350
LINE_B_SNACK_LEAD     = 8
LINE_B_SNACK_MIN      = 300

# All 50 SKUs — (sku, line_id, lead_time_weeks, min_run_cases, notes)
# Actual Cinderhaven SKU format: CHP-{line}-{NNN}
# Product lines: AS=Artisan Sauces, SC=Specialty Condiments,
#                PS=Pantry Staples, DG=Dried Goods, SB=Snack Bites
SKU_PRODUCTION_CONFIG = [
    # --- Artisan Sauces (CHP-AS-001 to CHP-AS-010) → Line A ---
    ("CHP-AS-001", "LINE-A", LINE_A_SAUCE_LEAD, LINE_A_SAUCE_MIN,
     "Top-selling sauce. February 2025 OOS event. Hero demo SKU."),
    ("CHP-AS-002", "LINE-A", LINE_A_SAUCE_LEAD, LINE_A_SAUCE_MIN, None),
    ("CHP-AS-003", "LINE-A", LINE_A_SAUCE_LEAD, LINE_A_SAUCE_MIN, None),
    ("CHP-AS-004", "LINE-A", LINE_A_SAUCE_LEAD, LINE_A_SAUCE_MIN, None),
    ("CHP-AS-005", "LINE-A", LINE_A_SAUCE_LEAD, LINE_A_SAUCE_MIN, None),
    ("CHP-AS-006", "LINE-A", LINE_A_SAUCE_LEAD, LINE_A_SAUCE_MIN, None),
    ("CHP-AS-007", "LINE-A", LINE_A_SAUCE_LEAD, LINE_A_SAUCE_MIN, None),
    ("CHP-AS-008", "LINE-A", LINE_A_SAUCE_LEAD, LINE_A_SAUCE_MIN, None),
    ("CHP-AS-009", "LINE-A", LINE_A_SAUCE_LEAD, LINE_A_SAUCE_MIN, None),
    ("CHP-AS-010", "LINE-A", LINE_A_SAUCE_LEAD, LINE_A_SAUCE_MIN, None),

    # --- Specialty Condiments top 5 (CHP-SC-001 to CHP-SC-005) → Line A (shared) ---
    ("CHP-SC-001", "LINE-A", LINE_A_CONDIMENT_LEAD, LINE_A_CONDIMENT_MIN,
     "Shares Line A with Artisan Sauces. Conflict demo SKU."),
    ("CHP-SC-002", "LINE-A", LINE_A_CONDIMENT_LEAD, LINE_A_CONDIMENT_MIN, None),
    ("CHP-SC-003", "LINE-A", LINE_A_CONDIMENT_LEAD, LINE_A_CONDIMENT_MIN, None),
    ("CHP-SC-004", "LINE-A", LINE_A_CONDIMENT_LEAD, LINE_A_CONDIMENT_MIN, None),
    ("CHP-SC-005", "LINE-A", LINE_A_CONDIMENT_LEAD, LINE_A_CONDIMENT_MIN, None),

    # --- Specialty Condiments remaining (CHP-SC-006 to CHP-SC-010) → Line B ---
    ("CHP-SC-006", "LINE-B", LINE_B_CONDIMENT_LEAD, LINE_B_CONDIMENT_MIN, None),
    ("CHP-SC-007", "LINE-B", LINE_B_CONDIMENT_LEAD, LINE_B_CONDIMENT_MIN, None),
    ("CHP-SC-008", "LINE-B", LINE_B_CONDIMENT_LEAD, LINE_B_CONDIMENT_MIN, None),
    ("CHP-SC-009", "LINE-B", LINE_B_CONDIMENT_LEAD, LINE_B_CONDIMENT_MIN, None),
    ("CHP-SC-010", "LINE-B", LINE_B_CONDIMENT_LEAD, LINE_B_CONDIMENT_MIN, None),

    # --- Dried Goods (CHP-DG-001 to CHP-DG-010) → Line B ---
    ("CHP-DG-001", "LINE-B", LINE_B_DRY_LEAD, LINE_B_DRY_MIN, None),
    ("CHP-DG-002", "LINE-B", LINE_B_DRY_LEAD, LINE_B_DRY_MIN, None),
    ("CHP-DG-003", "LINE-B", LINE_B_DRY_LEAD, LINE_B_DRY_MIN, None),
    ("CHP-DG-004", "LINE-B", LINE_B_DRY_LEAD, LINE_B_DRY_MIN, None),
    ("CHP-DG-005", "LINE-B", LINE_B_DRY_LEAD, LINE_B_DRY_MIN, None),
    ("CHP-DG-006", "LINE-B", LINE_B_DRY_LEAD, LINE_B_DRY_MIN, None),
    ("CHP-DG-007", "LINE-B", LINE_B_DRY_LEAD, LINE_B_DRY_MIN, None),
    ("CHP-DG-008", "LINE-B", LINE_B_DRY_LEAD, LINE_B_DRY_MIN, None),
    ("CHP-DG-009", "LINE-B", LINE_B_DRY_LEAD, LINE_B_DRY_MIN, None),
    ("CHP-DG-010", "LINE-B", LINE_B_DRY_LEAD, LINE_B_DRY_MIN, None),

    # --- Pantry Staples (CHP-PS-001 to CHP-PS-010) → Line B ---
    ("CHP-PS-001", "LINE-B", LINE_B_PANTRY_LEAD, LINE_B_PANTRY_MIN, None),
    ("CHP-PS-002", "LINE-B", LINE_B_PANTRY_LEAD, LINE_B_PANTRY_MIN, None),
    ("CHP-PS-003", "LINE-B", LINE_B_PANTRY_LEAD, LINE_B_PANTRY_MIN, None),
    ("CHP-PS-004", "LINE-B", LINE_B_PANTRY_LEAD, LINE_B_PANTRY_MIN, None),
    ("CHP-PS-005", "LINE-B", LINE_B_PANTRY_LEAD, LINE_B_PANTRY_MIN, None),
    ("CHP-PS-006", "LINE-B", LINE_B_PANTRY_LEAD, LINE_B_PANTRY_MIN, None),
    ("CHP-PS-007", "LINE-B", LINE_B_PANTRY_LEAD, LINE_B_PANTRY_MIN, None),
    ("CHP-PS-008", "LINE-B", LINE_B_PANTRY_LEAD, LINE_B_PANTRY_MIN, None),
    ("CHP-PS-009", "LINE-B", LINE_B_PANTRY_LEAD, LINE_B_PANTRY_MIN, None),
    ("CHP-PS-010", "LINE-B", LINE_B_PANTRY_LEAD, LINE_B_PANTRY_MIN, None),

    # --- Snack Bites (CHP-SB-001 to CHP-SB-010) → Line B ---
    ("CHP-SB-001", "LINE-B", LINE_B_SNACK_LEAD, LINE_B_SNACK_MIN, None),
    ("CHP-SB-002", "LINE-B", LINE_B_SNACK_LEAD, LINE_B_SNACK_MIN, None),
    ("CHP-SB-003", "LINE-B", LINE_B_SNACK_LEAD, LINE_B_SNACK_MIN, None),
    ("CHP-SB-004", "LINE-B", LINE_B_SNACK_LEAD, LINE_B_SNACK_MIN, None),
    ("CHP-SB-005", "LINE-B", LINE_B_SNACK_LEAD, LINE_B_SNACK_MIN, None),
    ("CHP-SB-006", "LINE-B", LINE_B_SNACK_LEAD, LINE_B_SNACK_MIN, None),
    ("CHP-SB-007", "LINE-B", LINE_B_SNACK_LEAD, LINE_B_SNACK_MIN, None),
    ("CHP-SB-008", "LINE-B", LINE_B_SNACK_LEAD, LINE_B_SNACK_MIN, None),
    ("CHP-SB-009", "LINE-B", LINE_B_SNACK_LEAD, LINE_B_SNACK_MIN, None),
    ("CHP-SB-010", "LINE-B", LINE_B_SNACK_LEAD, LINE_B_SNACK_MIN, None),
]

# Production schedule — booked runs, consistent with the calibrated inventory.
# Reference date: 2025-11-01. In-horizon replenishment runs go to healthy SKUs
# (they do not rescue an at-risk SKU's stockout); a cluster of late runs on
# 2026-02-07 represents the "next available co-packer slot" arriving AFTER the
# at-risk SKU has already stocked out — the core S&OP tension the tool surfaces.
# (run_id, sku, line_id, scheduled_week, quantity_cases, status)
PRODUCTION_SCHEDULE = [
    ('RUN-001', 'CHP-AS-002', 'LINE-A', '2025-11-15', 500, 'booked'),
    ('RUN-002', 'CHP-AS-008', 'LINE-A', '2025-11-22', 500, 'booked'),
    ('RUN-003', 'CHP-DG-001', 'LINE-B', '2025-11-29', 350, 'booked'),
    ('RUN-004', 'CHP-DG-005', 'LINE-B', '2025-12-06', 350, 'booked'),
    ('RUN-005', 'CHP-DG-008', 'LINE-B', '2025-12-13', 350, 'booked'),
    ('RUN-006', 'CHP-PS-001', 'LINE-B', '2025-12-20', 400, 'booked'),
    ('RUN-007', 'CHP-PS-005', 'LINE-B', '2025-12-27', 400, 'booked'),
    ('RUN-008', 'CHP-PS-007', 'LINE-B', '2026-01-03', 400, 'booked'),
    ('RUN-009', 'CHP-PS-010', 'LINE-B', '2025-11-15', 400, 'booked'),
    ('RUN-010', 'CHP-SC-003', 'LINE-A', '2025-11-22', 300, 'booked'),
    ('RUN-011', 'CHP-SC-006', 'LINE-B', '2025-11-29', 300, 'booked'),
    ('RUN-012', 'CHP-SC-009', 'LINE-B', '2025-12-06', 300, 'booked'),
    # Late runs — next co-packer slot lands after these SKUs stock out:
    ('RUN-013', 'CHP-AS-001', 'LINE-A', '2026-02-07', 500, 'booked'),
    ('RUN-014', 'CHP-SC-001', 'LINE-A', '2026-02-07', 300, 'booked'),
    ('RUN-015', 'CHP-PS-004', 'LINE-B', '2026-02-07', 400, 'booked'),
    ('RUN-016', 'CHP-DG-007', 'LINE-B', '2026-02-07', 350, 'booked'),
]

# Current on-hand inventory as of 2025-11-01, in cases.
# CALIBRATED against actual OOS-corrected forecast (78-week window) so the
# S&OP grid shows a differentiated urgency distribution rather than a uniform
# wall of PAST_DUE. Each SKU's on_hand_cases is sized so it stocks out at a
# target week (or survives the 12-week horizon = "healthy"); combined with the
# per-line lead times (SB/SC=8, AS/DG=10, PS=12) this yields, at baseline:
#   ~15 healthy (OK), ~9 WARNING, ~12 CRITICAL, ~14 PAST_DUE.
# The "stocks out ~week N" note is the design intent verified by the analytics.
# To recalibrate after a demand-data change, re-run db/_calibrate.py.
SKU_INVENTORY = [
    # --- Artisan Sauces ---
    ('CHP-AS-001', "2025-11-01", 1604, 'stocks out ~week 5'),
    ('CHP-AS-002', "2025-11-01", 4916, 'healthy'),
    ('CHP-AS-003', "2025-11-01", 278, 'stocks out ~week 11'),
    ('CHP-AS-004', "2025-11-01", 333, 'stocks out ~week 7'),
    ('CHP-AS-005', "2025-11-01", 1006, 'stocks out ~week 12'),
    ('CHP-AS-006', "2025-11-01", 8865, 'stocks out ~week 10'),
    ('CHP-AS-007', "2025-11-01", 479, 'stocks out ~week 8'),
    ('CHP-AS-008', "2025-11-01", 190, 'healthy'),
    ('CHP-AS-009', "2025-11-01", 1421, 'stocks out ~week 11'),
    ('CHP-AS-010', "2025-11-01", 184, 'stocks out ~week 6'),
    # --- Specialty Condiments ---
    ('CHP-SC-001', "2025-11-01", 3290, 'stocks out ~week 8'),
    ('CHP-SC-002', "2025-11-01", 488, 'stocks out ~week 10'),
    ('CHP-SC-003', "2025-11-01", 388, 'healthy'),
    ('CHP-SC-004', "2025-11-01", 1346, 'stocks out ~week 11'),
    ('CHP-SC-005', "2025-11-01", 275, 'stocks out ~week 9'),
    ('CHP-SC-006', "2025-11-01", 159, 'healthy'),
    ('CHP-SC-007', "2025-11-01", 213, 'stocks out ~week 10'),
    ('CHP-SC-008', "2025-11-01", 1037, 'stocks out ~week 5'),
    ('CHP-SC-009', "2025-11-01", 1083, 'healthy'),
    ('CHP-SC-010', "2025-11-01", 568, 'stocks out ~week 11'),
    # --- Dried Goods ---
    ('CHP-DG-001', "2025-11-01", 1972, 'healthy'),
    ('CHP-DG-002', "2025-11-01", 1303, 'stocks out ~week 10'),
    ('CHP-DG-003', "2025-11-01", 420, 'stocks out ~week 9'),
    ('CHP-DG-004', "2025-11-01", 295, 'stocks out ~week 12'),
    ('CHP-DG-005', "2025-11-01", 734, 'healthy'),
    ('CHP-DG-006', "2025-11-01", 80, 'stocks out ~week 11'),
    ('CHP-DG-007', "2025-11-01", 1637, 'stocks out ~week 4'),
    ('CHP-DG-008', "2025-11-01", 812, 'healthy'),
    ('CHP-DG-009', "2025-11-01", 248, 'stocks out ~week 10'),
    ('CHP-DG-010', "2025-11-01", 889, 'stocks out ~week 7'),
    # --- Pantry Staples ---
    ('CHP-PS-001', "2025-11-01", 729, 'healthy'),
    ('CHP-PS-002', "2025-11-01", 8580, 'stocks out ~week 10'),
    ('CHP-PS-003', "2025-11-01", 687, 'stocks out ~week 12'),
    ('CHP-PS-004', "2025-11-01", 550, 'stocks out ~week 6'),
    ('CHP-PS-005', "2025-11-01", 422, 'healthy'),
    ('CHP-PS-006', "2025-11-01", 244, 'stocks out ~week 11'),
    ('CHP-PS-007', "2025-11-01", 879, 'healthy'),
    ('CHP-PS-008', "2025-11-01", 276, 'stocks out ~week 12'),
    ('CHP-PS-009', "2025-11-01", 4316, 'stocks out ~week 8'),
    ('CHP-PS-010', "2025-11-01", 1248, 'healthy'),
    # --- Snack Bites ---
    ('CHP-SB-001', "2025-11-01", 3563, 'healthy'),
    ('CHP-SB-002', "2025-11-01", 492, 'stocks out ~week 9'),
    ('CHP-SB-003', "2025-11-01", 1635, 'stocks out ~week 10'),
    ('CHP-SB-004', "2025-11-01", 98, 'stocks out ~week 6'),
    ('CHP-SB-005', "2025-11-01", 533, 'healthy'),
    ('CHP-SB-006', "2025-11-01", 2405, 'stocks out ~week 8'),
    ('CHP-SB-007', "2025-11-01", 289, 'stocks out ~week 11'),
    ('CHP-SB-008', "2025-11-01", 581, 'stocks out ~week 7'),
    ('CHP-SB-009', "2025-11-01", 84, 'healthy'),
    ('CHP-SB-010', "2025-11-01", 690, 'stocks out ~week 10'),
]


import re as _re

def _run_ddl(cur, schema_path: pathlib.Path) -> None:
    ddl = schema_path.read_text(encoding="utf-8")
    # Strip line comments before splitting so semicolons inside comments don't confuse the split
    ddl_no_comments = _re.sub(r"--[^\n]*", "", ddl)
    for statement in ddl_no_comments.split(";"):
        if statement.strip():
            cur.execute(statement.strip())


def seed(conn) -> None:
    cur = conn.cursor()
    schema_path = pathlib.Path(__file__).parent / "schema_copack.sql"
    _run_ddl(cur, schema_path)
    print("DDL applied.")

    cur.executemany(
        """
        INSERT INTO co_packers (co_packer_id, name, location, notes)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (co_packer_id) DO NOTHING
        """,
        CO_PACKERS,
    )
    print(f"  co_packers: {cur.rowcount} inserted")

    cur.executemany(
        """
        INSERT INTO production_lines (line_id, co_packer_id, line_name, product_line_affinity, notes)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (line_id) DO NOTHING
        """,
        PRODUCTION_LINES,
    )
    print(f"  production_lines: {cur.rowcount} inserted")

    cur.executemany(
        """
        INSERT INTO sku_production_config (sku, line_id, lead_time_weeks, min_run_cases, notes)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (sku) DO NOTHING
        """,
        SKU_PRODUCTION_CONFIG,
    )
    print(f"  sku_production_config: {cur.rowcount} inserted")

    cur.executemany(
        """
        INSERT INTO production_schedule (run_id, sku, line_id, scheduled_week, quantity_cases, status)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (run_id) DO NOTHING
        """,
        PRODUCTION_SCHEDULE,
    )
    print(f"  production_schedule: {cur.rowcount} inserted")

    cur.executemany(
        """
        INSERT INTO sku_inventory (sku, as_of_date, on_hand_cases, notes)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (sku) DO NOTHING
        """,
        SKU_INVENTORY,
    )
    print(f"  sku_inventory: {cur.rowcount} inserted")

    conn.commit()
    print("Seed complete.")


def verify(conn) -> None:
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM sku_production_config")
    n = cur.fetchone()[0]
    assert n == 50, f"Expected 50 rows in sku_production_config, got {n}"

    cur.execute("SELECT COUNT(*) FROM production_schedule")
    n = cur.fetchone()[0]
    assert n == len(PRODUCTION_SCHEDULE), \
        f"Expected {len(PRODUCTION_SCHEDULE)} rows in production_schedule, got {n}"

    cur.execute("SELECT COUNT(*) FROM sku_inventory")
    n = cur.fetchone()[0]
    assert n == 50, f"Expected 50 rows in sku_inventory, got {n}"

    # Every product_master SKU must have exactly one sku_production_config row
    cur.execute("""
        SELECT COUNT(*)
        FROM product_master p
        LEFT JOIN sku_production_config c ON c.sku = p.sku
        WHERE c.sku IS NULL
    """)
    missing = cur.fetchone()[0]
    assert missing == 0, f"{missing} product_master SKUs have no sku_production_config row"

    # CHP-AS-001 should have exactly one production_schedule row (week 4 run)
    cur.execute("SELECT COUNT(*) FROM production_schedule WHERE sku = 'CHP-AS-001'")
    runs = cur.fetchone()[0]
    assert runs == 1, f"Expected 1 production run for CHP-AS-001, got {runs}"

    # At least two Line-A SKUs should share a scheduled_week (overlap → conflict candidate)
    cur.execute("""
        SELECT COUNT(*)
        FROM (
            SELECT scheduled_week, COUNT(DISTINCT sku) AS sku_count
            FROM production_schedule
            WHERE line_id = 'LINE-A'
            GROUP BY scheduled_week
            HAVING COUNT(DISTINCT sku) >= 2
        ) t
    """)
    conflict_weeks = cur.fetchone()[0]
    assert conflict_weeks >= 1, "Expected at least one week with 2+ Line-A SKUs scheduled"

    print("Verification passed.")


if __name__ == "__main__":
    prod_guard.check(DATABASE_URL)  # refuses a fly tunnel to production
    conn = psycopg2.connect(DATABASE_URL, options="-c search_path=copack,raw,public")
    conn.autocommit = False
    try:
        cur = conn.cursor()
        cur.execute("CREATE SCHEMA IF NOT EXISTS copack")
        conn.commit()
        seed(conn)
        verify(conn)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
