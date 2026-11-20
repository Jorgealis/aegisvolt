variable "region" {
  description = "Región AWS del proyecto"
  type        = string
  default     = "us-east-1"
}

variable "github_repo" {
  description = "Repositorio GitHub en formato owner/name (para la confianza OIDC)"
  type        = string
  default     = "Jorgealis/aegisvolt"
}

variable "create_oidc_provider" {
  description = "false si la cuenta ya tiene el proveedor OIDC de GitHub creado"
  type        = bool
  default     = true
}

variable "budget_limit_usd" {
  description = "Tope mensual del presupuesto de alerta (USD)"
  type        = number
  default     = 20
}

variable "budget_email" {
  description = "Correo que recibe las alertas de presupuesto (va en terraform.tfvars, no se versiona). Vacío = sin alerta"
  type        = string
  default     = ""
}
