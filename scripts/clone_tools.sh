#!/bin/sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
DEST="$ROOT/vendor"
mkdir -p "$DEST"

clone_one() {
  name="$1"
  repo="$2"
  if [ -d "$DEST/$name/.git" ]; then
    echo "$name already cloned"
    return
  fi
  git clone --depth=1 --filter=blob:none "$repo" "$DEST/$name"
}

clone_one openai-agents-python https://github.com/openai/openai-agents-python.git
clone_one temporal https://github.com/temporalio/temporal.git
clone_one temporal-sdk-python https://github.com/temporalio/sdk-python.git
clone_one opa https://github.com/open-policy-agent/opa.git
clone_one infisical https://github.com/Infisical/infisical.git
clone_one keycloak https://github.com/keycloak/keycloak.git
clone_one refine https://github.com/refinedev/refine.git
clone_one ant-design https://github.com/ant-design/ant-design.git
clone_one chainlit https://github.com/Chainlit/chainlit.git
clone_one openbb-backends https://github.com/OpenBB-finance/backends-for-openbb.git
clone_one superset https://github.com/apache/superset.git
clone_one grafana https://github.com/grafana/grafana.git
clone_one prometheus https://github.com/prometheus/prometheus.git
clone_one loki https://github.com/grafana/loki.git
clone_one opentelemetry-collector https://github.com/open-telemetry/opentelemetry-collector.git
clone_one langfuse https://github.com/langfuse/langfuse.git
clone_one minio https://github.com/minio/minio.git
clone_one dlt https://github.com/dlt-hub/dlt.git
clone_one great-expectations https://github.com/great-expectations/great_expectations.git
clone_one dvc https://github.com/treeverse/dvc.git
clone_one jupyterlab https://github.com/jupyterlab/jupyterlab.git
clone_one mlflow https://github.com/mlflow/mlflow.git
clone_one qlib https://github.com/microsoft/qlib.git
clone_one rd-agent https://github.com/microsoft/RD-Agent.git
clone_one quantconnect-lean https://github.com/QuantConnect/Lean.git
clone_one quantconnect-mcp-server https://github.com/QuantConnect/mcp-server.git
clone_one massive-mcp https://github.com/massive-com/mcp_massive.git
clone_one alphalens-reloaded https://github.com/stefan-jansen/alphalens-reloaded.git
clone_one quantstats https://github.com/ranaroussi/quantstats.git
clone_one pyportfolioopt https://github.com/PyPortfolio/PyPortfolioOpt.git
clone_one duckdb https://github.com/duckdb/duckdb.git
