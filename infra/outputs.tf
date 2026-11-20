output "environment" {
  value = local.env
}

output "dynamodb_tables" {
  value = module.dynamodb.table_names
}

output "log_groups" {
  value = module.cloudwatch.log_group_names
}

output "vpc_id" {
  value = module.network.vpc_id
}

output "dynamodb_prefix_list_id" {
  description = "Prefix list de DynamoDB enrutado por el Gateway VPCE en la route table privada"
  value       = module.vpce.dynamodb_prefix_list_id
}

output "platform_enabled" {
  value = var.enable_platform
}

output "eks_cluster_name" {
  value = try(module.eks[0].cluster_name, null)
}

output "graphql_url" {
  description = "URL pública de la API (solo con enable_platform = true)"
  value       = try(module.apigw[0].graphql_url, null)
}
