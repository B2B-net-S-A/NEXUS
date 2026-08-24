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
    candidate_contact,
    candidate_pins,
    candidate_scoring,
    candidate_activity_summary,
    candidate_identity_quarantine,
    candidate_profile_facts,
    jobs,
    clients,
    client_directory,
    clients_team,
    pipeline,
    notes,
    contracts,
    contractors,
    contract_analytics,
    contract_templates,
    cortex,
    fx,
    invoices,
    rate_cards,
    dashboard,
    search,
)
from app.api import activities
from app.api import admin
from app.api import analytics_v1 as analytics_v1_api
from app.api import dashboard_v2 as dashboard_v2_api
from app.api import finance as finance_api
from app.api import financial_adjustments as financial_adjustments_api
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
from app.api import client_order_groups as client_order_groups_api
from app.api import client_orders as client_orders_api
from app.api import dl_alerts as dl_alerts_api
from app.api import md_consumption as md_consumption_api
from app.api import my_clients as my_clients_api
from app.api import my_relationships as my_relationships_api
from app.api import hiring_managers_analytics as hiring_managers_api
from app.api import admin_clients_overview as admin_clients_overview_api
from app.api import admin_snapshot
from app.api import admin_pipeline_inventory
from app.api import admin_process_adoption
from app.api import admin_engagement_inventory
from app.api import admin_candidate_pii_orphans
from app.api import admin_index_coverage, admin_schema_drift
from app.api import admin_match_score_repair
from app.api import admin_workflows
from app.api import admin_recruitment_processes
from app.api import ai_matching_diagnostics
from app.api import (
    admin_candidates,
    admin_client_portfolio,
    admin_champion_ingest,
    admin_notes_insights,
    admin_traffit,
)
from app.api import admin_talent_pools
from app.api import required_documents
from app.api import screenings
from app.api import contacts
from app.api import prep_kit
from app.api import ai_writer
from app.api import talent_pools
from app.api import public_engagement
from app.api import public_interview_confirmation
from app.api import cv_generator_b2b
from app.api import b2b_contract_generator
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
from app.api import dynareporter_admin_hof
from app.api import dynareporter_admin_master_data
from app.api import dynareporter_admin_users

# dynareporter_admin_writes (Sales+Przetargi admin) usunięte 2026-05-19 —
# Nexus nie ma głównych dashboardów Sales/Przetargi w sidebarze, więc admin
# entry dla tych modułów nie był potrzebny (per user request).
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
from app.api import talent_radar
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
from app.api import help_materials as help_materials_api
from app.api import proposals as proposals_api
from app.api import job_shortlist as job_shortlist_api
from app.api import proposals_bulk as proposals_bulk_api
from app.api import invite_links as invite_links_api
from app.api import application_submissions as application_submissions_api
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
from app.api import public_signing as public_signing_api
from app.api import signing as signing_api
from app.api import ai_settings as ai_settings_api
from app.api import oauth_clients as oauth_clients_api
from app.api import oauth_token as oauth_token_api
from app.api import service_accounts as service_accounts_api
from app.api import candidate_sources as candidate_sources_api
from app.api import candidates_bulk as candidates_bulk_api
from app.api import dictionaries as dictionaries_api
from app.api import entity_fields as entity_fields_api
from app.api import teams_channels as teams_channels_api
from app.api import priority_work as priority_work_api

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

# HTTP status codes for transient Anthropic conditions: 429 rate-limit,
# 529 overloaded. Both are retried with backoff by the Claude callers.
_TRANSIENT_ANTHROPIC_STATUS = {429, 529}
_TRANSIENT_ANTHROPIC_TYPES = {"overloaded_error", "rate_limit_error"}


def _is_transient_anthropic_exc(exc: BaseException) -> bool:
    """True for momentary Anthropic 429/529 (overloaded / rate-limited) errors.

    Mirrors ``ai_client._is_retryable``'s status/type detection without importing
    the anthropic SDK here — inspects the SDK exception's ``status_code`` /
    ``response.status_code`` and the ``error.type`` carried in ``body``.
    """
    status = getattr(exc, "status_code", None)
    if status is None:
        response = getattr(exc, "response", None)
        if response is not None:
            status = getattr(response, "status_code", None)
    if status in _TRANSIENT_ANTHROPIC_STATUS:
        return True

    err_type = ""
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        err_obj = body.get("error") or {}
        if isinstance(err_obj, dict):
            err_type = err_obj.get("type", "")
    if not err_type:
        err_type = getattr(exc, "type", "") or ""
    return err_type in _TRANSIENT_ANTHROPIC_TYPES


def _sentry_before_send(event: dict, hint: dict) -> dict | None:
    """Drop transient Anthropic 429/529 errors auto-captured by Sentry's
    AnthropicIntegration at the raw ``messages.create`` boundary.

    Every Claude caller in this app wraps the SDK call and either retries with
    exponential backoff (``cv_generator_b2b.ai_client``) or returns a clean HTTP
    error. A momentary ``overloaded_error`` (529) / ``rate_limit_error`` (429) is
    an expected transient condition, not a code defect — yet the integration
    reports each one as an unhandled ``mechanism=anthropic`` event, spamming
    alerts (Sentry issue ``a5edd981…``, ``generate_from_upload``). The genuinely
    actionable failure — retries exhausted — is logged at ERROR level and still
    reaches Sentry via LoggingIntegration with full app context. So suppress only
    events that (a) carry a transient Anthropic exception and (b) came through
    the anthropic mechanism; never swallow errors raised by our own code.
    """
    exc_info = hint.get("exc_info") if hint else None
    if not (exc_info and len(exc_info) >= 2):
        return event
    if not _is_transient_anthropic_exc(exc_info[1]):
        return event
    for value in (event.get("exception") or {}).get("values", []):
        if (value.get("mechanism") or {}).get("type") == "anthropic":
            return None
    return event


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
            before_send=_sentry_before_send,
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
            # CSP dla odpowiedzi API. Domyślka jest maksymalnie ciasna, ale
            # przesłanka „nie serwujemy tu HTML-a" była NIEPRAWDZIWA i kosztowała
            # puste `/docs` i `/redoc` (bundle z CDN-a i inline'owy bootstrap
            # blokowane przez `default-src 'none'`, HTTP 200 i biała strona).
            # Trasy dokumentacji są dziś wyłączone poza DEBUG-iem, ale HTML
            # nadal wychodzi z widoków wydruku kontraktu i CV — te doklejają
            # WŁASNY nagłówek `Content-Security-Policy` (`contracts.py`,
            # `contract_templates.py`), a `setdefault` mu ustępuje. Każdy nowy
            # endpoint HTML musi zrobić to samo, inaczej odziedziczy pustą stronę.
            response.headers.setdefault(
                "Content-Security-Policy",
                "default-src 'none'; frame-ancestors 'none';",
            )
        return response


# Legacy powierzchnie statystyk (plan analytics PR 3): nagłówki deprecation
# na odpowiedziach — BEZ zmiany body (shadow mode nie dotyka legacy).
# Sunset = data orientacyjna cutoveru; Link wskazuje następcę per RFC 8594.
# 2026-08-07: `/api/competitions` wyjęte — to natywny, żywy moduł rywalizacji
# (nie DynaReporter), a analytics_v1 nie ma trasy-następcy dla rankingów.
_LEGACY_STATS_PREFIXES = (
    "/api/dashboard",
    "/api/reports",
    "/api/kpis",
)

# Kanoniczne powierzchnie wyłączone spod nagłówków legacy mimo pasującego
# prefiksu: `/api/dashboard/v2` to bieżący kontrakt RoleDashboard (PR #1031),
# nie legacy — `startswith("/api/dashboard")` łapał go omyłkowo.
_LEGACY_STATS_EXEMPT_PREFIXES = ("/api/dashboard/v2",)


def _legacy_stats_exempt(path: str) -> bool:
    """Czy ścieżka to kanoniczna powierzchnia zwolniona z nagłówków legacy.

    Dopasowanie z granicą segmentu: `/api/dashboard/v2` i `/api/dashboard/v2/...`
    są zwolnione, ale hipotetyczne `/api/dashboard/v2-beta` już nie — goły
    `startswith` nie zna granic segmentów URL.
    """
    return any(
        path == prefix or path.startswith(prefix + "/")
        for prefix in _LEGACY_STATS_EXEMPT_PREFIXES
    )


# Audyt M7 PR-02 (P0.3): metody mutujące blokowane przy DYNAREPORTER_MODE=read_only.
_DYNAREPORTER_MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# Ścieżki zwolnione z blokady read_only — nie tworzą DANYCH RAPORTOWYCH:
# - mindy/*: POST generujące komentarz/czat LLM (stateless, nic nie zapisują),
# - competitions notifications .../read: self-scoped read-marker powiadomień usera.
_DYNAREPORTER_READONLY_EXEMPT_PREFIXES = ("/api/dynareporter/mindy/",)


def _dynareporter_write_exempt(path: str, method: str) -> bool:
    """Czy dana mutacja DR jest zwolniona z blokady read_only (nie-raportowa)."""
    # upload/excel ma własny terminalny 410 GONE (R0) — mocniejszy niż read_only
    # 409; nie przykrywamy go (zachowuje kontrakt „trwale wycofane").
    if path == "/api/dynareporter/upload/excel":
        return True
    if path.startswith(_DYNAREPORTER_READONLY_EXEMPT_PREFIXES):
        return True
    if (
        method == "PATCH"
        and path.startswith("/api/dynareporter/competitions/notifications/")
        and path.endswith("/read")
    ):
        return True
    return False


class LegacyStatsDeprecationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Plan PR 7: telemetria ruchu legacy DynaReportera (sam path, bez PII)
        # + tryb DYNAREPORTER_MODE=off ⇒ 410 na odczytach (writes są już
        # admin-only; upload 410 od R0).
        if path.startswith("/api/dynareporter"):
            logger.info("legacy_dynareporter_hit path=%s", path)
            if settings.DYNAREPORTER_MODE == "off":
                from fastapi.responses import JSONResponse

                return JSONResponse(
                    status_code=410,
                    content={
                        "detail": (
                            "DynaReporter został wygaszony — bieżące statystyki: "
                            "/api/analytics/v1 (UI: /insights)"
                        )
                    },
                )

            # Audyt M7 PR-02 (P0.3): read_only egzekwuje read-only CENTRALNIE.
            # Dotąd read_only nie przechwytywało zapisów (split-brain: „archiwum",
            # które nadal przyjmuje mutacje). Teraz każda mutacja DR daje 409 z
            # kodem DYNAREPORTER_READ_ONLY, chyba że jest zwolniona (mindy/read-
            # marker) albo operator włączył break-glass na czas edycji danych.
            if (
                settings.DYNAREPORTER_MODE == "read_only"
                and request.method in _DYNAREPORTER_MUTATING_METHODS
                and not _dynareporter_write_exempt(path, request.method)
                and not settings.DYNAREPORTER_WRITE_BREAKGLASS
            ):
                # Audyt próby zapisu bez payloadu (bez PII).
                logger.warning(
                    "dynareporter_write_blocked method=%s path=%s",
                    request.method,
                    path,
                )
                from fastapi.responses import JSONResponse

                return JSONResponse(
                    status_code=409,
                    content={
                        "detail": (
                            "DynaReporter działa w trybie tylko-do-odczytu "
                            "(archiwum) — zapisy są zablokowane."
                        ),
                        "code": "DYNAREPORTER_READ_ONLY",
                    },
                )

        response = await call_next(request)
        if path.startswith(_LEGACY_STATS_PREFIXES) and not _legacy_stats_exempt(path):
            response.headers.setdefault("Deprecation", "true")
            response.headers.setdefault("Sunset", "Wed, 30 Sep 2026 00:00:00 GMT")
            response.headers.setdefault(
                "Link", '</api/analytics/v1>; rel="successor-version"'
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

    # The legacy entrypoint fallback bounds the hot-table INTEGER -> NUMERIC
    # conversion so a deploy cannot wait indefinitely for ACCESS EXCLUSIVE.
    # A timed-out fallback must not let the application serve decimal writes
    # against an INTEGER (or missing) column, so verify the physical contract
    # after every schema path and fail startup before accepting traffic.
    from app.services.candidate_profile_rate import (
        assert_candidate_profile_rate_schema,
    )

    async with engine.connect() as _profile_rate_schema_conn:
        await assert_candidate_profile_rate_schema(_profile_rate_schema_conn)

    # Migration 0207 rewrites every historic candidate saved search. Production
    # also has a legacy fail-open Alembic path, so repeat the idempotent rewrite
    # before accepting traffic and fail the startup if safety cannot be proven.
    from app.core.database import AsyncSessionLocal
    from app.services.candidate_monthly_rate_retirement import (
        retire_candidate_saved_searches,
    )

    async with AsyncSessionLocal() as _saved_search_db:
        retired_searches = await retire_candidate_saved_searches(_saved_search_db)
    logger.info(
        "Candidate monthly-rate retirement: sanitized_saved_searches=%d",
        retired_searches,
    )

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

    # Generator Umów B2B — idempotentny seed ról + szablonów (insert-if-missing,
    # nie nadpisuje edycji z UI). Bezpieczny przy każdym starcie.
    try:
        from app.core.database import AsyncSessionLocal
        from app.services.b2b_contract_generator.seeder import (
            ensure_b2b_seed_data,
        )

        async with AsyncSessionLocal() as _seed_db:
            await ensure_b2b_seed_data(_seed_db)
    except Exception as e:
        logger.warning("B2B generator seed skipped: %s", e)

    # Generator CV — reaper osieroconych „processing" po restarcie serwera.
    # Generacja CV leci w tle (BackgroundTasks); restart (np. redeploy Coolify)
    # ubija zadanie, a wiersz zostałby w „processing" na wieki. Świeży proces =
    # żadne z tych zadań nie przeżyło, więc każde „processing" jest osierocone →
    # oznacz jako „failed", by rekruter dostał czytelny błąd zamiast spinnera.
    try:
        from sqlalchemy import update as _sa_update

        from app.core.database import AsyncSessionLocal
        from app.models.cv_generated_document import CvGeneratedDocument

        async with AsyncSessionLocal() as _cv_db:
            _reap = await _cv_db.execute(
                _sa_update(CvGeneratedDocument)
                .where(CvGeneratedDocument.status == "processing")
                .values(
                    status="failed",
                    error_message=(
                        "Generacja przerwana (restart serwera) — wygeneruj ponownie."
                    ),
                )
            )
            await _cv_db.commit()
            if _reap.rowcount:
                logger.info(
                    "CV generator: reaped %d orphaned 'processing' rows", _reap.rowcount
                )
    except Exception as e:
        logger.warning("CV generator reaper skipped: %s", e)

    # Start calendar reminder background task
    from app.api.calendar import calendar_reminder_loop
    from app.tasks.match_history_ttl import match_history_ttl_loop
    from app.tasks.slack_sla_alerts import slack_sla_alerts_loop
    from app.tasks.ai_spend_alerts import ai_spend_alerts_loop
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
    from app.tasks.saved_search_alerts import saved_search_alerts_loop
    from app.tasks.chat_email_fallback import chat_email_fallback_loop
    from app.tasks.autenti_expiry_sweeper import autenti_sweeper_loop
    from app.tasks.signing_sweeper import signing_sweeper_loop
    from app.tasks.signature_reconciler import signature_reconciler_loop
    from app.tasks.dl_portal_expiry_scanner import dl_portal_expiry_loop
    from app.tasks.dl_alerts_scanner import dl_alerts_loop
    from app.tasks.job_deadline_alerts import job_deadline_alerts_loop
    from app.tasks.cloudtalk_sync import cloudtalk_sync_loop
    from app.tasks.traffit_sync import traffit_daily_sync_loop
    from app.tasks.notes_insights_sync import notes_insights_sync_loop
    from app.tasks.weekly_eval import weekly_eval_loop
    from app.tasks.match_digest import match_digest_loop
    from app.tasks.candidate_contact_queue import candidate_contact_queue_loop
    from app.tasks.candidate_contact_traffit import traffit_contact_intake_loop
    from app.tasks.index_drift_reconciler_task import index_drift_reconciler_loop
    from app.tasks.index_outbox_worker import index_outbox_loop
    from app.tasks.priority_work import priority_work_loop
    from app.services.fx_service import fx_refresh_loop

    # Background tasks registry — exposed via app.state so /api/admin/snapshot
    # can introspect running/expected counts. Order matches shutdown order.
    # Autenti sweeper exits immediately when AUTENTI_ENABLED=false; safe to
    # spawn unconditionally (mirrors LinkedIn/M365 patterns).
    app.state.background_tasks = {
        "calendar_reminder": asyncio.create_task(calendar_reminder_loop()),
        "match_history_ttl": asyncio.create_task(match_history_ttl_loop()),
        "slack_sla_alerts": asyncio.create_task(slack_sla_alerts_loop()),
        "ai_spend_alerts": asyncio.create_task(ai_spend_alerts_loop()),
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
        "saved_search_alerts": asyncio.create_task(saved_search_alerts_loop()),
        "chat_email_fallback": asyncio.create_task(chat_email_fallback_loop()),
        "autenti_sweeper": asyncio.create_task(autenti_sweeper_loop()),
        "signing_sweeper": asyncio.create_task(signing_sweeper_loop()),
        "signature_reconciler": asyncio.create_task(signature_reconciler_loop()),
        "dl_portal_expiry": asyncio.create_task(dl_portal_expiry_loop()),
        "job_deadline_alerts": asyncio.create_task(job_deadline_alerts_loop()),
        # Powiadomienia Delivery Leada (0233). Kill-switch sprawdzany PRZED
        # pętlą — wyłączona funkcja kończy zadanie, a nie budzi procesu co
        # 24 h po to, żeby sprawdzić tę samą flagę.
        "dl_alerts": asyncio.create_task(dl_alerts_loop()),
        "cloudtalk_sync": asyncio.create_task(cloudtalk_sync_loop()),
        "traffit_sync": asyncio.create_task(traffit_daily_sync_loop()),
        "notes_insights_sync": asyncio.create_task(notes_insights_sync_loop()),
        "weekly_eval": asyncio.create_task(weekly_eval_loop()),
        "match_digest": asyncio.create_task(match_digest_loop()),
        "candidate_contact_queue": asyncio.create_task(candidate_contact_queue_loop()),
        "candidate_contact_traffit": asyncio.create_task(traffit_contact_intake_loop()),
        "index_outbox": asyncio.create_task(index_outbox_loop()),
        "index_drift_reconciler": asyncio.create_task(index_drift_reconciler_loop()),
        "priority_work": asyncio.create_task(priority_work_loop()),
    }

    # Śmierć pętli musi być ZDARZENIEM, nie zmianą ułamka „running/expected".
    # Ten ułamek jest z założenia nierówny — 23 z 34 pętli kończą się celowo na
    # własnym kill-switchu — więc `running: 21` zamiast 22 jest nieodróżnialne
    # od zdrowego stanu i nikt tego nie umie zinterpretować. Callback loguje na
    # ERROR w CHWILI śmierci, czyli wtedy, gdy Sentry (`event_level=ERROR`)
    # jeszcze może zrobić z tego alert. Ma to też drugi skutek: silna referencja
    # w rejestrze tłumi wbudowany log asyncio „Task exception was never
    # retrieved", więc bez tego callbacku wyjątek nie pojawiłby się NIGDZIE.
    def _log_task_death(name: str):
        def _cb(task: "asyncio.Task") -> None:
            if task.cancelled():
                return
            exc = task.exception()
            if exc is not None:
                logger.error(
                    "background task %r died: %r — nic go nie restartuje "
                    "do najbliższego deployu",
                    name,
                    exc,
                    exc_info=exc,
                )

        return _cb

    for _name, _task in app.state.background_tasks.items():
        _task.add_done_callback(_log_task_death(_name))

    yield

    # Shutdown
    tasks = tuple(app.state.background_tasks.values())
    for t in tasks:
        t.cancel()
    # `gather(..., return_exceptions=True)`, nie pętla `await t` łapiąca sam
    # `CancelledError`: task, który padł na PRAWDZIWYM wyjątku, podnosił go tu
    # ponownie i przerywał zamykanie — pozostałe taski nie były doczekane, a
    # `engine.dispose()` nie leciało wcale.
    await asyncio.gather(*tasks, return_exceptions=True)
    await engine.dispose()


# Trzy trasy dokumentacji tylko poza produkcją. Na prodzie `/openapi.json`
# oddawał anonimowemu wywołującemu kompletny inwentarz powierzchni ataku —
# 747 ścieżek, 876 schematów i, co gorsza, listę operacji BEZ bloku `security`,
# czyli gotowy spis endpointów bez tokena wraz z kształtem ich żądań. Ten host
# jest gray-cloud (bez WAF-a Cloudflare), więc nie ma warstwy kompensacyjnej.
#
# `/docs` i `/redoc` i tak renderowały się PUSTO: `SecurityHeadersMiddleware`
# wysyła `default-src 'none'`, co blokuje bundle Swaggera/ReDoc z CDN-a i ich
# inline'owy bootstrap. Znikało więc to, czego nikt nie mógł użyć, a zostawało
# to, co niosło całe ryzyko (surowy JSON, którego CSP nie dotyczy).
#
# Bezpieczne do usunięcia: żaden workflow, smoke test, uptime probe ani plik
# rozszerzenia nie odwołuje się do tych URL-i. Testy budujące schemat wołają
# METODĘ `app.openapi()`, która działa niezależnie od tego, czy trasa istnieje.
_DOCS_ENABLED = settings.DEBUG

app = FastAPI(
    title="Nexus ATS",
    description="Modern ATS for IT staffing agencies (body leasing) — B2B.net",
    version="0.3.0",
    lifespan=lifespan,
    redirect_slashes=False,
    docs_url="/docs" if _DOCS_ENABLED else None,
    redoc_url="/redoc" if _DOCS_ENABLED else None,
    openapi_url="/openapi.json" if _DOCS_ENABLED else None,
)

# Rate limiter (attach first so it wraps everything)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(LegacyStatsDeprecationMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    # Allow Chrome extensions (NEXUS LinkedIn helper, etc.) — Chrome IDs are
    # 32-char lowercase a-p strings (base32-ish). Regex covers both dev
    # (load-unpacked) and Web Store production IDs.
    allow_origin_regex=r"^chrome-extension://[a-p]{32}$",
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "X-Requested-With",
        # Admin „podgląd jako użytkownik" — patrz app/api/deps.py.
        "X-Impersonate-User-Id",
        # Durable de-duplication for manually logged phone outcomes.
        "Idempotency-Key",
        # Optimistic concurrency for typed candidate profile facts.
        "If-Match",
    ],
    # `Content-Disposition` carries server-generated export filenames. Without
    # exposing it, cross-origin frontend fetches can download the bytes but
    # cannot read the required client/date filename.
    expose_headers=["ETag", "Content-Disposition"],
)

