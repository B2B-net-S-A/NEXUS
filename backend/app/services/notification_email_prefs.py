"""„Maile do Ciebie” — które maile konto dostaje i które wyłączyło sobie (0427).

Do 09.10.2026 lista maili stała tylko w zakładce administratora („Maile”,
polityka całej firmy). Rekruter nie widział, co przychodzi do niego, a własny
wyłącznik miał jeden mail — poranny skrót (0425). Decyzja Artura 09.10.2026:
każdy widzi swoje maile i każdy z nich może wyłączyć sobie, także maile-zadania
(zadanie zostaje w dzwonku i w „Czeka na Ciebie”). Zawsze przychodzą tylko
maile bezpieczeństwa konta.

Trzy rzeczy w jednym miejscu:

* ``email_opted_out`` (mieszka w ``notification_delivery``, bo importuje ją
  każdy nadawca) — czysta reguła pytana tuż przed wysyłką; strażnik w
  ``test_notification_email_prefs.py`` sprawdza, że każdy moduł wysyłający
  ją woła;
* ``APPLIES`` — czy mail w ogóle może trafić do konta (lustro reguł odbiorców
  u nadawców; nowy rodzaj w katalogu bez wpisu tutaj wywraca test);
* ``my_view`` / ``set_enabled`` — odczyt i zapis dla zakładki „Moje”.

Poranny skrót zostaje przy własnej kolumnie ``daily_digest_email_enabled``;
pozostałe rodzaje żyją w ``users.email_opt_outs`` jako ``{rodzaj: czas}``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.candidate_access import (
    CANDIDATE_READ_ROLES,
    user_can_access_candidate_domain,
)
from app.models.notification import NotificationType
from app.models.user import User, UserRole
from app.services.action_permissions import ProductAction, has_permission
from app.services.notification_access import (
    role_muted_types_of,
    user_may_receive_type,
)
from app.services.notification_categories import (
    CATEGORY_INFO,
    category_for,
    user_muted_types,
)
from app.services.notification_delivery import (
    CATALOG,
    DIGEST_KIND,
    RESUMED_KEY,
    SECURITY_CATALOG,
    email_opted_out,
    load_policy,
)
from app.services.section_permissions import (
    ProductSection,
    SectionAccess,
    section_access_for_user,
)

# Mail do kandydata — nie należy do żadnego konta.
_NOT_AN_ACCOUNT_EMAIL = frozenset({"application_confirmation"})

OPTABLE_KINDS: tuple[str, ...] = tuple(
    spec["id"] for spec in CATALOG if spec["id"] not in _NOT_AN_ACCOUNT_EMAIL
)
_OPTABLE = frozenset(OPTABLE_KINDS)

# Maile, które idą za wpisem w dzwonku z kategorii dającej się wyciszyć:
# wyciszona kategoria (własna albo dla roli) zatrzymuje także mail.
BELL_TYPE_BY_KIND: dict[str, NotificationType] = {
    "chat_unread": NotificationType.job_chat_message,
    "pipeline_stage": NotificationType.stage_rule,
    "job_deadline": NotificationType.job_deadline_7d,
}


class UnknownEmailKind(ValueError):
    """Rodzaj spoza katalogu maili konta."""


class EmailKindNotApplicable(ValueError):
    """Ten mail nie trafia do konta z taką rolą — nie ma czego wyłączać."""


@dataclass(frozen=True)
class _Context:
    """To, czego reguła „dotyczy konta” nie wyczyta z samego konta."""

    cpro_sender_ids: frozenset[int] = frozenset()


def _section_read(user: User, section: ProductSection) -> bool:
    return bool(
        user.has_role(UserRole.admin)
        or section_access_for_user(user, section) >= SectionAccess.read
    )


def _digest(user: User, _: _Context) -> bool:
    from app.tasks.daily_digest_email import DIGEST_ROLES

    return user.has_any_role(*DIGEST_ROLES) and _section_read(
        user, ProductSection.pipeline
    )


def _dl_review(user: User, ctx: _Context) -> bool:
    return (
        user.has_any_role(UserRole.delivery_lead) or user.id in ctx.cpro_sender_ids
    ) and user_may_receive_type(user, NotificationType.board_task_waiting)


def _cv_returned(user: User, _: _Context) -> bool:
    return user_can_access_candidate_domain(user) and user_may_receive_type(
        user, NotificationType.board_task_waiting
    )


def _request_assigned(user: User, _: _Context) -> bool:
    return user.has_any_role(
        UserRole.recruiter, UserRole.delivery_lead, UserRole.admin
    ) and user_may_receive_type(user, NotificationType.request_assignment_changed)


def _signature_request(user: User, _: _Context) -> bool:
    return has_permission(
        user, ProductAction.b2b_signature_confirmation
    ) and user_may_receive_type(user, NotificationType.b2b_signature_requested)


def _rate_change(user: User, _: _Context) -> bool:
    return user.has_any_role(UserRole.delivery_lead) and user_may_receive_type(
        user, NotificationType.candidate_rate_change_task
    )


def _delivery_alert(user: User, _: _Context) -> bool:
    return user.has_any_role(UserRole.delivery_lead) and _section_read(
        user, ProductSection.delivery
    )


def _system_failure(user: User, _: _Context) -> bool:
    return user.has_role(UserRole.admin)


def _chat_unread(user: User, _: _Context) -> bool:
    # Lustro zapytania `chat_email_fallback`: rola z dostępem do kandydatów,
    # bez Finansów i roli podglądu wśród ról. Nadawca patrzy na rolę główną;
    # tu liczymy każdą rolę konta — wiersz pokazany na zapas nie szkodzi,
    # a ukryty odebrałby komuś wyłącznik.
    roles = user.get_all_roles()
    return (
        user.has_any_role(*CANDIDATE_READ_ROLES)
        and UserRole.finance not in roles
        and UserRole.user not in roles
        and (
            _section_read(user, ProductSection.pipeline)
            or _section_read(user, ProductSection.sourcing)
        )
    )


def _mentions(user: User, _: _Context) -> bool:
    return user_can_access_candidate_domain(user)


def _pipeline_stage(user: User, _: _Context) -> bool:
    return user_can_access_candidate_domain(user) and user_may_receive_type(
        user, NotificationType.stage_rule
    )


def _job_deadline(user: User, _: _Context) -> bool:
    return user_can_access_candidate_domain(user) and user_may_receive_type(
        user, NotificationType.job_deadline_7d
    )


def _kpi_weekly(user: User, _: _Context) -> bool:
    return user.has_any_role(UserRole.head_of_recruitment) and _section_read(
        user, ProductSection.insights
    )


def _board_monthly(user: User, _: _Context) -> bool:
    return has_permission(user, ProductAction.finance_module) and _section_read(
        user, ProductSection.insights
    )


# Czy mail w ogóle może trafić do konta. Nie mówi, że trafi dziś — o tym
# decyduje przypisanie do klienta, rekrutacji albo karty.
APPLIES: dict[str, Callable[[User, _Context], bool]] = {
    "chat_unread": _chat_unread,
    "mentions": _mentions,
    "pipeline_stage": _pipeline_stage,
    "rate_change": _rate_change,
    "job_deadline": _job_deadline,
    "delivery_alert": _delivery_alert,
    "dl_review": _dl_review,
    "cv_returned": _cv_returned,
    "request_assigned": _request_assigned,
    "signature_request": _signature_request,
    "system_failure": _system_failure,
    DIGEST_KIND: _digest,
    "kpi_weekly_report": _kpi_weekly,
    "board_monthly_report": _board_monthly,
}


async def _context(db: AsyncSession, user: User) -> _Context:
    from app.models.job import Job
    from app.services import cpro_sender

    async with db.begin_nested():
        state = await cpro_sender.effective_sender(db)
        # Bez osoby od Cpro na firmę kolejkę dostaje osoba zapasowa
        # rekrutacji (`jobs.cpro_sender_id`) — ona też musi widzieć ten mail.
        per_job = await db.scalar(
            select(Job.id).where(Job.cpro_sender_id == user.id).limit(1)
        )
    senders = {uid for uid in (state.user_id,) if isinstance(uid, int)}
    if per_job is not None:
        senders.add(user.id)
    return _Context(cpro_sender_ids=frozenset(senders))


async def _context_safely(db: AsyncSession, user: User) -> _Context:
    """Osoba od Cpro jest dodatkiem do reguły — jej odczyt nie zabiera ekranu."""
    try:
        return await _context(db, user)
    except Exception:  # noqa: BLE001 — bez tej osoby reguła liczy same role
        return _Context()


def _bell_block(user: User, kind: str) -> tuple[str, str] | None:
    """(`role_muted` | `bell_muted`, zdanie) gdy mail stoi za wyciszoną kategorią."""
    bell_type = BELL_TYPE_BY_KIND.get(kind)
    if bell_type is None:
        return None
    by_role = bell_type in role_muted_types_of(user)
    if not by_role and bell_type not in user_muted_types(user):
        return None
    label = CATEGORY_INFO[category_for(bell_type)].label
    who = (
        "wyłączona dla Twojej roli przez administratora"
        if by_role
        else "wyłączona przez Ciebie w dzwonku"
    )
    rest = (
        "mailem przyjdą tylko wzmianki z czatu"
        if kind == "chat_unread"
        else "ten mail też nie przychodzi"
    )
    return (
        "role_muted" if by_role else "bell_muted",
        f"Kategoria „{label}” jest {who}, więc {rest}.",
    )


def _item(user: User, spec: Mapping[str, Any], *, company_enabled: bool) -> dict:
    kind = spec["id"]
    self_enabled = not email_opted_out(user, kind)
    blocked = _bell_block(user, kind)
    if not company_enabled:
        state, note = (
            "company_off",
            "Wyłączone dla całej firmy przez administratora — teraz nikt go nie dostaje.",
        )
    elif not self_enabled:
        state, note = "self_off", "Wyłączone przez Ciebie."
    elif blocked is not None:
        state, note = blocked
    else:
        state, note = "on", None
    return dict(
        id=kind,
        label=spec["label"],
        description=spec["trigger"],
        company_enabled=company_enabled,
        self_enabled=self_enabled,
        receiving=state == "on",
        state=state,
        note=note,
    )


async def my_view(db: AsyncSession, user: User) -> dict[str, Any]:
    """Maile konta: co przychodzi, co jest wyłączone i przez kogo."""
    from app.services.email import email_channel_enabled

    policy = await load_policy(db)
    ctx = await _context_safely(db, user)
    items: list[dict] = []
    not_applicable: list[dict] = []
    for spec in CATALOG:
        kind = spec["id"]
        if kind not in _OPTABLE:
            continue
        if APPLIES[kind](user, ctx):
            items.append(_item(user, spec, company_enabled=policy.kind_enabled(kind)))
        else:
            not_applicable.append(dict(id=kind, label=spec["label"]))
    return dict(
        channel_ready=email_channel_enabled(),
        items=items,
        not_applicable=not_applicable,
        always_on=[
            dict(id=spec["id"], label=spec["label"], description=spec["trigger"])
            for spec in SECURITY_CATALOG
        ],
    )


async def set_enabled(db: AsyncSession, user: User, kind: str, enabled: bool) -> None:
    """Włącz albo wyłącz mail temu kontu. Commit należy do wołającego."""
    if kind not in _OPTABLE:
        raise UnknownEmailKind(kind)
    # Włączenie z powrotem jest zawsze bezpieczne; wyłączyć można tylko mail,
    # który do konta w ogóle trafia — inaczej zapis nic by nie znaczył.
    if not enabled and not APPLIES[kind](user, await _context_safely(db, user)):
        raise EmailKindNotApplicable(kind)
    if kind == DIGEST_KIND:
        user.daily_digest_email_enabled = enabled
        return
    current = dict(user.email_opt_outs or {})
    resumed = dict(current.get(RESUMED_KEY) or {})
    now = datetime.now(timezone.utc).isoformat()
    if enabled:
        # Czas włączenia zostaje: zdarzenia z okresu wyłączenia nie wychodzą
        # jako zaległości (`notification_delivery.email_wanted`).
        if current.pop(kind, None):
            resumed[kind] = now
    else:
        current.setdefault(kind, now)
        resumed.pop(kind, None)
    if resumed:
        current[RESUMED_KEY] = resumed
    else:
        current.pop(RESUMED_KEY, None)
    # Nowy słownik, nie mutacja — SQLAlchemy nie śledzi zmian wewnątrz JSONB.
    user.email_opt_outs = current


async def opt_out_summary(db: AsyncSession) -> dict[str, list[str]]:
    """Kto wyłączył sobie który mail — dla zakładki administratora „Maile”."""
    rows = (
        await db.execute(
            select(
                User.name,
                User.email,
                User.email_opt_outs,
                User.daily_digest_email_enabled,
            ).where(User.is_active.is_(True))
        )
    ).all()
    summary: dict[str, list[str]] = {}
    for name, email, opt_outs, digest_enabled in rows:
        who = name or email
        kinds = {
            kind
            for kind, since in (
                opt_outs.items() if isinstance(opt_outs, Mapping) else ()
            )
            if since and kind in _OPTABLE
        }
        if digest_enabled is False:
            kinds.add(DIGEST_KIND)
        for kind in kinds:
            summary.setdefault(kind, []).append(who)
    return {kind: sorted(names) for kind, names in summary.items()}
