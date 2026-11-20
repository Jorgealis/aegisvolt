variable "env" {
  type = string
}

variable "enable_pitr" {
  type    = bool
  default = false
}

# Database-per-service: cada servicio es dueño de su tabla, y cada ambiente
# tiene las suyas (aegisvolt-<tabla>-<env>). Los registros de idempotencia
# viven dentro de la tabla de cada servicio (PK = IDEM#...) con TTL.
locals {
  tables = {
    reservations = { owner = "station-reservation-service", range_key = "SK", ttl = true }
    billing      = { owner = "billing-wallet-service", range_key = "SK", ttl = true }
    dispatch     = { owner = "energy-dispatch-service", range_key = "SK", ttl = true }
    sagas        = { owner = "saga-orchestrator", range_key = "SK", ttl = false }
    flags        = { owner = "feature-flags", range_key = null, ttl = false }
  }
}

resource "aws_dynamodb_table" "this" {
  for_each = local.tables

  name         = "aegisvolt-${each.key}-${var.env}"
  billing_mode = "PAY_PER_REQUEST" # sin capacidad aprovisionada: costo ~0 sin tráfico
  hash_key     = "PK"
  range_key    = each.value.range_key

  attribute {
    name = "PK"
    type = "S"
  }

  dynamic "attribute" {
    for_each = each.value.range_key == null ? [] : [each.value.range_key]
    content {
      name = attribute.value
      type = "S"
    }
  }

  dynamic "ttl" {
    for_each = each.value.ttl ? [1] : []
    content {
      attribute_name = "expires_at"
      enabled        = true
    }
  }

  point_in_time_recovery {
    enabled = var.enable_pitr
  }

  # false a propósito: test/prod se destruyen tras la sustentación para no
  # generar costos.
  deletion_protection_enabled = false

  tags = {
    Service = each.value.owner
  }
}

output "table_names" {
  value = { for k, t in aws_dynamodb_table.this : k => t.name }
}

output "table_arns" {
  value = { for k, t in aws_dynamodb_table.this : k => t.arn }
}
