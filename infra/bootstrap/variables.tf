variable "region" {
  description = "Región AWS del proyecto"
  type        = string
  default     = "us-east-1"
}


variable "github_sub_prefixes" {
  description = <<-EOT
    Prefijos del claim "sub" del token OIDC de GitHub. Los repos nuevos usan el
    formato inmutable repo:<owner>@<owner_id>/<repo>@<repo_id> (ver
    gh api repos/<owner>/<repo>/actions/oidc/customization/sub); se acepta
    también el formato clásico repo:<owner>/<repo>.
  EOT
  type        = list(string)
  default = [
    "repo:Jorgealis@170771367/aegisvolt@1465021447",
    "repo:Jorgealis/aegisvolt",
  ]
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
