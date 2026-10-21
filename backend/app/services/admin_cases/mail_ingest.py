"""Czytnik skrzynki administracja@ → sprawy (app-only Microsoft Graph).

Wzorzec: czytnik skrzynki zamówień (``app/services/order_mail_ingest.py``,
reguła ``docs/claude/zamowienia/zamowienia-z-maila-zamowienia-b2bnetwork-pl-czytnik.md``):
token aplikacji, ścieżki ``/users/{upn}/…``, znacznik ostatnio odebranego
maila z nakładką, stan przebiegu w bazie.

Reguły:

* **wyłączony**, gdy nie ma skrzynki M365 (``ADMIN_CASES_M365_MAILBOX``, pusta =
  ``ADMIN_CASES_MAILBOX``; role adresów w ``admin_cases/mailbox.py``),
  ``ADMIN_CASES_MAIL_INGEST_ENABLED`` ≠ ``true`` albo moduł „cases” jest
  wyłączony w ``app_settings['hr_modules']`` — wtedy niczego nie czyta
  i niczego nie zapisuje,
* **nowa wiadomość → nowa sprawa** (obszar z tematu, priorytet P2, termin
  z SLA od daty odebrania),
* **odpowiedź w wątku → ta sama sprawa**: najpierw ``conversationId``, potem
  ``In-Reply-To``/``References``. Compass zakładał sprawę z każdej odpowiedzi
  i tablica stała się bezużyteczna — auto-import wyłączono w Fazie 44.
  Odpowiedź do sprawy zrobionej albo zamkniętej otwiera ją ponownie
  (status „Nowa”), żeby nie przepadła,
* **idempotentnie** po ``graph_message_id`` — drugi przebieg niczego nie
  dubluje; jedna zepsuta wiadomość (osobny punkt zapisu) nie zatrzymuje reszty,
  a znacznik staje sekundę przed nią, więc następny przebieg spróbuje znowu,
* **trwale zepsuta wiadomość nie blokuje skrzynki**: liczba nieudanych prób
  per wiadomość leży w ``stats['message_attempts']`` (klucz = skrót id
  z ``mail_source_key``, nie id ani temat). Po ``MAX_MESSAGE_ATTEMPTS``
  porażkach czytnik ją pomija — znacznik idzie dalej, przebieg kończy się
  statusem ``partial`` z liczbą pominiętych, log niesie tylko skrót. Bez tego
  zepsuta wiadomość i ponad ``MAX_MESSAGES_PER_RUN`` nowszych zatrzymałyby
  odbiór nowszych na zawsze (każdy przebieg czytałby te same 200),
* **pełna paczka nie zatrzymuje odbioru**: odczyt idzie rosnąco od znacznika
  minus nakładka i kończy się na ``MAX_MESSAGES_PER_RUN``. Gdy w oknie nakładki
  leży cała paczka, znacznik nie rósłby nigdy. Po pełnej paczce następny
  przebieg czyta od najnowszej przetworzonej wiadomości BEZ nakładki
  (``stats['resume_from']``, włącznie — wiadomości z tą samą sekundą wracają
  jako duplikaty), aż paczka przestanie być pełna; potem wraca nakładka,
* załączniki tylko jako metadane (nazwa, typ, rozmiar) — bez treści plików,
* **odpowiedź na komunikat do konsultantów** (znacznik ``[Komunikat <id>/<kod>]``
  w temacie nowej sprawy) albo odbity mail — sprawa dostaje odnośnik do
  komunikatu i kontraktu nadawcy (``care/announcements.link_mail_case``),
* **mail od konsultanta** (nadawca = e-mail z kontraktu) z dokładnie jednym
  aktywnym kontraktem — nowa sprawa dostaje ``contract_id``
  (``admin_cases/contract_links.link_new_mail_case``); kilka kontraktów
  i mail z firmy klienta to tylko propozycje przy odczycie.

Klient Graph jest wstrzykiwany (``AdminMailbox``); testy podają fałszywą
skrzynkę. Prawdziwa skrzynka idzie przez rejestrację HR (``acquire_hr_token``)
— rejestracja zamówień ma politykę dostępu tylko na skrzynkę zamówień. Logi niosą wyłącznie identyfikatory i liczby — bez adresów,
tematów i treści.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional, Protocol
from urllib.parse import quote

from sqlalchemy import or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin_case import AdminCase, AdminCaseMessage, AdminMailIngestState
from app.models.hr_ops import HrJobRun
from app.services.admin_cases import rules
from app.services.admin_cases.service import (
    AutomaticCase,
    module_enabled,
    open_automatic_case,
)

logger = logging.getLogger(__name__)

MAILBOX_ENV = "ADMIN_CASES_MAILBOX"
M365_MAILBOX_ENV = "ADMIN_CASES_M365_MAILBOX"
ENABLED_ENV = "ADMIN_CASES_MAIL_INGEST_ENABLED"

JOB_KIND = "admin_cases_mail_ingest"
#: Jeden wiersz rezerwacji w ``hr_job_runs`` (dzierżawa), nie wiersz na
#: przebieg — pętla co 5 minut dałaby blisko 300 wierszy dziennie.
LEASE_KEY = "lease"
LEASE = timedelta(minutes=15)
OVERLAP = timedelta(hours=2)
INITIAL_LOOKBACK = timedelta(days=3)
MAX_MESSAGES_PER_RUN = 200
#: Tyle nieudanych prób zapisu jednej wiadomości, potem czytnik ją pomija.
MAX_MESSAGE_ATTEMPTS = 5
#: Klucz w ``admin_mail_ingest_state.stats``: skrót id wiadomości → porażki.
ATTEMPTS_KEY = "message_attempts"
#: Klucz w ``stats``: po pełnej paczce następny odczyt startuje stąd (ISO, UTC).
RESUME_KEY = "resume_from"

_MESSAGE_SELECT = (
    "id,internetMessageId,conversationId,subject,from,sender,receivedDateTime,"
    "hasAttachments,body,uniqueBody,internetMessageHeaders"
)
_MESSAGE_ID = re.compile(r"<[^<>\s]+>")


class AdminMailbox(Protocol):
    """Skrzynka administracja@ widziana przez czytnik (Graph albo fałszywka)."""

    async def list_messages(
        self, mailbox: str, since: datetime
    ) -> list[dict[str, Any]]: ...

    async def list_attachments(
        self, mailbox: str, message_id: str
    ) -> list[dict[str, Any]]: ...


class GraphAdminMailbox:
    """Prawdziwa skrzynka: ``AppGraphClient`` (retry, throttling, timeout).

    ``token_provider`` wybiera rejestrację aplikacji; ``run_once`` podaje
    rejestrację HR (``app/services/hr/m365/auth.py``). Rejestracja czytnika
    zamówień (domyślna w ``AppGraphClient``) ma politykę dostępu (Application
    Access Policy) tylko na skrzynkę zamówień — z nią Graph odpowie 403.
    """

    def __init__(self, token_provider: Optional[Callable[..., Optional[str]]] = None):
        self._token_provider = token_provider
        self._client = None

    async def __aenter__(self) -> "GraphAdminMailbox":
        from app.services.m365.app_graph_client import AppGraphClient

        self._client = AppGraphClient(token_provider=self._token_provider)
        await self._client.__aenter__()
        return self

    async def __aexit__(self, *exc_info) -> None:
        if self._client is not None:
            await self._client.__aexit__(*exc_info)

    async def list_messages(
        self, mailbox: str, since: datetime
    ) -> list[dict[str, Any]]:
        params = {
            "$filter": (
                "receivedDateTime ge "
                + since.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            ),
            "$select": _MESSAGE_SELECT,
            "$orderby": "receivedDateTime asc",
            "$top": "50",
        }
        messages: list[dict[str, Any]] = []
        async for page in self._client.paginate(
            f"/users/{mailbox}/mailFolders/Inbox/messages", params=params
        ):
            messages.extend(page.get("value", []))
            if len(messages) >= MAX_MESSAGES_PER_RUN:
                break
        return messages[:MAX_MESSAGES_PER_RUN]

    async def list_attachments(
        self, mailbox: str, message_id: str
    ) -> list[dict[str, Any]]:
        page = await self._client.get(
            f"/users/{mailbox}/messages/{quote(message_id, safe='')}/attachments",
            params={"$select": "name,contentType,size,isInline"},
        )
        return list((page or {}).get("value", []))


def mailbox_upn() -> Optional[str]:
    """Skrzynka M365 do czytania — ta sama reguła co ``mailbox.m365_mailbox``."""

    for env in (M365_MAILBOX_ENV, MAILBOX_ENV):
        value = (os.environ.get(env) or "").strip()
        if value:
            return value
    return None


def _own_addresses(upn: str) -> frozenset[str]:
    """Adresy administracji: skrzynka M365 i adres widoczny (home.pl)."""

    values = [upn] + [
        os.environ.get(env) or "" for env in (MAILBOX_ENV, M365_MAILBOX_ENV)
    ]
    return frozenset(value.strip().lower() for value in values if value.strip())


def ingest_enabled() -> bool:
    flag = (os.environ.get(ENABLED_ENV) or "").strip().lower()
    return flag == "true" and mailbox_upn() is not None


# ── Odczyt wiadomości Graph ──────────────────────────────────────────────────


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _nul_free(value: Optional[str], limit: int) -> Optional[str]:
    if not isinstance(value, str):
        return None
    cleaned = value.replace("\x00", "").strip()
    return cleaned[:limit] or None


def _sender(msg: dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
    for key in ("from", "sender"):
        address = (msg.get(key) or {}).get("emailAddress") or {}
        email = _nul_free(address.get("address"), 320)
        if email:
            return email.lower(), _nul_free(address.get("name"), 200)
    return None, None


def _header_ids(msg: dict[str, Any]) -> list[str]:
    """Identyfikatory z ``In-Reply-To`` i ``References`` (najbliższy pierwszy)."""

    in_reply: list[str] = []
    references: list[str] = []
    for header in msg.get("internetMessageHeaders") or []:
        name = str(header.get("name") or "").lower()
        value = str(header.get("value") or "")
        if name == "in-reply-to":
            in_reply.extend(_MESSAGE_ID.findall(value))
        elif name == "references":
            references.extend(_MESSAGE_ID.findall(value))
    ordered = in_reply + list(reversed(references))
    return list(dict.fromkeys(ordered))


#: Autoodpowiedzi (urlop, „poza biurem”) — nagłówki RFC 3834 i Exchange.
_AUTO_PRECEDENCE = frozenset({"auto_reply", "junk"})
_AUTO_SUBJECT_PREFIXES = (
    "automatic reply:",
    "autoreply:",
    "auto reply:",
    "auto-reply:",
    "odpowiedź automatyczna:",
    "odpowiedz automatyczna:",
    "out of office:",
    "abwesenheitsnotiz:",
)


def _is_auto_reply(msg: dict[str, Any], sender_email: Optional[str]) -> bool:
    """Autoodpowiedź, która nie jest zgłoszeniem (audyt 19.10.2026).

    Komunikat do kilkuset konsultantów albo mail powitalny dają falę
    odpowiedzi „jestem na urlopie” — każda zakładałaby nową sprawę. Zwrotki
    serwera poczty (postmaster, mailer-daemon) NIE są tu liczone: czytnik
    przypina je do komunikatu (``care.announcements.link_mail_case``).
    """

    from app.services.care.announcements import looks_like_bounce  # noqa: PLC0415

    if looks_like_bounce(sender_email):
        return False
    for header in msg.get("internetMessageHeaders") or []:
        name = str(header.get("name") or "").strip().lower()
        value = str(header.get("value") or "").strip().lower()
        if name == "auto-submitted" and value and value != "no":
            return True
        if name in {"x-autoreply", "x-autorespond", "x-autoresponder"}:
            return True
        if name == "precedence" and value in _AUTO_PRECEDENCE:
            return True
    subject = str(msg.get("subject") or "").strip().lower()
    return subject.startswith(_AUTO_SUBJECT_PREFIXES)


def _body(msg: dict[str, Any]) -> str:
    for key in ("uniqueBody", "body"):
        body = msg.get(key) or {}
        text_value = rules.body_to_text(body.get("content"), body.get("contentType"))
        if text_value:
            return text_value
    return ""


def _attachment_meta(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    meta = []
    for item in items[:50]:
        size = item.get("size")
        meta.append(
            {
                "name": _nul_free(item.get("name"), 255) or "załącznik",
                "content_type": _nul_free(item.get("contentType"), 120),
                "size": size if isinstance(size, int) and size >= 0 else None,
                "inline": item.get("isInline") is True,
            }
        )
    return meta


def mail_source_key(graph_message_id: str) -> str:
    digest = hashlib.sha256(graph_message_id.encode("utf-8")).hexdigest()[:40]
    return f"mail:{digest}"


async def _thread_case(db: AsyncSession, msg: dict[str, Any]) -> Optional[AdminCase]:
    conversation_id = _nul_free(msg.get("conversationId"), 512)
    if conversation_id:
        case_id = await db.scalar(
            select(AdminCaseMessage.case_id)
            .where(AdminCaseMessage.conversation_id == conversation_id)
            .order_by(AdminCaseMessage.id.desc())
            .limit(1)
        )
        if case_id is not None:
            return await db.get(AdminCase, case_id)
    for message_id in _header_ids(msg):
        case_id = await db.scalar(
            select(AdminCaseMessage.case_id)
            .where(AdminCaseMessage.internet_message_id == message_id)
            .order_by(AdminCaseMessage.id.desc())
            .limit(1)
        )
        if case_id is not None:
            return await db.get(AdminCase, case_id)
    return None


async def _ingest_message(
    db: AsyncSession, mailbox: AdminMailbox, upn: str, msg: dict[str, Any]
) -> str:
    graph_id = _nul_free(msg.get("id"), 512)
    if not graph_id:
        return "skipped"
    known = await db.scalar(
        select(AdminCaseMessage.id).where(AdminCaseMessage.graph_message_id == graph_id)
    )
    if known is not None:
        return "duplicate"
    sender_email, sender_name = _sender(msg)
    own = sender_email is not None and sender_email in _own_addresses(upn)
    received_at = _parse_dt(msg.get("receivedDateTime"))
    subject = _nul_free(msg.get("subject"), 500)

    case = await _thread_case(db, msg)
    outcome = "attached"
    now = datetime.now(timezone.utc)
    if own or _is_auto_reply(msg, sender_email):
        # Wiadomość wysłana przez administrację: kopia do siebie albo odpowiedź
        # z home.pl z administracja@ w kopii (wariant B). W wątku sprawy to jej
        # odpowiedź — dołącza bez ponownego otwarcia; poza wątkiem to nie
        # zgłoszenie. Autoodpowiedź tak samo: w wątku zostaje śladem, nie
        # otwiera zamkniętej sprawy i nie zakłada nowej.
        if case is None:
            return "skipped"
    elif case is None:
        case, _created = await open_automatic_case(
            db,
            AutomaticCase(
                title=rules.case_title_from_subject(subject),
                area=rules.area_from_subject(subject),
                priority="P2",
                source="mail",
                source_key=mail_source_key(graph_id),
                due_on=rules.due_date_for("P2", received_at or now),
            ),
        )
        outcome = "created"
    elif rules.is_terminal(case.status):
        case.status = "new"
        case.closed_at = None
        outcome = "reopened"
    case.updated_at = now

    attachments: list[dict[str, Any]] = []
    if msg.get("hasAttachments"):
        attachments = _attachment_meta(await mailbox.list_attachments(upn, graph_id))
    body_text = _body(msg)
    db.add(
        AdminCaseMessage(
            case_id=case.id,
            graph_message_id=graph_id,
            internet_message_id=_nul_free(msg.get("internetMessageId"), 512),
            conversation_id=_nul_free(msg.get("conversationId"), 512),
            sender_email=sender_email,
            sender_name=sender_name,
            subject=subject,
            received_at=received_at,
            body_text=body_text,
            attachments=attachments,
        )
    )
    await db.flush()
    if outcome == "created":
        # Odpowiedź na komunikat do konsultantów (znacznik w temacie) albo
        # odbity mail — sprawa dostaje odnośnik do komunikatu i kontraktu.
        from app.services.care.announcements import link_mail_case

        await link_mail_case(
            db, case, subject=subject, sender_email=sender_email, body_text=body_text
        )
        # Mail od konsultanta z dokładnie jednym aktywnym kontraktem — sprawa
        # wie, kogo dotyczy. Kilka kontraktów albo mail z firmy klienta =
        # propozycje przy odczycie (``contract_links.link_suggestions``).
        from app.services.admin_cases.contract_links import link_new_mail_case

        await link_new_mail_case(db, case, sender_email=sender_email)
    return outcome


# ── Dzierżawa przebiegu i stan ───────────────────────────────────────────────


async def _claim_lease(db: AsyncSession, now: datetime) -> bool:
    statement = (
        insert(HrJobRun)
        .values(
            kind=JOB_KIND,
            period_key=LEASE_KEY,
            status="claimed",
            counts={},
            claimed_at=now,
        )
        .on_conflict_do_update(
            constraint="uq_hr_job_runs_kind_period",
            set_={
                "status": "claimed",
                "claimed_at": now,
                "finished_at": None,
                "error": None,
            },
            where=or_(HrJobRun.status != "claimed", HrJobRun.claimed_at < now - LEASE),
        )
        .returning(HrJobRun.id)
    )
    claimed = await db.scalar(statement)
    await db.commit()
    return claimed is not None


async def _release_lease(
    db: AsyncSession, *, status: str, counts: dict[str, int], error: Optional[str]
) -> None:
    await db.execute(
        update(HrJobRun)
        .where(HrJobRun.kind == JOB_KIND, HrJobRun.period_key == LEASE_KEY)
        .values(
            status=status,
            counts=counts,
            error=error,
            finished_at=datetime.now(timezone.utc),
        )
    )


async def _state(db: AsyncSession, upn: str) -> AdminMailIngestState:
    await db.execute(
        insert(AdminMailIngestState)
        .values(id=1)
        .on_conflict_do_nothing(index_elements=[AdminMailIngestState.id])
    )
    state = await db.get(AdminMailIngestState, 1, populate_existing=True)
    if state.mailbox != upn:
        # Inna skrzynka = inny znacznik; stary dotyczyłby cudzych maili.
        state.mailbox = upn
        state.last_received_at = None
        state.stats = {
            key: value
            for key, value in (state.stats or {}).items()
            if key != RESUME_KEY
        }
    return state


def _stored_attempts(state: AdminMailIngestState) -> dict[str, int]:
    raw = (state.stats or {}).get(ATTEMPTS_KEY)
    if not isinstance(raw, dict):
        return {}
    return {
        str(key): value
        for key, value in raw.items()
        if isinstance(value, int) and value > 0
    }


def _stored_resume(state: AdminMailIngestState) -> Optional[datetime]:
    raw = (state.stats or {}).get(RESUME_KEY)
    return _parse_dt(raw) if isinstance(raw, str) else None


def _since(state: AdminMailIngestState, now: datetime) -> datetime:
    resume = _stored_resume(state)
    if resume is not None:
        # Poprzednia paczka była pełna — dalej, bez nakładki.
        return resume
    if state.last_received_at is not None:
        return state.last_received_at - OVERLAP
    return now - INITIAL_LOOKBACK


def _stats(
    counts: Counter[str], attempts: dict[str, int], resume: Optional[datetime]
) -> dict[str, Any]:
    stats: dict[str, Any] = dict(counts)
    if attempts:
        stats[ATTEMPTS_KEY] = attempts
    if resume is not None:
        stats[RESUME_KEY] = resume.astimezone(timezone.utc).isoformat()
    return stats


async def read_status(db: AsyncSession) -> dict[str, Any]:
    """Stan czytnika dla sondy zdrowia i ekranu (bez adresów i treści)."""

    state = await db.get(AdminMailIngestState, 1)
    return {
        "enabled": ingest_enabled(),
        "last_status": state.last_status if state else None,
        "last_run_finished_at": state.last_run_finished_at if state else None,
        "last_error": state.last_error if state else None,
        "stats": state.stats if state else {},
    }


# ── Przebieg ─────────────────────────────────────────────────────────────────


async def run_once(
    db: AsyncSession, graph: Optional[AdminMailbox] = None
) -> dict[str, Any]:
    """Jeden przebieg czytnika. Nie rzuca; wynik i błąd lądują w stanie."""

    upn = mailbox_upn()
    if not ingest_enabled() or upn is None:
        return {"status": "disabled"}
    if not await module_enabled(db):
        # Do przełączenia skrzynkę obsługuje Compass; nie zbieramy spraw w ciemno.
        return {"status": "disabled"}
    started = datetime.now(timezone.utc)
    if not await _claim_lease(db, started):
        return {"status": "skipped", "reason": "already_running"}

    counts: Counter[str] = Counter()
    status = "ok"
    error: Optional[str] = None
    attempts: dict[str, int] = {}
    resume: Optional[datetime] = None
    try:
        state = await _state(db, upn)
        state.last_run_started_at = started
        since = _since(state, started)
        attempts = _stored_attempts(state)
        if graph is None:
            from app.services.hr.m365.auth import acquire_hr_token

            async with GraphAdminMailbox(token_provider=acquire_hr_token) as real:
                messages = await real.list_messages(upn, since)
                attempts, resume = await _ingest_all(
                    db, real, upn, messages, state, counts, attempts
                )
        else:
            messages = await graph.list_messages(upn, since)
            attempts, resume = await _ingest_all(
                db, graph, upn, messages, state, counts, attempts
            )
        if counts["failed"]:
            status = "partial"
            error = f"{counts['failed']} wiadomości nie udało się zapisać"
            if counts["abandoned"]:
                error += (
                    f"; {counts['abandoned']} pominięto po "
                    f"{MAX_MESSAGE_ATTEMPTS} nieudanych próbach"
                )
    except Exception as exc:  # noqa: BLE001 — przebieg nie wywraca pętli
        logger.exception("[admin_cases] przebieg czytnika skrzynki padł")
        await db.rollback()
        status = "error"
        # Klasa wyjątku, nie treść: komunikaty Graph cytują adresy i tematy.
        error = f"Błąd sprawdzania skrzynki: {type(exc).__name__}"

    try:
        if status == "error":
            state = await _state(db, upn)
            attempts = _stored_attempts(state)
            resume = _stored_resume(state)
        state.last_run_finished_at = datetime.now(timezone.utc)
        state.last_status = status
        state.last_error = error
        state.stats = _stats(counts, attempts, resume)
        await _release_lease(
            db,
            status="done" if status != "error" else "failed",
            counts=dict(counts),
            error=error,
        )
        await db.commit()
    except Exception:  # noqa: BLE001 — dzierżawa i tak wygaśnie po LEASE
        logger.exception("[admin_cases] nie zapisano stanu przebiegu skrzynki")
        await db.rollback()
    logger.info("[admin_cases] skrzynka: status=%s %s", status, dict(counts))
    return {"status": status, **counts}


async def _ingest_all(
    db: AsyncSession,
    mailbox: AdminMailbox,
    upn: str,
    messages: list[dict[str, Any]],
    state: AdminMailIngestState,
    counts: Counter[str],
    attempts: dict[str, int],
) -> tuple[dict[str, int], Optional[datetime]]:
    """Zapisuje wiadomości; zwraca liczniki porażek wiadomości z tego odczytu
    i — po pełnej paczce — punkt startu następnego odczytu (bez nakładki).

    Licznik wiadomości, której odczyt już nie zwraca (znacznik poszedł dalej),
    wypada — mapa nie rośnie bez końca.
    """

    ordered = sorted(
        messages,
        key=lambda m: (
            _parse_dt(m.get("receivedDateTime"))
            or datetime.min.replace(tzinfo=timezone.utc)
        ),
    )
    batch = ordered[:MAX_MESSAGES_PER_RUN]
    newest: Optional[datetime] = state.last_received_at
    batch_newest: Optional[datetime] = None
    earliest_failed: Optional[datetime] = None
    still_failing: dict[str, int] = {}
    for msg in batch:
        received = _parse_dt(msg.get("receivedDateTime"))
        if received is not None and (batch_newest is None or received > batch_newest):
            batch_newest = received
        graph_id = _nul_free(msg.get("id"), 512)
        digest = mail_source_key(graph_id) if graph_id else None
        tried = attempts.get(digest, 0) if digest else 0
        if digest is not None and tried >= MAX_MESSAGE_ATTEMPTS:
            # Porzucona we wcześniejszym przebiegu i wciąż w oknie odczytu.
            still_failing[digest] = tried
            counts["skipped"] += 1
        else:
            try:
                async with db.begin_nested():
                    outcome = await _ingest_message(db, mailbox, upn, msg)
            except Exception:  # noqa: BLE001 — jedna wiadomość nie zatrzymuje reszty
                logger.exception("[admin_cases] wiadomość nie zapisana")
                counts["failed"] += 1
                tried += 1
                if digest is not None:
                    still_failing[digest] = tried
                if tried < MAX_MESSAGE_ATTEMPTS:
                    if received is not None and (
                        earliest_failed is None or received < earliest_failed
                    ):
                        earliest_failed = received
                    continue
                # Ostatnia próba — znacznik idzie dalej, w logu tylko skrót id.
                counts["abandoned"] += 1
                logger.warning(
                    "[admin_cases] wiadomość %s pominięta po %d nieudanych próbach",
                    digest,
                    tried,
                )
            else:
                counts[outcome] += 1
        if received is not None and (newest is None or received > newest):
            newest = received
    resume: Optional[datetime] = None
    if len(messages) >= MAX_MESSAGES_PER_RUN:
        # Pełna paczka: dalsze wiadomości mogą leżeć w oknie nakładki, którego
        # znacznik już nie przesunie — następny odczyt startuje od tej paczki.
        resume = batch_newest
    if earliest_failed is not None:
        # Następny przebieg zapyta o zepsutą wiadomość jeszcze raz.
        before_failed = earliest_failed - timedelta(seconds=1)
        newest = before_failed if newest is None else min(newest, before_failed)
        if resume is not None:
            resume = min(resume, before_failed)
    state.last_received_at = newest
    return still_failing, resume
