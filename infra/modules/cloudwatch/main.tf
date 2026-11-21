variable "env" {
  type = string
}

variable "retention_days" {
  type = number
}

# Un log group por componente y ambiente: /aegisvolt/<env>/<componente>.
# Sin datos no hay costo; la retención corta limita el almacenamiento.
locals {
  components = [
    "station-reservation",
    "billing-wallet",
    "energy-dispatch",
    "graphql-gateway",
    "apigw",
  ]
}

resource "aws_cloudwatch_log_group" "this" {
  for_each = toset(local.components)

  name              = "/aegisvolt/${var.env}/${each.key}"
  retention_in_days = var.retention_days
}

output "log_group_names" {
  value = { for k, g in aws_cloudwatch_log_group.this : k => g.name }
}

output "log_group_arns" {
  value = { for k, g in aws_cloudwatch_log_group.this : k => g.arn }
}
