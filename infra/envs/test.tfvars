# Solo tamaños y valores; los nombres salen de terraform.workspace.
enable_pitr        = false
log_retention_days = 14

feature_flags = {
  ENABLE_DYNAMIC_SURGE_PRICING    = true
  ENABLE_FAST_CHARGE_BOOST        = false
  SIMULATE_CHARGER_HARDWARE_FAULT = false
}

# Plataforma con costo por hora (EKS, NAT, NLB, API Gateway): apagada.
# Encender SOLO para la demo/sustentación: enable_platform = true
enable_platform = false
node_desired    = 2
