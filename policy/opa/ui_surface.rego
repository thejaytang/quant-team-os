package qto.ui_surface

default allow = false

allow if {
  count(deny) == 0
}

deny contains "Chainlit cannot directly mutate core state" if {
  input.surface == "chainlit"
  core_mutation_action
}

deny contains "external workspace is read-only for core state" if {
  external_read_only_surface
  not read_action
}

core_mutation_action if {
  input.action == "create_strategy"
}

core_mutation_action if {
  input.action == "update_strategy"
}

core_mutation_action if {
  input.action == "set_strategy_status"
}

core_mutation_action if {
  input.action == "register_strategy"
}

core_mutation_action if {
  input.action == "promote_to_paper"
}

external_read_only_surface if {
  input.surface == "openbb"
}

external_read_only_surface if {
  input.surface == "superset"
}

external_read_only_surface if {
  input.surface == "grafana"
}

external_read_only_surface if {
  input.surface == "jupyterlab"
}

read_action if {
  input.action == "read"
}

read_action if {
  input.action == "view"
}

read_action if {
  input.action == "query"
}

read_action if {
  input.action == "list"
}