# Register routers
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
# IMPORTANT: candidate_pins MUST be mounted BEFORE candidates so its
# `/pins` listing route matches before the catch-all `/{candidate_id}`
# route in candidates.py — otherwise FastAPI would try to coerce "pins"
# to an int and return 422.
app.include_router(
    candidate_pins.router, prefix="/api/candidates", tags=["candidate-pins"]
)
app.include_router(candidates.router, prefix="/api/candidates", tags=["candidates"])
app.include_router(
    candidate_profile_facts.router,
    prefix="/api/candidates",
    tags=["candidate-profile-facts"],
)
app.include_router(
    candidate_identity_quarantine.router,
    prefix="/api/candidates",
    tags=["candidate-identity-quarantine"],
)
app.include_router(
    candidate_contact.router,
    prefix="/api/candidate-contact",
    tags=["candidate-contact"],
)
app.include_router(
    candidate_scoring.router, prefix="/api/candidates", tags=["candidate-scoring"]
)
app.include_router(
    candidate_activity_summary.router,
    prefix="/api/candidates",
    tags=["candidate-activity-summary"],
)
app.include_router(public_engagement.router, prefix="/api", tags=["public-engagement"])
app.include_router(
    public_interview_confirmation.router,
    prefix="/api",
    tags=["public-interview-confirmation"],
)
app.include_router(jobs.router, prefix="/api/jobs", tags=["jobs"])
# Static `/directory` must be registered before `clients`' catch-all
# `/{client_id}` route.
app.include_router(
    client_directory.router,
    prefix="/api/clients",
    tags=["client-directory"],
)
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
    client_order_groups_api.router,
    prefix="/api/clients",
    tags=["client-order-groups"],
)
app.include_router(
    md_consumption_api.router,
    prefix="/api/md-consumption",
    tags=["md-consumption"],
)
app.include_router(
    dl_alerts_api.router,
    prefix="/api/dl-alerts",
    tags=["dl-alerts"],
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
    admin_client_portfolio.router,
    prefix="/api/admin/client-portfolio",
    tags=["admin-client-portfolio"],
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
app.include_router(
    admin_pipeline_inventory.router,
    prefix="/api/admin",
    tags=["admin-pipeline-inventory"],
)
app.include_router(
    admin_process_adoption.router,
    prefix="/api/admin",
    tags=["admin-process-adoption"],
)
app.include_router(
    admin_engagement_inventory.router,
    prefix="/api/admin",
    tags=["admin-engagement-inventory"],
)
app.include_router(
    admin_schema_drift.router,
    prefix="/api/admin",
    tags=["admin-schema-drift"],
)
app.include_router(
    admin_index_coverage.router,
    prefix="/api/admin",
    tags=["admin-index-coverage"],
)
app.include_router(
    admin_candidate_pii_orphans.router,
    prefix="/api/admin",
    tags=["admin-candidate-pii-orphans"],
)
app.include_router(
    admin_match_score_repair.router,
    prefix="/api/admin",
    tags=["admin-match-score-repair"],
)
app.include_router(
    admin_workflows.router,
    prefix="/api/admin",
    tags=["admin-workflows"],
)
app.include_router(
    admin_recruitment_processes.router,
    prefix="/api/admin",
    tags=["admin-recruitment-processes"],
)
app.include_router(
    ai_matching_diagnostics.router,
    prefix="/api/admin",
    tags=["ai-matching-diagnostics"],
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
app.include_router(cortex.router, prefix="/api/cortex", tags=["cortex"])
app.include_router(
    contract_templates.router,
    prefix="/api/contract-templates",
    tags=["contract-templates"],
)
app.include_router(
    b2b_contract_generator.router,
    prefix="/api/b2b-generator",
    tags=["b2b-generator"],
)
app.include_router(invoices.router, prefix="/api/invoices", tags=["invoices"])
app.include_router(fx.router, prefix="/api/fx", tags=["fx"])
app.include_router(dashboard.router, prefix="/api/dashboard", tags=["dashboard"])
app.include_router(search.router, prefix="/api/search", tags=["search"])
app.include_router(activities.router, prefix="/api/activities", tags=["activities"])
app.include_router(admin.router, prefix="/api/admin", tags=["admin"])
app.include_router(
    admin_traffit.router, prefix="/api/admin/traffit", tags=["admin", "traffit"]
)
app.include_router(
    admin_notes_insights.router,
    prefix="/api/admin/notes-insights",
    tags=["admin", "notes-insights"],
)
app.include_router(
    admin_champion_ingest.router,
    prefix="/api",
    tags=["admin-champion"],
)
app.include_router(
    admin_candidates.router,
    prefix="/api/admin/candidates",
    tags=["admin", "candidates"],
)
app.include_router(
    admin_talent_pools.router,
    prefix="/api/admin/talent-pools",
    tags=["admin", "talent-pools"],
)
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
    dynareporter_admin_hof.router,
    prefix="/api/dynareporter/admin-hof",
    tags=["dynareporter"],
)
app.include_router(
    dynareporter_admin_master_data.router,
    prefix="/api/dynareporter/admin-master-data",
    tags=["dynareporter"],
)
app.include_router(
    dynareporter_admin_users.router,
    prefix="/api/dynareporter/admin-users",
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
app.include_router(talent_radar.router, prefix="/api", tags=["talent-radar"])
app.include_router(phase3_actions.router, prefix="/api", tags=["recommendations"])
app.include_router(phase3.router, prefix="/api", tags=["phase3"])
app.include_router(phase4.router, prefix="/api", tags=["phase4"])
app.include_router(phase5.router, prefix="/api", tags=["phase5"])
app.include_router(admin_import.router, prefix="/api", tags=["admin-import"])
app.include_router(kpis_api.router, prefix="/api/kpis", tags=["kpis"])
# Analytics v1 (plan 2026-07-16, PR 3) — wersjonowany kontrakt statystyk.
# Endpointy 503 przy ANALYTICS_V1_MODE=off; RBAC/capabilities niezależnie.
app.include_router(
    analytics_v1_api.router, prefix="/api/analytics/v1", tags=["analytics-v1"]
)
# Canonical role dashboards; v1/legacy routes remain available during rollout.
app.include_router(
    dashboard_v2_api.router, prefix="/api/dashboard/v2", tags=["dashboard-v2"]
)
# Korekty finansowe (plan analytics PR 6) — immutable audit trail.
app.include_router(
    financial_adjustments_api.router,
    prefix="/api/financial-adjustments",
    tags=["financial-adjustments"],
)
# Moduł „Finanse" — import miesięcznych wyników kontraktorów (admin + finance).
app.include_router(finance_api.router, prefix="/api/finance", tags=["finance"])
app.include_router(onboarding_api.router, prefix="/api/users", tags=["onboarding"])
app.include_router(users_api.router, prefix="/api/users", tags=["users"])
app.include_router(procedures_api.router, prefix="/api", tags=["procedures"])
app.include_router(help_materials_api.router, prefix="/api", tags=["help-materials"])
app.include_router(proposals_api.router, prefix="/api", tags=["proposals"])
app.include_router(proposals_bulk_api.router, prefix="/api", tags=["proposals"])
app.include_router(job_shortlist_api.router, prefix="/api", tags=["shortlist"])
app.include_router(
    invite_links_api.router, prefix="/api/invite-links", tags=["invite-links"]
)
app.include_router(
    application_submissions_api.router,
    prefix="/api/application-submissions",
    tags=["application-submissions"],
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
    priority_work_api.router,
    prefix="/api/priority-work",
    tags=["priority-work"],
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

# In-house QES signing (drop Autenti, single-vendor KIR + OSS upload-validate).
# Router mounted unconditionally; write/IO handlers call _require_enabled()
# (503 when SIGNING_ENABLED=false). Public signing page under /api/public.
app.include_router(signing_api.router, prefix="/api/signing", tags=["signing"])
app.include_router(
    public_signing_api.router, prefix="/api/public", tags=["public-signing"]
)

# AI features panel (Settings → AI). Admin-only. Routes mounted at
# /api/settings/ai (prefix is declared on the router itself; we add /api here).
app.include_router(ai_settings_api.router, prefix="/api", tags=["ai-settings"])

# OAuth2 client manager (Settings → API integration). Admin-only CRUD.
app.include_router(oauth_clients_api.router, prefix="/api", tags=["oauth-clients"])

# OAuth2 token endpoint (client_credentials grant). Public — auth is via
# client_id + client_secret in the request body, not Authorization header.
app.include_router(oauth_token_api.router, prefix="/api", tags=["oauth-token"])

# Konta serwisowe / klucze API (Settings → API). Admin-only CRUD; samo
# uwierzytelnianie kluczem żyje w zależności ``require_service_scope``
# i jest wpięte w chronione endpointy, nie w ten router.
app.include_router(
    service_accounts_api.router, prefix="/api", tags=["service-accounts"]
)

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

    Strategy: return MAX(BUILT_AT env, __file__ mtime). Bo:
    - Coolify env vault często ma BUILT_AT jako static value (last manual
      set), które nie aktualizuje się per deploy → stale info (QA
      2026-05-27: prod pokazywał 27-dniowy timestamp mimo świeżego deployu)
    - Filesystem mtime __file__ ZAWSZE świeży po Docker rebuild (Coolify
      buduje od scratch przy każdym deploy)
    - Max() z obu daje "best available freshness" — env wygrywa tylko
      gdy ktoś świadomie ustawił go w przyszłości (np. test fixture)

    QA 2026-05-27: deployedAt 2026-05-01 dla deployu z 2026-05-27. Fix:
    fall through to mtime gdy env jest starszy od mtime.
    """
    import os
    from datetime import datetime, timezone

    candidates: list[tuple[datetime, str]] = []

    explicit = os.environ.get("BUILT_AT", "").strip()
    if explicit and explicit != "unknown":
        try:
            parsed = datetime.fromisoformat(explicit.replace("Z", "+00:00"))
            candidates.append((parsed, explicit))
        except ValueError:
            pass

    try:
        mtime = os.path.getmtime(__file__)
        mtime_dt = datetime.fromtimestamp(mtime, tz=timezone.utc)
        mtime_str = mtime_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        candidates.append((mtime_dt, mtime_str))
    except OSError:
        pass

    if not candidates:
        return "unknown"
    # Pick most-recent timestamp — fresher beats stale.
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


# Rozmiar wektora kolekcji kandydatów. Nie zmienia się przez całe życie procesu,
# a jego odczyt kosztuje dwa dodatkowe obiegi do Qdranta (`get_collections` +
# `get_collection`). Bez tego cache'u sonda poniżej mieściła się w ~2,4 s przy
# limicie 3 s — czyli przy pierwszym drgnięciu sieci meldowałaby awarię, której
# nie ma. Fałszywy alarm w healthchecku jest gorszy niż jego brak, bo uczy
# ignorować kolor.
_qdrant_vector_size: int | None = None


class _QdrantSlow(Exception):
    """Qdrant odpowiada, ale wolniej niż limit klienta — żywy, nie zepsuty.

    Osobny typ, bo tych dwóch stanów NIE wolno mylić. Klient ma własny limit
    (2 s) i przy wolnej odpowiedzi rzuca `ResponseHandlingException` owijający
    `httpx.TimeoutException` — czyli zwykły wyjątek, a nie `asyncio.TimeoutError`.
    Bez tego rozróżnienia wolny-ale-żywy Qdrant lądował w gałęzi „unhealthy",
    mimo że komentarz obok obiecywał „degraded". Wskazali to dwaj recenzenci
    PR #986 i mieli rację: limit `wait_for` (5 s) jest wtedy nieosiągalny,
    bo klient przerywa pierwszy.
    """


def _czy_przekroczony_czas(blad: BaseException) -> bool:
    """Czy w łańcuchu przyczyn siedzi przekroczenie czasu (a nie inny błąd).

    `qdrant-client` owija wyjątki `httpx`, więc typ zewnętrzny nic nie mówi:
    tak samo wygląda odmowa połączenia (Qdrant leży → `unhealthy`) i wolna
    odpowiedź (Qdrant żyje → `degraded`). Rozstrzyga dopiero `__cause__`.
    """
    widziane: set[int] = set()
    biezacy: BaseException | None = blad
    while biezacy is not None and id(biezacy) not in widziane:
        widziane.add(id(biezacy))
        if isinstance(biezacy, TimeoutError):
            return True
        # httpx importujemy leniwie — nie chcemy zależności w ścieżce startowej.
        try:
            import httpx

            if isinstance(biezacy, httpx.TimeoutException):
                return True
        except ImportError:
            pass
        biezacy = biezacy.__cause__ or biezacy.__context__
    return False


def _probe_qdrant() -> str:
    """Sprawdza Qdranta WYKONUJĄC zapytanie, którym żyje aplikacja.

    Dlaczego nie sama łączność. 2026-07-28 podbicie ``qdrant-client`` 1.12.1 →
    1.18.0 usunęło ``QdrantClient.search()``. Padło siedem wywołań w kodzie —
    wyszukiwanie semantyczne, matching, podpowiedzi do pul, klasyfikacja CC —
    a serwer Qdranta przez cały czas był zdrowy i odpowiadał. Ping byłby zielony
    przez całą dwugodzinną awarię; niezgodna była biblioteka po naszej stronie.

    Awaria była cicha z trzech powodów naraz: CI nie ma Qdranta, ``/api/health``
    nie miał klucza ``qdrant``, a wyjątek na ścieżce wyszukiwania jest połykany
    i zwraca pustą listę — użytkownik widzi „brak wyników", nie błąd.

    Uruchamiane w wątku (klient jest synchroniczny) i objęte limitem czasu przez
    wywołującego.
    """
    global _qdrant_vector_size

    from qdrant_client import QdrantClient

    from app.services.embedding_service import candidates_collection_name

    client = QdrantClient(
        host=settings.QDRANT_HOST,
        port=settings.QDRANT_PORT,
        timeout=2,
    )
    collection = candidates_collection_name()

    try:
        if _qdrant_vector_size is None:
            names = {c.name for c in client.get_collections().collections}
            if collection not in names:
                # Serwer żyje, ale kolekcji nie ma: indeks nigdy nie powstał albo
                # wskazujemy na złą instancję. Jedno i drugie to cicha utrata
                # wyszukiwania, więc nie udajemy, że jest dobrze.
                return "misconfigured"

            vectors = client.get_collection(collection).config.params.vectors
            size = getattr(vectors, "size", None)
            if size is None and isinstance(vectors, dict):
                # Konfiguracja z nazwanymi wektorami — bierzemy pierwszy.
                size = getattr(next(iter(vectors.values()), None), "size", None)
            if not size:
                return "degraded"
            _qdrant_vector_size = int(size)
    except Exception as blad:
        if _czy_przekroczony_czas(blad):
            raise _QdrantSlow from blad
        raise

    # Sedno sondy: to samo wywołanie, którego używa `embedding_service`. Gdy
    # kolejny bump usunie albo zmieni tę metodę, poniższe rzuci wyjątek i
    # healthcheck zrobi się czerwony w minutę, a nie po dwóch godzinach zgłoszeń
    # „wyszukiwarka nic nie znajduje".
    #
    # Uwaga przy migracji na `query_points()`: to wywołanie MUSI zostać
    # zmienione razem z siedmioma w `app/services/` — inaczej sonda przestanie
    # sprawdzać ścieżkę, którą faktycznie chodzi aplikacja.
    try:
        client.search(
            collection_name=collection,
            query_vector=[0.0] * _qdrant_vector_size,
            limit=1,
            with_payload=False,
        )
    except Exception as blad:
        if _czy_przekroczony_czas(blad):
            raise _QdrantSlow from blad
        raise
    return "healthy"


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

    # CloudTalk status — raportowany TYLKO gdy integracja jest włączona.
    #
    # Wcześniej klucz `cloudtalk: "unconfigured"` wisiał w odpowiedzi zawsze,
    # także przy wyłączonym kill-switchu — czyli od wdrożenia integracji do
    # dziś, bez jednego dnia przerwy. Stały wpis „czegoś tu nie ma" nie niesie
    # informacji: nie da się po nim poznać, czy ktoś właśnie wyłączył działającą
    # integrację, czy po prostu nigdy jej nie uruchomiono. Uczy natomiast
    # ignorować niezdrowe pozycje w `checks` — a to jest kosztowne, bo obok
    # stoją pozycje, które znaczą coś naprawdę (`database`, `traffit`).
    #
    # Decyzja produktowa 28.07: nie używamy CloudTalka. Kod zostaje (model
    # `Call` i kolumny są niezależne od dostawcy i przydadzą się przy następnej
    # telefonii), ale przestaje raportować swoją nieobecność.
    if not settings.CLOUDTALK_ENABLED or not settings.CLOUDTALK_API_KEY_ID:
        pass
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

    # Traffit daily sync — informational. Reads the persisted watermark so the
    # check reflects whether the scheduled import is actually running, not just
    # whether the flag is on. `unconfigured` (off) / `misconfigured` (no creds)
    # / `degraded` (enabled but no fresh successful run) / `healthy`.
    if not settings.TRAFFIT_SYNC_ENABLED:
        checks["traffit"] = "unconfigured"
    elif not (
        os.environ.get("TRAFFIT_CLIENT_SECRET") and os.environ.get("TRAFFIT_TENANT")
    ):
        checks["traffit"] = "misconfigured"
    else:
        try:
            from datetime import datetime as _dt
            from datetime import timedelta as _td
            from datetime import timezone as _tz

            async with AsyncSessionLocal() as session:
                row = await asyncio.wait_for(
                    session.execute(
                        text(
                            "SELECT last_run_finished_at, last_status "
                            "FROM traffit_sync_state WHERE phase = '__daily__'"
                        )
                    ),
                    timeout=1.0,
                )
            r = row.fetchone()
            if r is None or r[0] is None:
                checks["traffit"] = "degraded"  # enabled, no successful run yet
            elif (_dt.now(_tz.utc) - r[0]) > _td(hours=36) or r[1] not in (
                "ok",
                None,
            ):
                checks["traffit"] = "degraded"
            else:
                checks["traffit"] = "healthy"
        except Exception:
            checks["traffit"] = "degraded"

    # Cortex extraction — informational. Świeżość ostatniego przebiegu faktów
    # skilli (cortex_extraction_runs). Overall status pozostaje DB-only; to tylko
    # uwidacznia stale/failed backfill po deployu. `unconfigured` (brak runów) /
    # `degraded` (failed / stary / z błędami) / `healthy` (świeży ok / w toku).
    try:
        from datetime import datetime as _cdt
        from datetime import timedelta as _ctd
        from datetime import timezone as _ctz

        async with AsyncSessionLocal() as session:
            row = await asyncio.wait_for(
                session.execute(
                    text(
                        "SELECT status, finished_at, started_at "
                        "FROM cortex_extraction_runs "
                        "ORDER BY started_at DESC LIMIT 1"
                    )
                ),
                timeout=1.0,
            )
        r = row.fetchone()
        if r is None:
            checks["cortex"] = "unconfigured"  # nigdy nie ekstrahowano
        elif r[0] == "running":
            checks["cortex"] = "healthy"  # run w toku
        elif r[0] in ("failed", "errors"):
            checks["cortex"] = "degraded"
        else:  # ok
            finished = r[1] or r[2]
            if finished is None or (_cdt.now(_ctz.utc) - finished) > _ctd(days=8):
                checks["cortex"] = "degraded"  # stary (daily + weekly full)
            else:
                checks["cortex"] = "healthy"
    except Exception:
        checks["cortex"] = "degraded"

    # Qdrant — patrz `_probe_qdrant` po uzasadnienie kształtu tej sondy.
    #
    # Nigdy nie przestawia `overall` ani kodu HTTP: utrata wektorów to utrata
    # funkcji, nie utrata aplikacji, a healthcheck Dockera restartuje kontener
    # po 503 — restart nie naprawiłby ani niezgodnej biblioteki, ani cudzego
    # serwera, tylko dołożyłby przestój do awarii.
    try:
        checks["qdrant"] = await asyncio.wait_for(
            asyncio.to_thread(_probe_qdrant), timeout=5.0
        )
    except (_QdrantSlow, TimeoutError):
        # Świadomie NIE „unhealthy": Qdrant odpowiada, tylko wolno. Mylenie
        # „padł" z „zamulił" produkuje fałszywe alarmy, a te uczą ignorować
        # healthcheck.
        #
        # Dwa różne limity, w tej kolejności: klient przerywa po 2 s
        # (`_QdrantSlow`), `wait_for` po 5 s (`TimeoutError`) — ten drugi łapie
        # zwisy poza samym HTTP, np. rozwiązywanie nazwy albo głodzenie puli
        # wątków.
        checks["qdrant"] = "degraded"
    except Exception:
        checks["qdrant"] = "unhealthy"

    # Recruitment Priority Work — informational and feature-flag aware.
    # `off` is the safe default and therefore reported as disabled.  In
    # shadow/enforce a stale persisted heartbeat exposes a dead alert worker;
    # it never changes the uptime gate (overall remains database-only).
    if settings.RECRUITMENT_PRIORITY_MODE == "off":
        checks["priority_work"] = "disabled"
    else:
        try:
            from app.models.recruitment_priority import RecruitmentPriorityState
            from app.tasks.priority_work import worker_is_fresh

            async with AsyncSessionLocal() as session:
                priority_state = await asyncio.wait_for(
                    session.scalar(
                        select(RecruitmentPriorityState).where(
                            RecruitmentPriorityState.id == 1
                        )
                    ),
                    timeout=1.0,
                )
            if priority_state is None:
                checks["priority_work"] = "degraded"
            elif priority_state.last_error:
                checks["priority_work"] = "degraded"
            elif worker_is_fresh(priority_state.worker_heartbeat_at):
                checks["priority_work"] = "healthy"
            else:
                checks["priority_work"] = "degraded"
        except Exception:
            checks["priority_work"] = "degraded"

    # Anthropic key — config-only probe. Bez klucza generator CV (i każdy
    # feature na Claude API) wstaje, ale pierwsza generacja kończy się 502
    # (Sentry NEXUS-BE-F) — lepiej widzieć to w healthchecku po deployu.
    anthropic_key = settings.ANTHROPIC_API_KEY or os.environ.get("ANTHROPIC_API_KEY")
    if not anthropic_key:
        checks["anthropic"] = "unconfigured"
    else:
        # Runtime health from the in-process Claude circuit breaker: after a run
        # of recent failures the key is present but the provider is down. This
        # never flips `overall` (that tracks the DB only) — it just makes a Claude
        # outage visible in the healthcheck instead of a silent stream of 502s.
        from app.services.ai_health import provider_status

        checks["anthropic"] = {
            "ok": "configured",
            "degraded": "degraded",
            "down": "unhealthy",
        }[provider_status("claude")]

    # Voyage (embeddings + rerank) and Qdrant. Before this, a dead Voyage looked
    # identical to a healthy one from here: `generate_embedding` returns None,
    # search returns an empty list, and the healthcheck stayed green while the
    # index quietly stopped being written. `unknown` means the provider has not
    # been exercised since this process started — deliberately NOT a pass, so a
    # dependency wired up wrong cannot masquerade as working.
    from app.services.ai_health import provider_health_label

    if not settings.VOYAGE_API_KEY:
        checks["voyage"] = "unconfigured"
        checks["reranker"] = "unconfigured"
    else:
        checks["voyage"] = provider_health_label("voyage")
        checks["reranker"] = (
            provider_health_label("reranker")
            if settings.RERANKER_ENABLED
            else "disabled"
        )
    # Qdrant deliberately gets no key here: `checks["qdrant"]` above is an
    # active probe that issues a real query. Its per-provider window is still
    # recorded (see `_run_qdrant`) and feeds `meta.ai_status`, but publishing a
    # second, similarly-named key would only make this output ambiguous.

    # AI features with no monthly ceiling. Under fail-open quota semantics that
    # is a spend warning, not an outage — informational, never flips `overall`.
    #
    # "Uncapped" is BOTH a missing row and a row with `monthly_limit = 0`, which
    # `ai_quota` documents as unlimited. Counting only missing rows made this
    # probe report `healthy` on prod while all 19 configured features sat at 0 —
    # a green light on a system with no ceiling anywhere.
    #
    # The feature column is read as text on purpose. Hydrating it into
    # `AIFeatureKey` raises when a row holds a value the enum no longer has, and
    # prod has 11 such rows (`embeddings`, `matching`, `reranking`, …) left from
    # features that were renamed or dropped. A probe whose job is spotting
    # config drift must not be killed by that drift — before this, one orphan row
    # turned the whole check into a silent `unknown`.
    try:
        from sqlalchemy import Text, cast

        from app.models.ai_feature import AIFeatureConfig, AIFeatureKey

        async with AsyncSessionLocal() as session:
            rows = await asyncio.wait_for(
                session.execute(
                    select(
                        cast(AIFeatureConfig.feature, Text),
                        AIFeatureConfig.monthly_limit,
                    )
                ),
                timeout=1.0,
            )
        limits = {str(f): (lim or 0) for f, lim in rows.all()}
        uncapped = sorted(k.value for k in AIFeatureKey if limits.get(k.value, 0) <= 0)
        checks["ai_features"] = (
            "healthy" if not uncapped else f"uncapped: {','.join(uncapped)}"
        )
    except Exception as exc:
        # Log it: this is the safety net for fail-open quota semantics (a missing
        # config row means uncapped spend), and operators are told to treat
        # `ai_features` as informational. A silent `unknown` would hide the
        # warning at exactly the moment it matters most.
        logger.warning("[health] ai_features check failed: %s", exc)
        checks["ai_features"] = "unknown"

    # FX — wiek cache'u kursów NBP. To JEDYNE miejsce, w którym „NBP milczy od
    # dwóch miesięcy" jest w ogóle widoczne: `fetch_and_store_nbp_today` rzuca
    # teraz przy awarii, ale zdarzenie Sentry ginie w szumie, a po stronie
    # odczytu przeterminowany kurs dalej wycenia faktury w EUR/USD/GBP. Helper
    # `fx_age_days` istniał od początku i nie miał ANI JEDNEGO wywołania.
    # Informacyjny (nie przewraca `overall`) — brak kursów nie jest awarią
    # aplikacji, tylko cichym fałszowaniem sum finansowych.
    try:
        from app.services.fx_service import (
            HEALTH_CANARY_CURRENCY,
            MAX_RATE_AGE_DAYS,
            fx_age_days,
        )

        async with AsyncSessionLocal() as session:
            age = await asyncio.wait_for(
                fx_age_days(session, HEALTH_CANARY_CURRENCY), timeout=2.0
            )
        if age is None:
            checks["fx"] = "unconfigured"  # cache pusty — nigdy nie pobrano
        elif age > MAX_RATE_AGE_DAYS:
            checks["fx"] = f"degraded: stale {age}d"
        else:
            checks["fx"] = "healthy"
    except Exception as exc:
        logger.warning("[health] fx check failed: %s", exc)
        checks["fx"] = "unknown"

    # Pętle w tle — liczba tych, które PADŁY. Świadomie nie „running/expected":
    # ten ułamek jest z założenia nierówny (23 z 34 pętli kończą się celowo na
    # własnym kill-switchu), więc jego spadek o jeden jest nieodróżnialny od
    # zdrowego stanu. `crashed` przy zdrowej instalacji wynosi zero, więc każda
    # wartość powyżej zera jest jednoznaczna. Informacyjny — martwa pętla nie
    # jest powodem, żeby uptime-probe uznał backend za nieżywy.
    try:
        _bg = getattr(app.state, "background_tasks", None)
        if not isinstance(_bg, dict):
            checks["background_tasks"] = "unknown"
        else:
            crashed = [
                name
                for name, task in _bg.items()
                if task.done() and not task.cancelled() and task.exception() is not None
            ]
            checks["background_tasks"] = (
                "healthy" if not crashed else f"crashed: {','.join(sorted(crashed))}"
            )
    except Exception as exc:
        logger.warning("[health] background_tasks check failed: %s", exc)
        checks["background_tasks"] = "unknown"

    # Disk usage — informational only (never flips `overall` → no false outages).
    # `shutil.disk_usage("/")` inside the container reflects the host's backing
    # filesystem (overlay2 upperdir lives on the host disk), so this surfaces the
    # host disk filling up — the root cause of the 2026-07-17 outage (Coolify build
    # churn → 98.8% disk → Postgres/Coolify crash-loop). The `disk-alert.yml` cron
    # reads `diskPercent` and warns at 75%, days before it becomes an outage.
    disk_percent: int | None = None
    try:
        import shutil

        usage = shutil.disk_usage("/")
        disk_percent = round(usage.used / usage.total * 100)
        if disk_percent >= 90:
            checks["disk"] = "critical"
        elif disk_percent >= 80:
            checks["disk"] = "warning"
        else:
            checks["disk"] = "healthy"
    except Exception:
        checks["disk"] = "unknown"

    db_healthy = checks.get("database") == "healthy"
    overall = "healthy" if db_healthy else "unhealthy"

    return JSONResponse(
        content={
            "status": overall,
            "version": os.environ.get("GIT_SHA", "unknown"),
            "deployedAt": _resolve_deployed_at(),
            "diskPercent": disk_percent,
            "checks": checks,
        },
        status_code=http_status.HTTP_200_OK
        if db_healthy
        else http_status.HTTP_503_SERVICE_UNAVAILABLE,
    )


@app.get("/api/health/alembic")
async def api_health_alembic():
    """Read-only diagnostic: prod ``alembic_version`` vs the code's revisions.

    After the 2026-07-15 rollback the prod DB's migration bookmark points at a
    Codex revision the reverted code no longer ships, so ``alembic upgrade heads``
    is a no-op and schema lands only via the entrypoint safety-net. This surfaces
    the exact mismatch (DB bookmark vs code heads / which revisions are orphaned)
    so it can be reconciled deliberately. Auth-free by design — leaks only alembic
    revision ids, never data.
    """
    import os

    from fastapi import status as http_status
    from fastapi.responses import JSONResponse
    from sqlalchemy import text as _sql_text

    from app.core.database import AsyncSessionLocal

    out: dict = {}

    # The DB's bookmark(s). Multiple rows == the chronic multi-head state.
    try:
        async with AsyncSessionLocal() as session:
            rows = (
                (
                    await session.execute(
                        _sql_text("SELECT version_num FROM alembic_version")
                    )
                )
                .scalars()
                .all()
            )
        out["db_versions"] = list(rows)
    except Exception as exc:  # noqa: BLE001 — diagnostic must not raise
        out["db_versions"] = []
        out["db_error"] = type(exc).__name__

    # The code's revision graph (best-effort; alembic runs on prod).
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        script_location = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "alembic"
        )
        cfg = Config()
        cfg.set_main_option("script_location", script_location)
        script = ScriptDirectory.from_config(cfg)
        known = {rev.revision for rev in script.walk_revisions()}
        out["code_heads"] = list(script.get_heads())
        out["orphaned"] = [v for v in out.get("db_versions", []) if v not in known]
        out["reconcilable"] = not out["orphaned"]
    except Exception as exc:  # noqa: BLE001 — diagnostic must not raise
        out["code_error"] = type(exc).__name__

    return JSONResponse(content=out, status_code=http_status.HTTP_200_OK)


@app.get("/api/health/deep")
async def api_health_deep_check():
    """Deep healthcheck — probes core business tables against the live ORM.

    Motivation: /api/health only does `SELECT 1`, so it stays green even when
    a core module is 503-ing for real users. NEXUS prod has chronic alembic
    multi-head drift; the app boots anyway via entrypoint.sh's hand-maintained
    `_COLUMN_STATEMENTS` safety-net + `Base.metadata.create_all` (tables only).
    The trap: a migration that adds a COLUMN to an EXISTING table lands neither
    (create_all skips existing tables, and the manual list is easy to forget) —
    the ORM then `SELECT`s a column Postgres doesn't have → `UndefinedColumn` →
    the whole module renders empty (non-CORS 503), while the deploy ships GREEN
    because the smoke-test never touched that endpoint. This happened 2026-07-06:
    migration 0154 added `contract_candidate_rates.effective_to`; every contract
    query eager-loads that child table → all of /api/contracts 503'd for a day
    (PR #647). See memory `entrypoint-safetynet-new-columns`.

    This endpoint runs `SELECT <all mapped columns> ... LIMIT 1` for each core
    table, forcing Postgres to resolve every column the ORM maps. A drifted
    column makes the check (and, via the deploy smoke-test, the deploy) go RED
    instead of shipping a broken module. Drift-prone CHILD tables (contract_*_rates)
    are listed explicitly: a bare `SELECT Contract` would not touch them (their
    relationships are lazy), yet the real endpoints eager-load them — which is
    exactly how the 0154 incident slipped through.

    Auth-free by design (no CI-side login/token coupling that could itself block
    deploys). Response leaks only table names + the failing exception's class
    name; full errors go to server logs / Sentry. HTTP 503 if any core table
    fails; 200 when all pass.

    When a NEW core table (or a drift-prone child) is added, extend `core_checks`
    below in the same spirit as the entrypoint.sh safety-net checklist.
    """
    import asyncio
    import os

    from fastapi import status as http_status
    from fastapi.responses import JSONResponse
    from sqlalchemy import select, text

    from app.core import db_collation
    from app.core.database import AsyncSessionLocal
    from app.models.b2b_generated_contract import B2BGeneratedContract
    from app.models.b2b_generated_contract_status_event import (
        B2BGeneratedContractStatusEvent,
    )
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.client_order_group import (
        ClientOrderGroup,
        ClientOrderGroupEvent,
    )
    from app.models.md_consumption import (
        ClientOrderInvoiceConsumption,
        ClientOrderMdConsumption,
        MdConsumptionImport,
        MdConsumptionImportRow,
    )
    from app.models.dl_alert import DlAlert
    from app.models.contract import Contract
    from app.models.contract_candidate_rate import ContractCandidateRate
    from app.models.contract_client_rate import ContractClientRate
    from app.models.cortex import (
        CortexExtractionRun,
        CortexSkillFact,
        CortexUnmatchedObservation,
        CortexUnmatchedTerm,
    )
    from app.models.finance import FinanceImportRun, FinanceMonthlyResult
    from app.models.invite_link import CandidateInviteLink
    from app.models.job import Job
    from app.models.recruitment_priority import (
        RecruitmentPriorityAlert,
        RecruitmentPriorityAssignment,
        RecruitmentPriorityAuditEvent,
        RecruitmentPriorityBlocker,
        RecruitmentPriorityDemand,
        RecruitmentPriorityException,
        RecruitmentPriorityPlan,
        RecruitmentPriorityPlanMember,
        RecruitmentPriorityState,
        RecruitmentPriorityUserMode,
    )
    from app.models.note import Note
    from app.models.notification import Notification
    from app.models.candidate_document import CandidateDocument
    from app.models.recruitment_pipeline import CandidateStage
    from app.models.user import User
    from app.models.recruitment_process import RecruitmentProcess
    from app.models.candidate_contact import (
        CandidateContactCase,
        CandidateContactEvent,
        CandidateContactOpportunity,
        CandidateContactTraffitCursor,
        CandidateContactTraffitLedger,
    )

    # (check_name, ORM model). Names are table-oriented so a red check in the
    # deploy log points straight at the drifted table. Cortex tables added after
    # the 2026-07-12 incident (green deploy, tables missing → /api/cortex/* 500).
    core_checks = [
        ("contracts", Contract),
        ("contract_candidate_rates", ContractCandidateRate),
        ("contract_client_rates", ContractClientRate),
        # 0227: moduł Finanse. Bez tych dwóch wpisów zielony deploy nie mówi
        # nic o tym, czy tabele w ogóle powstały — a prodowy alembic bywa
        # osierocony, więc /api/health/deep jest jedynym realnym dowodem.
        ("finance_import_runs", FinanceImportRun),
        ("finance_monthly_results", FinanceMonthlyResult),
        ("b2b_generated_contracts", B2BGeneratedContract),
        (
            "b2b_generated_contract_status_events",
            B2BGeneratedContractStatusEvent,
        ),
        # Zamówienia wielo-konsultantowe (0227). Bez tych sond zakładka
        # „Zamówienia" trzech klientów rozliczanych na MD wywalałaby
        # UndefinedTable przy zielonym deployu — dokładnie tryb awarii
        # z incydentu Cortexa.
        ("client_order_groups", ClientOrderGroup),
        ("client_order_group_events", ClientOrderGroupEvent),
        ("client_order_md_consumptions", ClientOrderMdConsumption),
        ("md_consumption_imports", MdConsumptionImport),
        ("md_consumption_import_rows", MdConsumptionImportRow),
        # 0233: rozliczenie zamówień kosztowych i powiadomienia Delivery Leada.
        # Ta sama reguła co wyżej — brak tabeli wyszedłby dopiero przy pierwszym
        # imporcie faktur albo pierwszym przebiegu skanera alertów, czyli po
        # zielonym deployu i bez związku czasowego z przyczyną.
        ("client_order_invoice_consumptions", ClientOrderInvoiceConsumption),
        ("dl_alerts", DlAlert),
        ("candidates", Candidate),
        ("clients", Client),
        ("jobs", Job),
        # Pięć najgorętszych tabel produktu, których ta bramka nie obejmowała
        # do 2026-08-21 — czyli dokładnie te, na których rozjazd kolumny
        # kosztuje najwięcej. `candidate_stages` czyta każdy ruch w pipelinie,
        # każde renderowanie Kanbana i każdy lejek KPI, a kolumny dostawało
        # jeszcze niedawno (0199, 0122, 0056); `notes` (0129), `candidate_documents`
        # (0079, 0195), `users` (autoryzacja) i `notifications` są w tej samej
        # sytuacji. Sonda `candidates` ich NIE pokrywa: `select(Candidate)`
        # rozwiązuje wyłącznie kolumny `candidates`, a relacje są leniwe —
        # to jest ten sam mechanizm, którym przeszedł incydent 0154.
        ("candidate_stages", CandidateStage),
        ("notes", Note),
        ("candidate_documents", CandidateDocument),
        ("users", User),
        ("notifications", Notification),
        ("candidate_invite_links", CandidateInviteLink),
        ("recruitment_processes", RecruitmentProcess),
        ("recruitment_priority_plans", RecruitmentPriorityPlan),
        ("recruitment_priority_plan_members", RecruitmentPriorityPlanMember),
        ("recruitment_priority_demands", RecruitmentPriorityDemand),
        ("recruitment_priority_assignments", RecruitmentPriorityAssignment),
        ("recruitment_priority_blockers", RecruitmentPriorityBlocker),
        ("recruitment_priority_exceptions", RecruitmentPriorityException),
        ("recruitment_priority_state", RecruitmentPriorityState),
        ("recruitment_priority_user_modes", RecruitmentPriorityUserMode),
        ("recruitment_priority_alerts", RecruitmentPriorityAlert),
        ("recruitment_priority_audit_events", RecruitmentPriorityAuditEvent),
        # Kolejka kontaktu: prod ma osierocony alembic (bookmark 0152), więc
        # schemat dowozi idempotentny safety-net z entrypoint.sh. Bez sondy brak
        # tabeli wyszedłby dopiero przy włączeniu flagi — dokładnie ten scenariusz
        # co incydent Cortexa 2026-07-12 (zielony deploy, 500 na pierwszym ruchu).
        ("candidate_contact_cases", CandidateContactCase),
        ("candidate_contact_opportunities", CandidateContactOpportunity),
        ("candidate_contact_events", CandidateContactEvent),
        ("candidate_contact_traffit_cursors", CandidateContactTraffitCursor),
        ("candidate_contact_traffit_ledger", CandidateContactTraffitLedger),
        ("cortex_skill_facts", CortexSkillFact),
        ("cortex_unmatched_terms", CortexUnmatchedTerm),
        ("cortex_unmatched_observations", CortexUnmatchedObservation),
        ("cortex_extraction_runs", CortexExtractionRun),
    ]

    checks: dict[str, str] = {}
    errors: dict[str, str] = {}

    for name, model in core_checks:
        # Fresh session per check so a failed query (which aborts the
        # transaction) can't cascade "InFailedSqlTransaction" into the rest.
        try:
            async with AsyncSessionLocal() as session:
                await asyncio.wait_for(
                    session.execute(select(model).limit(1)), timeout=3.0
                )
            checks[name] = "healthy"
        except Exception as exc:  # noqa: BLE001
            checks[name] = "unhealthy"
            errors[name] = type(exc).__name__
            logger.warning("health/deep: %s probe failed: %r", name, exc)

    # The generated-contract ORM probe above resolves every mapped column, but
    # it cannot prove that the fail-open startup safety-net also installed the
    # default, enum labels, constraints and valid relation indexes required by
    # the signing transaction. Keep this catalog check auth-free and boolean:
    # no row data or schema details leave the service.
    b2b_signature_schema_query = text(
        """
        WITH expected_columns(name) AS (
            VALUES
                ('signature_status'),
                ('signature_source'),
                ('candidate_id'),
                ('job_id'),
                ('client_id'),
                ('contract_id'),
                ('signed_at'),
                ('signed_by_user_id')
        ),
        expected_constraints(name) AS (
            VALUES
                ('ck_b2b_generated_contracts_signature_status'),
                ('ck_b2b_generated_contracts_signature_source'),
                ('fk_b2b_generated_contracts_candidate_id'),
                ('fk_b2b_generated_contracts_job_id'),
                ('fk_b2b_generated_contracts_client_id'),
                ('fk_b2b_generated_contracts_contract_id'),
                ('fk_b2b_generated_contracts_signed_by_user_id')
        ),
        expected_indexes(name) AS (
            VALUES
                ('ix_b2b_generated_contracts_candidate_id'),
                ('ix_b2b_generated_contracts_job_id'),
                ('ix_b2b_generated_contracts_client_id'),
                ('ix_b2b_generated_contracts_contract_id'),
                ('ix_b2b_generated_contracts_signed_by_user_id')
        )
        SELECT
            (
                SELECT COUNT(DISTINCT c.column_name) = 8
                FROM information_schema.columns AS c
                JOIN expected_columns AS e ON e.name = c.column_name
                WHERE c.table_schema = 'public'
                  AND c.table_name = 'b2b_generated_contracts'
            )
            AND EXISTS (
                SELECT 1
                FROM information_schema.columns AS c
                WHERE c.table_schema = 'public'
                  AND c.table_name = 'b2b_generated_contracts'
                  AND c.column_name = 'signature_status'
                  AND c.is_nullable = 'NO'
                  AND POSITION('unsigned' IN COALESCE(c.column_default, '')) > 0
            )
            AND (
                SELECT COUNT(DISTINCT e.enumlabel) = 2
                FROM pg_type AS t
                JOIN pg_enum AS e ON e.enumtypid = t.oid
                WHERE t.typname = 'contractstatus'
                  AND e.enumlabel IN ('ready_for_signature', 'void')
            )
            AND (
                SELECT COUNT(DISTINCT c.conname) = 7
                FROM pg_constraint AS c
                JOIN expected_constraints AS e ON e.name = c.conname
                WHERE c.conrelid =
                    TO_REGCLASS('public.b2b_generated_contracts')
            )
            AND (
                SELECT COUNT(DISTINCT ic.relname) = 5
                       AND COALESCE(BOOL_AND(i.indisvalid), FALSE)
                FROM pg_index AS i
                JOIN pg_class AS ic ON ic.oid = i.indexrelid
                JOIN expected_indexes AS e ON e.name = ic.relname
                WHERE i.indrelid =
                    TO_REGCLASS('public.b2b_generated_contracts')
            )
        """
    )
    try:
        async with AsyncSessionLocal() as session:
            result = await asyncio.wait_for(
                session.execute(b2b_signature_schema_query), timeout=3.0
            )
            schema_matches = bool(result.scalar_one())
        checks["b2b_signature_schema"] = "healthy" if schema_matches else "unhealthy"
        if not schema_matches:
            errors["b2b_signature_schema"] = "SchemaMismatch"
    except Exception as exc:  # noqa: BLE001
        checks["b2b_signature_schema"] = "unhealthy"
        errors["b2b_signature_schema"] = type(exc).__name__
        logger.warning("health/deep: b2b_signature_schema probe failed: %r", exc)

    # Priority Work needs more than mapped columns: admission safety depends on
    # enum labels, process/invite provenance FKs, and valid partial-unique
    # indexes. A fail-open entrypoint repair must therefore remain visible to
    # deployment verification.
    priority_work_schema_query = text(
        """
        WITH expected_enum(type_name, label) AS (
            VALUES
                ('prioritymode', 'off'),
                ('prioritymode', 'shadow'),
                ('prioritymode', 'enforce'),
                ('priorityplanstatus', 'draft'),
                ('priorityplanstatus', 'published'),
                ('priorityplanstatus', 'superseded'),
                ('prioritymemberstatus', 'active'),
                ('prioritymemberstatus', 'paused'),
                ('prioritydemandstatus', 'open'),
                ('prioritydemandstatus', 'covered'),
                ('prioritydemandstatus', 'fulfilled'),
                ('prioritydemandstatus', 'paused'),
                ('prioritydemandstatus', 'cancelled'),
                ('priorityrank', 'A'),
                ('priorityrank', 'B'),
                ('priorityrank', 'C'),
                ('priorityrank', 'D'),
                ('priorityrank', 'E'),
                ('prioritychannel', 'database'),
                ('prioritychannel', 'linkedin'),
                ('prioritychannel', 'mixed'),
                ('priorityblockercategory', 'brief'),
                ('priorityblockercategory', 'client_feedback'),
                ('priorityblockercategory', 'rate'),
                ('priorityblockercategory', 'market'),
                ('priorityblockercategory', 'competence'),
                ('priorityblockercategory', 'capacity'),
                ('priorityblockercategory', 'access'),
                ('priorityblockercategory', 'other'),
                ('priorityblockerstatus', 'pending'),
                ('priorityblockerstatus', 'accepted'),
                ('priorityblockerstatus', 'rejected'),
                ('priorityblockerstatus', 'resolved'),
                ('priorityexceptionstatus', 'approved'),
                ('priorityexceptionstatus', 'consumed'),
                ('priorityexceptionstatus', 'revoked'),
                ('priorityexceptionstatus', 'expired'),
                ('priorityoriginkind', 'legacy'),
                ('priorityoriginkind', 'assigned'),
                ('priorityoriginkind', 'shadow_violation'),
                ('priorityoriginkind', 'external_inbound'),
                ('priorityoriginkind', 'external_observed'),
                ('priorityoriginkind', 'manager_inbound'),
                ('priorityoriginkind', 'approved_exception'),
                ('priorityalertseverity', 'info'),
                ('priorityalertseverity', 'warning'),
                ('priorityalertseverity', 'critical')
        ),
        expected_fk(table_name, column_name, target_table, delete_action) AS (
            VALUES
                ('recruitment_priority_demands', 'job_id', 'jobs', 'r'),
                ('recruitment_priority_plan_members', 'plan_id',
                 'recruitment_priority_plans', 'c'),
                ('recruitment_priority_plan_members', 'user_id', 'users', 'r'),
                ('recruitment_priority_assignments', 'plan_member_id',
                 'recruitment_priority_plan_members', 'c'),
                ('recruitment_priority_assignments', 'demand_id',
                 'recruitment_priority_demands', 'r'),
                ('recruitment_priority_assignments', 'job_id', 'jobs', 'r'),
                ('recruitment_priority_blockers', 'assignment_id',
                 'recruitment_priority_assignments', 'c'),
                ('recruitment_priority_exceptions', 'user_id', 'users', 'r'),
                ('recruitment_priority_exceptions', 'job_id', 'jobs', 'r'),
                ('recruitment_priority_exceptions', 'consumed_process_id',
                 'recruitment_processes', 'n'),
                ('recruitment_priority_state', 'current_plan_id',
                 'recruitment_priority_plans', 'n'),
                ('recruitment_priority_user_modes', 'user_id', 'users', 'c'),
                ('recruitment_processes', 'origin_assignment_id',
                 'recruitment_priority_assignments', 'n'),
                ('recruitment_processes', 'eligibility_assignment_id',
                 'recruitment_priority_assignments', 'n'),
                ('recruitment_processes', 'opened_by_user_id', 'users', 'n'),
                ('recruitment_processes', 'credit_user_id', 'users', 'n'),
                ('recruitment_processes', 'ownership_confirmed_by_user_id',
                 'users', 'n'),
                ('candidate_invite_links', 'origin_assignment_id',
                 'recruitment_priority_assignments', 'n')
        ),
        expected_check(table_name, constraint_name, definition_fragment) AS (
            VALUES
                ('recruitment_priority_demands',
                 'ck_priority_demand_recommendations_minimum',
                 'expected_recommendations >= 3')
        ),
        expected_constraint(table_name, constraint_name, constraint_type) AS (
            VALUES
                ('recruitment_priority_plans',
                 'recruitment_priority_plans_pkey', 'p'),
                ('recruitment_priority_plans',
                 'recruitment_priority_plans_version_key', 'u'),
                ('recruitment_priority_plans',
                 'ck_priority_plan_version_positive', 'c'),
                ('recruitment_priority_plans',
                 'ck_priority_plan_row_version_positive', 'c'),
                ('recruitment_priority_demands',
                 'recruitment_priority_demands_pkey', 'p'),
                ('recruitment_priority_demands',
                 'ck_priority_demand_recommendations_minimum', 'c'),
                ('recruitment_priority_demands',
                 'ck_priority_demand_row_version_positive', 'c'),
                ('recruitment_priority_plan_members',
                 'recruitment_priority_plan_members_pkey', 'p'),
                ('recruitment_priority_plan_members',
                 'uq_priority_plan_member_user', 'u'),
                ('recruitment_priority_plan_members',
                 'ck_priority_member_capacity_nonnegative', 'c'),
                ('recruitment_priority_plan_members',
                 'ck_priority_member_paused_reason', 'c'),
                ('recruitment_priority_assignments',
                 'recruitment_priority_assignments_pkey', 'p'),
                ('recruitment_priority_assignments',
                 'uq_priority_assignment_member_rank', 'u'),
                ('recruitment_priority_assignments',
                 'uq_priority_assignment_member_job', 'u'),
                ('recruitment_priority_assignments',
                 'ck_priority_assignment_verifications_nonnegative', 'c'),
                ('recruitment_priority_assignments',
                 'ck_priority_assignment_recommendations_nonnegative', 'c'),
                ('recruitment_priority_assignments',
                 'ck_priority_assignment_extra_slot_reason', 'c'),
                ('recruitment_priority_assignments',
                 'ck_priority_assignment_cc_exception_reason', 'c'),
                ('recruitment_priority_blockers',
                 'recruitment_priority_blockers_pkey', 'p'),
                ('recruitment_priority_blockers',
                 'ck_priority_blocker_decision_timestamp', 'c'),
                ('recruitment_priority_blockers',
                 'ck_priority_blocker_resolved_at', 'c'),
                ('recruitment_priority_exceptions',
                 'recruitment_priority_exceptions_pkey', 'p'),
                ('recruitment_priority_exceptions',
                 'recruitment_priority_exceptions_consumed_process_id_key', 'u'),
                ('recruitment_priority_exceptions',
                 'ck_priority_exception_valid_window', 'c'),
                ('recruitment_priority_exceptions',
                 'ck_priority_exception_consumed_at', 'c'),
                ('recruitment_priority_state',
                 'recruitment_priority_state_pkey', 'p'),
                ('recruitment_priority_state',
                 'recruitment_priority_state_current_plan_id_key', 'u'),
                ('recruitment_priority_state',
                 'ck_recruitment_priority_state_singleton', 'c'),
                ('recruitment_priority_state',
                 'ck_priority_state_row_version_positive', 'c'),
                ('recruitment_priority_user_modes',
                 'recruitment_priority_user_modes_pkey', 'p'),
                ('recruitment_priority_alerts',
                 'recruitment_priority_alerts_pkey', 'p'),
                ('recruitment_priority_alerts',
                 'recruitment_priority_alerts_dedupe_key_key', 'u'),
                ('recruitment_priority_alerts',
                 'ck_priority_alert_occurrence_count_positive', 'c'),
                ('recruitment_priority_alerts',
                 'ck_priority_alert_seen_window', 'c'),
                ('recruitment_priority_audit_events',
                 'recruitment_priority_audit_events_pkey', 'p')
        ),
        expected_index(table_name, index_name, must_be_unique, must_be_partial) AS (
            VALUES
                ('recruitment_priority_plans',
                 'ux_recruitment_priority_one_published', TRUE, TRUE),
                ('recruitment_priority_plans',
                 'ix_recruitment_priority_plans_status', FALSE, FALSE),
                ('recruitment_priority_plans',
                 'ix_recruitment_priority_plans_review_due_at', FALSE, FALSE),
                ('recruitment_priority_demands',
                 'ux_recruitment_priority_one_active_demand_per_job', TRUE, TRUE),
                ('recruitment_priority_demands',
                 'ix_recruitment_priority_demands_job_id', FALSE, FALSE),
                ('recruitment_priority_demands',
                 'ix_recruitment_priority_demands_requested_by_user_id',
                 FALSE, FALSE),
                ('recruitment_priority_demands',
                 'ix_recruitment_priority_demands_status', FALSE, FALSE),
                ('recruitment_priority_demands',
                 'ix_recruitment_priority_demands_due_at', FALSE, FALSE),
                ('recruitment_priority_plan_members',
                 'ix_recruitment_priority_plan_members_plan_id', FALSE, FALSE),
                ('recruitment_priority_plan_members',
                 'ix_recruitment_priority_plan_members_user_id', FALSE, FALSE),
                ('recruitment_priority_assignments',
                 'ix_recruitment_priority_assignments_plan_member_id',
                 FALSE, FALSE),
                ('recruitment_priority_assignments',
                 'ix_priority_assignment_job', FALSE, FALSE),
                ('recruitment_priority_assignments',
                 'ix_priority_assignment_demand', FALSE, FALSE),
                ('recruitment_priority_blockers',
                 'ux_priority_blocker_assignment_active', TRUE, TRUE),
                ('recruitment_priority_blockers',
                 'ix_recruitment_priority_blockers_assignment_id', FALSE, FALSE),
                ('recruitment_priority_blockers',
                 'ix_recruitment_priority_blockers_status', FALSE, FALSE),
                ('recruitment_priority_exceptions',
                 'ux_priority_exception_one_approved_per_user_job', TRUE, TRUE),
                ('recruitment_priority_exceptions',
                 'ix_priority_exception_expiry', FALSE, FALSE),
                ('recruitment_priority_exceptions',
                 'ix_recruitment_priority_exceptions_user_id', FALSE, FALSE),
                ('recruitment_priority_exceptions',
                 'ix_recruitment_priority_exceptions_job_id', FALSE, FALSE),
                ('recruitment_priority_exceptions',
                 'ix_recruitment_priority_exceptions_status', FALSE, FALSE),
                ('recruitment_priority_alerts',
                 'ix_priority_alert_unresolved', FALSE, TRUE),
                ('recruitment_priority_alerts',
                 'ix_recruitment_priority_alerts_kind', FALSE, FALSE),
                ('recruitment_priority_alerts',
                 'ix_recruitment_priority_alerts_user_id', FALSE, FALSE),
                ('recruitment_priority_alerts',
                 'ix_recruitment_priority_alerts_job_id', FALSE, FALSE),
                ('recruitment_priority_alerts',
                 'ix_recruitment_priority_alerts_assignment_id', FALSE, FALSE),
                ('recruitment_priority_audit_events',
                 'ix_priority_audit_event_type_occurred', FALSE, FALSE),
                ('recruitment_priority_audit_events',
                 'ix_priority_audit_plan_occurred', FALSE, FALSE),
                ('recruitment_priority_audit_events',
                 'ix_recruitment_priority_audit_events_correlation_id',
                 FALSE, FALSE),
                ('recruitment_processes',
                 'ix_recruitment_processes_origin_assignment_id', FALSE, FALSE),
                ('recruitment_processes',
                 'ix_recruitment_processes_eligibility_assignment_id',
                 FALSE, FALSE),
                ('recruitment_processes',
                 'ix_recruitment_processes_credit_user_id', FALSE, FALSE),
                ('recruitment_processes',
                 'ix_recruitment_processes_origin_kind', FALSE, FALSE),
                ('candidate_invite_links',
                 'ix_candidate_invite_links_origin_assignment_id', FALSE, FALSE)
        ),
        expected_index_columns(table_name, index_name, column_names) AS (
            VALUES
                ('recruitment_priority_plans',
                 'ux_recruitment_priority_one_published', 'status'),
                ('recruitment_priority_plans',
                 'ix_recruitment_priority_plans_status', 'status'),
                ('recruitment_priority_plans',
                 'ix_recruitment_priority_plans_review_due_at', 'review_due_at'),
                ('recruitment_priority_demands',
                 'ux_recruitment_priority_one_active_demand_per_job', 'job_id'),
                ('recruitment_priority_demands',
                 'ix_recruitment_priority_demands_job_id', 'job_id'),
                ('recruitment_priority_demands',
                 'ix_recruitment_priority_demands_requested_by_user_id',
                 'requested_by_user_id'),
                ('recruitment_priority_demands',
                 'ix_recruitment_priority_demands_status', 'status'),
                ('recruitment_priority_demands',
                 'ix_recruitment_priority_demands_due_at', 'due_at'),
                ('recruitment_priority_plan_members',
                 'ix_recruitment_priority_plan_members_plan_id', 'plan_id'),
                ('recruitment_priority_plan_members',
                 'ix_recruitment_priority_plan_members_user_id', 'user_id'),
                ('recruitment_priority_assignments',
                 'ix_recruitment_priority_assignments_plan_member_id',
                 'plan_member_id'),
                ('recruitment_priority_assignments',
                 'ix_priority_assignment_job', 'job_id'),
                ('recruitment_priority_assignments',
                 'ix_priority_assignment_demand', 'demand_id'),
                ('recruitment_priority_blockers',
                 'ux_priority_blocker_assignment_active', 'assignment_id'),
                ('recruitment_priority_blockers',
                 'ix_recruitment_priority_blockers_assignment_id',
                 'assignment_id'),
                ('recruitment_priority_blockers',
                 'ix_recruitment_priority_blockers_status', 'status'),
                ('recruitment_priority_exceptions',
                 'ux_priority_exception_one_approved_per_user_job',
                 'user_id,job_id'),
                ('recruitment_priority_exceptions',
                 'ix_priority_exception_expiry', 'status,expires_at'),
                ('recruitment_priority_exceptions',
                 'ix_recruitment_priority_exceptions_user_id', 'user_id'),
                ('recruitment_priority_exceptions',
                 'ix_recruitment_priority_exceptions_job_id', 'job_id'),
                ('recruitment_priority_exceptions',
                 'ix_recruitment_priority_exceptions_status', 'status'),
                ('recruitment_priority_alerts',
                 'ix_priority_alert_unresolved', 'severity,last_seen_at'),
                ('recruitment_priority_alerts',
                 'ix_recruitment_priority_alerts_kind', 'kind'),
                ('recruitment_priority_alerts',
                 'ix_recruitment_priority_alerts_user_id', 'user_id'),
                ('recruitment_priority_alerts',
                 'ix_recruitment_priority_alerts_job_id', 'job_id'),
                ('recruitment_priority_alerts',
                 'ix_recruitment_priority_alerts_assignment_id',
                 'assignment_id'),
                ('recruitment_priority_audit_events',
                 'ix_priority_audit_event_type_occurred',
                 'event_type,occurred_at'),
                ('recruitment_priority_audit_events',
                 'ix_priority_audit_plan_occurred', 'plan_id,occurred_at'),
                ('recruitment_priority_audit_events',
                 'ix_recruitment_priority_audit_events_correlation_id',
                 'correlation_id'),
                ('recruitment_processes',
                 'ix_recruitment_processes_origin_assignment_id',
                 'origin_assignment_id'),
                ('recruitment_processes',
                 'ix_recruitment_processes_eligibility_assignment_id',
                 'eligibility_assignment_id'),
                ('recruitment_processes',
                 'ix_recruitment_processes_credit_user_id', 'credit_user_id'),
                ('recruitment_processes',
                 'ix_recruitment_processes_origin_kind', 'origin_kind'),
                ('candidate_invite_links',
                 'ix_candidate_invite_links_origin_assignment_id',
                 'origin_assignment_id')
        ),
        expected_index_predicate(
            table_name,
            index_name,
            canonical_definition
        ) AS (
            VALUES
                ('recruitment_priority_plans',
                 'ux_recruitment_priority_one_published',
                 'status=''published'''),
                ('recruitment_priority_demands',
                 'ux_recruitment_priority_one_active_demand_per_job',
                 'status=anyarray[''open'',''covered'',''paused'']'),
                ('recruitment_priority_blockers',
                 'ux_priority_blocker_assignment_active',
                 'status=anyarray[''pending'',''accepted'']andresolved_atisnull'),
                ('recruitment_priority_exceptions',
                 'ux_priority_exception_one_approved_per_user_job',
                 'status=''approved'''),
                ('recruitment_priority_alerts',
                 'ix_priority_alert_unresolved',
                 'resolved_atisnull')
        )
        SELECT
            NOT EXISTS (
                SELECT 1
                FROM expected_enum AS expected
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM pg_type AS enum_type
                    JOIN pg_enum AS enum_value
                      ON enum_value.enumtypid = enum_type.oid
                    WHERE enum_type.typname = expected.type_name
                      AND enum_value.enumlabel = expected.label
                )
            )
            AND NOT EXISTS (
                SELECT 1
                FROM expected_fk AS expected
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM pg_constraint AS constraint_row
                    JOIN pg_attribute AS source_column
                      ON source_column.attrelid = constraint_row.conrelid
                     AND source_column.attnum = ANY(constraint_row.conkey)
                    WHERE constraint_row.contype = 'f'
                      AND constraint_row.conrelid =
                          TO_REGCLASS('public.' || expected.table_name)
                      AND constraint_row.confrelid =
                          TO_REGCLASS('public.' || expected.target_table)
                      AND source_column.attname = expected.column_name
                      AND constraint_row.confdeltype::text =
                          expected.delete_action
                )
            )
            AND NOT EXISTS (
                SELECT 1
                FROM expected_check AS expected
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM pg_constraint AS constraint_row
                    WHERE constraint_row.conrelid =
                          TO_REGCLASS('public.' || expected.table_name)
                      AND constraint_row.conname = expected.constraint_name
                      AND constraint_row.contype = 'c'
                      AND PG_GET_CONSTRAINTDEF(constraint_row.oid)
                          LIKE '%' || expected.definition_fragment || '%'
                )
            )
            AND NOT EXISTS (
                SELECT 1
                FROM expected_constraint AS expected
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM pg_constraint AS constraint_row
                    WHERE constraint_row.conrelid =
                          TO_REGCLASS('public.' || expected.table_name)
                      AND constraint_row.conname = expected.constraint_name
                      AND constraint_row.contype::text =
                          expected.constraint_type
                )
            )
            AND NOT EXISTS (
                SELECT 1
                FROM expected_index AS expected
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM pg_index AS index_row
                    JOIN pg_class AS index_class
                      ON index_class.oid = index_row.indexrelid
                    WHERE index_row.indrelid =
                          TO_REGCLASS('public.' || expected.table_name)
                      AND index_class.relname = expected.index_name
                      AND index_row.indisvalid
                      AND index_row.indisready
                      AND index_row.indisunique = expected.must_be_unique
                      AND (index_row.indpred IS NOT NULL) =
                          expected.must_be_partial
                )
            )
            AND NOT EXISTS (
                SELECT 1
                FROM expected_index_columns AS expected
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM pg_index AS index_row
                    JOIN pg_class AS index_class
                      ON index_class.oid = index_row.indexrelid
                    WHERE index_row.indrelid =
                          TO_REGCLASS('public.' || expected.table_name)
                      AND index_class.relname = expected.index_name
                      AND ARRAY_TO_STRING(
                          ARRAY(
                              SELECT attribute.attname
                              FROM UNNEST(index_row.indkey)
                                   WITH ORDINALITY
                                   AS indexed(attnum, position)
                              JOIN pg_attribute AS attribute
                                ON attribute.attrelid = index_row.indrelid
                               AND attribute.attnum = indexed.attnum
                              WHERE indexed.attnum > 0
                              ORDER BY indexed.position
                          ),
                          ','
                      ) = expected.column_names
                )
            )
            AND NOT EXISTS (
                SELECT 1
                FROM expected_index_predicate AS expected
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM pg_index AS index_row
                    JOIN pg_class AS index_class
                      ON index_class.oid = index_row.indexrelid
                    WHERE index_row.indrelid =
                          TO_REGCLASS('public.' || expected.table_name)
                      AND index_class.relname = expected.index_name
                      AND REGEXP_REPLACE(
                          REGEXP_REPLACE(
                              LOWER(
                                  COALESCE(
                                      PG_GET_EXPR(
                                          index_row.indpred,
                                          index_row.indrelid
                                      ),
                                      ''
                                  )
                              ),
                              '::[a-z_][a-z0-9_]*(\\[\\])?',
                              '',
                              'g'
                          ),
                          '[[:space:]()]',
                          '',
                          'g'
                      ) = expected.canonical_definition
                )
            )
        """
    )
    try:
        async with AsyncSessionLocal() as session:
            result = await asyncio.wait_for(
                session.execute(priority_work_schema_query), timeout=3.0
            )
            schema_matches = bool(result.scalar_one())
        checks["priority_work_schema"] = "healthy" if schema_matches else "unhealthy"
        if not schema_matches:
            errors["priority_work_schema"] = "SchemaMismatch"
    except Exception as exc:  # noqa: BLE001
        checks["priority_work_schema"] = "unhealthy"
        errors["priority_work_schema"] = type(exc).__name__
        logger.warning("health/deep: priority_work_schema probe failed: %r", exc)

    # The client-directory deploy is not complete until the exact checked-in
    # manifest hash has one consistent applied run.  Expose only the hash,
    # status and aggregate counters: no source/client names or row payloads.
    from app.services.client_portfolio_import import (
        get_client_portfolio_import_health,
        load_client_portfolio_manifest,
    )

    portfolio_manifest = None
    portfolio_import: dict = {
        "expected_source_sha256": None,
        "expected_manifest_sha256": None,
        "status": "error",
        "run_id": None,
        "applied_at": None,
        "counts": {},
    }
    try:
        portfolio_manifest = load_client_portfolio_manifest()
        portfolio_import["expected_source_sha256"] = portfolio_manifest["source"][
            "sha256"
        ]
        portfolio_import["counts"] = {
            "expected_manifest_rows": len(portfolio_manifest["rows"])
        }
        async with AsyncSessionLocal() as session:
            portfolio_import = await asyncio.wait_for(
                get_client_portfolio_import_health(
                    session,
                    manifest=portfolio_manifest,
                ),
                timeout=3.0,
            )
        import_status = portfolio_import["status"]
        checks["client_portfolio_import"] = (
            "healthy" if import_status == "applied" else "unhealthy"
        )
        if import_status != "applied":
            errors["client_portfolio_import"] = {
                "not_applied": "ManifestNotApplied",
                "inconsistent": "ImportCountMismatch",
            }.get(import_status, "ImportStateInvalid")
    except Exception as exc:  # noqa: BLE001
        checks["client_portfolio_import"] = "unhealthy"
        errors["client_portfolio_import"] = type(exc).__name__
        logger.warning("health/deep: client portfolio import probe failed: %r", exc)

    # Kolacja bazy — patrz `app/core/db_collation.py` po pełne uzasadnienie.
    # W skrócie: porządek sortowania CAŁEGO tekstu wybiera niejawnie tag obrazu
    # w docker-compose.yml, katalog `pg_database` na to pytanie odpowiada
    # MYLĄCO (obie warianty raportują `en_US.utf8`), a wbudowane ostrzeżenie
    # PostgreSQL o dryfie kolacji nie może wystrzelić, bo pod musl
    # `datcollversion` jest pusty. Ta sonda jest jedynym miejscem, w którym
    # podmiana obrazu na istniejącym wolumenie przestaje być niema.
    collation_report: dict = {"status": "unknown"}
    try:
        async with AsyncSessionLocal() as session:
            result = await asyncio.wait_for(
                session.execute(db_collation.COLLATION_PROBE_SQL), timeout=3.0
            )
            row = result.mappings().one()
        matches, collation_report = db_collation.evaluate(dict(row))
        checks["db_collation"] = "healthy" if matches else "unhealthy"
        if not matches:
            errors["db_collation"] = "CollationDrift"
    except Exception as exc:  # noqa: BLE001
        checks["db_collation"] = "unhealthy"
        errors["db_collation"] = type(exc).__name__
        collation_report = {"error": type(exc).__name__}
        logger.warning("health/deep: db_collation probe failed: %r", exc)

    all_healthy = all(v == "healthy" for v in checks.values())

    body: dict = {
        "status": "healthy" if all_healthy else "unhealthy",
        "version": os.environ.get("GIT_SHA", "unknown"),
        "checks": checks,
        "collation": collation_report,
        "client_portfolio_import": portfolio_import,
    }
    if errors:
        body["errors"] = errors

    return JSONResponse(
        content=body,
        status_code=http_status.HTTP_200_OK
        if all_healthy
        else http_status.HTTP_503_SERVICE_UNAVAILABLE,
    )
