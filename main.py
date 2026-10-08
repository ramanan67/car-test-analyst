"""
main.py
FastAPI application entry point for the Automotive Prototype Testing Analytics Platform.

Registers all routers, middleware, lifespan events, and health check endpoint.
"""
from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.routers import analytics, auth, criteria, test_runs, vehicles
from app.core.config import get_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)
settings = get_settings()


# ---------------------------------------------------------------------------
# Application Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle management."""
    logger.info("🚗 %s v%s starting up...", settings.APP_NAME, settings.APP_VERSION)
    logger.info("Environment: %s | Debug: %s", settings.ENVIRONMENT, settings.DEBUG)
    yield
    logger.info("🛑 Application shutdown complete.")


# ---------------------------------------------------------------------------
# FastAPI Application
# ---------------------------------------------------------------------------

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="""
## Automotive Prototype Testing Analytics Platform

End-to-end analytics workflow for automotive prototype validation:

- **Module A** – Vehicle Master Configuration & Pre-Test Intake
- **Module B** – Multi-format Telemetry Ingestion (CSV, Parquet, XLSX, MDF4)
- **Module C** – Dynamic Criteria Evaluation Engine (PASS / MARGINAL_DEVIATION / FAIL)
- **Module D** – Visual Analytics, Run Comparison Matrix & PDF/Excel Sign-Off Export

### Authentication
All endpoints (except `/health` and `/auth/login`) require a JWT bearer token.
Obtain a token via `POST /api/v1/auth/login`.

### Role Hierarchy
`VIEWER` < `TECHNICIAN` < `TEST_ANALYST` < `LEAD_ENGINEER` < `ADMIN`
    """,
    openapi_url="/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(GZipMiddleware, minimum_size=1000)


@app.middleware("http")
async def add_request_timing(request: Request, call_next):
    """Inject X-Process-Time header into every response."""
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start) * 1000
    response.headers["X-Process-Time-Ms"] = f"{duration_ms:.2f}"
    return response


# ---------------------------------------------------------------------------
# Global Exception Handlers
# ---------------------------------------------------------------------------

@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": str(exc)},
    )


@app.exception_handler(PermissionError)
async def permission_error_handler(request: Request, exc: PermissionError):
    return JSONResponse(
        status_code=status.HTTP_403_FORBIDDEN,
        content={"detail": str(exc)},
    )


# ---------------------------------------------------------------------------
# Health Check
# ---------------------------------------------------------------------------

@app.get("/health", tags=["System"], include_in_schema=True)
async def health_check():
    """
    System health probe. Returns service status and version.
    Used by Docker healthcheck and Kubernetes liveness probe.
    """
    return {
        "status": "healthy",
        "service": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "environment": settings.ENVIRONMENT,
    }


# ---------------------------------------------------------------------------
# API Router Registration
# ---------------------------------------------------------------------------

API_PREFIX = "/api/v1"

app.include_router(auth.router, prefix=API_PREFIX)
app.include_router(vehicles.router, prefix=API_PREFIX)
app.include_router(criteria.router, prefix=API_PREFIX)
app.include_router(test_runs.router, prefix=API_PREFIX)
app.include_router(analytics.router, prefix=API_PREFIX)
