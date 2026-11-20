# EKS estándar por ambiente, nodos on-demand en subredes privadas.
# Se instancia solo con enable_platform = true (ver infra/main.tf).

variable "env" {
  type = string
}

variable "private_subnet_ids" {
  type = list(string)
}

variable "kubernetes_version" {
  description = "null = la versión por defecto de EKS (siempre en soporte estándar)"
  type        = string
  default     = null
}

variable "node_instance_type" {
  type    = string
  default = "t3.medium"
}

variable "node_desired" {
  type    = number
  default = 2
}

variable "node_min" {
  type    = number
  default = 1
}

variable "node_max" {
  type    = number
  default = 3
}

variable "admin_principal_arns" {
  description = "IAM con acceso admin a Kubernetes (rol de despliegue de GitHub + usuario local)"
  type        = list(string)
}

variable "public_access_cidrs" {
  description = "Desde dónde se alcanza el API server (kubectl de GitHub Actions y local). Autenticación siempre por IAM."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

data "aws_region" "current" {}
data "aws_caller_identity" "current" {}

locals {
  name    = "aegisvolt-${var.env}"
  region  = data.aws_region.current.region
  account = data.aws_caller_identity.current.account_id
}

# --- IAM del plano de control ---------------------------------------------
data "aws_iam_policy_document" "cluster_trust" {
  statement {
    actions = ["sts:AssumeRole", "sts:TagSession"]
    principals {
      type        = "Service"
      identifiers = ["eks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "cluster" {
  name               = "${local.name}-eks-cluster"
  assume_role_policy = data.aws_iam_policy_document.cluster_trust.json
}

resource "aws_iam_role_policy_attachment" "cluster" {
  role       = aws_iam_role.cluster.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSClusterPolicy"
}

# --- IAM de los nodos (los pods usan este rol) -----------------------------
data "aws_iam_policy_document" "node_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "node" {
  name               = "${local.name}-eks-node"
  assume_role_policy = data.aws_iam_policy_document.node_trust.json
}

resource "aws_iam_role_policy_attachment" "node" {
  for_each = toset([
    "arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy",
    "arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy",
    "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly",
  ])
  role       = aws_iam_role.node.name
  policy_arn = each.value
}

# Mínimo privilegio por ambiente: solo las tablas y log groups de ESTE ambiente.
data "aws_iam_policy_document" "node_app" {
  statement {
    sid = "DynamoDBThisEnv"
    actions = [
      "dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem",
      "dynamodb:Query", "dynamodb:Scan", "dynamodb:TransactWriteItems", "dynamodb:DescribeTable",
      "dynamodb:ConditionCheckItem",
    ]
    resources = [
      "arn:aws:dynamodb:${local.region}:${local.account}:table/aegisvolt-*-${var.env}",
      "arn:aws:dynamodb:${local.region}:${local.account}:table/aegisvolt-*-${var.env}/*",
    ]
  }
  statement {
    sid       = "LogsThisEnv"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents", "logs:DescribeLogStreams"]
    resources = ["arn:aws:logs:${local.region}:${local.account}:log-group:/aegisvolt/${var.env}/*"]
  }
  statement {
    sid       = "CanaryAnalysis" # Argo Rollouts consulta métricas de CloudWatch
    actions   = ["cloudwatch:GetMetricData", "cloudwatch:GetMetricStatistics", "cloudwatch:ListMetrics"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "node_app" {
  name   = "aegisvolt-app"
  role   = aws_iam_role.node.id
  policy = data.aws_iam_policy_document.node_app.json
}

# --- Clúster -----------------------------------------------------------------
resource "aws_eks_cluster" "this" {
  name     = local.name
  version  = var.kubernetes_version
  role_arn = aws_iam_role.cluster.arn

  vpc_config {
    subnet_ids              = var.private_subnet_ids
    endpoint_private_access = true # los nodos hablan con el API server dentro de la VPC
    endpoint_public_access  = true # GitHub Actions / kubectl local (autenticados por IAM)
    public_access_cidrs     = var.public_access_cidrs
  }

  access_config {
    authentication_mode                         = "API"
    bootstrap_cluster_creator_admin_permissions = false # los admins se declaran abajo
  }

  # Evita el "extended support" (USD 0,60/h): si la versión vence, se actualiza.
  upgrade_policy {
    support_type = "STANDARD"
  }

  enabled_cluster_log_types = [] # logs del plano de control desactivados (costo)

  depends_on = [aws_iam_role_policy_attachment.cluster]
}

resource "aws_eks_access_entry" "admin" {
  for_each      = toset(var.admin_principal_arns)
  cluster_name  = aws_eks_cluster.this.name
  principal_arn = each.value
  type          = "STANDARD"
}

resource "aws_eks_access_policy_association" "admin" {
  for_each      = toset(var.admin_principal_arns)
  cluster_name  = aws_eks_cluster.this.name
  principal_arn = each.value
  policy_arn    = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"

  access_scope {
    type = "cluster"
  }

  depends_on = [aws_eks_access_entry.admin]
}

resource "aws_eks_node_group" "default" {
  cluster_name    = aws_eks_cluster.this.name
  node_group_name = "${local.name}-nodes"
  node_role_arn   = aws_iam_role.node.arn
  subnet_ids      = var.private_subnet_ids
  ami_type        = "AL2023_x86_64_STANDARD"
  capacity_type   = "ON_DEMAND"
  instance_types  = [var.node_instance_type]
  disk_size       = 20

  scaling_config {
    desired_size = var.node_desired
    min_size     = var.node_min
    max_size     = var.node_max
  }

  update_config {
    max_unavailable = 1
  }

  depends_on = [aws_iam_role_policy_attachment.node]
}

output "cluster_name" {
  value = aws_eks_cluster.this.name
}

output "cluster_security_group_id" {
  value = aws_eks_cluster.this.vpc_config[0].cluster_security_group_id
}

output "node_asg_name" {
  value = aws_eks_node_group.default.resources[0].autoscaling_groups[0].name
}
