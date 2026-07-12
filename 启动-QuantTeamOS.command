#!/bin/zsh
set -u

PROJECT_DIR="/Users/tang/Documents/2-探索项目/各种AI玩具/量化"
APP_URL="http://127.0.0.1:5173/dashboard"
API_URL="http://127.0.0.1:8000/healthz"
CHROME_APP="/Applications/Google Chrome.app"
LOG_DIR="$HOME/Library/Logs/Quant Team OS"
CONTROL_UI_DIR="$PROJECT_DIR/apps/control-ui"

# The project's own .venv lives inside iCloud Drive and, after the folder was
# moved, macOS loads its native extensions extremely slowly (per-file Gatekeeper
# validation + iCloud reads), so the API took many minutes to start. Run the API
# instead from a small dedicated venv on the local disk, created once. Keeping it
# under Application Support keeps it out of iCloud so imports are fast.
QTO_SUPPORT="$HOME/Library/Application Support/QuantTeamOS"
LOCAL_VENV="$QTO_SUPPORT/venv"
VENV_PY="$LOCAL_VENV/bin/python"
API_REQS="fastapi uvicorn[standard] pydantic pydantic-settings sqlalchemy httpx pyyaml python-jose[cryptography] prometheus-client pandas pyarrow duckdb"

export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export PYTHONPATH="$PROJECT_DIR:$PROJECT_DIR/apps/api:${PYTHONPATH:-}"
NPM_BIN="$(command -v npm 2>/dev/null || true)"

port_listening() {
  /usr/sbin/lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1
}

# Kill any process still holding a port (e.g. a stale server left over from a
# previous project location that now serves 404s). Try a graceful TERM first,
# then force with KILL if it is still bound.
free_port() {
  local pids
  pids="$(/usr/sbin/lsof -ti tcp:"$1" -sTCP:LISTEN 2>/dev/null)"
  if [ -n "$pids" ]; then
    kill $pids 2>/dev/null
    /bin/sleep 1
    pids="$(/usr/sbin/lsof -ti tcp:"$1" -sTCP:LISTEN 2>/dev/null)"
    [ -n "$pids" ] && kill -9 $pids 2>/dev/null
  fi
}

http_ok() {
  /usr/bin/curl -fsS --max-time 1 "$1" >/dev/null 2>&1
}

# Create the local API venv on first run, or repair it if the packages are not
# fully installed. Judged by whether uvicorn actually imports, so a half-built
# venv from an interrupted run gets finished rather than skipped. All setup
# output is captured so failures are diagnosable.
bootstrap_local_venv() {
  if [ -x "$VENV_PY" ] && "$VENV_PY" -c "import uvicorn" >/dev/null 2>&1; then
    return 0
  fi
  local base="/opt/anaconda3/bin/python3"
  [ -x "$base" ] || base="$(command -v python3 || true)"
  [ -n "$base" ] || return 1
  echo "First run: creating local API environment (this can take a couple of minutes)..."
  {
    [ -x "$VENV_PY" ] || "$base" -m venv "$LOCAL_VENV"
    "$VENV_PY" -m pip install --upgrade pip
    # zsh does not word-split unquoted parameters, so ${=API_REQS} forces the
    # requirement list to expand into separate arguments for pip.
    "$VENV_PY" -m pip install ${=API_REQS}
  } > "$LOG_DIR/api-setup.log" 2>&1
  "$VENV_PY" -c "import uvicorn" >/dev/null 2>&1
}

mkdir -p "$LOG_DIR" "$QTO_SUPPORT"
cd "$PROJECT_DIR" || exit 1
mkdir -p "$PROJECT_DIR/data" "$PROJECT_DIR/artifacts"

export QTO_SETTINGS_ENV_FILE=""
# Keep the launcher database on the local disk (not iCloud) so SQLite file locks
# during startup do not stall.
export DATABASE_URL="sqlite:///$QTO_SUPPORT/launcher.db"
export ARTIFACT_ROOT="$PROJECT_DIR/artifacts"
export ALLOW_LOCAL_SECRET_FALLBACK=true
export ALLOW_TEMPORAL_FALLBACK=true
export ALLOW_LOCAL_POLICY_FALLBACK=true
export ALLOW_LOCAL_AUTH_FALLBACK=true
export ALLOW_AGENT_FALLBACK=true
export ALLOW_MATURE_TOOL_FALLBACK=true
export ENABLE_MINIO_UPLOAD=false
export ALLOW_LIVE_TRADING=false

# Start the API only if it is not already answering health checks. If the port
# is held by an unhealthy/stale process, reclaim it before starting fresh.
if ! http_ok "$API_URL"; then
  # Kill any stale/slow API process from an earlier attempt, then reclaim the port.
  /usr/bin/pkill -f "uvicorn app.main:app" 2>/dev/null
  free_port 8000
  bootstrap_local_venv
  if [ -x "$VENV_PY" ]; then
    PYTHONUNBUFFERED=1 /usr/bin/nohup "$VENV_PY" -m uvicorn app.main:app --app-dir "$PROJECT_DIR/apps/api" --host 127.0.0.1 --port 8000 > "$LOG_DIR/api.log" 2>&1 &
  fi
fi

# Start the control UI only if /dashboard is not already served. A stale server
# from a previous project location returns 404 here, so reclaim the port first.
if ! http_ok "$APP_URL"; then
  free_port 5173
  if [ -n "$NPM_BIN" ] && [ -x "$NPM_BIN" ]; then
    VITE_API_URL="http://127.0.0.1:8000" /usr/bin/nohup "$NPM_BIN" --prefix "$CONTROL_UI_DIR" run dev -- --host 127.0.0.1 --port 5173 > "$LOG_DIR/control-ui.log" 2>&1 &
  fi
fi

for _ in {1..50}; do
  { /usr/bin/curl -fsS --max-time 1 "$APP_URL" >/dev/null 2>&1 && /usr/bin/curl -fsS --max-time 1 "$API_URL" >/dev/null 2>&1; } && break
  /bin/sleep 0.4
done

if [ "${QTO_START_ONLY:-false}" = "true" ]; then
  exit 0
fi

if [ -d "$CHROME_APP" ]; then
  /usr/bin/open -a "$CHROME_APP" "$APP_URL"
else
  /usr/bin/open -a "Google Chrome" "$APP_URL" >/dev/null 2>&1 || /usr/bin/open "$APP_URL"
fi
