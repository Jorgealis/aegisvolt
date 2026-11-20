variable "region" {
  description = "Región AWS"
  type        = string
  default     = "us-east-1"
}

# --- Tamaños y flags por ambiente (envs/<env>.tfvars). Nunca nombres. ---

variable "enable_pitr" {
  description = "Point-in-time recovery en DynamoDB (solo prod)"
  type        = bool
  default     = false
}

variable "log_retention_days" {
  description = "Retención de los log groups de CloudWatch"
  type        = number
  default     = 7
}

variable "feature_flags" {
  description = "Valor inicial de cada feature flag en este ambiente (luego se cambian en caliente)"
  type        = map(bool)
  default = {
    ENABLE_DYNAMIC_SURGE_PRICING    = false
    ENABLE_FAST_CHARGE_BOOST        = false
    SIMULATE_CHARGER_HARDWARE_FAULT = false
  }
}
