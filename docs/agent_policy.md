# Agent Policy

- Agents use provider credentials only through **Infisical** secret refs resolved by the backend **ToolGateway**.
- Agents may reference `OPENAI_MODEL`, but they cannot receive or inspect provider API key values.
- Agents cannot read secrets.
- Agents cannot call external SDKs directly.
- Every tool call goes through `AdapterRunner`.
- Every tool call writes `tool_calls` and `audit_logs`.
- Agent commentary is advisory. **OPA** policy decisions and `ApprovalRecord` control state changes.
- Live trading is locked in MVP.
