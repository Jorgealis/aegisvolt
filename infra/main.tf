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

# ---------------------------------------------------------------------------
# Red. Lo gratis existe siempre (VPC, subredes, rutas, IGW, Gateway VPCE).
# Lo que se cobra por hora (NAT, Interface VPCE, NLB, EKS) solo existe con
# enable_platform = true -> se enciende para la demo y se apaga después.
# ---------------------------------------------------------------------------
module "network" {
  source     = "./modules/network"
  env        = local.env
  cidr       = local.cidr
  enable_nat = var.enable_platform

  depends_on = [terraform_data.workspace_guard]
}

module "vpce" {
  source                  = "./modules/vpce"
  env                     = local.env
  vpc_id                  = module.network.vpc_id
  vpc_cidr                = module.network.vpc_cidr
  private_route_table_ids = [module.network.private_route_table_id]
  interface_subnet_ids    = slice(module.network.private_subnet_ids, 0, 1)
  enable_interface        = var.enable_platform
  enable_execute_api      = var.enable_execute_api_vpce
}

module "eks" {
  source = "./modules/eks"
  count  = var.enable_platform ? 1 : 0

  env                  = local.env
  private_subnet_ids   = module.network.private_subnet_ids
  node_instance_type   = var.node_instance_type
  node_desired         = var.node_desired
  node_min             = 1
  node_max             = var.node_desired + 1
  admin_principal_arns = var.eks_admin_principal_arns

  # Los nodos necesitan el NAT y los VPCE listos para arrancar.
  depends_on = [module.network, module.vpce]
}

module "apigw" {
  source = "./modules/apigw"
  count  = var.enable_platform ? 1 : 0

  env                       = local.env
  vpc_id                    = module.network.vpc_id
  vpc_cidr                  = module.network.vpc_cidr
  private_subnet_ids        = module.network.private_subnet_ids
  node_asg_name             = module.eks[0].node_asg_name
  cluster_security_group_id = module.eks[0].cluster_security_group_id
  access_log_group_arn      = module.cloudwatch.log_group_arns["apigw"]
}
