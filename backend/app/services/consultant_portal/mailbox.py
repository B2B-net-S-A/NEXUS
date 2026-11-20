"""Czytnik skrzynki ``rozliczenia@``: drugi kanał dokumentów konsultanta.

Wzór: ``order_mail_ingest`` (wspólnej warstwy skrzynek nie ma). Czytamy przez rejestrację
„NEXUS Kadry”, tylko do odczytu: nic w skrzynce nie zmieniamy. Skrzynka i dostęp nie są
jeszcze skonfigurowane, dlatego brak ``CONSULTANT_PORTAL_SETTLEMENTS_MAILBOX`` albo tokenu
daje czytelny stan w ``cp_mailbox_state``, a nie wyjątek.

* Wyłączony portal = czytnik nie rusza. W pilotażu bierze wyłącznie nadawców z pilotażu:
  reszta firmy nadal rozlicza się po staremu i jej maili nie dotykamy. W ``internal``
  („Tylko zespół”) i ``all`` bierze każdego nadawcę z kontraktem, także bez aktywacji
  panelu (``identity.resolve_sender``): odczyt maila nie otwiera nikomu panelu.
* Nadawcę dopasowujemy po adresie z kontraktu (w ``internal``/``all`` potem z kartoteki). Adres można podrobić, dlatego dokument
  z maila zawsze czeka na decyzję Finansów, a nieznany nadawca (tylko w stanie ``all``)
  daje kartę do ręcznego przypisania.
* Znacznik idzie z zakładką 2 h, a duplikaty zamyka unikat na (wiadomość, plik).
  Do logu trafia klasa błędu, nigdy adres ani temat.
* Jedna skrzynka wsparcie@ (E8): na skrzynce wspólnej ze sprawami bierzemy tylko maile
  z załącznikiem na adresy rozliczeń (``support_mail_route``), resztę czytnik spraw. Zła
  konfiguracja (``support_mail_route.misconfiguration``) = stan ``error`` i nic nie czytamy.
"""

from __future__ import annotations

import base64
import logging
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional, Protocol
from urllib.parse import quote

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.scheduling import business_today
from app.models.client_settlement import ClientSettlement
from app.models.consultant_portal import CpMailboxState
from app.models.contract import Contract
from app.models.user import User
from app.services import support_mail_route
from app.services.admin_cases.mailbox import m365_mailbox as cases_mailbox
from app.services.client_settlements import kesu
from app.services.consultant_portal import (
    documents,
    forwarded,
    identity,
    portal_settings,
)
from app.services.consultant_portal.auth import PortalError
from app.services.m365.app_graph_client import AppGraphClient, AppOnlyTokenUnavailable
from app.services.m365.graph_client import GraphRequestError

logger = logging.getLogger(__name__)

