"""Genera k8s/base/<servicio>.yaml (Rollout + Service) para los 4 servicios.

Los 4 manifiestos comparten la misma forma; generarlos evita divergencias.
  python scripts/gen_k8s_base.py
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SERVICES = [
    # (nombre k8s / DNS,             SERVICE_NAME en logs,  extra env,                                   NodePort)
    ("station-reservation-service", "station-reservation", [], None),
    ("billing-wallet-service", "billing-wallet", [("SURGE_HOURS", "configmap")], None),
    ("energy-dispatch-service", "energy-dispatch", [], None),
    (
        "graphql-gateway",
        "graphql-gateway",
        [
            ("RESERVATION_URL", "http://station-reservation-service:8000"),
            ("BILLING_URL", "http://billing-wallet-service:8000"),
            ("DISPATCH_URL", "http://energy-dispatch-service:8000"),
            ("CORS_ORIGINS", "*"),
        ],
        30080,
    ),
]

TEMPLATE = """# Generado por scripts/gen_k8s_base.py: no editar a mano.
apiVersion: v1
kind: Service
metadata:
  name: {name}
  labels:
    app: {name}
spec:
  type: {svc_type}
  selector:
    app: {name}
  ports:
    - name: http
      port: 8000
      targetPort: http{node_port}
---
apiVersion: argoproj.io/v1alpha1
kind: Rollout
metadata:
  name: {name}
  labels:
    app: {name}
spec:
  replicas: 1 # cada overlay fija las réplicas del ambiente
  revisionHistoryLimit: 3
  selector:
    matchLabels:
      app: {name}
  template:
    metadata:
      labels:
        app: {name}
    spec:
      securityContext:
        runAsNonRoot: true
        runAsUser: 10001
        seccompProfile:
          type: RuntimeDefault
      containers:
        - name: app
          image: aegisvolt/{name} # el pipeline fija <ECR>/aegisvolt/{name}:<sha>
          ports:
            - name: http
              containerPort: 8000
          env:
            - name: ENV
              valueFrom:
                configMapKeyRef: {{ name: aegisvolt-config, key: ENV }}
            - name: AWS_REGION
              valueFrom:
                configMapKeyRef: {{ name: aegisvolt-config, key: AWS_REGION }}
            - name: SERVICE_NAME
              value: {log_name}
            - name: CLOUDWATCH_LOG_GROUP
              value: /aegisvolt/$(ENV)/{log_name}
            # Versión = hash de la plantilla del pod: separa stable y canary en
            # los logs y en las métricas que evalúa el análisis del canary.
            - name: APP_VERSION
              valueFrom:
                fieldRef:
                  fieldPath: metadata.labels['rollouts-pod-template-hash']
{extra_env}          readinessProbe:
            httpGet: {{ path: /ready, port: http }}
            periodSeconds: 5
          livenessProbe:
            httpGet: {{ path: /health, port: http }}
            initialDelaySeconds: 10
            periodSeconds: 15
          resources:
            requests: {{ cpu: 50m, memory: 96Mi }}
            limits: {{ cpu: 500m, memory: 256Mi }}
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities:
              drop: [ALL]
          volumeMounts:
            - name: tmp
              mountPath: /tmp
      volumes:
        - name: tmp
          emptyDir: {{}}
  strategy:
    canary:
      # Sin traffic router: el peso se logra con réplicas (5 réplicas -> 1 pod canary = 20 %).
      steps:
        - setWeight: 20
        - pause: {{ duration: 60s }}
        - analysis:
            templates:
              - templateName: error-rate-cloudwatch
            args:
              - name: service
                value: {log_name}
              - name: version
                valueFrom:
                  podTemplateHashValue: Latest
              - name: env
                valueFrom:
                  fieldRef:
                    fieldPath: metadata.labels['aegisvolt.io/env']
        - setWeight: 50
        - pause: {{ duration: 30s }}
        - setWeight: 100
"""


def env_lines(extra) -> str:
    out = []
    for key, value in extra:
        if value == "configmap":
            out.append(f"            - name: {key}\n              valueFrom:\n                configMapKeyRef: {{ name: aegisvolt-config, key: {key} }}\n")
        else:
            out.append(f'            - name: {key}\n              value: "{value}"\n')
    return "".join(out)


def main() -> None:
    for name, log_name, extra, node_port in SERVICES:
        text = TEMPLATE.format(
            name=name,
            log_name=log_name,
            svc_type="NodePort" if node_port else "ClusterIP",
            node_port=f"\n      nodePort: {node_port} # destino del NLB (API Gateway -> VPC Link -> NLB)" if node_port else "",
            extra_env=env_lines(extra),
        )
        path = ROOT / "k8s" / "base" / f"{name}.yaml"
        path.write_text(text, encoding="utf-8", newline="\n")
        print(f"escrito {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
