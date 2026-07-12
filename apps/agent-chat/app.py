from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import quote

import httpx

API_URL = os.getenv("QTO_API_URL", "http://api:8000").rstrip("/")
APPROVAL_ROUTES = {
    "approve": "approve",
    "reject": "reject",
    "request_changes": "request-changes",
}
APPROVAL_STATUS = {
    "approve": "approved",
    "reject": "rejected",
    "request_changes": "changes_requested",
}


try:
    import chainlit as cl
except Exception:  # pragma: no cover - local test env may not install chainlit
    cl = None


def command_payload(text: str) -> dict[str, Any]:
    stripped = text.strip()
    command, _, argument = stripped.partition(" ")
    if command == "/workflow" and argument.strip():
        return {"action": "start_research_workflow", "research_idea_id": argument.strip()}
    if command == "/status":
        return {"action": "status"}
    if command == "/tools":
        return {"action": "tool_calls"}
    if command == "/approvals":
        status = argument.strip()
        payload: dict[str, Any] = {"action": "approvals"}
        if status:
            payload["status"] = status
        return payload
    if command in {"/approve", "/reject", "/request-changes"}:
        return approval_command_payload(command, argument)
    return {"action": "chat", "message": stripped}


def approval_command_payload(command: str, argument: str) -> dict[str, Any]:
    approval_id, _, comment = argument.strip().partition(" ")
    if not approval_id:
        return {"action": "chat", "message": command}
    resolution = command.removeprefix("/").replace("-", "_")
    if not comment.strip():
        return {"action": "approval_comment_required", "approval_id": approval_id, "resolution": resolution}
    return {
        "action": "resolve_approval",
        "approval_id": approval_id,
        "resolution": resolution,
        "human_comment": comment.strip(),
    }


def api_headers(token: str | None = None) -> dict[str, str]:
    token = token or os.getenv("QTO_API_TOKEN") or os.getenv("QTO_AUTH_TOKEN")
    return {"Authorization": f"Bearer {token}"} if token else {}


def oauth_configured() -> bool:
    return all(
        os.getenv(key)
        for key in [
            "OAUTH_GENERIC_CLIENT_ID",
            "OAUTH_GENERIC_CLIENT_SECRET",
            "OAUTH_GENERIC_AUTH_URL",
            "OAUTH_GENERIC_TOKEN_URL",
            "OAUTH_GENERIC_USER_INFO_URL",
            "OAUTH_GENERIC_SCOPES",
        ]
    )


def current_api_token() -> str | None:
    if cl is None:
        return None
    user = cl.user_session.get("user")
    metadata = getattr(user, "metadata", None) or {}
    return metadata.get("api_token")


def approval_endpoint(approval_id: str, resolution: str) -> str:
    return f"/api/v1/approvals/{quote(approval_id, safe='')}/{APPROVAL_ROUTES[resolution]}"


async def call_api(payload: dict[str, Any], token: str | None = None) -> dict[str, Any] | list[Any]:
    headers = api_headers(token)
    async with httpx.AsyncClient(timeout=5) as client:
        if payload["action"] == "start_research_workflow":
            response = await client.post(
                f"{API_URL}/api/v1/workflows/research",
                headers=headers,
                json={"research_idea_id": payload["research_idea_id"]},
            )
        elif payload["action"] == "status":
            response = await client.get(f"{API_URL}/api/v1/workflows", headers=headers)
        elif payload["action"] == "tool_calls":
            response = await client.get(f"{API_URL}/api/v1/tool-calls", headers=headers)
        elif payload["action"] == "approvals":
            response = await client.get(f"{API_URL}/api/v1/approvals", headers=headers)
        elif payload["action"] == "resolve_approval":
            response = await client.post(
                f"{API_URL}{approval_endpoint(payload['approval_id'], payload['resolution'])}",
                headers=headers,
                json={"human_comment": payload["human_comment"]},
            )
        else:
            response = await client.post(
                f"{API_URL}/api/v1/agent-runs",
                headers=headers,
                json={"task_type": "chat", "input_payload": payload},
            )
        response.raise_for_status()
        result = response.json()
        if payload["action"] == "chat" and isinstance(result, dict) and result.get("id"):
            events_response = await client.get(
                f"{API_URL}/api/v1/agent-runs/{quote(str(result['id']), safe='')}/events",
                headers=headers,
            )
            events_response.raise_for_status()
            result["_agent_steps"] = parse_sse_events(events_response.text)
        return result


