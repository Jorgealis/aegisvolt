"""graphql-gateway: punto de entrada único (POST /graphql) + orquestador SAGA."""

import os

from fastapi.middleware.cors import CORSMiddleware
from strawberry.fastapi import GraphQLRouter

from aegis_common.web import create_app

from .schema import schema

app = create_app("graphql-gateway")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["x-correlation-id"],
)
app.include_router(GraphQLRouter(schema), prefix="/graphql")
