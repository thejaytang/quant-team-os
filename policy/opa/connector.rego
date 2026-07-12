package qto.connector

default allow = false

allow if {
  input.connection.status == "connected"
  not secret_payload
  not untrusted_secret_ref
}

secret_payload if {
  input.payload.secret
}

secret_payload if {
  input.payload.api_key
}

secret_payload if {
  input.payload.api_token
}

secret_payload if {
  input.payload.access_token
}

secret_payload if {
  input.payload.refresh_token
}

secret_payload if {
  input.payload.client_secret
}

secret_payload if {
  input.payload.secret_key
}

secret_payload if {
  input.payload.private_key
}

secret_payload if {
  input.payload.password
}

secret_payload if {
  input.payload.credential
}

secret_payload if {
  input.payload.credentials
}

secret_payload if {
  input.payload.authorization
}

secret_payload if {
  input.payload_meta.sensitive_value_present == true
}

trusted_secret_ref_actor if {
  input.agent.name == "LangfuseService"
}

trusted_secret_ref_actor if {
  input.agent.name == "openbb-backend"
}

untrusted_secret_ref if {
  input.payload_meta.ref_requested == true
  not trusted_secret_ref_actor
}

deny contains "connector is not connected" if {
  input.connection.status != "connected"
}

deny contains "secret must not be present in tool payload" if {
  secret_payload
}

deny contains "secret refs must be resolved by trusted service adapters" if {
  untrusted_secret_ref
}
