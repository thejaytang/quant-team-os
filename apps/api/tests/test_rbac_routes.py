import os
from inspect import signature

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app.api.compat import HTTPException
from app.api.routes_agent_runs import create_agent_run
from app.api.routes_approvals import approve
from app.api.routes_audit import list_audit_logs
from app.api.routes_data_quality import run_sample_ohlcv_pipeline
from app.api.routes_factors import analyze_factor
from app.api.routes_research import start_agent_workflow
from app.api.routes_risk import create_risk_review, list_risk_policy_decisions
from app.core import auth as auth_module
from app.core.auth import CurrentUser, get_current_user, require_any_role, require_role
from app.core.config import get_settings
from app.db.models import ApprovalRecord
from app.schemas import ApprovalResolveRequest
from app.services.approval_service import create_approval_request


def route_dependency(fn, name="_user"):
    dependency = signature(fn).parameters[name].default
    return getattr(dependency, "dependency", dependency)


def test_researcher_cannot_pass_approver_dependency():
    dependency = require_role("approver")
    with pytest.raises(HTTPException) as exc:
        dependency(CurrentUser(sub="u1", username="alice", roles={"researcher"}))
    assert exc.value.status_code == 403


def test_viewer_cannot_pass_write_dependency():
    dependency = require_any_role("researcher", "admin")
    with pytest.raises(HTTPException) as exc:
        dependency(CurrentUser(sub="u1", username="viewer", roles={"viewer"}))
    assert exc.value.status_code == 403


def test_start_agent_workflow_alias_keeps_write_rbac_dependency():
    dependency = route_dependency(start_agent_workflow)

    with pytest.raises(HTTPException):
        dependency(CurrentUser(sub="u1", username="viewer", roles={"viewer"}))
    assert dependency(CurrentUser(sub="u2", username="researcher", roles={"researcher"})).username == "researcher"


def test_audit_routes_reject_viewer_dependency():
    dependency = route_dependency(list_audit_logs)

    with pytest.raises(HTTPException):
        dependency(CurrentUser(sub="viewer-1", username="viewer", roles={"viewer"}))
    assert dependency(CurrentUser(sub="risk-1", username="risk", roles={"risk_reviewer"})).username == "risk"


def test_risk_write_and_policy_decisions_reject_viewer_dependency():
    create_dependency = route_dependency(create_risk_review)
    policy_dependency = route_dependency(list_risk_policy_decisions)

    for dependency in [create_dependency, policy_dependency]:
        with pytest.raises(HTTPException):
            dependency(CurrentUser(sub="viewer-1", username="viewer", roles={"viewer"}))
        assert dependency(CurrentUser(sub="risk-1", username="risk", roles={"risk_reviewer"})).username == "risk"


def test_agent_run_create_rejects_viewer_dependency():
    dependency = route_dependency(create_agent_run)

    with pytest.raises(HTTPException):
        dependency(CurrentUser(sub="viewer-1", username="viewer", roles={"viewer"}))
    assert dependency(CurrentUser(sub="researcher-1", username="researcher", roles={"researcher"})).username == "researcher"


def test_factor_analyze_alias_rejects_viewer_dependency():
    dependency = route_dependency(analyze_factor)

    with pytest.raises(HTTPException):
        dependency(CurrentUser(sub="viewer-1", username="viewer", roles={"viewer"}))
    assert dependency(CurrentUser(sub="researcher-1", username="researcher", roles={"researcher"})).username == "researcher"


def test_sample_ohlcv_pipeline_rejects_viewer_dependency():
    dependency = route_dependency(run_sample_ohlcv_pipeline)

    with pytest.raises(HTTPException):
        dependency(CurrentUser(sub="viewer-1", username="viewer", roles={"viewer"}))
    assert dependency(CurrentUser(sub="researcher-1", username="researcher", roles={"researcher"})).username == "researcher"


def test_approver_actor_comes_from_auth_user(db):
    request = create_approval_request(db, "memo_review", "strategy", "s1", "ChiefAgent", {})
    result = approve(
        request.id,
        ApprovalResolveRequest(human_comment="reviewed", human_actor="spoof"),
        db=db,
        user=CurrentUser(sub="u2", username="bob", roles={"approver"}),
    )
    assert result.human_comment == "reviewed"
    record = db.query(ApprovalRecord).one()
    assert record.human_actor == "bob"


def test_production_requires_keycloak_token(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    get_settings.cache_clear()
    with pytest.raises(HTTPException) as exc:
        get_current_user(credentials=None)
    assert exc.value.status_code == 401
    get_settings.cache_clear()


def test_development_can_disable_local_auth_fallback(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("ALLOW_LOCAL_AUTH_FALLBACK", "false")
    get_settings.cache_clear()
    with pytest.raises(HTTPException) as exc:
        get_current_user(credentials=None)
    assert exc.value.status_code == 401
    get_settings.cache_clear()


def test_jwks_uses_configured_internal_url(monkeypatch):
    class Response:
        def json(self):
            return {"keys": []}

    seen = {}

    def fake_get(url, timeout):
        seen["url"] = url
        seen["timeout"] = timeout
        return Response()

    monkeypatch.setenv("KEYCLOAK_JWKS_URL", "http://keycloak:8080/realms/quant-team-os/protocol/openid-connect/certs")
    monkeypatch.setattr(auth_module.httpx, "get", fake_get)
    get_settings.cache_clear()
    assert auth_module._jwks() == {"keys": []}
    assert seen == {
        "url": "http://keycloak:8080/realms/quant-team-os/protocol/openid-connect/certs",
        "timeout": 2,
    }
    get_settings.cache_clear()


def test_keycloak_token_accepts_internal_issuer(monkeypatch):
    seen_issuers = []

    class Jwt:
        @staticmethod
        def decode(token, keys, algorithms, audience, issuer):
            seen_issuers.append(issuer)
            if issuer == "http://keycloak:8080/realms/quant-team-os":
                return {"sub": "svc-1", "client_id": "openbb-backend", "realm_access": {"roles": ["service_account"]}}
            raise RuntimeError("issuer mismatch")

    credentials = type("Credentials", (), {"credentials": "token"})()
    monkeypatch.setenv("KEYCLOAK_BASE_URL", "http://localhost:8080")
    monkeypatch.setenv("KEYCLOAK_INTERNAL_BASE_URL", "http://keycloak:8080")
    monkeypatch.setattr(auth_module, "jwt", Jwt)
    monkeypatch.setattr(auth_module, "_jwks", lambda: {"keys": []})
    get_settings.cache_clear()

    user = get_current_user(credentials=credentials)

    assert user.username == "openbb-backend"
    assert user.service_account is True
    assert seen_issuers == [
        "http://localhost:8080/realms/quant-team-os",
        "http://keycloak:8080/realms/quant-team-os",
    ]
    get_settings.cache_clear()
