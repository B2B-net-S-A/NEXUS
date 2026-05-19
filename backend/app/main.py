import logging
import os
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

# Eager-import the models package so every ORM class is registered in the
# SQLAlchemy registry before lifespan's create_all / configure_mappers runs.
# Without this, cross-file relationship("X", ...) strings (e.g. rejection_email
# → Email from m365) fail to resolve when no imported router pulled in the
# target class.
import app.models  # noqa: F401

from app.api import (
    auth,
    candidates,
    jobs,
    clients,
    clients_team,
    pipeline,
    notes,
    contracts,
    contractors,
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
from app.api import user_email_templates as user_email_templates_api
from app.api import postings
from app.api import calls
from app.api import cloudtalk as cloudtalk_api
from app.api import reports
from app.api import client_knowledge
from app.api import client_materials
from app.api import client_framework_contracts
from app.api import client_contract_amendments
from app.api import client_orders as client_orders_api
from app.api import my_clients as my_clients_api
from app.api import my_relationships as my_relationships_api
from app.api import hiring_managers_analytics as hiring_managers_api
from app.api import admin_clients_overview as admin_clients_overview_api
from app.api import admin_snapshot
from app.api import required_documents
from app.api import screenings
from app.api import contacts
from app.api import prep_kit
from app.api import ai_writer
from app.api import talent_pools
from app.api import public_engagement
from app.api import public_interview_confirmation
from app.api import cv_generator_b2b
from app.api import dynareporter_profile
from app.api import dynareporter_kpi_body_leasing
from app.api import dynareporter_kpi_sales
from app.api import dynareporter_kpi_delivery_lead
from app.api import dynareporter_placements
from app.api import dynareporter_clients_mrr
from app.api import dynareporter_competitions
from app.api import dynareporter_przetargi
from app.api import dynareporter_board
from app.api import dynareporter_sales_mgmt
from app.api import dynareporter_mindy
from app.api import dynareporter_upload
from app.api import dynareporter_redirect
from app.api import dynareporter_rekrutacja
from app.api import dynareporter_delivery_lead_dashboard
from app.api import dynareporter_board_dashboard
from app.api import dynareporter_admin_dashboard
from app.api import dynareporter_admin_config
from app.api import candidate_stage_cv as candidate_stage_cv_api
from app.api import calendar
from app.api import notifications
from app.api import import_export
from app.api import fireflies
from app.api import ws
from app.api import matching
from app.api import pipeline_templates
from app.api import recommendations
from app.api import cv_match_preview
from app.api import phase3_actions
from app.api import skills as skills_api
from app.api import scoring_weights as scoring_weights_api
from app.api import public_share as public_share_api
from app.api import phase3
from app.api import phase4
from app.api import phase5
from app.api import admin_import
from app.api import kpis as kpis_api
from app.api import onboarding as onboarding_api
from app.api import procedures as procedures_api
from app.api import proposals as proposals_api
from app.api import proposals_bulk as proposals_bulk_api
from app.api import invite_links as invite_links_api
from app.api import users as users_api
from app.api import settings as app_settings_api
from app.api import champion_suggestions as champion_suggestions_api
from app.api import rate_benchmarks as rate_benchmarks_api
from app.api import team_structure as team_structure_api
from app.api import competitions as competitions_api
from app.api import linkedin_metrics as linkedin_metrics_api
from app.api import competence_categories as competence_categories_api
from app.api import interview_questions as interview_questions_api
from app.api import interview_feedback as interview_feedback_api
from app.api import rejection_emails as rejection_emails_api
from app.api import microsoft365 as microsoft365_api
from app.api import auth_microsoft as auth_microsoft_api
from app.api import email_threads as email_threads_api
from app.api import marketplace as marketplace_api
from app.api import presence as presence_api
from app.api import job_chat as job_chat_api
from app.api import candidate_chat as candidate_chat_api
from app.api import admin_chats as admin_chats_api
from app.api import stage_notification_rules as stage_notification_rules_api
from app.api import autenti as autenti_api
from app.api import ai_settings as ai_settings_api
from app.api import oauth_clients as oauth_clients_api
from app.api import oauth_token as oauth_token_api
from app.api import candidate_sources as candidate_sources_api
from app.api import candidates_bulk as candidates_bulk_api
from app.api import dictionaries as dictionaries_api
from app.api import entity_fields as entity_fields_api
from app.api import teams_channels as teams_channels_api

# Force-load every SQLAlchemy model into Base.metadata so FKs across tables
# (e.g. scheduled_rejection_emails.email_id → emails.id from m365.py) can
# resolve during `Base.metadata.create_all()` in DEBUG lifespan.
import app.models as _models  # noqa: F401

logger = logging.getLogger(__name__)


# ── Sentry (optional) ──────────────────────────────────────────────────────
# AsyncioIntegration propagates breadcrumbs/scope across `asyncio.create_task`
# so the background tasks spawned in lifespan capture their own context.
# LoggingIntegration mirrors `logging.error()` calls into Sentry as breadcrumbs
# (level=INFO) and events (level=ERROR) — bridges JSON logs to the Sentry UI.
# FastApiIntegration tags transactions by route (transaction_style="endpoint").
# release=$GIT_SHA matches the Compass/Atlas pattern so deploy markers in
# Grafana correlate across all 3 apps.
if settings.SENTRY_DSN:
    try:
        import sentry_sdk
        from sentry_sdk.integrations.asyncio import AsyncioIntegration
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.logging import LoggingIntegration

        sentry_sdk.init(
            dsn=settings.SENTRY_DSN,
            environment=settings.SENTRY_ENVIRONMENT,
            release=os.getenv("GIT_SHA"),
            traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.1")),
            profiles_sample_rate=float(os.getenv("SENTRY_PROFILES_SAMPLE_RATE", "0.1")),
            send_default_pii=False,
            integrations=[
                FastApiIntegration(transaction_style="endpoint"),
                AsyncioIntegration(),
                LoggingIntegration(
                    level=logging.INFO,
                    event_level=logging.ERROR,
                ),
            ],
        )
        logger.info(
            "Sentry initialized for environment=%s release=%s",
            settings.SENTRY_ENVIRONMENT,
            os.getenv("GIT_SHA", "unknown"),
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
    from app.tasks.competition_autofreeze import competition_autofreeze_loop
    from app.tasks.cc_centroid_sync import cc_centroid_sync_loop
    from app.tasks.kpi_coach_nudger import kpi_coach_nudger_loop
    from app.tasks.triggers_loop import notification_triggers_loop
    from app.tasks.rejection_email_loop import rejection_email_loop
    from app.tasks.linkedin_sync import linkedin_sync_loop
    from app.tasks.microsoft365_sync import (
        graph_subscription_renewal_loop,
        meeting_recording_discovery_loop,
        microsoft365_sync_loop,
        rematch_unlinked_emails_loop,
    )
    from app.tasks.marketplace_sweeper import marketplace_sweeper_loop
    from app.tasks.chat_email_fallback import chat_email_fallback_loop
    from app.tasks.autenti_expiry_sweeper import autenti_sweeper_loop
    from app.tasks.dl_portal_expiry_scanner import dl_portal_expiry_loop
    from app.tasks.cloudtalk_sync import cloudtalk_sync_loop
    from app.services.fx_service import fx_refresh_loop

    # Background tasks registry — exposed via app.state so /api/admin/snapshot
    # can introspect running/expected counts. Order matches shutdown order.
    # Autenti sweeper exits immediately when AUTENTI_ENABLED=false; safe to
    # spawn unconditionally (mirrors LinkedIn/M365 patterns).
    app.state.background_tasks = {
        "calendar_reminder": asyncio.create_task(calendar_reminder_loop()),
        "match_history_ttl": asyncio.create_task(match_history_ttl_loop()),
        "slack_sla_alerts": asyncio.create_task(slack_sla_alerts_loop()),
        "contract_alerts": asyncio.create_task(contract_alerts_loop()),
        "fx_refresh": asyncio.create_task(fx_refresh_loop()),
        "competition_autofreeze": asyncio.create_task(competition_autofreeze_loop()),
        "cc_centroid_sync": asyncio.create_task(cc_centroid_sync_loop()),
        "kpi_coach_nudger": asyncio.create_task(kpi_coach_nudger_loop()),
        "notification_triggers": asyncio.create_task(notification_triggers_loop()),
        "rejection_email": asyncio.create_task(rejection_email_loop()),
        "linkedin_sync": asyncio.create_task(linkedin_sync_loop()),
        "microsoft365_sync": asyncio.create_task(microsoft365_sync_loop()),
        "m365_rematch": asyncio.create_task(rematch_unlinked_emails_loop()),
        "m365_webhook_renewal": asyncio.create_task(graph_subscription_renewal_loop()),
        "m365_recording_discovery": asyncio.create_task(
            meeting_recording_discovery_loop()
        ),
        "marketplace_sweeper": asyncio.create_task(marketplace_sweeper_loop()),
        "chat_email_fallback": asyncio.create_task(chat_email_fallback_loop()),
        "autenti_sweeper": asyncio.create_task(autenti_sweeper_loop()),
        "dl_portal_expiry": asyncio.create_task(dl_portal_expiry_loop()),
        "cloudtalk_sync": asyncio.create_task(cloudtalk_sync_loop()),
    }

    yield

    # Shutdown
    tasks = tuple(app.state.background_tasks.values())
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
    # Allow Chrome extensions (NEXUS LinkedIn helper, etc.) — Chrome IDs are
    # 32-char lowercase a-p strings (base32-ish). Regex covers both dev
    # (load-unpacked) and Web Store production IDs.
    allow_origin_regex=r"^chrome-extension://[a-p]{32}$",
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
)

# Register routers
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(candidates.router, prefix="/api/candidates", tags=["candidates"])
app.include_router(public_engagement.router, prefix="/api", tags=["public-engagement"])
app.include_router(
    public_interview_confirmation.router,
    prefix="/api",
    tags=["public-interview-confirmation"],
)
app.include_router(jobs.router, prefix="/api/jobs", tags=["jobs"])
app.include_router(clients.router, prefix="/api/clients", tags=["clients"])
app.include_router(clients_team.router, prefix="/api/clients", tags=["clients-team"])
app.include_router(
    client_framework_contracts.router,
    prefix="/api/clients",
    tags=["client-framework-contracts"],
)
app.include_router(
    client_contract_amendments.router,
    prefix="/api/clients",
    tags=["client-contract-amendments"],
)
app.include_router(
    client_orders_api.router,
    prefix="/api/clients",
    tags=["client-orders"],
)
app.include_router(
    my_clients_api.router,
    prefix="/api/my-clients",
    tags=["my-clients"],
)
app.include_router(
    admin_clients_overview_api.router,
    prefix="/api/admin/clients-overview",
    tags=["admin-clients-overview"],
)
app.include_router(
    my_relationships_api.router,
    prefix="/api/my-relationships",
    tags=["my-relationships"],
)
app.include_router(
    hiring_managers_api.router,
    prefix="/api/reports/hiring-managers",
    tags=["hiring-managers-analytics"],
)
app.include_router(
    admin_snapshot.router,
    prefix="/api/admin",
    tags=["admin-snapshot"],
)
app.include_router(pipeline.router, prefix="/api/pipeline", tags=["pipeline"])
app.include_router(
    rejection_emails_api.router,
    prefix="/api/rejection-emails",
    tags=["rejection-emails"],
)
app.include_router(notes.router, prefix="/api/notes", tags=["notes"])
app.include_router(contracts.router, prefix="/api/contracts", tags=["contracts"])
app.include_router(contractors.router, prefix="/api/contractors", tags=["contractors"])
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
app.include_router(
    user_email_templates_api.router,
    prefix="/api/user-email-templates",
    tags=["user-email-templates"],
)
app.include_router(postings.router, prefix="/api", tags=["postings"])
app.include_router(calls.router, prefix="/api", tags=["calls"])
app.include_router(cloudtalk_api.router, prefix="/api/cloudtalk", tags=["cloudtalk"])
app.include_router(
    teams_channels_api.router,
    prefix="/api/teams-channels",
    tags=["teams-channels"],
)
app.include_router(reports.router, prefix="/api/reports", tags=["reports"])
app.include_router(
    dynareporter_profile.router,
    prefix="/api/dynareporter/profile",
    tags=["dynareporter"],
)
app.include_router(
    dynareporter_kpi_body_leasing.router,
    prefix="/api/dynareporter/kpi/body-leasing",
    tags=["dynareporter"],
)
app.include_router(
    dynareporter_kpi_sales.router,
    prefix="/api/dynareporter/kpi/sales",
    tags=["dynareporter"],
)
app.include_router(
    dynareporter_kpi_delivery_lead.router,
    prefix="/api/dynareporter/kpi/delivery-lead",
    tags=["dynareporter"],
)
app.include_router(
    dynareporter_placements.router,
    prefix="/api/dynareporter/placements",
    tags=["dynareporter"],
)
app.include_router(
    dynareporter_clients_mrr.router,
    prefix="/api/dynareporter/clients-mrr",
    tags=["dynareporter"],
)
app.include_router(
    dynareporter_competitions.router,
    prefix="/api/dynareporter/competitions",
    tags=["dynareporter"],
)
app.include_router(
    dynareporter_przetargi.router,
    prefix="/api/dynareporter/przetargi",
    tags=["dynareporter"],
)
app.include_router(
    dynareporter_board.router,
    prefix="/api/dynareporter/board",
    tags=["dynareporter"],
)
app.include_router(
    dynareporter_sales_mgmt.router,
    prefix="/api/dynareporter/sales-mgmt",
    tags=["dynareporter"],
)
app.include_router(
    dynareporter_mindy.router,
    prefix="/api/dynareporter/mindy",
    tags=["dynareporter"],
)
app.include_router(
    dynareporter_upload.router,
    prefix="/api/dynareporter/upload",
    tags=["dynareporter"],
)
app.include_router(
    dynareporter_rekrutacja.router,
    prefix="/api/dynareporter/rekrutacja",
    tags=["dynareporter"],
)
app.include_router(
    dynareporter_delivery_lead_dashboard.router,
    prefix="/api/dynareporter/delivery-lead-dashboard",
    tags=["dynareporter"],
)
app.include_router(
    dynareporter_board_dashboard.router,
    prefix="/api/dynareporter/board-dashboard",
    tags=["dynareporter"],
)
app.include_router(
    dynareporter_admin_dashboard.router,
    prefix="/api/dynareporter/admin-dashboard",
    tags=["dynareporter"],
)
app.include_router(
    dynareporter_admin_config.router,
    prefix="/api/dynareporter/admin-config",
    tags=["dynareporter"],
)
app.include_router(
    dynareporter_redirect.router,
    prefix="/api/dynareporter",
    tags=["dynareporter"],
)
app.include_router(client_knowledge.router, prefix="/api", tags=["client-knowledge"])
app.include_router(client_materials.router, prefix="/api", tags=["client-materials"])
app.include_router(
    required_documents.router, prefix="/api", tags=["required-documents"]
)
app.include_router(screenings.router, prefix="/api", tags=["screenings"])
app.include_router(contacts.router, prefix="/api", tags=["contacts"])
app.include_router(prep_kit.router, prefix="/api", tags=["prep-kit"])
app.include_router(
    interview_questions_api.router, prefix="/api", tags=["interview-questions"]
)
app.include_router(ai_writer.router, prefix="/api", tags=["ai-writer"])
app.include_router(talent_pools.router, prefix="/api", tags=["talent-pools"])
app.include_router(marketplace_api.router, prefix="/api", tags=["marketplace"])
app.include_router(cv_generator_b2b.router, prefix="/api", tags=["cv-generator-b2b"])
app.include_router(
    candidate_stage_cv_api.router, prefix="/api", tags=["candidate-stage-cv"]
)
app.include_router(calendar.router, prefix="/api", tags=["calendar"])
app.include_router(notifications.router, prefix="/api", tags=["notifications"])
app.include_router(import_export.router, prefix="/api", tags=["import-export"])
app.include_router(fireflies.router, prefix="/api", tags=["fireflies"])
app.include_router(ws.router, tags=["websocket"])
app.include_router(presence_api.router, tags=["presence"])
app.include_router(job_chat_api.router, prefix="/api/jobs", tags=["job-chat"])
app.include_router(
    candidate_chat_api.router, prefix="/api/candidates", tags=["candidate-chat"]
)
app.include_router(admin_chats_api.router, prefix="/api/admin", tags=["admin-chats"])
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
app.include_router(
    stage_notification_rules_api.template_router,
    prefix="/api/pipeline-templates",
    tags=["stage-notification-rules"],
)
app.include_router(
    stage_notification_rules_api.client_router,
    prefix="/api/clients",
    tags=["stage-notification-overrides"],
)
app.include_router(recommendations.router, prefix="/api", tags=["recommendations"])
app.include_router(cv_match_preview.router, prefix="/api", tags=["recommendations"])
app.include_router(phase3_actions.router, prefix="/api", tags=["recommendations"])
app.include_router(phase3.router, prefix="/api", tags=["phase3"])
app.include_router(phase4.router, prefix="/api", tags=["phase4"])
app.include_router(phase5.router, prefix="/api", tags=["phase5"])
app.include_router(admin_import.router, prefix="/api", tags=["admin-import"])
app.include_router(kpis_api.router, prefix="/api/kpis", tags=["kpis"])
app.include_router(onboarding_api.router, prefix="/api/users", tags=["onboarding"])
app.include_router(users_api.router, prefix="/api/users", tags=["users"])
app.include_router(procedures_api.router, prefix="/api", tags=["procedures"])
app.include_router(proposals_api.router, prefix="/api", tags=["proposals"])
app.include_router(proposals_bulk_api.router, prefix="/api", tags=["proposals"])
app.include_router(
    invite_links_api.router, prefix="/api/invite-links", tags=["invite-links"]
)
app.include_router(app_settings_api.router, prefix="/api/settings", tags=["settings"])
app.include_router(
    rate_benchmarks_api.router,
    prefix="/api/rate-benchmarks",
    tags=["rate-benchmarks"],
)
app.include_router(
    team_structure_api.router,
    prefix="/api/team-structure",
    tags=["team-structure"],
)
app.include_router(
    competitions_api.router,
    prefix="/api/competitions",
    tags=["competitions"],
)
app.include_router(
    linkedin_metrics_api.router,
    prefix="/api/linkedin-metrics",
    tags=["linkedin-metrics"],
)
app.include_router(
    competence_categories_api.router,
    prefix="/api/competence-categories",
    tags=["competence-categories"],
)
# champion_suggestions.router already declares its own `/champion-suggestions`
# prefix, so we mount it under `/api`.
app.include_router(champion_suggestions_api.router, prefix="/api")
app.include_router(
    interview_feedback_api.router, prefix="/api", tags=["interview-feedback"]
)

# Phase M365.1 — Microsoft 365 integration (OAuth + inbox threads + calendar)
if settings.M365_INTEGRATION_ENABLED:
    app.include_router(
        microsoft365_api.router, prefix="/api/microsoft365", tags=["microsoft365"]
    )
    app.include_router(email_threads_api.router, prefix="/api", tags=["emails"])
    # Faza B — "Sign in with Microsoft" SSO. Reuses M365 Azure AD app.
    app.include_router(
        auth_microsoft_api.router,
        prefix="/api/auth/microsoft",
        tags=["auth-microsoft"],
    )

# Phase Autenti.1 — e-signature integration (Autenti, eIDAS-compliant).
# Router mounted unconditionally so write/IO endpoints can return 503 at
# runtime when AUTENTI_ENABLED=false (rolling rollback friendly — Autenti
# retries 5xx, so webhook payload survives a temporary kill-switch).
# Each write/IO handler invokes _require_enabled() internally; read-only
# GETs stay live so the FE can show empty timelines.
app.include_router(autenti_api.router, prefix="/api/autenti", tags=["autenti"])

# AI features panel (Settings → AI). Admin-only. Routes mounted at
# /api/settings/ai (prefix is declared on the router itself; we add /api here).
app.include_router(ai_settings_api.router, prefix="/api", tags=["ai-settings"])

# OAuth2 client manager (Settings → API integration). Admin-only CRUD.
app.include_router(oauth_clients_api.router, prefix="/api", tags=["oauth-clients"])

# OAuth2 token endpoint (client_credentials grant). Public — auth is via
# client_id + client_secret in the request body, not Authorization header.
app.include_router(oauth_token_api.router, prefix="/api", tags=["oauth-token"])

# Multi-source attribution (#4): /api/candidates/{cid}/sources + reports.
app.include_router(
    candidate_sources_api.router, prefix="/api", tags=["candidate-sources"]
)
app.include_router(
    candidate_sources_api.reports_router,
    prefix="/api/reports",
    tags=["reports-sources"],
)

# Bulk actions on candidates list (#3): single dispatch endpoint
# POST /api/candidates/bulk routes to per-action handlers.
app.include_router(candidates_bulk_api.router, prefix="/api", tags=["candidates-bulk"])

# Editable taxonomies (#8): Settings → Słowniki + GET /api/dictionaries/{slug}
app.include_router(dictionaries_api.router, prefix="/api", tags=["dictionaries"])

# Custom-field schema editor (#7): Settings → Konfiguracja pól.
app.include_router(entity_fields_api.router, prefix="/api", tags=["entity-fields"])


@app.get("/health")
async def health_check():
    """Legacy healthcheck. Alias for /api/health on shape transition (7 days).

    Kept for backwards compatibility with uptime-probe.yml and any external
    monitor that grepped `.status == "ok"` shape. Prefer /api/health which
    follows the standard shape from ~/.claude/rules/deployment.md.
    """
    return {"status": "ok", "app": "Nexus ATS", "version": "0.3.0"}


def _resolve_deployed_at() -> str:
    """Return ISO-8601 deployedAt string.

    Prefer BUILT_AT env var when it looks like a valid ISO timestamp (set by
    Coolify/CI). Fallback to filesystem mtime of __file__ — kontener freshly
    rebuilt at each deploy gets fresh mtime, so health "świeżość" reflects
    actual deploy moment instead of static env var that may be stale.
    """
    import os
    from datetime import datetime, timezone

    explicit = os.environ.get("BUILT_AT", "").strip()
    if explicit and explicit != "unknown":
        try:
            datetime.fromisoformat(explicit.replace("Z", "+00:00"))
            return explicit
        except ValueError:
            pass
    try:
        mtime = os.path.getmtime(__file__)
        return datetime.fromtimestamp(mtime, tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
    except OSError:
        return "unknown"


@app.get("/api/health")
async def api_health_check():
    """Standard healthcheck per ~/.claude/rules/deployment.md.

    Shape: {status, version, deployedAt, checks: {database, m365, cloudtalk, autenti}}.
    HTTP 503 only when `database` is unhealthy (uptime-probe contract);
    `m365` is informational and does not affect the gate.
    Database ping is bounded to 2s; M365 connection count to 1s.
    """
    import asyncio
    import os

    from fastapi import status as http_status
    from fastapi.responses import JSONResponse
    from sqlalchemy import func, select, text

    from app.core.config import settings
    from app.core.database import AsyncSessionLocal

    checks: dict[str, str] = {}

    try:
        async with AsyncSessionLocal() as session:
            await asyncio.wait_for(session.execute(text("SELECT 1")), timeout=2.0)
        checks["database"] = "healthy"
    except Exception:
        checks["database"] = "unhealthy"

    # M365 status — informational only (does not affect HTTP 503 gate).
    if not settings.M365_INTEGRATION_ENABLED:
        checks["m365"] = "disabled"
    elif not settings.M365_SYNC_LOOP_ENABLED:
        checks["m365"] = "degraded"
    else:
        try:
            from app.models.m365 import M365Connection

            async with AsyncSessionLocal() as session:
                count = await asyncio.wait_for(
                    session.scalar(
                        select(func.count())
                        .select_from(M365Connection)
                        .where(M365Connection.is_active.is_(True))
                    ),
                    timeout=1.0,
                )
            checks["m365"] = "healthy" if (count or 0) >= 1 else "degraded"
        except Exception:
            checks["m365"] = "degraded"

    # M365 encryption — separate from `m365` because a misconfigured key
    # silently breaks every refresh (see Sentry NEXUS-BE-1, 2026-05). Round-trip
    # encrypt→decrypt with a sentinel so "key set" alone is not enough.
    if settings.M365_INTEGRATION_ENABLED:
        try:
            from app.core.encryption import (
                TokenCipherNotConfigured,
                get_token_cipher,
            )

            cipher = get_token_cipher()
            if cipher.decrypt(cipher.encrypt("ping")) == "ping":
                checks["m365_encryption"] = "healthy"
            else:
                checks["m365_encryption"] = "unhealthy"
        except TokenCipherNotConfigured:
            checks["m365_encryption"] = "unhealthy"
        except Exception:
            checks["m365_encryption"] = "unhealthy"

    # CloudTalk status — informational only. `unconfigured` while kill-switch
    # is off OR API key id is empty (default state pre-provisioning).
    if not settings.CLOUDTALK_ENABLED or not settings.CLOUDTALK_API_KEY_ID:
        checks["cloudtalk"] = "unconfigured"
    else:
        try:
            from app.services.cloudtalk import CloudTalkClient, CloudTalkConfig

            cfg = CloudTalkConfig.from_settings()
            async with CloudTalkClient(cfg) as ct:
                await asyncio.wait_for(ct.ping(), timeout=2.0)
            checks["cloudtalk"] = "healthy"
        except asyncio.TimeoutError:
            checks["cloudtalk"] = "degraded"
        except Exception:
            checks["cloudtalk"] = "unhealthy"

    # Autenti status — informational only. Config-only probe (no network call
    # to keep uptime-probe latency low — full ping lives at /api/autenti/health
    # which is auth-protected).
    if not settings.AUTENTI_ENABLED:
        checks["autenti"] = "unconfigured"
    elif not settings.AUTENTI_CLIENT_ID or not settings.AUTENTI_CLIENT_SECRET:
        checks["autenti"] = "misconfigured"
    else:
        checks["autenti"] = "healthy"

    db_healthy = checks.get("database") == "healthy"
    overall = "healthy" if db_healthy else "unhealthy"

    return JSONResponse(
        content={
            "status": overall,
            "version": os.environ.get("GIT_SHA", "unknown"),
            "deployedAt": _resolve_deployed_at(),
            "checks": checks,
        },
        status_code=http_status.HTTP_200_OK
        if db_healthy
        else http_status.HTTP_503_SERVICE_UNAVAILABLE,
    )
