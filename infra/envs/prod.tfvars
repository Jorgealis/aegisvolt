# Solo tamaños y valores; los nombres salen de terraform.workspace.
enable_pitr        = true
log_retention_days = 30

feature_flags = {
  ENABLE_DYNAMIC_SURGE_PRICING    = false
  ENABLE_FAST_CHARGE_BOOST        = false
  SIMULATE_CHARGER_HARDWARE_FAULT = false
}