def render_response(payload: dict[str, Any], result: dict[str, Any] | list[Any]) -> str:
    if payload["action"] == "start_research_workflow":
        return f"ResearchWorkflow started: `{result.get('workflow_id', 'unknown')}`"
    if payload["action"] == "status":
        count = len(result) if isinstance(result, list) else 0
        return f"Workflow count: {count}"
    if payload["action"] == "tool_calls":
        return render_tool_calls(result)
    if payload["action"] == "approvals":
        return render_approvals(result, status=payload.get("status"))
    if payload["action"] == "resolve_approval":
        status = (
            result.get("status", APPROVAL_STATUS.get(payload["resolution"], "resolved"))
            if isinstance(result, dict)
            else "resolved"
        )
        return f"Approval `{payload['approval_id']}` resolved through Approval API: `{status}`"
    if payload["action"] == "approval_comment_required":
        return f"Human comment is required. Use `/{payload['resolution'].replace('_', '-')} {payload['approval_id']} <comment>`."
    lines = [f"Agent run queued: `{result.get('id', 'unknown')}`"]
    steps = result.get("_agent_steps") if isinstance(result, dict) else None
    if steps:
        lines.append(render_agent_steps(steps))
    return "\n\n".join(lines)


def parse_sse_events(text: str) -> list[dict[str, str]]:
    events: list[dict[str, str]] = []
    for block in text.split("\n\n"):
        event_type = "message"
        data = ""
        for line in block.splitlines():
            if line.startswith("event:"):
                event_type = line.removeprefix("event:").strip()
            elif line.startswith("data:"):
                data = line.removeprefix("data:").strip()
        if data:
            events.append({"type": event_type, "data": data})
    return events


def render_agent_steps(steps: list[dict[str, str]], limit: int = 8) -> str:
    lines = ["### Agent steps"]
    for step in steps[:limit]:
        lines.append(f"- `{step.get('type', 'message')}` {step.get('data', '')}")
    if len(steps) > limit:
        lines.append(f"... {len(steps) - limit} more steps not shown")
    return "\n".join(lines)


def render_tool_calls(result: dict[str, Any] | list[Any], limit: int = 8) -> str:
    tool_calls = result if isinstance(result, list) else []
    if not tool_calls:
        return "No tool calls found."
    lines = ["### Tool calls"]
    for call in tool_calls[:limit]:
        call_id = call.get("id", "unknown")
        adapter = call.get("adapter_name", "unknown")
        tool_name = call.get("tool_name", "unknown")
        status = call.get("status", "unknown")
        risk = call.get("risk_level", "unknown")
        line = f"- `{call_id}` `{adapter}.{tool_name}` status=`{status}` risk=`{risk}`"
        if call.get("agent_run_id"):
            line += f" run=`{call['agent_run_id']}`"
        if call.get("error"):
            line += f" error=`{call['error']}`"
        lines.append(line)
        if call.get("output_payload"):
            lines.append(f"  output: `{compact_json(call['output_payload'])}`")
    if len(tool_calls) > limit:
        lines.append(f"... {len(tool_calls) - limit} more tool calls not shown")
    return "\n".join(lines)


def render_approvals(result: dict[str, Any] | list[Any], status: str | None = None, limit: int = 8) -> str:
    approvals = result if isinstance(result, list) else []
    if status:
        approvals = [item for item in approvals if item.get("status") == status]
    if not approvals:
        return "No approval requests found."
    lines = ["### Approval requests"]
    for approval in approvals[:limit]:
        approval_id = approval.get("id", "unknown")
        request_type = approval.get("request_type", "unknown")
        target_type = approval.get("target_type", "unknown")
        target_id = approval.get("target_id", "unknown")
        current_status = approval.get("status", "unknown")
        lines.append(
            f"- `{approval_id}` type=`{request_type}` target=`{target_type}:{target_id}` "
            f"status=`{current_status}`"
        )
        if current_status == "pending":
            if approval.get("policy_lock_reason"):
                lines.append(f"  policy lock: `{approval['policy_lock_reason']}`")
            action_specs = approval_action_specs(approval)
            if action_specs:
                commands = ", ".join(f"`/{spec['command']} {approval_id} <comment>`" for spec in action_specs)
                lines.append(f"  actions: {commands}")
            else:
                lines.append("  actions: none allowed by policy")
        if approval.get("risk_summary"):
            lines.append(f"  risk: `{compact_json(approval['risk_summary'])}`")
    if len(approvals) > limit:
        lines.append(f"... {len(approvals) - limit} more approval requests not shown")
    return "\n".join(lines)


def compact_json(value: Any, limit: int = 240) -> str:
    rendered = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    if len(rendered) <= limit:
        return rendered
    return rendered[: limit - 3] + "..."