OVERLAP = timedelta(hours=2)
INITIAL_LOOKBACK = timedelta(days=3)
MAX_MESSAGES_PER_RUN = 200
_MESSAGE_SELECT = (
    "id,subject,from,receivedDateTime,hasAttachments,"
    + support_mail_route.RECIPIENT_FIELDS
)
_FILE_ATTACHMENT = "#microsoft.graph.fileAttachment"
# Dowód pracy: RCP (BNP), Time Sheet (Bosch, PKO), arkusz (Velo), protokół (PKO), KEŚU (Alior).
# Bez tego plik „RCP_10_2026.pdf” szedł jako faktura i omijał kontrole RCP (16.11.2026).
# KCP: karta pracy Banku Pocztowego („KCP 10/2026”, plik z nazwiskiem).
_REPORT = re.compile(
    r"raport|time[\s_-]*sheet|ewidencj|godzin|ke[sś]u|rozliczenie\s+kontraktora"
    r"|rcp|arkusz|protok[oó][lł]|(?<![a-z])kcp(?![a-z])"
    # Próba IX–XI 2026: RCP BNP jako „Nazwisko_TS_09.2026.pdf”, „KP-…-sig.pdf”,
    # „Karta pracy …”, „Dokument rozliczający czas świadczonych usług” szły jako
    # faktury, więc 40 osobo-miesięcy BNP nie miało rozliczenia.
    r"|(?<![a-z])(?:ts|kp)(?![a-z])|karta\s+pracy|dokument\s+rozliczaj"
    r"|monthly\s+confirmation",
    re.IGNORECASE,
)
# Arkusz albo zrzut ekranu bez słów-kluczy to dowód pracy: w próbie na archiwum
# IX–XI 2026 78 arkuszy z godzinami („BIK wrzesien.xlsx”) szło jako faktury.
_PROOF_EXTENSIONS = re.compile(
    r"\.(xlsx|xlsm|xls|ods|csv|png|jpe?g|heic|gif|bmp|webp)$", re.IGNORECASE
)
_INVOICE = re.compile(
    r"faktur|invoice|(?:^|[^a-z])fv(?:at)?(?:[^a-z]|$)", re.IGNORECASE
)
_PERIOD_NUMERIC = re.compile(r"(?<!\d)(0?[1-9]|1[0-2])[./_-](20\d{2})(?!\d)")
_PERIOD_ISO = re.compile(r"(?<!\d)(20\d{2})[./_-](0?[1-9]|1[0-2])(?!\d)")
_MONTH_STEMS = (
    "stycz",
    "lut",
    "mar",
    "kwie",
    "maj",
    "czerw",
    "lip",
    "sierp",
    "wrze",
    "pa[zź]dziern",
    "listopad",
    "grud",
)
_PERIOD_WORD = re.compile(
    r"(" + "|".join(_MONTH_STEMS) + r")\w*\s+(20\d{2})", re.IGNORECASE
)
# Formy z próby IX–XI 2026: „202609_TS”, „Pazdziernik_2026”, „sierpien26”, „TS 09.26”,
# „F/001/26/09”, „TS_wrzesień” i „timesheet August” (bez roku: rok z daty maila).
_PERIOD_COMPACT = re.compile(r"(?<!\d)(20\d{2})(0[1-9]|1[0-2])(?!\d)")
_PERIOD_SHORT = re.compile(r"(?<![\d./])(0?[1-9]|1[0-2])[._-](\d{2})(?!\d|[./]\d)")
_PERIOD_SLASHED = re.compile(r"/(\d{2})/(0[1-9]|1[0-2])(?!\d)")
# Całe słowa, nie rdzenie: „Mariusz” to nie marzec, „Majewski” to nie maj.
_MONTH_WORDS = {
    word: month
    for month, words in enumerate(
        (
            "styczen stycznia styczniu january",
            "luty lutego lutym february",
            "marzec marca marcu march",
            "kwiecien kwietnia kwietniu april",
            "maja maju",
            "czerwiec czerwca czerwcu june",
            "lipiec lipca lipcu july",
            "sierpien sierpnia sierpniu august",
            "wrzesien wrzesnia wrzesniu september",
            "pazdziernik pazdziernika pazdzierniku october",
            "listopad listopada listopadzie november",
            "grudzien grudnia grudniu december",
        ),
        start=1,
    )
    for word in words.split()
}


class SettlementsMailbox(Protocol):
    async def list_messages(self, since: datetime) -> list[dict[str, Any]]: ...

    async def attachments(self, message_id: str) -> list[dict[str, Any]]: ...

    async def mime(self, message_id: str) -> Optional[bytes]: ...


def mailbox_upn() -> Optional[str]:
    return (settings.CONSULTANT_PORTAL_SETTLEMENTS_MAILBOX or "").strip() or None


class GraphSettlementsMailbox:
    """Skrzynka przez Graph app-only. Ścieżki zawsze ``/users/{upn}/…``."""

    def __init__(self, upn: str) -> None:
        self._prefix = f"/users/{quote(upn, safe='@.')}"

    def _client(self) -> AppGraphClient:
        from app.services.hr.m365.auth import acquire_hr_token

        return AppGraphClient(token_provider=acquire_hr_token)

    async def list_messages(self, since: datetime) -> list[dict[str, Any]]:
        moment = since.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        params = {
            "$filter": f"receivedDateTime ge {moment}",
            "$select": _MESSAGE_SELECT,
            "$orderby": "receivedDateTime asc",
            "$top": "50",
        }
        out: list[dict[str, Any]] = []
        async with self._client() as client:
            async for page in client.paginate(
                f"{self._prefix}/mailFolders/Inbox/messages", params=params
            ):
                out.extend(page.get("value", []))
                if len(out) >= MAX_MESSAGES_PER_RUN:
                    return out[:MAX_MESSAGES_PER_RUN]
        return out

    async def attachments(self, message_id: str) -> list[dict[str, Any]]:
        async with self._client() as client:
            page = await client.get(
                f"{self._prefix}/messages/{quote(message_id, safe='')}/attachments"
            )
        return list((page or {}).get("value") or [])

    async def mime(self, message_id: str) -> Optional[bytes]:
        """Cały mail (MIME), np. z Jiry: treść niesie opiekuna i czas akceptacji."""

        async with self._client() as client:
            return await client.download(
                f"{self._prefix}/messages/{quote(message_id, safe='')}/$value"
            )


