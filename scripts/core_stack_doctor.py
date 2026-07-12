"""Live health checks for the v0.4 core stack (infra/docker-compose.core.yml).

Checks only the services the core stack runs. For the full stack use
scripts/full_stack_doctor.py.

Usage:
    python3 scripts/core_stack_doctor.py --env .env
"""

from __future__ import annotations

import argparse
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        values[key.strip()] = value.strip()
    return values


def check_http(name: str, url: str, ok_statuses: tuple[int, ...] = (200,), allow_any_response: bool = False) -> str | None:
    request = urllib.request.Request(url, headers={"User-Agent": "qto-core-doctor"})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            if allow_any_response or response.status in ok_statuses:
                return None
            return f"{name}: unexpected status {response.status} from {url}"
    except urllib.error.HTTPError as exc:
        if allow_any_response and exc.code < 500:
            return None
        return f"{name}: HTTP {exc.code} from {url}"
    except Exception as exc:
        return f"{name}: {url} unreachable ({exc})"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", default=".env")
    args = parser.parse_args()
    env = load_env(ROOT / args.env)

    api_url = env.get("API_BASE_URL", "http://localhost:8000")
    checks = [
        ("api healthz", f"{api_url}/healthz", (200,), False),
        ("api docs", f"{api_url}/docs", (200,), False),
        ("keycloak realm", f"{env.get('KEYCLOAK_BASE_URL', 'http://localhost:8080')}/realms/{env.get('KEYCLOAK_REALM', 'quant-team-os')}", (200,), False),
        ("infisical status", f"{env.get('INFISICAL_UI_URL', 'http://localhost:8082')}/api/status", (200,), False),
        ("opa health", f"{env.get('OPA_PUBLIC_URL', 'http://localhost:8181')}/health", (200,), False),
        ("temporal ui", env.get("TEMPORAL_UI_URL", "http://localhost:8233"), (200,), True),
        ("minio ready", "http://localhost:9000/minio/health/ready", (200,), False),
        ("mlflow ui", env.get("MLFLOW_UI_URL", "http://localhost:5000"), (200,), True),
        ("control ui", env.get("CONTROL_UI_URL", "http://localhost:5173"), (200,), True),
    ]

    failures = [message for name, url, statuses, lenient in checks if (message := check_http(name, url, statuses, lenient))]

    if env.get("ALLOW_LIVE_TRADING", "false").lower() != "false":
        failures.append("ALLOW_LIVE_TRADING must stay false")

    if failures:
        print("core stack doctor failed:")
        for failure in failures:
            print(f"- {failure}")
        sys.exit(1)
    print("core stack doctor passed")


if __name__ == "__main__":
    main()
