"""Czytnik skrzynki zgód: odpowiedź „approved” zatwierdza zgodę (etap 2, 20.10.2026).

Wzorzec: czytnik spraw administracja@ (``admin_cases/mail_ingest.py``) —
token rejestracji „NEXUS Kadry”, ``/users/{skrzynka}/mailFolders/Inbox``,
znacznik ostatnio odebranego maila z nakładką.

Reguły (``docs/claude/ludzie/zgody-wydatki-i-premie-poza-umowa.md``):

* **wyłączony**, gdy ``HR_APPROVALS_MAIL_REPLY_ENABLED`` ≠ ``true``, nie ma
  skrzynki ``HR_APPROVALS_REPLY_MAILBOX`` albo moduł „approvals” jest
  wyłączony — wtedy niczego nie czyta i niczego nie zapisuje,
* **zgoda ze znacznika** ``[Zgoda <id>/<kod>]`` w temacie (albo w cytacie):
  kod musi pasować do obecnej wersji zgody (``mail_reply.code_matches``),
* **decyduje tylko konto, które może teraz zdecydować** (``can_decide``):
  nadawca (``from``) = e-mail aktywnego konta, ``sender`` taki sam (bez
  wysyłania w czyimś imieniu), a Exchange potwierdził nadawcę
  (``authenticated``: ``AuthAs: Internal`` albo ``dmarc=pass``, bez ``fail``),
* zgoda zablokowana (``FOR UPDATE``) przed sprawdzeniem kodu i decyzją,
* odpowiedź od decydującego, której nie zapisaliśmy (nieuwierzytelniona,
  na starą wersję, odmowa serwisu, zgoda już u autora) = dzwonek i krótki
  mail do niego (``_notice``),
* samo słowo („approved”, „ok”, „zgoda”, „tak”…) = ``decide(approve)``, inna
  treść = ``decide(return)`` z treścią jako pytaniem do autora (decyzja Artura
  20.10.2026), pusta odpowiedź i autoodpowiedź = nic. Kanał ``mail_reply``,
* **idempotentnie**: przetworzone wiadomości (skrót id) leżą w stanie razem
  z decyzjami — jedna transakcja, więc ten sam mail drugi raz nic nie robi.
  Zgoda już rozpatrzona też nic nie dostaje (``can_decide`` = fałsz).

Stan i blokada przebiegu: wiersz ``app_settings['hr_approval_mail_reader']``
(``FOR UPDATE SKIP LOCKED`` — drugi worker pomija przebieg). Logi niosą tylko
liczby i skróty — bez adresów, tematów i treści.
"""

from __future__ import annotations

import hashlib
import logging
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Protocol

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_setting import AppSetting
from app.models.hr_approval import ApprovalRequest
from app.models.notification import NotificationType
from app.models.user import User
from app.services.hr.approvals import mail_reply, service
from app.services.hr.notify import notify_each
from app.services.hr.payroll_errors import PayrollError

logger = logging.getLogger(__name__)

STATE_KEY = "hr_approval_mail_reader"
OVERLAP = timedelta(hours=2)
INITIAL_LOOKBACK = timedelta(days=1)
MAX_MESSAGES_PER_RUN = 200
#: Tyle nieudanych prób jednej wiadomości, potem czytnik ją pomija.
MAX_MESSAGE_ATTEMPTS = 3
#: Skróty przetworzonych wiadomości trzymamy tyle dłużej niż nakładkę.
SEEN_RETENTION = timedelta(days=2)

_AUTO_SUBJECT_PREFIXES = (
    "automatic reply:",
    "autoreply:",
    "auto reply:",
    "auto-reply:",
    "odpowiedź automatyczna:",
    "odpowiedz automatyczna:",
    "out of office:",
)


class ReplyMailbox(Protocol):
    """Skrzynka zgód widziana przez czytnik (Graph albo fałszywka w testach)."""

    async def list_messages(
        self, mailbox: str, since: datetime
    ) -> list[dict[str, Any]]: ...


def reader_enabled() -> bool:
    return mail_reply.reply_mailbox() is not None


async def _module_enabled(db: AsyncSession) -> bool:
    from app.services.hr import modules as hr_modules

    return (await hr_modules.load_modules(db)).get(hr_modules.HrModule.approvals, False)


# ── Odczyt wiadomości ────────────────────────────────────────────────────────