def classify_kind(subject: str, file_name: str) -> str:
    """Raport albo faktura z nazwy pliku, potem z tematu; bez słów-kluczy arkusz
    i obraz to raport, reszta faktura."""

    for text in (file_name, subject):
        if _INVOICE.search(text):
            return "invoice"
        if _REPORT.search(text):
            return "report"
    return "report" if _PROOF_EXTENSIONS.search(file_name.strip()) else "invoice"


def _named_kind(subject: str, file_name: str) -> bool:
    """Rodzaj wynika z nazwy pliku albo tematu, a nie z domyślnej „faktury”."""

    if _PROOF_EXTENSIONS.search(file_name.strip()):
        return True
    return any(
        pattern.search(text)
        for pattern in (_INVOICE, _REPORT)
        for text in (file_name, subject)
    )


def _month_of(word: str) -> Optional[int]:
    lowered = word.lower()
    for index, pattern in enumerate(_MONTH_STEMS, start=1):
        if re.fullmatch(pattern, lowered):
            return index
    return None


def _folded_tokens(text: str) -> list[str]:
    raw = unicodedata.normalize("NFKD", text.replace("ł", "l").replace("Ł", "L"))
    folded = raw.encode("ascii", "ignore").decode().lower()
    return re.findall(r"[a-z]+|\d+", folded)


def find_period(
    text: str, received: Optional[date] = None
) -> Optional[tuple[int, int]]:
    """(rok, miesiąc) z tekstu: „10/2026”, „2026-10”, „październik 2026”.

    Z ``received`` także formy bez pełnego roku („09.26”, „TS_wrzesień”): rok
    dwucyfrowy musi być bieżący albo zeszły, a okres nie późniejszy niż miesiąc
    maila, bo „10.25” w treści to częściej data niż okres.
    """

    match = _PERIOD_ISO.search(text)
    if match:
        return int(match.group(1)), int(match.group(2))
    match = _PERIOD_NUMERIC.search(text)
    if match:
        return int(match.group(2)), int(match.group(1))
    match = _PERIOD_WORD.search(text)
    if match:
        month = _month_of(match.group(1))
        if month:
            return int(match.group(2)), month
    match = _PERIOD_COMPACT.search(text)
    if match:
        return int(match.group(1)), int(match.group(2))
    if received is None:
        return None
    return _loose_period(text, received)


def _loose_period(text: str, received: date) -> Optional[tuple[int, int]]:
    def plausible(year: int, month: int) -> Optional[tuple[int, int]]:
        months_back = (received.year - year) * 12 + received.month - month
        return (year, month) if 0 <= months_back <= 12 else None

    century = received.year - received.year % 100
    for match in _PERIOD_SHORT.finditer(text):
        found = plausible(century + int(match.group(2)), int(match.group(1)))
        if found:
            return found
    for match in _PERIOD_SLASHED.finditer(text):
        found = plausible(century + int(match.group(1)), int(match.group(2)))
        if found:
            return found
    tokens = _folded_tokens(text)
    for index, token in enumerate(tokens):
        month = _MONTH_WORDS.get(token)
        if month is None:
            continue
        after = tokens[index + 1] if index + 1 < len(tokens) else ""
        if after.isdigit() and len(after) in (2, 4):
            year = int(after) if len(after) == 4 else century + int(after)
        else:
            year = received.year if month <= received.month else received.year - 1
        found = plausible(year, month)
        if found:
            return found
    return None


