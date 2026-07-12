from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-static-fallback", action="store_true", help="allow string-level policy contract checks when opa CLI is unavailable")
    args = parser.parse_args()
    opa = shutil.which("opa")
    if opa:
        subprocess.run([opa, "test", "policy/opa", "policy/tests"], cwd=ROOT, check=True)
        print("opa policy tests passed")
        return
    if not args.allow_static_fallback:
        raise SystemExit("opa policy gate failed: opa CLI not installed; pass --allow-static-fallback for local static contract checks")
    _static_contract_gate()
    print("opa policy static gate passed (opa CLI not installed)")


def _static_contract_gate() -> None:
    test_text = (ROOT / "policy/tests/qto_policy_test.rego").read_text(encoding="utf-8")
    expected_tests = [
        "test_live_trading_denied_when_locked",
        "test_agent_cannot_approve",
        "test_connector_denies_disconnected_status",
        "test_connector_denies_secret_payload",
        "test_strategy_registration_requires_human_approval",
        "test_paper_promotion_requires_latest_risk_pass",
        "test_strategy_promotion_requires_cost_model",
        "test_chainlit_cannot_directly_mutate_strategy_state",
        "test_openbb_workspace_is_read_only",
        "test_grafana_workspace_is_read_only",
    ]
    expected_denials = {
        "policy/opa/trading_lock.rego": ["live trading is locked"],
        "policy/opa/agent.rego": ["agent cannot approve or reject approvals"],
        "policy/opa/connector.rego": ["connector is not connected", "secret must not be present in tool payload"],
        "policy/opa/strategy_lifecycle.rego": [
            "human approval is required",
            "latest risk review must pass",
            "cost model is required",
            "slippage model is required",
        ],
        "policy/opa/ui_surface.rego": [
            "Chainlit cannot directly mutate core state",
            "external workspace is read-only for core state",
        ],
    }

    failures: list[str] = [f"missing OPA policy test: {name}" for name in expected_tests if name not in test_text]
    for relative_path, denials in expected_denials.items():
        text = (ROOT / relative_path).read_text(encoding="utf-8")
        failures.extend(f"{relative_path} missing denial: {denial}" for denial in denials if denial not in text)

    if failures:
        raise SystemExit("opa policy gate failed:\n" + "\n".join(f"- {failure}" for failure in failures))


if __name__ == "__main__":
    main()
