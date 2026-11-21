# VPC Endpoints: el tráfico de los pods hacia DynamoDB, S3 y CloudWatch Logs
# no sale a internet.
#   - Gateway (S3, DynamoDB): GRATIS, rutas en la route table privada.
#   - Interface (logs, execute-api opcional): se cobran por hora -> enable_interface.

variable "env" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "vpc_cidr" {
  type = string
}

variable "private_route_table_ids" {
  type = list(string)
}

variable "interface_subnet_ids" {
  description = "Subredes para las ENI de los Interface VPCE (1 subred = 1 ENI = la mitad de costo)"
  type        = list(string)
}

variable "enable_interface" {
  type    = bool
  default = false
}

variable "enable_execute_api" {
  description = "Interface VPCE para API Gateway privado (opcional; no se usa en la arquitectura base)"
  type        = bool
  default     = false
}

data "aws_region" "current" {}
data "aws_caller_identity" "current" {}

locals {
  prefix = "aegisvolt-${var.env}"
  region = data.aws_region.current.region
}

# --- Gateway VPC Endpoints (gratis) ------------------------------------------
resource "aws_vpc_endpoint" "s3" {
  vpc_id            = var.vpc_id
  service_name      = "com.amazonaws.${local.region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = var.private_route_table_ids
  tags              = { Name = "${local.prefix}-vpce-s3" }
}

# La política del endpoint aísla ambientes: desde la VPC de dev solo se
# alcanzan las tablas aegisvolt-*-dev (nunca las de prod).
data "aws_iam_policy_document" "dynamodb_endpoint" {
  statement {
    sid     = "OnlyThisEnvironmentTables"
    actions = ["dynamodb:*"]
    resources = [
      "arn:aws:dynamodb:${local.region}:${data.aws_caller_identity.current.account_id}:table/aegisvolt-*-${var.env}",
      "arn:aws:dynamodb:${local.region}:${data.aws_caller_identity.current.account_id}:table/aegisvolt-*-${var.env}/*",
    ]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
  }
}

resource "aws_vpc_endpoint" "dynamodb" {
  vpc_id            = var.vpc_id
  service_name      = "com.amazonaws.${local.region}.dynamodb"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = var.private_route_table_ids
  policy            = data.aws_iam_policy_document.dynamodb_endpoint.json
  tags              = { Name = "${local.prefix}-vpce-dynamodb" }
}

# --- Interface VPC Endpoints (se cobran por hora) -----------------------------
resource "aws_security_group" "vpce" {
  name        = "${local.prefix}-vpce-sg"
  description = "HTTPS desde la VPC hacia los Interface VPC Endpoints"
  vpc_id      = var.vpc_id
  tags        = { Name = "${local.prefix}-vpce-sg" }
}

resource "aws_vpc_security_group_ingress_rule" "vpce_https" {
  security_group_id = aws_security_group.vpce.id
  description       = "443 solo desde el CIDR de la VPC"
  cidr_ipv4         = var.vpc_cidr
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}

resource "aws_vpc_endpoint" "logs" {
  count               = var.enable_interface ? 1 : 0
  vpc_id              = var.vpc_id
  service_name        = "com.amazonaws.${local.region}.logs"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = var.interface_subnet_ids
  security_group_ids  = [aws_security_group.vpce.id]
  private_dns_enabled = true # logs.us-east-1.amazonaws.com resuelve a la IP privada del VPCE
  tags                = { Name = "${local.prefix}-vpce-logs" }
}

resource "aws_vpc_endpoint" "execute_api" {
  count               = var.enable_interface && var.enable_execute_api ? 1 : 0
  vpc_id              = var.vpc_id
  service_name        = "com.amazonaws.${local.region}.execute-api"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = var.interface_subnet_ids
  security_group_ids  = [aws_security_group.vpce.id]
  private_dns_enabled = false # no interferir con la API regional del frontend
  tags                = { Name = "${local.prefix}-vpce-execute-api" }
}

output "s3_endpoint_id" {
  value = aws_vpc_endpoint.s3.id
}

output "dynamodb_endpoint_id" {
  value = aws_vpc_endpoint.dynamodb.id
}

output "dynamodb_prefix_list_id" {
  value = aws_vpc_endpoint.dynamodb.prefix_list_id
}

output "logs_endpoint_id" {
  value = try(aws_vpc_endpoint.logs[0].id, null)
}
