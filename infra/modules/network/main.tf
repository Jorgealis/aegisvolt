# VPC dedicada por ambiente: 2 subredes públicas + 2 privadas en 2 AZ.
# Costo: VPC, subredes, route tables e IGW son gratis. Solo el NAT (+ su EIP)
# se cobra por hora, por eso va detrás de enable_nat.

variable "env" {
  type = string
}

variable "cidr" {
  type = string
}

variable "enable_nat" {
  description = "NAT Gateway para la salida a internet de los nodos (descargar imágenes). Se cobra por hora."
  type        = bool
  default     = false
}

data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  prefix = "aegisvolt-${var.env}"
  azs    = slice(data.aws_availability_zones.available.names, 0, 2)
}

resource "aws_vpc" "this" {
  cidr_block           = var.cidr
  enable_dns_support   = true
  enable_dns_hostnames = true # necesario para el DNS privado de los Interface VPCE

  tags = { Name = "${local.prefix}-vpc" }
}

resource "aws_internet_gateway" "this" {
  vpc_id = aws_vpc.this.id
  tags   = { Name = "${local.prefix}-igw" }
}

resource "aws_subnet" "public" {
  count             = 2
  vpc_id            = aws_vpc.this.id
  cidr_block        = cidrsubnet(var.cidr, 8, count.index) # x.x.0.0/24, x.x.1.0/24
  availability_zone = local.azs[count.index]

  tags = {
    Name                     = "${local.prefix}-public-${local.azs[count.index]}"
    Tier                     = "public"
    "kubernetes.io/role/elb" = "1"
  }
}

resource "aws_subnet" "private" {
  count             = 2
  vpc_id            = aws_vpc.this.id
  cidr_block        = cidrsubnet(var.cidr, 8, 10 + count.index) # x.x.10.0/24, x.x.11.0/24
  availability_zone = local.azs[count.index]

  tags = {
    Name                              = "${local.prefix}-private-${local.azs[count.index]}"
    Tier                              = "private"
    "kubernetes.io/role/internal-elb" = "1"
  }
}

# --- Rutas públicas: 0.0.0.0/0 -> Internet Gateway ---------------------------
resource "aws_route_table" "public" {
  vpc_id = aws_vpc.this.id
  tags   = { Name = "${local.prefix}-rt-public" }
}

resource "aws_route" "public_internet" {
  route_table_id         = aws_route_table.public.id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.this.id
}

resource "aws_route_table_association" "public" {
  count          = 2
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

# --- Rutas privadas: sin salida a internet salvo NAT -------------------------
# Los Gateway VPCE de S3 y DynamoDB añaden aquí sus rutas al prefix list
# (pl-xxxx), más específicas que 0.0.0.0/0: ese tráfico nunca pasa por el NAT.
resource "aws_route_table" "private" {
  vpc_id = aws_vpc.this.id
  tags   = { Name = "${local.prefix}-rt-private" }
}

resource "aws_route_table_association" "private" {
  count          = 2
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private.id
}

resource "aws_eip" "nat" {
  count  = var.enable_nat ? 1 : 0
  domain = "vpc"
  tags   = { Name = "${local.prefix}-nat-eip" }
}

resource "aws_nat_gateway" "this" {
  count         = var.enable_nat ? 1 : 0
  allocation_id = aws_eip.nat[0].id
  subnet_id     = aws_subnet.public[0].id # un solo NAT (no uno por AZ) para ahorrar
  tags          = { Name = "${local.prefix}-nat" }

  depends_on = [aws_internet_gateway.this]
}

resource "aws_route" "private_nat" {
  count                  = var.enable_nat ? 1 : 0
  route_table_id         = aws_route_table.private.id
  destination_cidr_block = "0.0.0.0/0"
  nat_gateway_id         = aws_nat_gateway.this[0].id
}

output "vpc_id" {
  value = aws_vpc.this.id
}

output "vpc_cidr" {
  value = aws_vpc.this.cidr_block
}

output "public_subnet_ids" {
  value = aws_subnet.public[*].id
}

output "private_subnet_ids" {
  value = aws_subnet.private[*].id
}

output "private_route_table_id" {
  value = aws_route_table.private.id
}
