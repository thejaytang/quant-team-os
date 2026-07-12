import re
from typing import Any

SECRET_KEYS = {
    "api_key",
    "api_token",
    "access_token",
    "refresh_token",
    "client_secret",
    "secret_key",
    "private_key",
    "token",
    "secret",
    "password",
    "credential",
    "credentials",
    "authorization",
}
SECRET_KEY_TERMS = {
    "api_key",
    "api_token",
    "access_token",
    "refresh_token",
    "client_secret",
    "secret_key",
    "private_key",
    "auth_token",
    "bearer_token",
}
SECRET_KEY_SEGMENTS = {"secret", "password"}
SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{12,}"),  # OpenAI / Anthropic (sk-ant-...)
    re.compile(r"gh[opsu]_[A-Za-z0-9_]{20,}"),  # GitHub personal/OAuth/server/user tokens
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),  # GitHub fine-grained PAT
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{20,}"),  # Slack
    re.compile(r"AKIA[0-9A-Z]{16}"),  # AWS access key id
    re.compile(r"AIza[0-9A-Za-z_\-]{35}"),  # Google API key
    re.compile(r"(?i)\b[sr]k_(live|test)_[0-9a-zA-Z]{16,}"),  # Stripe secret/restricted keys
    re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{6,}"),  # JWT / JWS
    re.compile(r"-----BEGIN(?: [A-Z0-9]+)? PRIVATE KEY-----"),  # PEM private key block
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{12,}"),
    re.compile(
        r"(?i)(api[_-]?key|api[_-]?token|access[_-]?token|refresh[_-]?token|client[_-]?secret|secret[_-]?key|private[_-]?key|password|authorization)\s*[:=]\s*['\"]?[^,'\"\s}]+"
    ),
]


def mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "****"
    return f"{value[:3]}-****{value[-4:]}" if value.startswith("sk-") else f"****{value[-4:]}"


def redact_secrets(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            if is_secret_key(key):
                redacted[key] = mask_secret(str(item))
            else:
                redacted[key] = redact_secrets(item)
        return redacted
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    if isinstance(value, str):
        redacted = value
        for pattern in SECRET_PATTERNS:
            redacted = pattern.sub("[REDACTED_SECRET]", redacted)
        return redacted
    return value


def is_secret_key(key: object) -> bool:
    normalized = str(key).lower().replace("-", "_")
    if is_secret_ref_key(normalized):
        return False
    parts = set(normalized.split("_"))
    return (
        normalized in SECRET_KEYS
        or any(term in normalized for term in SECRET_KEY_TERMS)
        or bool(parts & SECRET_KEY_SEGMENTS)
        or normalized.endswith("_token")
    )


def is_secret_ref_key(key: object) -> bool:
    normalized = str(key).lower().replace("-", "_")
    return normalized in {"secret_ref", "secret_refs"} or normalized.endswith(("_secret_ref", "_secret_refs"))


def _is_masked(value: Any) -> bool:
    if value in (None, ""):
        return True
    if isinstance(value, str):
        return value == "[REDACTED_SECRET]" or "****" in value
    return False


def contains_secret(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if is_secret_ref_key(key):
                continue
            if is_secret_key(key) and not _is_masked(item):
                return True
            if contains_secret(item):
                return True
        return False
    if isinstance(value, list):
        return any(contains_secret(item) for item in value)
    if isinstance(value, str):
        return any(pattern.search(value) for pattern in SECRET_PATTERNS)
    return False
