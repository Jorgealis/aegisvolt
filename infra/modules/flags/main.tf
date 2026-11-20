variable "table_name" {
  type = string
}

variable "flags" {
  type = map(bool)
}

# Siembra el valor inicial de cada flag en la tabla del ambiente.
# ignore_changes: un apply posterior NO pisa los cambios hechos en caliente
# (scripts/flag.ps1 o aws dynamodb update-item).
resource "aws_dynamodb_table_item" "flag" {
  for_each = var.flags

  table_name = var.table_name
  hash_key   = "PK"

  item = jsonencode({
    PK         = { S = "FLAG#${each.key}" }
    name       = { S = each.key }
    enabled    = { BOOL = each.value }
    updated_by = { S = "terraform" }
  })

  lifecycle {
    ignore_changes = [item]
  }
}
