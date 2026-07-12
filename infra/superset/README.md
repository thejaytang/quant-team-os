# Superset starter assets

This directory keeps the Quant Team OS starter BI spec for Superset.

`dashboards/strategy_backtest_aggregate.json` is the source spec for the MVP
dashboard. `seed_dashboard.py` uses the same aggregate shape to create the
Superset database, virtual dataset, charts, and dashboard inside the metadata DB.

The `superset-init` compose service initializes Superset metadata and creates a
local admin user. It then seeds `Strategy and Backtest Aggregate`, exports it
with `superset export-dashboards`, and immediately imports that native zip with
`superset import-dashboards` so the startup path exercises the real Superset
import format.
