"""Admin-controlled routine email delivery. Missing policy is deliberately OFF.

Activation establishes a server timestamp; an event from an earlier disabled
period can never be replayed. In-app notifications and account-security email
are independent. This module never grants provider access or sends test mail.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

from sqlalchemy import create_engine, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.app_setting import AppSetting

logger = logging.getLogger(__name__)
SETTING_KEY = "notification_email_delivery"
_send_local = threading.local()

CATALOG = (
    dict(
        id="chat_unread",
        label="Nieprzeczytane wiadomości czatu",
        module="Czat",
        trigger="Nieprzeczytana wiadomość lub wzmianka; adresat jest offline od co najmniej 15 minut.",
        recipient_rule="Adresat powiadomienia czatu, nadal aktywny i uprawniony do jego sekcji.",
    ),
    dict(
        id="mentions",
        label="Wzmianki w notatkach",
        module="Notatki i screening",
        trigger="Oznaczenie osoby przez @wzmiankę w nowej lub edytowanej notatce.",
        recipient_rule="Oznaczone aktywne osoby z aktualnym dostępem do sekcji.",
    ),
    dict(
        id="pipeline_stage",
        label="Zmiany etapów rekrutacji",
        module="Rekrutacje",
        trigger="Zmiana etapu spełniająca skonfigurowaną regułę powiadomień.",
        recipient_rule="Odbiorcy reguły etapu: rekruter, DL, TAC, wskazana osoba, rola lub twórca kandydata. Nadal obowiązują szczegółowe reguły etapów.",
    ),
    dict(
        id="job_deadline",
        label="Terminy rekrutacji",
        module="Rekrutacje",
        trigger="Zbliżający się termin otwartej rekrutacji: progi 7, 3 i 1 dzień zgodnie z konfiguracją skanera.",
        recipient_rule="Przypisany rekruter, Delivery Lead, TAC i aktywni współpracownicy rekrutacji, z aktualnym dostępem.",
    ),
    dict(
        id="delivery_alert",
        label="Alerty klientów i umów",
        module="Klienci i umowy",
        trigger="Nowy alert lub próg przypomnienia z włączonym kanałem email w regule alertu.",
        recipient_rule="Aktywni administratorzy i Delivery Leadzi przypisani do danego klienta, z dostępem do sekcji.",
    ),
    dict(
        id="application_confirmation",
        label="Potwierdzenie aplikacji",
        module="Strona kariery",
        trigger="Kandydat wysłał zgłoszenie z CV przez link aplikacyjny lub stronę kariery (najwyżej jeden mail na adres i link w ciągu 24 h).",
        recipient_rule="Kandydat — adres z formularza. Treść jest taka sama, niezależnie od tego, czy osoba była już w bazie.",
    ),
    # Raporty KPI mailem (plan PR3, 23.09.2026) — `tasks/kpi_email_reports.py`.
    dict(
        id="kpi_weekly_report",
        label="Tygodniowy raport KPI zespołu",
        module="Statystyki",
        trigger="Poniedziałek od 8:00 — KPI zespołu za zamknięty tydzień (weryfikacje, rekomendacje, placementy, nowi kandydaci).",
        recipient_rule="Aktywni Head of Recruitment (rola główna albo dodatkowa) z dostępem do sekcji Insights; zespół według zakresu pulpitu odbiorcy.",
    ),
    dict(
        id="board_monthly_report",
        label="Miesięczne podsumowanie Rady",
        module="Statystyki",
        trigger="1. dzień roboczy miesiąca od 8:00 — kokpit Rady i porównanie rok do roku za zamknięty miesiąc.",
        recipient_rule="Aktywni administratorzy i Finanse z dostępem do sekcji Insights (mail niesie przychód i marżę).",
    ),
)
# Raporty nie mają odpowiednika w dzwonku — wychodzą wyłącznie mailem.
REPORT_KINDS = frozenset({"kpi_weekly_report", "board_monthly_report"})
ROUTINE_KINDS = frozenset(item["id"] for item in CATALOG)
SECURITY_CATALOG = (
    dict(
        id="password_reset",
        label="Reset hasła",
        trigger="Żądanie resetu hasła użytkownika lub administratora.",
    ),
    dict(
        id="email_verification",
        label="Weryfikacja adresu",
        trigger="Rejestracja lub ponowienie weryfikacji adresu email.",
    ),
    dict(
        id="password_changed",
        label="Zmiana hasła",
        trigger="Zmiana hasła konta przez użytkownika lub administratora.",
    ),
)


def _datetime(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
        if not isinstance(parsed, datetime) or parsed.tzinfo is None:
            return None
        return parsed.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


@dataclass(frozen=True)
class DeliveryPolicy:
    enabled: bool = False
    send_not_before: datetime | None = None
    types: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def from_value(cls, value: Any) -> DeliveryPolicy:
        value = value if isinstance(value, dict) else {}
        raw_types = value.get("types")
        return cls(
            enabled=value.get("enabled") is True,
            send_not_before=_datetime(value.get("send_not_before")),
            types={
                key: item
                for key, item in (raw_types or {}).items()
                if key in ROUTINE_KINDS and isinstance(item, dict)
            }
            if isinstance(raw_types, dict)
            else {},
        )

    def cutoff_for(self, kind: str) -> datetime | None:
        local = _datetime(self.types.get(kind, {}).get("send_not_before"))
        if self.send_not_before is None or local is None:
            return None
        return max(self.send_not_before, local)

    def kind_enabled(self, kind: str) -> bool:
        return bool(
            kind in ROUTINE_KINDS
            and self.enabled
            and self.types.get(kind, {}).get("email_enabled") is True
            and self.cutoff_for(kind) is not None
        )

    @property
    def effective_enabled(self) -> bool:
        return any(self.kind_enabled(kind) for kind in ROUTINE_KINDS)

    def allows(self, kind: str, event_at: datetime | None) -> bool:
        event_at = _datetime(event_at)
        cutoff = self.cutoff_for(kind)
        return bool(
            self.kind_enabled(kind) and event_at and cutoff and event_at >= cutoff
        )


def notification_kind(notification_type: Any) -> str | None:
    return {
        "job_chat_message": "chat_unread",
        "job_chat_mention": "chat_unread",
        "note_mention": "mentions",
        "stage_rule": "pipeline_stage",
        "job_deadline_7d": "job_deadline",
        "job_deadline_3d": "job_deadline",
        "job_deadline_1d": "job_deadline",
    }.get(getattr(notification_type, "value", notification_type))


async def load_policy(db: AsyncSession) -> DeliveryPolicy:
    # A fresh scalar avoids identity-map caching when an admin changes policy
    # during a long worker pass.
    value = await db.scalar(
        select(AppSetting.value).where(AppSetting.key == SETTING_KEY)
    )
    return DeliveryPolicy.from_value(value)


@lru_cache(maxsize=1)
def _read_engine():
    return create_engine(
        make_url(settings.DATABASE_URL).set(drivername="postgresql+psycopg2"),
        pool_size=1,
        max_overflow=0,
        pool_timeout=2,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 2, "options": "-c statement_timeout=2000"},
    )


def load_policy_sync() -> DeliveryPolicy:
    with _read_engine().connect() as conn:
        value = conn.execute(
            text("SELECT value FROM app_settings WHERE key=:key"), {"key": SETTING_KEY}
        ).scalar_one_or_none()
    return DeliveryPolicy.from_value(value)


def is_delivery_allowed_sync(kind: str, event_at: datetime | None) -> bool:
    try:
        return load_policy_sync().allows(kind, event_at)
    except Exception:
        logger.warning("notification email policy unavailable; delivery blocked")
        return False


def guarded_send(kind: str, event_at: datetime | None, send, *args, **kwargs) -> bool:
    """Recheck current policy immediately before entering a synchronous sender."""
    _send_local.policy_blocked = not is_delivery_allowed_sync(kind, event_at)
    if _send_local.policy_blocked:
        return False
    return send(*args, **kwargs)


def last_send_policy_blocked() -> bool:
    return bool(getattr(_send_local, "policy_blocked", False))


def updated_value(
    previous: DeliveryPolicy, *, enabled: bool, toggles: dict[str, bool], now: datetime
) -> dict:
    """Pure transition used after locking the stored row. Never accept client cutoffs."""
    if not set(toggles) <= ROUTINE_KINDS:
        raise ValueError("unknown notification email type")
    global_cutoff = previous.send_not_before
    if enabled and (not previous.enabled or global_cutoff is None):
        global_cutoff = now
    types = {}
    for kind in ROUTINE_KINDS:
        old = previous.types.get(kind, {})
        was_enabled = old.get("email_enabled") is True
        is_enabled = toggles.get(kind, was_enabled)
        cutoff = _datetime(old.get("send_not_before"))
        if is_enabled and (not was_enabled or cutoff is None):
            cutoff = now
        types[kind] = {
            "email_enabled": is_enabled,
            "send_not_before": cutoff.isoformat() if cutoff else None,
        }
    return {
        "enabled": enabled,
        "send_not_before": global_cutoff.isoformat() if global_cutoff else None,
        "types": types,
    }


async def save_policy(
    db: AsyncSession, *, enabled: bool, toggles: dict[str, bool], admin_id: int
) -> None:
    await db.execute(
        insert(AppSetting)
        .values(key=SETTING_KEY, value={"enabled": False})
        .on_conflict_do_nothing(index_elements=[AppSetting.key])
    )
    row = await db.scalar(
        select(AppSetting)
        .where(AppSetting.key == SETTING_KEY)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert row is not None
    row.value = updated_value(
        DeliveryPolicy.from_value(row.value),
        enabled=enabled,
        toggles=toggles,
        now=datetime.now(timezone.utc),
    )
    row.updated_by = admin_id
    await db.commit()


def _iso_epoch(value: Any) -> str | None:
    return (
        datetime.fromtimestamp(value, timezone.utc).isoformat()
        if isinstance(value, (float, int)) and value > 0
        else None
    )


async def admin_view(db: AsyncSession) -> dict[str, Any]:
    from app.services.m365 import app_mail, mail_circuit
    from app.services.m365.system_mail import get_system_sender_connection
    from app.tasks.app_mail_monitor import snapshot_queue

    policy = await load_policy(db)
    row = await db.get(AppSetting, SETTING_KEY)
    now = datetime.now(timezone.utc)
    if settings.M365_APP_MAIL_ENABLED:
        try:
            state = await asyncio.to_thread(mail_circuit.snapshot)
            state_available = True
        except Exception:
            logger.warning("notification email provider history unavailable")
            state = {}
            state_available = False
        configured = app_mail.is_configured()
        observed = app_mail.app_mail_send_verdict(
            app_mail.AppMailSendState(
                **{
                    key: state[key]
                    for key in app_mail.AppMailSendState.__dataclass_fields__
                    if key in state
                }
            ),
            configured=configured,
        )
        if configured and not state_available:
            observed = "unknown"
        provider = dict(
            kind="graph_app",
            sender=settings.M365_MAIL_SENDER_UPN or None,
            configured=configured,
            observed_status=observed,
            last_success_at=_iso_epoch(state.get("last_success_at")),
            last_failure_at=_iso_epoch(state.get("last_failure_at")),
            failure_code=state.get("last_failure_code")
            if state_available
            else "monitoring_state_unavailable",
            cooldown_until=_iso_epoch(state.get("next_attempt_at")),
        )
    else:
        configured = bool(settings.SMTP_ENABLED and settings.SMTP_HOST)
        provider = dict(
            kind="smtp" if settings.SMTP_ENABLED else "none",
            sender=settings.SMTP_FROM_EMAIL or None,
            configured=configured,
            observed_status="unknown" if configured else "unconfigured",
            last_success_at=None,
            last_failure_at=None,
            failure_code=None,
            cooldown_until=None,
        )
    delegated = await get_system_sender_connection(db)
    types = []
    for spec in CATALOG:
        kind = spec["id"]
        use_delegated = (
            kind in {"job_deadline", "delivery_alert"} and delegated is not None
        )
        cutoff = policy.cutoff_for(kind)
        types.append(
            dict(
                **spec,
                email_enabled=policy.types.get(kind, {}).get("email_enabled") is True,
                effective_enabled=policy.kind_enabled(kind),
                send_not_before=cutoff.isoformat() if cutoff else None,
                channels=["email"]
                if kind in REPORT_KINDS or kind == "application_confirmation"
                else [
                    "client_panel" if kind == "delivery_alert" else "in_app",
                    "email",
                ],
                sender=delegated.mailbox_upn if use_delegated else provider["sender"],
                provider_kind="graph_delegated" if use_delegated else provider["kind"],
                provider_status="unknown"
                if use_delegated
                else provider["observed_status"],
                editable=True,
            )
        )
    for spec in SECURITY_CATALOG:
        types.append(
            dict(
                **spec,
                module="Bezpieczeństwo konta",
                recipient_rule="Właściciel konta, którego dotyczy żądanie.",
                email_enabled=True,
                effective_enabled=True,
                send_not_before=None,
                channels=["email"],
                sender=provider["sender"],
                provider_kind=provider["kind"],
                provider_status=provider["observed_status"],
                editable=False,
            )
        )
    queue = await snapshot_queue(db, policy, now)
    return dict(
        enabled=policy.enabled,
        updated_at=row.updated_at.isoformat() if row else None,
        updated_by=row.updated_by if row else None,
        send_not_before=policy.send_not_before.isoformat()
        if policy.send_not_before
        else None,
        provider=provider,
        backlog={
            "pending_retry": queue["pending_retry"],
            "ready_upper_bound": queue["ready_candidates_upper_bound"],
            "uncertain": queue["uncertain"],
            "legacy_suppressed": queue["legacy_suppressed"],
            "scope": queue.get("scope", "routine_email"),
        },
        types=types,
        excluded_channels=[
            dict(
                id="manual_m365",
                label="Korespondencja z osobistej skrzynki",
                description="Ręczne maile, shortlisty i zaplanowane odpowiedzi odmowne korzystają z połączenia Microsoft 365 użytkownika oraz własnych zgód i reguł.",
            ),
            dict(
                id="order_mail_read",
                label="Odczyt poczty i zamówień",
                description="Synchronizacja Microsoft 365 i odczyt zamówień nie są wysyłką powiadomień i nie podlegają temu przełącznikowi.",
            ),
            dict(
                id="account_security",
                label="Bezpieczeństwo konta",
                description="Reset i zmiana hasła oraz weryfikacja adresu działają niezależnie od automatycznych powiadomień.",
            ),
            dict(
                id="external_monitoring",
                label="Monitoring Sentry i Grafana",
                description="Alarmy błędów i infrastruktury mają osobną konfigurację. Te przełączniki sterują automatycznymi mailami NEXUS.",
            ),
        ],
    )