def approval_action_specs(approval: dict[str, Any]) -> list[dict[str, Any]]:
    approval_id = str(approval.get("id") or "")
    if approval.get("status") != "pending" or not approval_id:
        return []
    short_id = approval_id[:8]
    allowed_actions = approval.get("allowed_actions")
    allowed = set(allowed_actions) if isinstance(allowed_actions, list) else {"approve", "reject", "request-changes"}
    specs = [
        {
            "name": "approval_approve",
            "command": "approve",
            "action": "approve",
            "label": f"Approve {short_id}",
            "payload": {"approval_id": approval_id, "resolution": "approve"},
        },
        {
            "name": "approval_reject",
            "command": "reject",
            "action": "reject",
            "label": f"Reject {short_id}",
            "payload": {"approval_id": approval_id, "resolution": "reject"},
        },
        {
            "name": "approval_request_changes",
            "command": "request-changes",
            "action": "request-changes",
            "label": f"Request changes {short_id}",
            "payload": {"approval_id": approval_id, "resolution": "request_changes"},
        },
    ]
    return [spec for spec in specs if spec["action"] in allowed]


def chainlit_actions_for_payload(
    payload: dict[str, Any],
    result: dict[str, Any] | list[Any],
    limit: int = 5,
) -> list[Any]:
    if cl is None or payload["action"] != "approvals" or not isinstance(result, list):
        return []
    actions = []
    for approval in result[:limit]:
        for spec in approval_action_specs(approval):
            actions.append(cl.Action(name=spec["name"], label=spec["label"], payload=spec["payload"]))
    return actions


def chainlit_action_payload(action: Any) -> dict[str, Any]:
    if isinstance(action, dict):
        return dict(action.get("payload") or {})
    return dict(getattr(action, "payload", None) or {})


if cl is not None:

    if oauth_configured():

        @cl.oauth_callback
        async def oauth_callback(provider_id, token, raw_user_data, default_app_user, id_token=None):
            default_app_user.metadata = {
                **(default_app_user.metadata or {}),
                "provider": provider_id,
                "api_token": token,
                "keycloak_sub": raw_user_data.get("sub"),
            }
            return default_app_user

    @cl.on_chat_start
    async def on_chat_start() -> None:
        await cl.Message(
            content=(
                "Quant Team OS agent chat. Use `/workflow <research_idea_id>`, `/status`, `/tools`, "
                "or `/approvals`. Approval buttons submit through the FastAPI Approval API."
            )
        ).send()

    @cl.on_message
    async def on_message(message) -> None:
        payload = command_payload(message.content)
        if payload["action"] == "approval_comment_required":
            content = render_response(payload, {})
            actions = []
        else:
            try:
                result = await call_api(payload, token=current_api_token())
                content = render_response(payload, result)
                actions = chainlit_actions_for_payload(payload, result)
            except Exception as exc:
                content = f"Request failed: {exc}"
                actions = []
        message_kwargs = {"content": content}
        if actions:
            message_kwargs["actions"] = actions
        await cl.Message(**message_kwargs).send()

    async def resolve_from_chainlit_action(action: Any, expected_resolution: str) -> None:
        payload = chainlit_action_payload(action)
        approval_id = payload.get("approval_id")
        resolution = payload.get("resolution") or expected_resolution
        if not approval_id or resolution != expected_resolution:
            await cl.Message(content="Approval action failed: invalid action payload.").send()
            return
        human_comment = str(payload.get("human_comment") or "").strip()
        if not human_comment:
            answer = await cl.AskUserMessage(
                content=f"Add a human comment for `{resolution}` on approval `{approval_id}`.",
                timeout=120,
            ).send()
            human_comment = str((answer or {}).get("output") or "").strip()
        if not human_comment:
            await cl.Message(content="Approval action cancelled: human comment is required.").send()
            return
        api_payload = {
            "action": "resolve_approval",
            "approval_id": approval_id,
            "resolution": resolution,
            "human_comment": human_comment,
        }
        try:
            result = await call_api(api_payload, token=current_api_token())
            content = render_response(api_payload, result)
        except Exception as exc:
            content = f"Approval action failed: {exc}"
        await cl.Message(content=content).send()

    @cl.action_callback("approval_approve")
    async def on_approval_approve(action) -> None:
        await resolve_from_chainlit_action(action, "approve")

    @cl.action_callback("approval_reject")
    async def on_approval_reject(action) -> None:
        await resolve_from_chainlit_action(action, "reject")

    @cl.action_callback("approval_request_changes")
    async def on_approval_request_changes(action) -> None:
        await resolve_from_chainlit_action(action, "request_changes")


class FallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.end_headers()
        body = {
            "service": "agent-chat",
            "ui": "chainlit",
            "mode": "fallback_http",
            "api_url": API_URL,
            "capabilities": ["agent_chat", "tool_call_display", "human_action_buttons"],
            "approval_api": "/api/v1/approvals/{id}/approve|reject|request-changes",
        }
        self.wfile.write(json.dumps(body).encode("utf-8"))


def main() -> None:
    HTTPServer(("0.0.0.0", 8001), FallbackHandler).serve_forever()


if __name__ == "__main__":
    if cl is not None:
        print("Run with: chainlit run app.py --host 0.0.0.0 --port 8001", flush=True)
    main()
