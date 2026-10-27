"""Staging na laptopie: pełna kopia produkcji bez wyjścia na świat.

Plan: ``docs/staging-laptop-plan.md``. Przy ``NEXUS_ENV=staging`` baza jest
kopią produkcji (kandydaci, kolejki wysyłek, kursory synchronizacji), więc
każda pętla w tle, która coś wysyła albo synchronizuje, zrobiłaby to naprawdę.
Dlatego na stagingu pętle są domyślnie WYŁĄCZONE, a działają tylko te
z ``STAGING_ALLOWED_TASKS`` — porządki i przeliczenia wyłącznie na bazie.

Każda nazwa z rejestru ``app.state.background_tasks`` (``app/main.py``) musi
być w dokładnie jednym z dwóch zbiorów. Pilnuje tego
``tests/test_staging_background_tasks.py``: nowa pętla bez decyzji „wolno /
nie wolno” zatrzymuje CI, zamiast po cichu ruszyć na stagingu.

Druga zapora to wyjście sieciowe (``install_egress_guard``). Wspólnego klienta
HTTP w kodzie nie ma (ponad 40 miejsc z ``httpx.AsyncClient(``, do tego msal,
boto3, smtplib), więc zapora siedzi na klasach transportu bibliotek: każde
połączenie do hosta spoza listy kończy się błędem połączenia, zanim cokolwiek
wyjdzie z laptopa — także z obsługi żądań, nie tylko z pętli.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
from collections.abc import Callable, Iterable, Mapping
from typing import Any

logger = logging.getLogger(__name__)

# Dostawcy AI: bez nich większość ścieżek (odczyt CV, Champion, Jarvis,
# wyszukiwanie) nie da się sprawdzić. Resztę dokłada
# `STAGING_EXTRA_ALLOWED_HOSTS` (lista po przecinku), np. host MinIO.
STAGING_ALLOWED_EXTERNAL_HOSTS: frozenset[str] = frozenset(
    {
        "api.anthropic.com",
        "api.voyageai.com",
        "api.openai.com",
        "api.deepseek.com",
    }
)
_LOCAL_SUFFIXES = (".localhost", ".internal", ".local", ".test")


class StagingEgressBlocked(ConnectionError):
    """Połączenie ze stagingu do hosta spoza listy dozwolonych."""


# Porządki, retencja i przeliczenia na samej bazie. `index_outbox` liczy
# wektory w Voyage (AI zostaje na stagingu włączone), bez niego zmiany
# zrobione na stagingu nie trafiają do wyszukiwania.
STAGING_ALLOWED_TASKS: frozenset[str] = frozenset(
    {
        "candidate_search_retention",
        "jarvis_retention",
        "queue_retention",
        "match_history_ttl",
        "runtime_metrics",
        "keyword_corpus_backfill",
        "note_kind_backfill",
        "requirement_row_counts",
        "candidate_rate_from",
        "order_gaps",
        "insights_seniority_journal",
        "cc_participants_sync",
        "competition_autofreeze",
        "dl_portal_expiry",
        "index_outbox",
    }
)

# Wysyłki (maile, Slack, Teams), synchronizacje z M365/Compassem/CloudTalkiem/
# KSeF/Autenti/portalami oraz nocne przebiegi AI na całej bazie (koszt modeli
# drugi raz dziennie, a wynik i tak jest na produkcji).
STAGING_BLOCKED_TASKS: frozenset[str] = frozenset(
    {
        "cv_generation",
        "cv_approval",
        "cv_source_cleanup",
        "cv_version_maps",
        "candidate_search",
        "academy_intake",
        "application_screening",
        "trainee_call_lists",
        "calendar_reminder",
        "slack_sla_alerts",
        "ai_spend_alerts",
        "candidate_data_access_alerts",
        "contract_alerts",
        "teams_prep_scope_alerts",
        "fx_refresh",
        "cc_centroid_sync",
        "kpi_coach_nudger",
        "notification_triggers",
        "notification_volume_monitor",
        "app_mail_monitor",
        "rejection_email",
        "linkedin_sync",
        "microsoft365_sync",
        "m365_cv_parse",
        "m365_rematch",
        "m365_webhook_renewal",
        "m365_recording_discovery",
        "marketplace_sweeper",
        "saved_search_alerts",
        "cv_qc_recompute",
        "qc_quality_daily",
        "job_ad_prepare",
        "recommendation_card_import",
        "chat_email_fallback",
        "autenti_sweeper",
        "signature_reconciler",
        "b2b_esign_sweeper",
        "pre_contract_sweeper",
        "job_deadline_alerts",
        "kpi_email_reports",
        "daily_digest_email",
        "notification_email_outbox",
        "dl_alerts",
        "integration_stale_alerts",
        "integration_webhooks",
        "jjit_import",
        "cloudtalk_sync",
        "traffit_sync",
        "order_mail_ingest",
        "teams_prep_transcripts",
        "contract_docs_sharepoint",
        "compass_workdays_sync",
        "compass_lifecycle_sync",
        "m365_account_sweep",
        "job_portal_worker",
        "notes_insights_sync",
        "weekly_eval",
        "match_digest",
        "candidate_contact_queue",
        "candidate_contact_traffit",
        "candidate_auto_match",
        "auto_full_review",
        "new_column_autofill",
        "index_drift_reconciler",
        "priority_work",
        "workforce_availability",
        "recruitment_allocation",
        "allocation_matching",
        "hr_workdays",
        "hr_m365_outbox",
        "hr_m365_reconcile",
        "hr_m365_daily",
        "hr_timesheet_reminder",
        "care_reminders",
        "care_announcements_send",
        "ksef_fetch",
        "sales_ksef_fetch",
        "hr_agreements_signing",
        "hr_lifecycle",
        "hr_contract_hooks",
        "hr_bonus_proposals",
        "equipment_reminders",
        "equipment_intune_sync",
        "admin_cases_mail_ingest",
        "hr_approval_mail_replies",
    }
)


def stop_blocked_background_tasks(tasks: Mapping[str, asyncio.Task[Any]]) -> list[str]:
    """Anuluj na stagingu każdą pętlę spoza ``STAGING_ALLOWED_TASKS``.

    Wołane zaraz po zbudowaniu rejestru, przed pierwszym ``await`` lifespanu:
    zadanie anulowane, zanim pętla zdarzeń je uruchomi, nie wykonuje ani jednej
    linii swojej pętli. Nazwa spoza obu list też jest zatrzymywana — domyślnie
    „nie wolno”. Zwraca listę zatrzymanych nazw.
    """
    stopped = []
    for name, task in tasks.items():
        if name in STAGING_ALLOWED_TASKS:
            continue
        task.cancel()
        stopped.append(name)
    logger.warning(
        "staging: zatrzymane pętle w tle (%d z %d): %s",
        len(stopped),
        len(tasks),
        ", ".join(sorted(stopped)),
    )
    return stopped


def host_allowed(host: str | None, extra: Iterable[str] = ()) -> bool:
    """Czy staging może połączyć się z ``host``.

    Wolno: nazwy usług compose (bez kropki), ``localhost`` i domeny lokalne,
    adresy prywatne i pętli zwrotnej oraz hosty z listy dozwolonych. Publiczny
    adres IP produkcji czy obce API — nie.
    """
    if not host:
        return False
    name = host.strip().strip("[]").rstrip(".").lower()
    if not name:
        return False
    try:
        ip = ipaddress.ip_address(name)
    except ValueError:
        ip = None
    if ip is not None:
        return ip.is_loopback or ip.is_private
    if name == "localhost" or name.endswith(_LOCAL_SUFFIXES) or "." not in name:
        return True
    allowed = STAGING_ALLOWED_EXTERNAL_HOSTS | {h.strip().lower() for h in extra}
    return name in allowed


_originals: dict[tuple[Any, str], Callable[..., Any]] = {}


def _patch(
    owner: Any, attr: str, make: Callable[[Callable[..., Any]], Callable[..., Any]]
) -> None:
    original = getattr(owner, attr)
    _originals[(owner, attr)] = original
    setattr(owner, attr, make(original))


def _refuse(host: str | None, via: str) -> StagingEgressBlocked:
    logger.warning("staging: zablokowane wyjście do %s (%s)", host, via)
    return StagingEgressBlocked(f"staging: połączenie z {host} zablokowane")


def install_egress_guard(extra_hosts: Iterable[str] = ()) -> None:
    """Zablokuj na stagingu połączenia do hostów spoza listy (idempotentne)."""
    if _originals:
        return
    extra = tuple(h for h in extra_hosts if h.strip())

    import httpx

    def _httpx_sync(original: Callable[..., Any]) -> Callable[..., Any]:
        def handle_request(self: Any, request: Any) -> Any:
            host = request.url.host
            if not host_allowed(host, extra):
                raise httpx.ConnectError(str(_refuse(host, "httpx")), request=request)
            return original(self, request)

        return handle_request

    def _httpx_async(original: Callable[..., Any]) -> Callable[..., Any]:
        async def handle_async_request(self: Any, request: Any) -> Any:
            host = request.url.host
            if not host_allowed(host, extra):
                raise httpx.ConnectError(str(_refuse(host, "httpx")), request=request)
            return await original(self, request)

        return handle_async_request

    _patch(httpx.HTTPTransport, "handle_request", _httpx_sync)
    _patch(httpx.AsyncHTTPTransport, "handle_async_request", _httpx_async)

    # urllib3 niesie msal (tokeny M365) i botocore (magazyn dokumentów S3).
    import urllib3.connectionpool

    def _urllib3(original: Callable[..., Any]) -> Callable[..., Any]:
        def urlopen(self: Any, *args: Any, **kwargs: Any) -> Any:
            if not host_allowed(self.host, extra):
                raise _refuse(self.host, "urllib3")
            return original(self, *args, **kwargs)

        return urlopen

    _patch(urllib3.connectionpool.HTTPConnectionPool, "urlopen", _urllib3)

    import smtplib

    def _smtp(original: Callable[..., Any]) -> Callable[..., Any]:
        def connect(
            self: Any, host: str = "localhost", *args: Any, **kwargs: Any
        ) -> Any:
            if not host_allowed(host, extra):
                raise _refuse(host, "smtp")
            return original(self, host, *args, **kwargs)

        return connect

    _patch(smtplib.SMTP, "connect", _smtp)

    # SDK Anthropic jeździ na forku `httpx2`; dostawca jest dozwolony, ale
    # zapora ma objąć każdy inny host, który ktoś kiedyś przez niego zawoła.
    try:
        import httpx2  # type: ignore[import-not-found]
    except ImportError:
        pass
    else:
        _patch(httpx2.HTTPTransport, "handle_request", _httpx_sync)
        _patch(httpx2.AsyncHTTPTransport, "handle_async_request", _httpx_async)

    try:
        import aiohttp
    except ImportError:
        pass
    else:

        def _aiohttp(original: Callable[..., Any]) -> Callable[..., Any]:
            async def _request(
                self: Any, method: str, str_or_url: Any, *args: Any, **kwargs: Any
            ) -> Any:
                host = httpx.URL(str(str_or_url)).host
                if not host_allowed(host, extra):
                    raise _refuse(host, "aiohttp")
                return await original(self, method, str_or_url, *args, **kwargs)

            return _request

        _patch(aiohttp.ClientSession, "_request", _aiohttp)

    logger.warning(
        "staging: zapora wyjścia włączona; poza siecią lokalną dozwolone: %s",
        ", ".join(sorted(STAGING_ALLOWED_EXTERNAL_HOSTS | set(extra))),
    )


def uninstall_egress_guard() -> None:
    """Przywróć oryginalne metody (testy)."""
    for (owner, attr), original in _originals.items():
        setattr(owner, attr, original)
    _originals.clear()
