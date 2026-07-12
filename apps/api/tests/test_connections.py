from app.db.models import AuditLog, ExternalConnection, WorkflowLink
from app.services.connections import connect_provider, list_connections, seed_connections, validate_provider_connection


def test_seed_connections_creates_locked_ibkr(db):
    seed_connections(db)
    ibkr = db.query(ExternalConnection).filter_by(provider="ibkr").one()
    assert ibkr.status == "locked"
    assert "live_trade_locked" in ibkr.permissions
    assert ibkr.meta["capabilities"]["connectable"] is False
    assert ibkr.meta["capabilities"]["read_holdings"] is False
    assert ibkr.meta["capabilities"]["paper_trade"] is True
    assert ibkr.meta["capabilities"]["live_trade"] == "locked"


def test_seed_connections_covers_v03_provider_list(db):
    providers = {item["provider"] for item in list_connections(db)}
    assert {
        "openai",
        "massive",
        "quantconnect",
        "openbb",
        "mlflow",
        "langfuse",
        "superset",
        "grafana",
        "temporal",
        "jupyterlab",
        "infisical",
        "keycloak",
        "minio",
        "chainlit",
        "ibkr",
    }.issubset(providers)


def test_seed_connections_uses_browser_ui_urls(db):
    connections = {item["provider"]: item for item in list_connections(db)}

    assert connections["openbb"]["metadata"]["open_ui_url"] == "https://pro.openbb.co"
    assert connections["langfuse"]["metadata"]["open_ui_url"] == "http://localhost:3002"
    assert connections["infisical"]["metadata"]["open_ui_url"] == "http://localhost:8082"


def test_public_connection_includes_provider_specific_fields(db):
    connections = {item["provider"]: item for item in list_connections(db)}
    fields = {field["name"]: field for field in connections["quantconnect"]["metadata"]["credential_fields"]}

    assert fields["user_id"]["required"] is True
    assert fields["user_id"]["secret"] is False
    assert fields["api_token"]["required"] is True
    assert fields["api_token"]["secret"] is True


def test_public_connection_includes_provider_capabilities(db):
    connections = {item["provider"]: item for item in list_connections(db)}

    quantconnect = connections["quantconnect"]["metadata"]["capabilities"]
    assert quantconnect["connectable"] is True
    assert quantconnect["read_holdings"] is False
    assert quantconnect["paper_trade"] is True
    assert quantconnect["live_trade"] is False

    ibkr = connections["ibkr"]["metadata"]["capabilities"]
    assert ibkr["connectable"] is False
    assert ibkr["read_holdings"] is False
    assert ibkr["paper_trade"] is True
    assert ibkr["live_trade"] == "locked"


def test_connect_provider_rejects_unknown_fields(db):
    try:
        connect_provider(db, "openai", {"api_key": "sk-testsecret1234", "api_key_copy": "sk-testsecret5678"})
    except ValueError as exc:
        assert "unsupported credential fields for openai: api_key_copy" in str(exc)
    else:
        raise AssertionError("connect_provider should reject unknown credential fields")

    connection = db.query(ExternalConnection).filter_by(provider="openai").one()
    assert "api_key_copy" not in str(connection.meta)


def test_connection_test_failure_writes_audit(db):
    seed_connections(db)
    result = validate_provider_connection(db, "massive")
    db.commit()
    assert result["ok"] is False
    assert "missing required fields" in result["error"]
    assert result["workflow_id"].startswith("ConnectionTestWorkflow-")
    assert db.query(AuditLog).filter_by(action="connection.test_failed").count() == 1
    assert db.query(WorkflowLink).filter_by(workflow_type="ConnectionTestWorkflow").count() == 1


def test_connect_quantconnect_masks_token(db):
    public = connect_provider(db, "quantconnect", {"user_id": "u1", "api_token": "token-abcdef1234"})
    assert public["status"] == "connected"
    assert "token-abcdef1234" not in str(public)
    assert public["metadata"]["last_test_workflow_id"].startswith("ConnectionTestWorkflow-")


def test_connect_ibkr_keeps_live_locked_capabilities(db):
    public = connect_provider(db, "ibkr", {})
    assert public["status"] == "locked"
    assert public["metadata"]["capabilities"]["connectable"] is False
    assert public["metadata"]["capabilities"]["read_holdings"] is False
    assert public["metadata"]["capabilities"]["live_trade"] == "locked"


def test_connection_audit_payload_has_provider(db):
    connect_provider(db, "mlflow", {"tracking_uri": "http://localhost:5000"})
    db.commit()
    log = db.query(AuditLog).filter_by(action="connection.connected").one()
    assert log.payload["provider"] == "mlflow"
