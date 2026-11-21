# Entrada: API Gateway (REST, regional) -> VPC Link -> NLB interno -> NodePort
# del graphql-gateway en los nodos EKS.
#
# El VPC Link de una REST API se implementa con AWS PrivateLink: crea un
# VPC Endpoint Service sobre el NLB, así API Gateway entra a la VPC por un
# endpoint privado y el tráfico nunca cruza internet hasta los pods.

variable "env" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "vpc_cidr" {
  type = string
}

variable "private_subnet_ids" {
  type = list(string)
}

variable "node_asg_name" {
  type = string
}

variable "cluster_security_group_id" {
  type = string
}

variable "node_port" {
  description = "NodePort fijo del Service graphql-gateway en Kubernetes"
  type        = number
  default     = 30080
}

variable "access_log_group_arn" {
  type = string
}

locals {
  name = "aegisvolt-${var.env}"
}

# --- NLB interno en las subredes privadas ------------------------------------
resource "aws_lb" "nlb" {
  name               = "${local.name}-nlb"
  internal           = true
  load_balancer_type = "network"
  subnets            = var.private_subnet_ids
}

resource "aws_lb_target_group" "gateway" {
  name               = "${local.name}-gw"
  port               = var.node_port
  protocol           = "TCP"
  vpc_id             = var.vpc_id
  target_type        = "instance"
  preserve_client_ip = "false"

  health_check {
    protocol = "HTTP"
    path     = "/health"
    port     = "traffic-port"
  }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.nlb.arn
  port              = 80
  protocol          = "TCP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.gateway.arn
  }
}

# Cada nodo del node group se registra solo en el target group.
resource "aws_autoscaling_attachment" "nodes" {
  autoscaling_group_name = var.node_asg_name
  lb_target_group_arn    = aws_lb_target_group.gateway.arn
}

# Security group de los nodos: el NodePort solo acepta tráfico desde la VPC
# (IPs privadas del NLB / PrivateLink), nunca desde internet.
resource "aws_vpc_security_group_ingress_rule" "nodeport" {
  security_group_id = var.cluster_security_group_id
  description       = "NLB -> NodePort graphql-gateway"
  cidr_ipv4         = var.vpc_cidr
  ip_protocol       = "tcp"
  from_port         = var.node_port
  to_port           = var.node_port
}

# --- API Gateway ---------------------------------------------------------------
resource "aws_api_gateway_vpc_link" "this" {
  name        = "${local.name}-vpclink"
  target_arns = [aws_lb.nlb.arn]
}

resource "aws_api_gateway_rest_api" "this" {
  name        = "${local.name}-api"
  description = "AegisVolt ${var.env}: POST /graphql, GET /health"

  endpoint_configuration {
    types = ["REGIONAL"]
  }
}

resource "aws_api_gateway_resource" "proxy" {
  rest_api_id = aws_api_gateway_rest_api.this.id
  parent_id   = aws_api_gateway_rest_api.this.root_resource_id
  path_part   = "{proxy+}"
}

resource "aws_api_gateway_method" "proxy" {
  rest_api_id        = aws_api_gateway_rest_api.this.id
  resource_id        = aws_api_gateway_resource.proxy.id
  http_method        = "ANY"
  authorization      = "NONE"
  request_parameters = { "method.request.path.proxy" = true }
}

resource "aws_api_gateway_integration" "proxy" {
  rest_api_id             = aws_api_gateway_rest_api.this.id
  resource_id             = aws_api_gateway_resource.proxy.id
  http_method             = aws_api_gateway_method.proxy.http_method
  type                    = "HTTP_PROXY"
  integration_http_method = "ANY"
  uri                     = "http://${aws_lb.nlb.dns_name}/{proxy}"
  connection_type         = "VPC_LINK"
  connection_id           = aws_api_gateway_vpc_link.this.id
  request_parameters      = { "integration.request.path.proxy" = "method.request.path.proxy" }
  timeout_milliseconds    = 29000
}

resource "aws_api_gateway_deployment" "this" {
  rest_api_id = aws_api_gateway_rest_api.this.id

  triggers = {
    redeploy = sha1(jsonencode([aws_api_gateway_resource.proxy, aws_api_gateway_method.proxy, aws_api_gateway_integration.proxy]))
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_api_gateway_stage" "this" {
  rest_api_id   = aws_api_gateway_rest_api.this.id
  deployment_id = aws_api_gateway_deployment.this.id
  stage_name    = var.env

  access_log_settings {
    destination_arn = var.access_log_group_arn # /aegisvolt/<env>/apigw
    format = jsonencode({
      requestId      = "$context.requestId"
      ip             = "$context.identity.sourceIp"
      method         = "$context.httpMethod"
      path           = "$context.path"
      status         = "$context.status"
      latencyMs      = "$context.responseLatency"
      integrationErr = "$context.integrationErrorMessage"
    })
  }
}

# Límite de peticiones: protege el costo ante tráfico inesperado.
resource "aws_api_gateway_method_settings" "all" {
  rest_api_id = aws_api_gateway_rest_api.this.id
  stage_name  = aws_api_gateway_stage.this.stage_name
  method_path = "*/*"

  settings {
    throttling_burst_limit = 50
    throttling_rate_limit  = 20
    metrics_enabled        = false
    logging_level          = "OFF"
  }
}

output "invoke_url" {
  value = aws_api_gateway_stage.this.invoke_url
}

output "graphql_url" {
  value = "${aws_api_gateway_stage.this.invoke_url}/graphql"
}

output "nlb_dns_name" {
  value = aws_lb.nlb.dns_name
}
