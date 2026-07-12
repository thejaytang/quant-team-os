import sys
import types
from datetime import date

from app.core.config import get_settings
from app.db.models import BacktestRun, DatasetSpec
from app.services.artifacts import create_artifact
from app.services.mlflow_tracking import log_backtest_run_to_mlflow


def test_log_backtest_run_to_mlflow_uses_sdk(tmp_path, monkeypatch, db):
    monkeypatch.setenv("ARTIFACT_ROOT", str(tmp_path))
    monkeypatch.setenv("MLFLOW_TRACKING_URI", "http://mlflow:5000")
    monkeypatch.setenv("GIT_COMMIT", "git-sha-test")
    get_settings.cache_clear()
    calls = []

    class FakeRun:
        info = types.SimpleNamespace(run_id="run-123")

        def __enter__(self):
            calls.append(("start_enter",))
            return self

        def __exit__(self, exc_type, exc, tb):
            calls.append(("start_exit",))

    fake_mlflow = types.SimpleNamespace(
        set_tracking_uri=lambda uri: calls.append(("set_tracking_uri", uri)),
        start_run=lambda run_name: (calls.append(("start_run", run_name)) or FakeRun()),
        log_params=lambda params: calls.append(("log_params", params)),
        log_metrics=lambda metrics: calls.append(("log_metrics", metrics)),
        log_artifact=lambda path, artifact_path=None: calls.append(("log_artifact", path, artifact_path)),
    )
    monkeypatch.setitem(__import__("sys").modules, "mlflow", fake_mlflow)

    dataset = DatasetSpec(name="ds", dataset_version="dlt:massive:test", dvc_rev="abc123")
    db.add(dataset)
    db.flush()
    backtest = BacktestRun(
        strategy_id="s1",
        dataset_spec_id=dataset.id,
        dataset_version=dataset.dataset_version,
        start_date=date(2020, 1, 1),
        end_date=date(2025, 1, 1),
        metrics={"sharpe": 1.2},
    )
    db.add(backtest)
    db.flush()
    artifact = create_artifact(db, "backtest_metrics", "backtest", backtest.id, "backtests/b1/metrics.json", "{}", "application/json")

    result = log_backtest_run_to_mlflow(db, backtest, {"dataset_version": dataset.dataset_version, "workflow_id": "wf-1", "dvc_rev": dataset.dvc_rev}, {"sharpe": 1.2}, [artifact])

    assert result == {"mlflow_run_id": "run-123", "mode": "mlflow", "error": None}
    assert backtest.mlflow_run_id == "run-123"
    assert artifact.mlflow_run_id == "run-123"
    assert ("set_tracking_uri", "http://mlflow:5000") in calls
    params = next(call[1] for call in calls if call[0] == "log_params")
    assert params["strategy_id"] == "s1"
    assert params["dataset_spec_id"] == dataset.id
    assert params["dataset_version"] == "dlt:massive:test"
    assert params["workflow_id"] == "wf-1"
    assert params["dvc_rev"] == "abc123"
    assert params["git_commit"] == "git-sha-test"
    assert any(call[0] == "log_metrics" and call[1]["sharpe"] == 1.2 for call in calls)
    assert any(call[0] == "log_artifact" for call in calls)
    get_settings.cache_clear()


def test_log_backtest_run_to_mlflow_rejects_local_mirror_when_mature_fallback_disabled(tmp_path, monkeypatch, db):
    monkeypatch.setenv("ARTIFACT_ROOT", str(tmp_path))
    monkeypatch.setenv("ALLOW_MATURE_TOOL_FALLBACK", "false")
    get_settings.cache_clear()

    dataset = DatasetSpec(name="ds", dataset_version="dlt:massive:test", dvc_rev="abc123")
    db.add(dataset)
    db.flush()
    backtest = BacktestRun(
        strategy_id="s1",
        dataset_spec_id=dataset.id,
        dataset_version=dataset.dataset_version,
        start_date=date(2020, 1, 1),
        end_date=date(2025, 1, 1),
        metrics={"sharpe": 1.2},
    )
    db.add(backtest)
    db.flush()

    fake_mlflow = types.SimpleNamespace(
        set_tracking_uri=lambda uri: None,
        start_run=lambda run_name: (_ for _ in ()).throw(RuntimeError("mlflow unavailable")),
    )
    monkeypatch.setitem(sys.modules, "mlflow", fake_mlflow)

    try:
        log_backtest_run_to_mlflow(db, backtest, {"dataset_version": dataset.dataset_version}, {"sharpe": 1.2}, [])
    except RuntimeError as exc:
        assert "mlflow unavailable" in str(exc)
    else:
        raise AssertionError("strict mature tool mode must reject MLflow local_mirror")
    finally:
        get_settings.cache_clear()
