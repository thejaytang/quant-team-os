package qto.agent

default allow = false

allow if {
  input.action == "tool_call"
  agent_tool_allowed
  count(deny) == 0
}

allowed_tools := {
  "ChiefAgent": {"openai", "rd_agent"},
  "ResearchAgent": {"openai", "rd_agent", "qlib", "alphalens", "duckdb", "report_artifact"},
  "DataAgent": {"massive", "massive_mcp", "dlt", "great_expectations", "dvc", "duckdb", "minio_artifact"},
  "FactorAgent": {"qlib", "alphalens", "duckdb", "minio_artifact"},
  "BacktestAgent": {"dvc", "quantconnect_mcp", "quantstats", "mlflow", "duckdb", "minio_artifact"},
  "RiskAgent": {"opa", "duckdb"},
  "ReportAgent": {"report_artifact", "mlflow", "duckdb", "minio_artifact"},
  "ExecutionAgent": {"quantconnect_paper"},
  "ConnectionTestAgent": {
    "openai",
    "massive",
    "massive_mcp",
    "quantconnect_mcp",
    "openbb_widget",
    "mlflow",
    "langfuse",
    "superset_link",
    "grafana_link",
    "temporal_workflow",
    "jupyterlab_link",
    "infisical",
    "keycloak_user",
    "minio_artifact",
    "chainlit_link",
  },
  "LangfuseService": {"langfuse"},
  "openbb-backend": {"keycloak_service_token"},
}

agent_tool_allowed if {
  allowed_tools[input.agent.name][input.tool.name]
}

deny contains "agent action must be tool_call" if {
  input.action != "tool_call"
}

deny contains "agent is not allowed to call this tool" if {
  not agent_tool_allowed
}

deny contains "agent cannot approve or reject approvals" if {
  input.agent.service_account == true
  input.action == "approve"
}

deny contains "agent cannot approve or reject approvals" if {
  input.agent.service_account == true
  input.action == "reject"
}

deny contains "arbitrary agent code execution is disabled" if {
  input.action == "run_arbitrary_code"
  input.system.allow_agent_arbitrary_code_execution == false
}
