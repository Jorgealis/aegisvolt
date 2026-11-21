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

# --- Plataforma con costo por hora (NAT, Interface VPCE, NLB, API Gateway, EKS) ---

variable "enable_platform" {
  description = <<-EOT
    false (por defecto): solo red gratuita + DynamoDB + logs -> ~USD 0.
    true: crea NAT, VPCE de logs, EKS, NLB y API Gateway (~USD 0,27/h por ambiente).
    Se enciende solo para la demo/sustentación y se vuelve a apagar.
  EOT
  type        = bool
  default     = false
}

variable "enable_execute_api_vpce" {
  description = "Interface VPCE de execute-api (opcional, no lo usa la arquitectura base)"
  type        = bool
  default     = false
}

variable "node_instance_type" {
  type    = string
  default = "t3.medium"
}

variable "node_desired" {
  type    = number
  default = 2
}

variable "eks_admin_principal_arns" {
  description = "Quién administra el clúster: rol de despliegue de GitHub Actions y el usuario local"
  type        = list(string)
  default = [
    "arn:aws:iam::185658217743:role/aegisvolt-gha-deploy",
    "arn:aws:iam::185658217743:user/jorge-cli",
  ]
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
