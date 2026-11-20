# Solo tamaños y valores; los nombres salen de terraform.workspace.
enable_pitr        = false
log_retention_days = 7

feature_flags = {
  ENABLE_DYNAMIC_SURGE_PRICING    = true
  ENABLE_FAST_CHARGE_BOOST        = true
  SIMULATE_CHARGER_HARDWARE_FAULT = false
}
