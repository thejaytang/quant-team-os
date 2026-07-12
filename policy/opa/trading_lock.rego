package qto.trading_lock

default allow = false

allow if {
  input.action != "live_order"
}

allow if {
  input.system.allow_live_trading == true
}

deny contains "live trading is locked" if {
  input.action == "live_order"
  input.system.allow_live_trading == false
}
