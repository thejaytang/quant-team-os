"""Coverage for secret patterns added in the security-hardening round and the
JWKS TTL cache."""

import pytest

from app.core import auth
from app.core.redaction import contains_secret, redact_secrets


@pytest.mark.parametrize(
    "secret",
    [
        "AIzaSyA1234567890abcdefghijklmnopqrstuvw",  # Google API key
        "sk_live_0123456789abcdefABCDEF",  # Stripe secret key
        "rk_test_0123456789abcdefABCDEF",  # Stripe restricted key
        "github_pat_11ABCDEFG0abcdefghij_KLMNOPqrstuvwxyz0123456789",  # GitHub fine-grained PAT
        "gho_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345",  # GitHub OAuth token
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U",  # JWT
        "-----BEGIN RSA PRIVATE KEY-----",  # PEM header
        "-----BEGIN PRIVATE KEY-----",  # PKCS8 PEM header
    ],
)
def test_new_patterns_are_detected_and_redacted(secret):
    text = f"leaked value = {secret} end"
    assert contains_secret(text) is True
    redacted = redact_secrets(text)
    assert secret not in redacted
    assert "[REDACTED_SECRET]" in redacted


def test_non_secret_text_is_untouched():
    text = "the quick brown fox jumps over 12345 lazy dogs"
    assert contains_secret(text) is False
    assert redact_secrets(text) == text


def test_jwks_cache_hits_within_ttl(monkeypatch):
    auth.clear_jwks_cache()
    calls = {"n": 0}

    class _Resp:
        def json(self):
            return {"keys": ["k"]}

    def fake_get(url, timeout):
        calls["n"] += 1
        return _Resp()

    monkeypatch.setattr(auth.httpx, "get", fake_get)

    first = auth._jwks()
    second = auth._jwks()
    assert first == second == {"keys": ["k"]}
    assert calls["n"] == 1  # second call served from cache

    auth.clear_jwks_cache()
    auth._jwks()
    assert calls["n"] == 2  # cache cleared -> refetch


def test_jwks_serves_stale_cache_when_provider_unreachable(monkeypatch):
    auth.clear_jwks_cache()

    class _Resp:
        def json(self):
            return {"keys": ["good"]}

    monkeypatch.setattr(auth.httpx, "get", lambda url, timeout: _Resp())
    auth._jwks()

    # Expire the cached entry, then make the provider fail.
    url = next(iter(auth._jwks_cache))
    ts, keys = auth._jwks_cache[url]
    auth._jwks_cache[url] = (ts - auth._JWKS_TTL_SECONDS - 1, keys)

    def boom(url, timeout):
        raise RuntimeError("network down")

    monkeypatch.setattr(auth.httpx, "get", boom)
    assert auth._jwks() == {"keys": ["good"]}  # stale served, auth not broken


def test_jwks_raises_503_when_unreachable_and_no_cache(monkeypatch):
    auth.clear_jwks_cache()

    def boom(url, timeout):
        raise RuntimeError("network down")

    monkeypatch.setattr(auth.httpx, "get", boom)
    with pytest.raises(auth.HTTPException) as exc:
        auth._jwks()
    assert exc.value.status_code == 503
