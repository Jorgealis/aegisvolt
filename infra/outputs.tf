output "environment" {
  value = local.env
}

output "dynamodb_tables" {
  value = module.dynamodb.table_names
}

output "log_groups" {
  value = module.cloudwatch.log_group_names
}
