# Dockerfile multi-stage compartido por los 4 servicios Python.
# Contexto de build = services/. Ejemplo:
#   docker build -f services/Dockerfile --build-arg SERVICE_DIR=billing-wallet-service \
#                --build-arg PACKAGE=billing_wallet -t aegisvolt/billing-wallet-service services
ARG PYTHON_IMAGE=python:3.12-slim

FROM ${PYTHON_IMAGE} AS build
ARG SERVICE_DIR
WORKDIR /build
COPY ${SERVICE_DIR}/requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM ${PYTHON_IMAGE}
ARG SERVICE_DIR
ARG PACKAGE
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_MODULE=${PACKAGE}.main:app
RUN useradd --uid 10001 --create-home app
WORKDIR /app
COPY --from=build /install /usr/local
COPY common/aegis_common ./aegis_common
COPY ${SERVICE_DIR}/${PACKAGE} ./${PACKAGE}
USER 10001
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)" || exit 1
CMD ["sh", "-c", "exec uvicorn \"$APP_MODULE\" --host 0.0.0.0 --port 8000 --no-access-log"]
