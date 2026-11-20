locals {
  # El ambiente SIEMPRE sale del workspace; los tfvars nunca definen nombres.
  env    = terraform.workspace
  prefix = "aegisvolt-${local.env}"

  allowed_envs = ["dev", "test", "prod"]

  cidr = lookup({
    dev  = "10.10.0.0/16"
    test = "10.20.0.0/16"
    prod = "10.30.0.0/16"
  }, local.env, "10.99.0.0/16")

  tags = {
    Project     = "AegisVolt"
    Environment = local.env
    ManagedBy   = "Terraform"
  }
}

# Guarda: impide aplicar en el workspace "default" (u otro no previsto),
# que crearía recursos sin ambiente en el nombre.
resource "terraform_data" "workspace_guard" {
  input = local.env

  lifecycle {
    precondition {
      condition     = contains(local.allowed_envs, terraform.workspace)
      error_message = "Workspace inválido '${terraform.workspace}'. Usa: terraform workspace select dev|test|prod"
    }
  }
}
