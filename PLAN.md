# production-demand-forecast — Current Work Plan

The current arc of work. Updated when the arc changes, not every
session. For session-by-session state, see HANDOFF.md.

---

## Goal

Build and deploy a Fly.io web app that corrects Cinderhaven's POS velocity for OOS periods, forecasts 12-week rolling demand by SKU, overlays co-packer capacity constraints, and surfaces per-SKU stockout dates + production decision deadlines with interactive scenario controls and a downloadable decision brief.

## Why this arc, why now

This is the full v1 build — the analytical core (OOS correction → forecast → capacity overlay → decision deadline) plus the interactive web interface. Everything else depends on this foundation being right.

## Business question this arc answers

Given current inventory, scheduled production, and true (OOS-corrected) projected demand, which SKUs will stock out, when, and what is the last date a production run can be ordered to prevent it?

## Stack

- **UI:** Python + Dash 3.x + Plotly + dash-ag-grid + dash-bootstrap-components (Lailara Design System via constants.py + charts.py)
- **Analytics:** `app/analytics/` package — OOS correction, rolling forecast (STL via statsmodels), capacity overlay
- **Database:** Cinderhaven Data Platform — existing synthetic Postgres SSOT + new co-packer schema (4 tables)
- **Deployment:** Fly.io (python:3.13-slim, gunicorn 3 workers, 2GB memory)
- **Export:** Excel via openpyxl, PDF via WeasyPrint + Jinja2

## Tasks

Work in vertical slices — one piece end-to-end before moving to the next.
Full plan: `docs/plans/2026-05-31-001-feat-production-demand-forecast-plan.md`

**Phase 1 — Foundation**
- [x] /clarify, /ce:brainstorm, /ce:plan — scope confirmed, requirements and plan written
- [x] Cinderhaven Postgres schema confirmed (scan_data, distribution_log, product_master, promotions)
- [x] U1: App scaffold — copy db.py, data.py, constants.py, charts.py, run.py from competitive-shelf-intelligence
- [x] U2: Co-packer schema — design + seed 4 tables in Cinderhaven Postgres SSOT

**Phase 2 — Analytics Core**
- [x] U3: OOS correction module (`app/analytics/oos_correction.py`)
- [x] U4: Rolling forecast module (`app/analytics/forecast.py`)
- [x] U5: Capacity overlay + decision deadline (`app/analytics/capacity.py`)

**Phase 3 — App Views**
- [x] U6: Data query layer (`app/data.py` — wraps analytics, caches via Flask-Caching)
- [x] U7: S&OP view tab — per-SKU table, red flags, conflict indicators
- [x] U8: Scenario controls tab — promo lift, retailer doors, lead-time slip
- [x] U9: Doom loop narrative tab — hero case chart (Artisan Sauce Feb OOS)

**Phase 4 — Export + Deployment**
- [x] U10: Excel export (.xlsx via openpyxl)
- [x] U11: PDF export (WeasyPrint, Jinja2 template)
- [x] U12: Fly.io deployment (Dockerfile, fly.toml)

## Out of scope for this arc

- Deep co-packer capacity optimization (that's #22, Co-Packer/Production Capacity Model)
- Automated production ordering
- Ingredient/raw material planning (MRP)
- Exotic forecasting methods (ML, neural nets)
- Multi-co-packer routing (v2)

## Definition of done for this arc

- [x] App deployed and live on Fly.io (https://cinderhaven-demand-forecast.fly.dev/)
- [x] Cinderhaven Artisan Sauce SKU shows the February OOS event — true demand corrects above observed velocity
- [x] Per-SKU S&OP view renders with stockout date and decision deadline
- [x] At least one SKU flags red (decision deadline < 14 days)
- [x] Scenario controls update deadlines in real time without page reload
- [x] Export downloads a usable decision brief
- [x] Doom loop narrative is present and legible to a non-data-science reader

---

## Arc history

### 2026-05-31 — Project initialized
- Outcome: Repo scaffolded, brief reviewed, state files created
- Tag: v0.1-foundation

---

## Improvement history

<!-- Entries are added by /improve — don't delete this section -->

### 2026-06-01 — Improvement pass
- **Trigger:** User-initiated, just after v1.0 launch
- **What was reviewed:** Security (ce-security-sentinel), correctness (ce-correctness-reviewer), workflow files, code quality, tests, dependencies, documentation, git hygiene
- **What was fixed:**
  - CRITICAL: `logger` NameError in `sop_view.py` — crashed PDF export callback on Windows
  - CRITICAL: New-doors scenario added demand to `insufficient_data` SKUs (missing guard, same as promo-lift guard)
  - CRITICAL: OOS rolling median included promo weeks in neighbor selection, inflating corrections near promotions
  - IMPORTANT: Detail panel called `get_forecast()` with no scenario params — runway chart diverged from table during active scenarios
  - IMPORTANT: Running inventory clamped display but not `current` variable — post-stockout production arrivals silently absorbed into deficit
  - IMPORTANT: `%-d` strftime format fails on Windows — Stockout/Decision By columns showed raw ISO dates in dev
  - IMPORTANT: `hero_svg` template slot lacked `| safe` — SVG was entity-encoded; documented trust boundary in comment
  - IMPORTANT: `get_scan_data` used f-string interpolation for WHERE clause — refactored to two static SQL strings
  - IMPORTANT: CSP header missing from `run.py` security middleware
  - IMPORTANT: CLAUDE.md Stack section had stale "TBD" placeholders from scaffold
  - IMPORTANT: `src/CLAUDE.md` with wrong guidance deleted (code lives in `app/`, not `src/`)
  - NICE TO HAVE: `/cache` directory mode set to 700 in Dockerfile
  - NICE TO HAVE: `FLASK_SECRET_KEY` missing now logs a warning instead of silently using per-process random
  - NICE TO HAVE: O(n²) OOS correction loop — pre-compute position lookups and neighbor_positions once outside the OOS loop
  - NICE TO HAVE: WeasyPrint CVE-2025-68616 — upgraded pin from `>=61.0,<62.0` to `>=68.0,<69.0`
  - NICE TO HAVE: `portfolio_project_brief_...md` moved from root to `docs/`
- **Deferred:** Stockout off-by-one interpretation (domain question — stockout week vs. last in-stock week), all-promo-neighbor edge case in OOS correction (rare, added fallback to all non-OOS)
- **Next review:** 2026-07-01

### 2026-09-23 — Audit (health check only)
- **Findings:** 0 critical, 7 important, 5 nice-to-have
- **Top concerns:** The analytics layer fails open — any exception in `capacity.py` marks every SKU "OK", so a bug looks like a healthy plan — and the Fly deploy workflow is not gated on the golden/client-mode tests. The README quick start omits `db/precompute_forecast.py`, which the default snapshot mode needs, and the live new-doors scenario uses one global per-door velocity while snapshot mode uses per-SKU velocity. HANDOFF.md stops at 2026-07-13 despite 27 later commits, and this review was due 2026-07-01.
- **Action taken:** Audit only — no fixes this session
- **Next review:** 2026-10-21
