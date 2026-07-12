package qto.approval

default allow = false

allow if {
  has_approver_role
  input.agent.service_account != true
  input.comment != ""
  count(deny) == 0
}

deny contains "Live trading is locked by OPA" if {
  input.request_type == "unlock_live"
  input.action == "create_request"
}

deny contains "Live trading is locked by OPA" if {
  input.request_type == "unlock_live"
  input.action == "approved"
}

has_approver_role if {
  input.user.roles[_] == "approver"
}

deny contains "approver role is required" if {
  not has_approver_role
}

deny contains "human comment is required" if {
  input.comment == ""
}

deny contains "agent service account cannot resolve approval" if {
  input.agent.service_account == true
}
