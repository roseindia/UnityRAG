"""FastAPI application factory."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import (
    admin,
    analytics,
    audit,
    auth,
    chat,
    collections,
    conversations,
    departments,
    documents,
    evaluation,
    groups,
    health,
    ingestion,
    permissions,
    platform_admin,
    roles,
    search,
    tenants,
    users,
)
from app.core.config import get_settings
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging
from app.database.session import dispose_engines, enforce_role_safety
from app.middleware.correlation import CorrelationMiddleware
from app.observability.tracing import configure_tracing

TAGS = [
    {"name": "Authentication", "description": "Login, SSO exchange, token rotation, tenant selection, MFA"},
    {"name": "Search", "description": "Permission-aware vector / full-text / hybrid retrieval"},
    {"name": "Chat", "description": "Grounded RAG answers with verified citations (JSON or SSE)"},
    {"name": "Platform Admin", "description": "Platform Super Admin Console (platform permissions only)"},
]


@asynccontextmanager
async def lifespan(_: FastAPI):
    if get_settings().environment != "test":
        enforce_role_safety(("app",))  # never serve with a superuser / BYPASSRLS / owner credential
    yield
    dispose_engines()


def create_app() -> FastAPI:
    s = get_settings()
    configure_logging(s.log_level, "api")
    configure_tracing("api")
    interactive = s.environment != "production"  # no interactive API explorer in production
    app = FastAPI(title=s.app_name, version="1.0.0", openapi_tags=TAGS, lifespan=lifespan,
                  docs_url="/docs" if interactive else None, redoc_url="/redoc" if interactive else None,
                  openapi_url=f"{s.api_prefix}/openapi.json" if interactive else None,
                  description="Multi-tenant UnityRAG Platform API. Tenant identity is always resolved "
                              "server-side; PostgreSQL row-level security enforces isolation on every request.")
    app.add_middleware(CORSMiddleware, allow_origins=s.cors_origins, allow_credentials=True,
                       allow_methods=["GET", "POST", "PUT", "DELETE"], allow_headers=["Authorization", "Content-Type",
                                                                                     "X-Correlation-ID", "Idempotency-Key",
                                                                                     "traceparent", "tracestate"],
                       expose_headers=["X-Correlation-ID", "X-Trace-ID", "Content-Disposition"])
    app.add_middleware(CorrelationMiddleware)
    install_error_handlers(app)
    for module in (auth, users, roles, permissions, departments, groups, documents, collections, ingestion, search, chat,
                   conversations, admin, analytics, audit, evaluation, tenants, platform_admin):
        app.include_router(module.router, prefix=s.api_prefix)
        if hasattr(module, "admin_router"):
            app.include_router(module.admin_router, prefix=s.api_prefix)
    app.include_router(health.router)
    return app


app = create_app()