def period_for(subject: str, file_name: str, received: date) -> tuple[int, int, bool]:
    """Okres pliku; bez znaku w treści: z daty maila, z flagą „zgadnięty”."""

    found = (
        find_period(file_name)
        or find_period(subject)
        or find_period(file_name, received)
        or find_period(subject, received)
    )
    if found:
        return found[0], found[1], False
    # Raport z końca miesiąca jest za ten miesiąc (próba IX–XI 2026: karty pracy
    # z 30.09 szły na sierpień), z początku miesiąca za poprzedni.
    total = received.year * 12 + received.month - (1 if received.day >= 25 else 2)
    return total // 12, total % 12 + 1, True


def _parse_time(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _sender(message: dict[str, Any]) -> str:
    address = ((message.get("from") or {}).get("emailAddress") or {}).get("address")
    return identity.normalize_email(address)


async def _state(db: AsyncSession) -> Optional[CpMailboxState]:
    return await db.get(CpMailboxState, 1)


async def _write_state(
    db: AsyncSession,
    *,
    now: datetime,
    status: str,
    error: Optional[str] = None,
    seen: Optional[datetime] = None,
) -> None:
    values: dict[str, Any] = {
        "last_run_at": now,
        "last_status": status,
        "last_error": error,
    }
    if seen is not None:
        values["last_seen_received_at"] = seen
    await db.execute(
        insert(CpMailboxState)
        .values(id=1, **values)
        .on_conflict_do_update(index_elements=[CpMailboxState.id], set_=values)
    )
    await db.commit()


async def _ingest_message(
    db: AsyncSession,
    mailbox: SettlementsMailbox,
    message: dict[str, Any],
    *,
    state: portal_settings.PortalSettings,
    today: date,
    now: datetime,
) -> tuple[int, int]:
    """(nowe, pominięte). Reguła pilotażu przed odczytem załączników."""

    sender = _sender(message)
    subject = str(message.get("subject") or "")
    reply = await _store_client_reply(db, mailbox, message, subject=subject, now=now)
    if reply is not None:
        return reply, 0
    if not message.get("hasAttachments"):
        return 0, 0
    by_subject = await _kesu_contract(db, subject, sender, state=state, today=today)
    contract = by_subject or await identity.resolve_sender(
        db, sender, settings=state, today=today
    )
    if contract is None and not state.any_sender:
        return 0, 1
    files = list(await mailbox.attachments(str(message["id"])))
    inner = None
    if contract is None or any(
        f.get("@odata.type") == forwarded.ITEM_ATTACHMENT for f in files
    ):
        inner = await _forwarded(mailbox, message)
        files.extend(inner.files if inner else ())
    # Osoba nie z nadawcy (pierwotny nadawca przekazanego maila, nazwisko w temacie
    # albo nazwie pliku) dostaje tylko pliki, które z nazwy są raportem albo fakturą.
    indirect = None
    if contract is None and inner is not None:
        indirect = await _forwarded_contract(
            db, inner.senders, state=state, today=today
        )
    if contract is None and indirect is None and identity.is_company_address(sender):
        # Nazwisko z tematu tylko od adresu firmy (koordynator, skrzynka firmowa):
        # temat może napisać każdy, więc obcy adres nie wskazuje nim osoby.
        names = " ".join([subject, *(str(f.get("name") or "") for f in files)])
        indirect = await identity.resolve_named_in_text(db, names, today=today)
    indirect_created = 0
    contract_id = contract.id if contract else None
    received = _parse_time(message.get("receivedDateTime")) or now
    created = skipped = 0
    if kesu.parse_jira(subject, "") is not None:
        made = await _store_jira_mail(
            db,
            mailbox,
            message,
            contract_id=contract_id,
            subject=subject,
            received=received,
            now=now,
            sender=sender,
        )
        created += made
    for attachment in files:
        if attachment.get("@odata.type") != _FILE_ATTACHMENT or attachment.get(
            "isInline"
        ):
            continue
        raw = attachment.get("contentBytes")
        if not isinstance(raw, str):
            continue
        name = str(attachment.get("name") or "")
        if kesu.is_kesu_subject(subject) and kesu.is_transport_statement(name):
            # Oświadczenie o własnym transporcie ma PESEL i dowód: nie w NEXUS-ie
            # (odpowiedź rozliczeń z 12.11.2026), rozliczenia dosyłają je osobno.
            skipped += 1
            continue
        try:
            content = base64.b64decode(raw, validate=True)
        except ValueError:
            skipped += 1
            continue
        year, month, guessed = period_for(subject, name, received.date())
        owner = contract_id
        if owner is None and indirect is not None and _named_kind(subject, name):
            # Wypowiedzenie, zaświadczenie czy oferta przekazane z łańcuchem konsultanta
            # nie mogą wejść do rozliczenia jako faktura kontraktora (próba IX–XI 2026).
            owner = indirect.id
        try:
            stored = await documents.store(
                db,
                contract_id=owner,
                kind=classify_kind(subject, name),
                year=year,
                month=month,
                content=content,
                file_name=name or None,
                channel="mailbox",
                now=now,
                period_guessed=guessed,
                graph_message_id=str(message["id"])[:512],
                sender_email=sender[:320] or None,
            )
        except PortalError:
            # Plik spoza listy typów (np. podpis graficzny w innym formacie).
            skipped += 1
            continue
        created += 0 if stored.duplicate else 1
        if owner is not None and owner != contract_id and not stored.duplicate:
            indirect_created += 1
    body_owner = contract or (indirect if indirect_created else None)
    if created and body_owner is not None and kesu.parse_jira(subject, "") is None:
        # Akceptacja klienta przekazana dalej (PKO): treść maila to dowód godzin.
        created += await _store_mail_body(
            db,
            mailbox,
            message,
            body_owner,
            subject=subject,
            received=received,
            now=now,
        )
    return created, skipped


async def _forwarded(
    mailbox: SettlementsMailbox, message: dict[str, Any]
) -> Optional[forwarded.Forwarded]:
    fetch = getattr(mailbox, "mime", None)
    if fetch is None:
        return None
    try:
        raw = await fetch(str(message["id"]))
    except (GraphRequestError, AppOnlyTokenUnavailable) as exc:
        logger.info("rozliczenia@: MIME pominięty (%s)", type(exc).__name__)
        return None
    return forwarded.parse(raw) if raw else None


async def _forwarded_contract(
    db: AsyncSession,
    senders: tuple[str, ...],
    *,
    state: portal_settings.PortalSettings,
    today: date,
) -> Optional[Contract]:
    """Kontrakt pierwotnego nadawcy przekazanego maila; dwie osoby w łańcuchu = nikt."""

    found: dict[int, Contract] = {}
    for address in senders:
        contract = await identity.resolve_sender(
            db, address, settings=state, today=today
        )
        if contract is not None:
            found[contract.id] = contract
    return next(iter(found.values())) if len(found) == 1 else None


async def _kesu_contract(
    db: AsyncSession,
    subject: str,
    sender: str,
    *,
    state: portal_settings.PortalSettings,
    today: date,
) -> Optional[Contract]:
    """KEŚU (E6.3): osoba z tematu, ale tylko z zaufanego kanału.

    Mail z Jiry przekazuje koordynator, więc nadawcą musi być aktywne konto
    NEXUS-a (osoba z tematu ma pierwszeństwo przed kontraktem nadawcy, gdyby
    koordynator sam miał kontrakt). Odpowiedź „KEŚU … - osoba” przychodzi od
    klienta: przypisujemy ją tylko z domeny opiekuna z maila z Jiry tej osoby.
    Inny nadawca = zwykła ścieżka (adres z kontraktu albo karta do przypisania),
    bo sam temat może napisać każdy.
    """

    person = kesu.person_from_subject(subject)
    if person is None or "@" not in sender:
        return None
    if kesu.parse_jira(subject, "") is not None:
        staff = await db.scalar(
            select(User.id).where(
                func.lower(User.email) == sender, User.is_active.is_(True)
            )
        )
        if staff is None:
            return None
        return await identity.resolve_by_name(db, person, settings=state, today=today)
    contract = await identity.resolve_by_name(db, person, settings=state, today=today)
    if contract is None:
        return None
    from app.services.client_settlements import service as settlements

    domain = sender.rsplit("@", 1)[1]
    recent = (
        await db.scalars(
            select(ClientSettlement)
            .where(ClientSettlement.contract_id == contract.id)
            .order_by(ClientSettlement.period_month.desc())
            .limit(3)
        )
    ).all()
    for settlement in recent:
        approver = (settlements.meta_of(settlement).get("kesu") or {}).get(
            "approver_email"
        )
        if approver and str(approver).lower().rsplit("@", 1)[-1] == domain:
            return contract
    return None


async def _store_jira_mail(
    db: AsyncSession,
    mailbox: SettlementsMailbox,
    message: dict[str, Any],
    *,
    contract_id: Optional[int],
    subject: str,
    received: datetime,
    now: datetime,
    sender: str,
) -> int:
    """Mail z Jiry jako EML przy KEŚU: z treści bierzemy opiekuna i czas akceptacji."""

    reader = getattr(mailbox, "mime", None)
    if reader is None:
        return 0
    try:
        content = await reader(str(message["id"]))
    except (GraphRequestError, AppOnlyTokenUnavailable) as exc:
        code = (
            f"http_{exc.status}" if isinstance(exc, GraphRequestError) else "no_token"
        )
        logger.warning("consultant_portal_mailbox: jira mime failed %s", code)
        return 0
    if not content:
        return 0
    year, month, guessed = period_for(subject, "", received.date())
    try:
        stored = await documents.store(
            db,
            contract_id=contract_id,
            kind="report",
            year=year,
            month=month,
            content=content,
            file_name=f"Akceptacja Jira {month:02d}-{year}.eml",
            channel="mailbox",
            now=now,
            period_guessed=guessed,
            graph_message_id=str(message["id"])[:512],
            sender_email=sender[:320] or None,
        )
    except PortalError:
        return 0
    return 0 if stored.duplicate else 1


async def _store_client_reply(
    db: AsyncSession,
    mailbox: SettlementsMailbox,
    message: dict[str, Any],
    *,
    subject: str,
    now: datetime,
) -> Optional[int]:
    """Odpowiedź klienta na paczkę KCP (E6.5, Bank Pocztowy): nadawca z domeny
    adresu z reguły ``cl.client_acceptance``. Zapisujemy cały mail bez kontraktu
    tylko wtedy, gdy akceptuje; zapis sam zaznacza akceptację osób. ``None`` —
    to nie mail od takiego klienta (zwykła ścieżka)."""

    from app.services.client_settlements import client_acceptance

    sender = _sender(message)
    received = _parse_time(message.get("receivedDateTime")) or now
    year, month, guessed = period_for(subject, "", received.date())
    if not await client_acceptance.is_client_domain(db, sender, f"{year}-{month:02d}"):
        return None
    fetch = getattr(mailbox, "mime", None)
    if fetch is None:
        return 0
    try:
        content = await fetch(str(message["id"]))
        reply = client_acceptance.read_reply(content or b"", "message/rfc822")
        if not content or reply is None or not reply.accepted:
            return 0
        stored = await documents.store(
            db,
            contract_id=None,
            kind="report",
            year=year,
            month=month,
            content=content,
            file_name=(subject.strip()[:120] or "odpowiedz klienta") + ".eml",
            channel="mailbox",
            now=now,
            period_guessed=guessed,
            graph_message_id=str(message["id"])[:512],
            sender_email=sender[:320] or None,
        )
    except (PortalError, GraphRequestError, AppOnlyTokenUnavailable) as exc:
        logger.info(
            "rozliczenia@: odpowiedź klienta pominięta (%s)", type(exc).__name__
        )
        return 0
    return 0 if stored.duplicate else 1


async def _store_mail_body(
    db: AsyncSession,
    mailbox: SettlementsMailbox,
    message: dict[str, Any],
    contract: Any,
    *,
    subject: str,
    received: datetime,
    now: datetime,
) -> int:
    """Klient z regułą ``proof.accept_has_hours`` (PKO, E6.1): akceptacja jest
    w treści forwardu, nie w załączniku, więc zapisujemy też sam mail jako
    ``.eml``. U pozostałych klientów treści maila nie zbieramy."""

    fetch = getattr(mailbox, "mime", None)
    if fetch is None:
        return 0
    year, month, guessed = period_for(subject, "", received.date())
    from app.services.client_settlements import service as settlements

    rules = await settlements.rules_for(db, contract.client_id, f"{year}-{month:02d}")
    if rules["proof.accept_has_hours"]["level"] == "off":
        return 0
    try:
        content = await fetch(str(message["id"]))
        if not content:
            return 0
        stored = await documents.store(
            db,
            contract_id=contract.id,
            kind="report",
            year=year,
            month=month,
            content=content,
            file_name=(subject.strip()[:120] or "akceptacja") + ".eml",
            channel="mailbox",
            now=now,
            period_guessed=guessed,
            graph_message_id=str(message["id"])[:512],
            sender_email=_sender(message)[:320] or None,
        )
    except (PortalError, GraphRequestError, AppOnlyTokenUnavailable) as exc:
        logger.info("rozliczenia@: treść maila pominięta (%s)", type(exc).__name__)
        return 0
    return 0 if stored.duplicate else 1


async def run_once(
    db: AsyncSession,
    *,
    mailbox: Optional[SettlementsMailbox] = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    moment = now or datetime.now(timezone.utc)
    state = await portal_settings.load(db)
    if not state.reads_mailbox:
        return {"status": "disabled"}
    upn = mailbox_upn()
    if mailbox is None and upn is None:
        await _write_state(db, now=moment, status="disabled", error="no_mailbox")
        return {"status": "disabled", "reason": "no_mailbox"}
    route = support_mail_route.shared_route(upn, cases_mailbox())
    misconfigured = support_mail_route.misconfiguration(route)
    if misconfigured:
        # Wspólna skrzynka bez adresów: każdy mail byłby i sprawą, i dokumentem. Adresy przy
        # osobnych skrzynkach: wsparcie@ ustawiona przed skrzynką spraw zrobiłaby dokument
        # z każdego maila. Stoimy bez ruszania znacznika, więc nic nie przepada.
        await _write_state(db, now=moment, status="error", error=misconfigured)
        return {"status": "error", "reason": misconfigured}
    reader: SettlementsMailbox = mailbox or GraphSettlementsMailbox(upn or "")
    current = await _state(db)
    seen = current.last_seen_received_at if current else None
    since = (seen - OVERLAP) if seen else moment - INITIAL_LOOKBACK
    today = business_today()
    try:
        messages = await reader.list_messages(since)
    except (GraphRequestError, AppOnlyTokenUnavailable) as exc:
        code = (
            f"http_{exc.status}" if isinstance(exc, GraphRequestError) else "no_token"
        )
        logger.warning("consultant_portal_mailbox: list failed %s", code)
        await _write_state(db, now=moment, status="error", error=code)
        return {"status": "error", "reason": code}
    created = skipped = failed = 0
    newest = seen
    for message in messages:
        if route and not support_mail_route.is_settlements_mail(message, route):
            # Sprawa dla czytnika spraw: znacznik idzie dalej, nic nie zapisujemy.
            received = _parse_time(message.get("receivedDateTime"))
            if received and (newest is None or received > newest):
                newest = received
            continue
        try:
            async with db.begin_nested():
                made, ignored = await _ingest_message(
                    db, reader, message, state=state, today=today, now=moment
                )
            created += made
            skipped += ignored
        except Exception as exc:  # noqa: BLE001 — jedna wiadomość nie zatrzymuje reszty
            failed += 1
            logger.warning(
                "consultant_portal_mailbox: message failed (%s)", type(exc).__name__
            )
            # Znacznik nie idzie poza pierwszą porażkę: spróbujemy jej ponownie.
            break
        received = _parse_time(message.get("receivedDateTime"))
        if received and (newest is None or received > newest):
            newest = received
    await _write_state(
        db,
        now=moment,
        status="partial" if failed else "ok",
        error=None,
        seen=newest,
    )
    return {
        "status": "partial" if failed else "ok",
        "messages": len(messages),
        "created": created,
        "skipped": skipped,
        "failed": failed,
    }


async def status(db: AsyncSession) -> dict[str, Any]:
    row = await db.scalar(select(CpMailboxState).where(CpMailboxState.id == 1))
    return {
        "configured": mailbox_upn() is not None,
        "last_run_at": row.last_run_at.isoformat() if row and row.last_run_at else None,
        "last_status": row.last_status if row else None,
        "last_error": row.last_error if row else None,
    }
