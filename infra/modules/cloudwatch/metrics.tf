# Métricas para el análisis del canary (Argo Rollouts consulta CloudWatch).
# Se derivan de los logs JSON "HTTP_REQUEST" que escribe cada servicio:
#   AegisVolt/RequestCount y AegisVolt/ErrorCount (status >= 500)
#   dimensiones: Service, Version (hash de la plantilla del pod), Environment
# Los metric filters son gratis; solo hay costo de métrica cuando llegan datos.
locals {
  app_components = ["station-reservation", "billing-wallet", "energy-dispatch", "graphql-gateway"]
  metric_dimensions = {
    Service     = "$.service"
    Version     = "$.version"
    Environment = "$.env"
  }
}

resource "aws_cloudwatch_log_metric_filter" "requests" {
  for_each       = toset(local.app_components)
  name           = "aegisvolt-${var.env}-${each.key}-requests"
  log_group_name = aws_cloudwatch_log_group.this[each.key].name
  pattern        = "{ $.event = \"HTTP_REQUEST\" }"

  metric_transformation {
    namespace  = "AegisVolt"
    name       = "RequestCount"
    value      = "1"
    unit       = "Count"
    dimensions = local.metric_dimensions
  }
}

resource "aws_cloudwatch_log_metric_filter" "errors" {
  for_each       = toset(local.app_components)
  name           = "aegisvolt-${var.env}-${each.key}-errors"
  log_group_name = aws_cloudwatch_log_group.this[each.key].name
  pattern        = "{ $.event = \"HTTP_REQUEST\" && $.status >= 500 }"

  metric_transformation {
    namespace  = "AegisVolt"
    name       = "ErrorCount"
    value      = "1"
    unit       = "Count"
    dimensions = local.metric_dimensions
  }
}

# Compensaciones de SAGA (para observabilidad / Prefect)
resource "aws_cloudwatch_log_metric_filter" "saga_compensated" {
  name           = "aegisvolt-${var.env}-saga-compensated"
  log_group_name = aws_cloudwatch_log_group.this["graphql-gateway"].name
  pattern        = "{ $.event = \"SAGA_COMPENSATED\" }"

  metric_transformation {
    namespace = "AegisVolt"
    name      = "SagaCompensated"
    value     = "1"
    unit      = "Count"
    dimensions = {
      Environment = "$.env"
    }
  }
}
