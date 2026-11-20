# Stack por ambiente. Seleccionar el workspace antes de cualquier plan/apply:
#   terraform workspace select dev|test|prod
#   terraform plan -var-file=envs/$(terraform workspace show).tfvars

module "dynamodb" {
  source      = "./modules/dynamodb"
  env         = local.env
  enable_pitr = var.enable_pitr

  depends_on = [terraform_data.workspace_guard]
}

module "flags" {
  source     = "./modules/flags"
  table_name = module.dynamodb.table_names["flags"]
  flags      = var.feature_flags
}

module "cloudwatch" {
  source         = "./modules/cloudwatch"
  env            = local.env
  retention_days = var.log_retention_days

  depends_on = [terraform_data.workspace_guard]
}

# Fase 2 (recursos con costo por hora; se activan con aviso previo):
#   module "network", module "vpce", module "apigw", module "eks"
