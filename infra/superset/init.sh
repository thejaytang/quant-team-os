#!/bin/sh
set -eu

superset db upgrade
superset fab create-admin \
  --username "${SUPERSET_ADMIN_USERNAME:-admin}" \
  --firstname Quant \
  --lastname Admin \
  --email "${SUPERSET_ADMIN_EMAIL:-admin@example.com}" \
  --password "${SUPERSET_ADMIN_PASSWORD:-admin}" || true
superset init

python /app/qto-superset/seed_dashboard.py
superset export-dashboards -f /tmp/strategy_backtest_aggregate.zip

superset import-dashboards \
  -p /tmp/strategy_backtest_aggregate.zip \
  -u "${SUPERSET_ADMIN_USERNAME:-admin}"