def _parse_dt(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def message_key(graph_id: str) -> str:
    return hashlib.sha256(graph_id.encode("utf-8")).hexdigest()[:32]


def _address(msg: dict[str, Any], key: str) -> Optional[str]:
    value = ((msg.get(key) or {}).get("emailAddress") or {}).get("address")
    if not isinstance(value, str):
        return None
    return value.replace("\x00", "").strip().lower() or None


def _headers(msg: dict[str, Any]) -> list[tuple[str, str]]:
    return [
        (str(item.get("name") or "").strip().lower(), str(item.get("value") or ""))
        for item in msg.get("internetMessageHeaders") or []
    ]


def is_auto_reply(msg: dict[str, Any]) -> bool:
    for name, value in _headers(msg):
        value = value.strip().lower()
        if name == "auto-submitted" and value and value != "no":
            return True
        if name in {"x-autoreply", "x-autorespond", "x-autoresponder"}:
            return True
        if name == "precedence" and value in {"auto_reply", "junk", "bulk"}:
            return True
    subject = str(msg.get("subject") or "").strip().lower()
    return subject.startswith(_AUTO_SUBJECT_PREFIXES)


def sender_address(msg: dict[str, Any]) -> Optional[str]:
    """Adres ``from``, gdy nikt nie pisze w czyimś imieniu (``sender`` = ``from``)."""

    sender_from = _address(msg, "from")
    if sender_from is None:
        return None
    sender = _address(msg, "sender")
    if sender is not None and sender != sender_from:
        return None
    return sender_from


def authenticated(msg: dict[str, Any]) -> bool:
    """Exchange potwierdził nadawcę — bez tego nie decydujemy (fail-closed).

    Wymagane: ``X-MS-Exchange-Organization-AuthAs: Internal`` (poczta z wnętrza
    organizacji) albo ``dmarc=pass`` w ``Authentication-Results``; żadne
    ``fail``/``softfail`` i żadne ``AuthAs`` inne niż ``Internal``. Na MX
    domeny nie polegamy: na adres domeny w M365 da się wysłać wprost
    (``*.mail.protection.outlook.com``).
    """

    internal = False
    dmarc_pass = False
    for name, value in _headers(msg):
        lowered = value.lower()
        if name == "authentication-results":
            if any(
                f"{check}={verdict}" in lowered
                for check in ("spf", "dkim", "dmarc", "compauth")
                for verdict in ("fail", "softfail")
            ):
                return False
            dmarc_pass = dmarc_pass or "dmarc=pass" in lowered
        if name == "x-ms-exchange-organization-authas":
            if lowered.strip() != "internal":
                return False
            internal = True
    return internal or dmarc_pass


def _body(msg: dict[str, Any]) -> tuple[str, str]:
    body = msg.get("body") or {}
    return str(body.get("content") or ""), str(body.get("contentType") or "")


# ── Jedna wiadomość ──────────────────────────────────────────────────────────

_NOTICES = {
    "unauthenticated": (
        "Nie dało się potwierdzić, że odpowiedź przyszła z Twojej skrzynki, "
        "więc nic nie zapisaliśmy. Zdecyduj w Nexusie."
    ),
    "stale": (
        "Autor poprawił zgodę po mailu, na który odpowiadasz — sprawdź nową "
        "wersję i zdecyduj w Nexusie."
    ),
}
_STATUS_NOTICES = {
    "returned": "Zgoda czeka na poprawkę autora — po poprawce przyjdzie nowy mail.",
    "rejected": "Ta zgoda jest już odrzucona — odpowiedź jej nie zmieniła.",
    "withdrawn": "Autor wycofał tę zgodę — odpowiedź niczego nie zmieniła.",
}


async def _decider(db: AsyncSession, address: str) -> Optional[User]:
    return await db.scalar(
        select(User).where(func.lower(User.email) == address, User.is_active.is_(True))
    )


async def _locked_request(
    db: AsyncSession, request_id: int
) -> Optional[ApprovalRequest]:
    # Blokada wiersza przed sprawdzeniem kodu: poprawka autora (nowe
    # ``submitted_at``) nie wejdzie między sprawdzenie a decyzję.
    return await db.scalar(
        select(ApprovalRequest)
        .where(ApprovalRequest.id == request_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


async def _notice(
    db: AsyncSession, actor: User, request: ApprovalRequest, message: str
) -> None:
    """Dzwonek i krótki mail do decydującego: odpowiedź nie została zapisana.

    Bez ``related_entity_id``: dzienny dedup ``emit`` (``ix_notif_dedup_daily``
    = osoba, typ, id encji, dzień — bez rodzaju encji) połknąłby go razem
    z dzwonkiem „zgoda do decyzji” tej zgody. Powtórek pilnuje zbiór
    przetworzonych wiadomości. Bez treści odpowiedzi i bez kwot.
    """

    await notify_each(
        db,
        [actor.id],
        title=f"Odpowiedź mailem nie zapisana: {request.title}",
        message=message,
        ntype=NotificationType.hr_approval_requested,
        link=service.request_link(request.id),
        related_entity_type=mail_reply.NOTICE_ENTITY,
        related_entity_id=None,
        log_tag="approvals",
    )


async def handle_message(db: AsyncSession, msg: dict[str, Any]) -> str:
    """Wynik jednej wiadomości (licznik przebiegu). Zapisy robi ``service.decide``."""

    if is_auto_reply(msg):
        return "auto_reply"
    content, content_type = _body(msg)
    found = mail_reply.find_marker(str(msg.get("subject") or ""), content)
    if found is None:
        return "no_marker"
    request_id, code = found
    address = sender_address(msg)
    actor = await _decider(db, address) if address else None
    if actor is None:
        return "foreign_sender"
    request = await _locked_request(db, request_id)
    if request is None:
        return "stale"
    finals = await service.finals_for_request(db, request)
    deciding = service.can_decide(actor.id, request, finals)
    if not authenticated(msg):
        # Mail idzie na prawdziwą skrzynkę konta — przy podróbce właściciel
        # dowie się o próbie, przy prawdziwej odpowiedzi — że trzeba w Nexusie.
        if deciding:
            await _notice(db, actor, request, _NOTICES["unauthenticated"])
        return "unauthenticated"
    if not mail_reply.code_matches(request.id, request.submitted_at, code):
        # Odpowiedź na wersję sprzed poprawki autora.
        if deciding:
            await _notice(db, actor, request, _NOTICES["stale"])
        return "stale"
    if not deciding:
        if request.status in ("pending_supervisor", "pending_final"):
            return "not_decider"
        involved = actor.id == request.supervisor_user_id or actor.id in finals
        if involved and request.status in _STATUS_NOTICES:
            await _notice(db, actor, request, _STATUS_NOTICES[request.status])
        return "already_decided"
    reply = mail_reply.classify(
        mail_reply.new_text(content, content_type), signer_name=actor.name
    )
    if reply.kind == "empty":
        return "empty"
    action = "approve" if reply.kind == "approve" else "return"
    try:
        async with db.begin_nested():
            decided = await service.decide(
                db,
                actor,
                request.id,
                action=action,
                note=None if action == "approve" else reply.text,
                channel="mail_reply",
            )
    except (service.ApprovalError, PayrollError) as exc:
        # Np. zamknięty miesiąc wypłaty premii albo decyzja tej samej chwili
        # w aplikacji — zgoda zostaje w skrzynce decydującego.
        logger.info(
            "[approvals] odpowiedź mailem nie przeszła: zgoda=%d %s",
            request.id,
            type(exc).__name__,
        )
        reason = getattr(exc, "message", "") or "Nexus nie zapisał decyzji."
        await _notice(db, actor, request, f"{reason} Zdecyduj w Nexusie.")
        return "refused"
    if action == "return":
        return "returned"
    return "approved" if decided.status == "approved" else "endorsed"


# ── Stan i przebieg ──────────────────────────────────────────────────────────


async def _locked_state(db: AsyncSession) -> Optional[AppSetting]:
    await db.execute(
        insert(AppSetting)
        .values(key=STATE_KEY, value={})
        .on_conflict_do_nothing(index_elements=[AppSetting.key])
    )
    return await db.scalar(
        select(AppSetting)
        .where(AppSetting.key == STATE_KEY)
        .with_for_update(skip_locked=True)
        .execution_options(populate_existing=True)
    )


def _since(state: dict[str, Any], upn: str, now: datetime) -> datetime:
    last = _parse_dt(state.get("last_received_at"))
    if state.get("mailbox") != upn or last is None:
        return now - INITIAL_LOOKBACK
    return last if state.get("resume") else last - OVERLAP


async def run_once(
    db: AsyncSession, mailbox: Optional[ReplyMailbox] = None
) -> dict[str, Any]:
    """Jeden przebieg czytnika. Nie rzuca; wynik i błąd lądują w stanie."""

    upn = mail_reply.reply_mailbox()
    if upn is None or not await _module_enabled(db):
        return {"status": "disabled"}
    upn = upn.lower()
    row = await _locked_state(db)
    if row is None:
        await db.rollback()
        return {"status": "skipped", "reason": "already_running"}
    state = dict(row.value or {})
    now = datetime.now(timezone.utc)
    since = _since(state, upn, now)
    try:
        if mailbox is None:
            from app.services.admin_cases.mail_ingest import GraphAdminMailbox
            from app.services.hr.m365.auth import acquire_hr_token

            async with GraphAdminMailbox(token_provider=acquire_hr_token) as real:
                messages = await real.list_messages(upn, since)
        else:
            messages = await mailbox.list_messages(upn, since)
    except Exception as exc:  # noqa: BLE001 — przebieg nie wywraca pętli
        logger.warning("[approvals] skrzynka zgód: odczyt padł %s", type(exc).__name__)
        state.update(
            mailbox=upn,
            last_status="error",
            last_run_at=now.isoformat(),
            # Klasa wyjątku, nie treść: komunikaty Graph cytują adresy.
            last_error=f"Błąd odczytu skrzynki: {type(exc).__name__}",
        )
        row.value = state
        await db.commit()
        return {"status": "error"}

    seen: dict[str, str] = (
        dict(state.get("seen") or {}) if state.get("mailbox") == upn else {}
    )
    failures: dict[str, int] = dict(state.get("failures") or {})
    counts: Counter[str] = Counter()
    newest = (
        _parse_dt(state.get("last_received_at"))
        if state.get("mailbox") == upn
        else None
    )
    earliest_failed: Optional[datetime] = None
    ordered = sorted(
        messages,
        key=lambda m: (
            _parse_dt(m.get("receivedDateTime"))
            or datetime.min.replace(tzinfo=timezone.utc)
        ),
    )[:MAX_MESSAGES_PER_RUN]
    for msg in ordered:
        graph_id = msg.get("id")
        if not isinstance(graph_id, str) or not graph_id:
            counts["skipped"] += 1
            continue
        digest = message_key(graph_id)
        received = _parse_dt(msg.get("receivedDateTime")) or now
        if digest in seen:
            counts["duplicate"] += 1
        else:
            try:
                async with db.begin_nested():
                    outcome = await handle_message(db, msg)
            except Exception:  # noqa: BLE001 — jedna wiadomość nie zatrzymuje reszty
                logger.exception("[approvals] wiadomość %s nie przetworzona", digest)
                counts["failed"] += 1
                failures[digest] = failures.get(digest, 0) + 1
                if failures[digest] < MAX_MESSAGE_ATTEMPTS:
                    if earliest_failed is None or received < earliest_failed:
                        earliest_failed = received
                    continue
                outcome = "abandoned"
            counts[outcome] += 1
            seen[digest] = received.isoformat()
            failures.pop(digest, None)
        if newest is None or received > newest:
            newest = received
    if earliest_failed is not None:
        # Następny przebieg zapyta o nieudaną wiadomość jeszcze raz.
        before_failed = earliest_failed - timedelta(seconds=1)
        newest = before_failed if newest is None else min(newest, before_failed)
    horizon = (newest or now) - OVERLAP - SEEN_RETENTION
    state.update(
        mailbox=upn,
        last_received_at=newest.isoformat() if newest else None,
        # Pełna paczka: dalsze wiadomości mogą leżeć w nakładce — następny
        # odczyt startuje od najnowszej, bez nakładki.
        resume=len(messages) >= MAX_MESSAGES_PER_RUN and earliest_failed is None,
        seen={
            key: when
            for key, when in seen.items()
            if (_parse_dt(when) or now) >= horizon
        },
        failures={key: n for key, n in failures.items() if key not in seen},
        last_status="partial" if counts["failed"] else "ok",
        last_run_at=now.isoformat(),
        last_error=(
            f"{counts['failed']} wiadomości nie udało się przetworzyć"
            if counts["failed"]
            else None
        ),
        counts=dict(counts),
    )
    row.value = state
    await db.commit()
    if counts:
        logger.info("[approvals] skrzynka zgód: %s", dict(counts))
    return {"status": state["last_status"], **counts}


async def read_status(db: AsyncSession) -> dict[str, Any]:
    """Stan czytnika (bez adresów i treści) — do sondy i ręcznego sprawdzenia."""

    state = (
        await db.scalar(select(AppSetting.value).where(AppSetting.key == STATE_KEY))
    ) or {}
    return {
        "enabled": reader_enabled(),
        "last_status": state.get("last_status"),
        "last_run_at": state.get("last_run_at"),
        "last_error": state.get("last_error"),
        "counts": state.get("counts") or {},
    }


__all__ = [
    "handle_message",
    "is_auto_reply",
    "message_key",
    "read_status",
    "reader_enabled",
    "run_once",
    "sender_address",
    "authenticated",
]
