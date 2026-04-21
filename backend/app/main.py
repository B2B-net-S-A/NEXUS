import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings
from app.core.database import engine, Base
from app.core.logging_config import configure_json_logging
from app.core.rate_limit import limiter
from app.api import (
    auth,
    candidates,
    jobs,
    clients,
    pipeline,
    notes,
    contracts,
    contract_analytics,
    contract_templates,
    fx,
    invoices,
    rate_cards,
    dashboard,
    search,
)
from app.api import activities
from app.api import admin
from app.api import emails
from app.api import postings
from app.api import calls
from app.api import reports
from app.api import client_knowledge
from app.api import screenings
from app.api import contacts
from app.api import prep_kit
from app.api import ai_writer
from app.api import talent_pools
from app.api import cv_generator
from app.api import calendar
from app.api import notifications
from app.api import import_export
from app.api import fireflies
from app.api import ws
from app.api import matching
from app.api import pipeline_templates
from app.api import recommendations
from app.api import skills as skills_api
from app.api import scoring_weights as scoring_weights_api
from app.api import public_share as public_share_api
from app.api import phase3
from app.api import phase4
from app.api import phase5
from app.api import admin_import

logger = logging.getLogger(__name__)


# ── Sentry (optional) ──────────────────────────────────────────────────────
if settings.SENTRY_DSN:
    try:
        import sentry_sdk

        sentry_sdk.init(
            dsn=settings.SENTRY_DSN,
            environment=settings.SENTRY_ENVIRONMENT,
            traces_sample_rate=0.1,
            profiles_sample_rate=0.1,
        )
        logger.info(
            "Sentry initialized for environment=%s", settings.SENTRY_ENVIRONMENT
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("Sentry init failed: %s", e)


# ── Security headers middleware ────────────────────────────────────────────
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Adds conservative security response headers on every reply.

    Defaults are safe for an API + Next.js app behind a reverse proxy with TLS.
    """

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault(
            "Referrer-Policy", "strict-origin-when-cross-origin"
        )
        response.headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
        )
        if not settings.DEBUG:
            # HSTS only in prod — avoids pinning localhost dev to HTTPS.
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=63072000; includeSubDomains; preload",
            )
            # CSP for API responses — tight because we don't serve HTML here.
            response.headers.setdefault(
                "Content-Security-Policy",
                "default-src 'none'; frame-ancestors 'none';",
            )
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Install JSON log formatter (no-op in DEBUG mode). Must happen early
    # so every subsequent log line uses structured JSON.
    configure_json_logging(debug=settings.DEBUG)

    # Startup: create tables if not exists.
    # Only in DEBUG — production deploys must run `alembic upgrade head` explicitly.
    # See plan Faza 1.1 for the Alembic reset that replaces this shortcut entirely.
    if settings.DEBUG:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    # Startup: ensure Qdrant collection exists
    import asyncio
    from app.services.embedding_service import init_qdrant_collection

    try:
        await asyncio.to_thread(init_qdrant_collection)
    except Exception as e:
        logger.warning("Qdrant init skipped: %s", e)

    # Phase B1: preload skill alias map into scoring engine
    try:
        from app.services.skill_taxonomy_loader import refresh_alias_map

        count = await refresh_alias_map()
        logger.info("Skill alias map loaded: %d aliases", count)
    except Exception as e:
        logger.warning("Skill alias map preload skipped: %s", e)

    # Start calendar reminder background task
    from app.api.calendar import calendar_reminder_loop
    from app.tasks.match_history_ttl import match_history_ttl_loop
    from app.tasks.slack_sla_alerts import slack_sla_alerts_loop
    from app.tasks.contract_alerts import contract_alerts_loop
    from app.services.fx_service import fx_refresh_loop

    reminder_task = asyncio.create_task(calendar_reminder_loop())
    ttl_task = asyncio.create_task(match_history_ttl_loop())
    slack_task = asyncio.create_task(slack_sla_alerts_loop())
    contract_task = asyncio.create_task(contract_alerts_loop())
    fx_task = asyncio.create_task(fx_refresh_loop())

    yield

    # Shutdown
    tasks = (reminder_task, ttl_task, slack_task, contract_task, fx_task)
    for t in tasks:
        t.cancel()
    for t in tasks:
        try:
            await t
        except asyncio.CancelledError:
            pass
    await engine.dispose()


app = FastAPI(
    title="Nexus ATS",
    description="Modern ATS for IT staffing agencies (body leasing) — B2B.net",
    version="0.3.0",
    lifespan=lifespan,
    redirect_slashes=False,
)

# Rate limiter (attach first so it wraps everything)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(SecurityHeadersMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
)

# Register routers
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(candidates.router, prefix="/api/candidates", tags=["candidates"])
app.include_router(jobs.router, prefix="/api/jobs", tags=["jobs"])
app.include_router(clients.router, prefix="/api/clients", tags=["clients"])
app.include_router(pipeline.router, prefix="/api/pipeline", tags=["pipeline"])
app.include_router(notes.router, prefix="/api/notes", tags=["notes"])
app.include_router(contracts.router, prefix="/api/contracts", tags=["contracts"])
app.include_router(rate_cards.router, prefix="/api/rate-cards", tags=["rate-cards"])
app.include_router(
    contract_analytics.router,
    prefix="/api/contract-analytics",
    tags=["contract-analytics"],
)
app.include_router(
    contract_templates.router,
    prefix="/api/contract-templates",
    tags=["contract-templates"],
)
app.include_router(invoices.router, prefix="/api/invoices", tags=["invoices"])
app.include_router(fx.router, prefix="/api/fx", tags=["fx"])
app.include_router(dashboard.router, prefix="/api/dashboard", tags=["dashboard"])
app.include_router(search.router, prefix="/api/search", tags=["search"])
app.include_router(activities.router, prefix="/api/activities", tags=["activities"])
app.include_router(admin.router, prefix="/api/admin", tags=["admin"])
app.include_router(emails.router, prefix="/api", tags=["emails"])
app.include_router(postings.router, prefix="/api", tags=["postings"])
app.include_router(calls.router, prefix="/api", tags=["calls"])
app.include_router(reports.router, prefix="/api/reports", tags=["reports"])
app.include_router(client_knowledge.router, prefix="/api", tags=["client-knowledge"])
app.include_router(screenings.router, prefix="/api", tags=["screenings"])
app.include_router(contacts.router, prefix="/api", tags=["contacts"])
app.include_router(prep_kit.router, prefix="/api", tags=["prep-kit"])
app.include_router(ai_writer.router, prefix="/api", tags=["ai-writer"])
app.include_router(talent_pools.router, prefix="/api", tags=["talent-pools"])
app.include_router(cv_generator.router, prefix="/api", tags=["cv-generator"])
app.include_router(calendar.router, prefix="/api", tags=["calendar"])
app.include_router(notifications.router, prefix="/api", tags=["notifications"])
app.include_router(import_export.router, prefix="/api", tags=["import-export"])
app.include_router(fireflies.router, prefix="/api", tags=["fireflies"])
app.include_router(ws.router, tags=["websocket"])
app.include_router(matching.router, prefix="/api", tags=["matching"])
app.include_router(skills_api.router, prefix="/api/skills", tags=["skills"])
app.include_router(
    scoring_weights_api.router,
    prefix="/api/scoring-weights",
    tags=["scoring-weights"],
)
app.include_router(
    public_share_api.router,
    prefix="/api/public",
    tags=["public-share"],
)
app.include_router(
    pipeline_templates.router,
    prefix="/api/pipeline-templates",
    tags=["pipeline-templates"],
)
app.include_router(recommendations.router, prefix="/api", tags=["recommendations"])
app.include_router(phase3.router, prefix="/api", tags=["phase3"])
app.include_router(phase4.router, prefix="/api", tags=["phase4"])
app.include_router(phase5.router, prefix="/api", tags=["phase5"])
app.include_router(admin_import.router, prefix="/api", tags=["admin-import"])


@app.get("/health")
async def health_check():
    return {"status": "ok", "app": "Nexus ATS", "version": "0.3.0"}
