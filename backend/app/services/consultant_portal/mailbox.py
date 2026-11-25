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
* Wyjątek: trzy maile bez pliku na adres rozliczeń czytamy też, gdy router oddał je sprawom,
  i zapisujemy ich treść jako ``.eml`` jednej osoby. Sprawa powstaje jak dotąd (decyzja
  Artura 23.11.2026, „sprawa i dokument”): akceptacja klienta z regułą akceptacji mailowej
  (``support_mail_route.is_client_acceptance_mail``, osoba z tematu) i mail z adresu firmy
  z tematem rozliczenia (``is_body_only_settlement``, nadawca albo osoba z tematu).
  Trzeci: mail konsultanta z adresu firmy z tematem faktury u klienta z regułą
  ``report.consultant_declaration`` (``is_body_only_declaration``, tylko nadawca).
* Odpowiedź klienta bez pliku na nasz mail z Wysłanych (``is_reply_to_sent``): plik godzin
  bierzemy z naszego maila, osobę z jego tematu (decyzja Artura 23.11.2026, BNP CIB).
  Sprawa też powstaje.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import logging
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional, Protocol
from urllib.parse import quote

import httpx
from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import InterfaceError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.scheduling import business_date, business_today
from app.models.client_settlement import ClientSettlement
from app.models.consultant_portal import CpMailboxState
from app.models.contract import Contract
from app.models.user import User
from app.services import support_mail_route
from app.services.admin_cases.mailbox import m365_mailbox as cases_mailbox
from app.services.client_settlements import (
    hours_summary,
    kesu,
    mail_text,
    order_split,
    protocol_collective,
    report_ca,
    t4t_mail,
    timesheet_plus,
)
from app.services.consultant_portal import (
    documents,
    forwarded,
    identity,
    portal_settings,
    zip_files,
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
#: Odpowiedź klienta szuka naszego maila w Wysłanych najwyżej tyle wstecz.
REPLY_WINDOW = timedelta(days=45)
MAX_SENT_PER_RUN = 1000
_SENT_SELECT = (
    "id,subject,from,sentDateTime,hasAttachments,conversationId,"
    + support_mail_route.RECIPIENT_FIELDS
)
_REPLY_SUBJECT = re.compile(
    r"^\s*(?:\[[^\]]{0,40}\]\s*)*(?:re|odp|aw|sv)\s*:", re.IGNORECASE
)
_THREAD_PREFIX = re.compile(
    r"^\s*(?:(?:re|odp|aw|sv|fw|fwd|pd|wg)\s*:\s*|\[[^\]]{0,40}\]\s*)+", re.IGNORECASE
)
_QUOTED_FROM = re.compile(r"^\s*(?:from|od)\s*:(.*)$", re.IGNORECASE | re.MULTILINE)
_ADDRESS = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# Obrazki stopki Outlooka (powtórka IX 2026: 3 na zestawienie w Wysłanych, 44 w poczcie).
# Webmail Open-Xchange przy odpowiedzi nazywa cytowaną stopkę „image.png” (55742).
_OUTLOOK_SIGNATURE = re.compile(r"^image(?:\d{3})?\.(?:png|jpe?g|gif)$", re.IGNORECASE)
# Ikona, logo albo baner stopki ma mniej pikseli; zrzut godzin wklejony w treść też
# nazywa się ``image00N``, ale jest większy (tydzień T4T 1570×300). Decyzja Artura
# z 23.11.2026: małe wycinki godzin (ok. 500×160) giną razem ze stopką.
_SIGNATURE_MAX_PIXELS = 350_000
# Dowód pracy: RCP (BNP), Time Sheet (Bosch, PKO), arkusz (Velo), protokół (PKO), KEŚU (Alior).
# Bez tego plik „RCP_10_2026.pdf” szedł jako faktura i omijał kontrole RCP (16.11.2026).
# KCP: karta pracy Banku Pocztowego („KCP 10/2026”, plik z nazwiskiem).
# TS: raport BIK w PDF („<nazwisko>_TS_wrzesien_2026.pdf”) szedł jako faktura.
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
# Mail klienta z odbiorem usług jako plik (PKO, „Dokumenty.zip” za X 2026) szedł jako
# faktura. Tylko nazwa pliku .msg/.eml: temat „Odbiór usług …” nie zmienia rodzaju
# innych plików maila.
_ACCEPTANCE_MAIL_FILE = re.compile(r"odbi[oó]r\s+us[lł]ug.*\.(msg|eml)$", re.IGNORECASE)
# Arkusz albo zrzut ekranu bez słów-kluczy to dowód pracy: w próbie na archiwum
# IX–XI 2026 78 arkuszy z godzinami („BIK wrzesien.xlsx”) szło jako faktury.
_PROOF_EXTENSIONS = re.compile(
    r"\.(xlsx|xlsm|xls|ods|csv|png|jpe?g|heic|gif|bmp|webp)$", re.IGNORECASE
)
# Temat maila bez pliku, który niesie akceptację godzin w treści (próba IX–X 2026: NN
# „Rozliczenie pracownika … za okres 09-2026” z MD w treści, „Fwd: FW: Timesheet wrzesień”).
_BODY_SUBJECT = re.compile(
    r"raport|time[\s_-]*sheet|ewidencj|godzin|rozliczeni|rcp|karta\s+pracy"
    r"|zestawieni|(?<![a-z])(?:ts|kcp)(?![a-z])",
    re.IGNORECASE,
)
_INVOICE = re.compile(
    r"faktur|invoice|(?:^|[^a-z])fv(?:at)?(?:[^a-z]|$)", re.IGNORECASE
)
# Także „09 2026” ze spacją: karta pracy Banku Pocztowego „KCP Nazwisko Imię 09 2026.pdf”
# szła bez okresu i z maila z połowy miesiąca na poprzedni (archiwum VI 2025–XI 2026:
# 30 z 15 126 plików zmienia okres, wszystkie na właściwy).
_PERIOD_NUMERIC = re.compile(r"(?<!\d)(0?[1-9]|1[0-2])(?:[./_-]| )(20\d{2})(?!\d)")
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
# Szablon PKO: „TimeSheet 2610 - Nazwisko Imię PZ0xxxxx.xlsm” (RRMM).
_PERIOD_PKO_SHEET = re.compile(
    r"timesheet\s+(\d{2})(0[1-9]|1[0-2])(?!\d)", re.IGNORECASE
)
# Okres dalej niż dwa miesiące po mailu to literówka w roku („Październik 2027”
# w odpowiedzi klienta z 30.10.2026, próba IX–X), nie okres. Faktury z wyprzedzeniem
# do dwóch miesięcy zostają.
_MAX_MONTHS_AHEAD = 2
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
        self._sent: Optional[tuple[datetime, list[dict[str, Any]]]] = None

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

    async def sent_messages(self, since: datetime) -> list[dict[str, Any]]:
        """Nasze maile z Wysłanych od ``since`` (bez treści). Odpowiedzi w przebiegu
        idą od najstarszej, więc pierwsza lista wystarcza na cały przebieg."""

        if self._sent is not None and self._sent[0] <= since:
            return self._sent[1]
        moment = since.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        params = {
            "$filter": f"sentDateTime ge {moment}",
            "$select": _SENT_SELECT,
            "$orderby": "sentDateTime desc",
            "$top": "100",
        }
        out: list[dict[str, Any]] = []
        async with self._client() as client:
            async for page in client.paginate(
                f"{self._prefix}/mailFolders/SentItems/messages", params=params
            ):
                out.extend(page.get("value", []))
                if len(out) >= MAX_SENT_PER_RUN:
                    break
        self._sent = (since, out[:MAX_SENT_PER_RUN])
        return self._sent[1]

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
    name = file_name.strip()
    if _PROOF_EXTENSIONS.search(name) or _ACCEPTANCE_MAIL_FILE.search(name):
        return "report"
    return "invoice"


_PDF_MIME = "application/pdf"
_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def kind_of_file(subject: str, file_name: str, content: bytes) -> str:
    """Rodzaj z nazwy i tematu, a „faktura” sprawdzona treścią: PDF albo arkusz
    rozpoznany jako RCP BNP to raport, choć temat mówi „faktura” albo plik nazywa
    się „2026-09.pdf” (próba IX–X 2026: 9 RCP BNP zapisanych jako faktury, więc
    rozliczenie nie powstało). Dwa PDF-y w jednym mailu („FV i rozliczenie
    godzinowe”) dzieli dopiero treść. To samo dla wzorów innych klientów, które
    czyta rozliczenie: potwierdzenie godzin ERGO bez słowa-klucza w nazwie,
    Time Sheet i raport BIK pod tematem „faktura”, protokół Orlenu, arkusz
    zbiorczy klienta („B2B_09_2026.pdf”, czyta go ``signoffs``). Od próby VI–VIII
    2026 także karta KCP Banku Pocztowego („timelogLip.pdf” w mailu „Faktura”),
    karta PKO, czas pracy z Redmine, zestawienie dostawcy BNP CIB i raport CA."""

    kind = classify_kind(subject, file_name)
    if kind != "invoice":
        return kind
    lower = file_name.lower()
    if content[:5] == b"%PDF-":
        mime = _PDF_MIME
    elif content[:2] == b"PK" and lower.endswith((".xlsx", ".xlsm")):
        mime = _XLSX_MIME
    elif content[:2] == b"PK" and lower.endswith(".docx"):
        mime = _DOCX_MIME
    else:
        return kind
    from app.services.client_settlements import (
        confirmation_ergo,
        ewidencja_orlen,
        kcp,
        protocol_orlen,
        rcp_bnp,
        redmine_timelog,
        report_ca,
        signoffs,
        timesheet,
        timesheet_bik,
        timesheet_fieldglass,
        timesheet_pko,
        vendor_file,
    )

    # Każdy czytnik sam odrzuca typ pliku, którego nie zna.
    readers = (
        rcp_bnp,
        confirmation_ergo,
        protocol_orlen,
        ewidencja_orlen,
        timesheet,
        timesheet_bik,
        timesheet_fieldglass,
        signoffs,
        kcp,
        timesheet_pko,
        redmine_timelog,
        vendor_file,
        report_ca,
    )
    if any(reader.parse(content, mime) is not None for reader in readers):
        return "report"
    return kind


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

    Nazwy plików z Maca przychodzą rozłożone (NFD: „z” i osobny akcent), więc
    „październik 2026” nie pasował do wzorca i okres brał się z tematu wątku
    (ERSTE, próba IX–X 2026: Time Sheet za X w wątku „wrzesień” poszedł na IX).
    """

    text = unicodedata.normalize("NFC", text)
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
    for pattern in (_PERIOD_SLASHED, _PERIOD_PKO_SHEET):
        for match in pattern.finditer(text):
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

    def not_far_ahead(period: Optional[tuple[int, int]]) -> Optional[tuple[int, int]]:
        if period is None:
            return None
        ahead = (period[0] - received.year) * 12 + period[1] - received.month
        return period if ahead <= _MAX_MONTHS_AHEAD else None

    found = (
        not_far_ahead(find_period(file_name))
        or not_far_ahead(find_period(subject))
        or not_far_ahead(find_period(file_name, received))
        or not_far_ahead(find_period(subject, received))
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


def _is_document(attachment: dict[str, Any]) -> bool:
    """Plik do zapisania: załącznik pliku, nie inline i nie obrazek stopki Outlooka.

    Samo ``isInline`` nie wystarcza: Open-Xchange i onet podają obrazki stopki bez
    ``Content-Disposition: inline`` albo jako zwykły załącznik, a Graph bywa, że daje
    im ``isInline: false``. Powtórka 30.09–06.10.2026: 44 ``image00N`` jako raporty
    i faktury na kontraktach. Zrzut ekranu z godzinami przechodzi: pod inną nazwą
    zawsze, jako ``image00N`` od ``_SIGNATURE_MAX_PIXELS`` w górę."""

    return (
        attachment.get("@odata.type") == _FILE_ATTACHMENT
        and not attachment.get("isInline")
        and not _is_signature_image(attachment)
    )


def _is_signature_image(attachment: dict[str, Any]) -> bool:
    """``image00N``/``image.png`` poniżej ``_SIGNATURE_MAX_PIXELS``; obraz nieczytelny
    zostaje plikiem."""

    if not _OUTLOOK_SIGNATURE.match(str(attachment.get("name") or "").strip()):
        return False
    raw = attachment.get("contentBytes")
    if not isinstance(raw, str):
        return False
    try:
        # Sam nagłówek: Image.open nie dekoduje pikseli.
        with Image.open(io.BytesIO(base64.b64decode(raw, validate=True))) as image:
            width, height = image.size
    except (ValueError, OSError, Image.DecompressionBombError):
        return False
    return width * height < _SIGNATURE_MAX_PIXELS


async def _store_without_file(
    db: AsyncSession,
    mailbox: SettlementsMailbox,
    message: dict[str, Any],
    acceptance: Optional[dict[str, frozenset[int]]],
    *,
    state: portal_settings.PortalSettings,
    today: date,
    now: datetime,
    declaring: frozenset[int] = frozenset(),
) -> tuple[int, int]:
    """Mail bez pliku: zestawienie godzin koordynatora, akceptacja w treści, deklaracja
    konsultanta w mailu z fakturą, odpowiedź na nasz mail z Wysłanych albo akceptacja
    klienta z regułą akceptacji mailowej."""

    summary = await _store_hours_summary(
        db, mailbox, message, state=state, today=today, now=now
    )
    if summary is not None:
        return summary, 0
    if declaring and is_body_only_declaration(message):
        made = await _store_declaration(
            db, mailbox, message, declaring, state=state, today=today, now=now
        )
        if made:
            return made, 0
    if is_body_only_settlement(message):
        made = await _store_body_only(
            db, mailbox, message, state=state, today=today, now=now
        )
        return made, 0
    if state.any_sender and is_reply_to_sent(message):
        answered = await _store_reply_to_sent(
            db, mailbox, message, state=state, today=today, now=now
        )
        if answered is not None:
            return answered, 0
    return await _store_client_acceptance(
        db,
        mailbox,
        message,
        acceptance or {},
        subject=str(message.get("subject") or ""),
        state=state,
        today=today,
        now=now,
    )


async def _ingest_message(
    db: AsyncSession,
    mailbox: SettlementsMailbox,
    message: dict[str, Any],
    *,
    state: portal_settings.PortalSettings,
    today: date,
    now: datetime,
    acceptance: Optional[dict[str, frozenset[int]]] = None,
    declaring: frozenset[int] = frozenset(),
) -> tuple[int, int]:
    """(nowe, pominięte). Reguła pilotażu przed odczytem załączników."""

    sender = _sender(message)
    subject = str(message.get("subject") or "")
    reply = await _store_client_reply(db, mailbox, message, subject=subject, now=now)
    if reply is not None:
        return reply, 0
    if not message.get("hasAttachments"):
        return await _store_without_file(
            db,
            mailbox,
            message,
            acceptance,
            state=state,
            today=today,
            now=now,
            declaring=declaring,
        )
    received = _parse_time(message.get("receivedDateTime")) or now
    # ZIP (raport CA z hasłem, „Dokumenty.zip” PKO): pliki ze środka jak załączniki.
    passwords = zip_files.configured_passwords()
    files = zip_files.expand(
        list(await mailbox.attachments(str(message["id"]))), passwords=passwords
    )
    if not any(
        _is_document(f) or f.get("@odata.type") == forwarded.ITEM_ATTACHMENT
        for f in files
    ):
        # Same obrazki stopki: w M365 taki mail ma zwykle ``hasAttachments`` false,
        # więc czytamy go jak mail bez pliku (akceptacja w treści, próba IX 2026).
        return await _store_without_file(
            db,
            mailbox,
            {**message, "hasAttachments": False},
            acceptance,
            state=state,
            today=today,
            now=now,
        )
    # Raport godzin klienta (T4T Nordei) wchodzi jako wersja raportu miesiąca, zanim
    # nadawca i pilotaż zdecydują o dokumentach konsultantów (23.11.2026).
    time_report = await t4t_mail.ingest(db, files, received_on=business_date(received))
    if time_report.consumed:
        files = [f for i, f in enumerate(files) if i not in time_report.consumed]
        if not any(_is_document(f) for f in files):
            return time_report.versions, time_report.duplicates
    client_report, consumed = await _store_client_reports(
        db,
        files,
        message,
        mailbox=mailbox,
        sender=sender,
        received=received,
        state=state,
        today=today,
        now=now,
    )
    if consumed:
        files = [f for i, f in enumerate(files) if i not in consumed]
        if not any(_is_document(f) for f in files):
            return time_report.versions + client_report, 0
    by_subject = await _kesu_contract(db, subject, sender, state=state, today=today)
    contract = by_subject or await identity.resolve_sender(
        db, sender, settings=state, today=today
    )
    if contract is None and not state.any_sender:
        return time_report.versions + client_report, 1
    inner = None
    if contract is None or any(
        f.get("@odata.type") == forwarded.ITEM_ATTACHMENT for f in files
    ):
        inner = await _forwarded(mailbox, message)
        inner_files = (
            zip_files.expand(list(inner.files), passwords=passwords) if inner else []
        )
        if inner_files:
            # Raport T4T przekazany jako załączony mail (Finanse „Przekaż jako załącznik”).
            nested = await t4t_mail.ingest(
                db, inner_files, received_on=business_date(received)
            )
            time_report.versions += nested.versions
            time_report.duplicates += nested.duplicates
            inner_files = [
                f for i, f in enumerate(inner_files) if i not in nested.consumed
            ]
        files.extend(inner_files)
    # Osoba nie z nadawcy (pierwotny nadawca przekazanego maila, nazwisko w temacie
    # albo nazwie pliku) dostaje tylko pliki, które z nazwy są raportem albo fakturą.
    indirect = None
    if contract is None and inner is not None:
        indirect = await _forwarded_contract(
            db, inner.senders, state=state, today=today
        )
    by_file_name = False
    company = contract is None and identity.is_company_address(sender)
    staff_clients: frozenset[int] = frozenset()
    if company and indirect is None:
        # Nazwisko z tematu tylko od adresu firmy (koordynator, skrzynka firmowa):
        # temat może napisać każdy, więc obcy adres nie wskazuje nim osoby.
        names = " ".join([subject, *(str(f.get("name") or "") for f in files)])
        indirect = await identity.resolve_named_in_text(db, names, today=today)
        # Kilka osób w mailu: każdy plik osobno, po nazwisku z jego nazwy.
        by_file_name = indirect is None
        # Portfel DL-a, który pisze albo do którego piszemy: wśród jego klientów
        # nazwisko z literówką w imieniu wskazuje osobę (próba IX–X 2026, Orlen).
        staff_clients = await identity.staff_client_ids(
            db, [sender, *support_mail_route.recipients(message)]
        )
    sender_clients: frozenset[int] = frozenset()
    if (
        contract is None
        and indirect is None
        and not identity.is_company_address(sender)
    ):
        # Klient przekazuje raport ze swojej domeny, a osoba stoi tylko w nazwie pliku
        # (próba IX–X 2026: PKO, ERGO, BIK — 8 osobo-miesięcy bez rozliczenia). Nazwa
        # wskazuje osobę tylko wśród kontraktów klienta tej domeny (decyzja 23.11.2026).
        sender_clients = await identity.client_ids_for_sender(db, sender)
    by_file: dict[int, Contract] = {}
    indirect_created = 0
    contract_id = contract.id if contract else None
    created = skipped = 0
    # Plik nadawcy, który już mamy (ten sam Time Sheet drugi raz): mail i tak może
    # nieść akceptację klienta, więc jego treść idzie do ``_store_mail_body``.
    known = 0
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
    report_owner = None
    if contract is None and indirect is None:
        report_owner = await identity.resolve_report_owner(
            db, sender, settings=state, today=today
        )
    for attachment in files:
        if not _is_document(attachment):
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
            # Plik z imieniem albo nazwiskiem innej osoby nie dziedziczy osoby z maila:
            # czeka na człowieka (próba IX–X 2026, Orlen: plik osoby po zmianie
            # nazwiska trafił do kontraktu drugiej osoby z tego samego maila).
            own = await identity.resolve_named_in_text(db, name, today=today)
            if (own is not None and own.id == indirect.id) or not (
                await identity.names_someone_else(db, name, indirect, today=today)
            ):
                owner = indirect.id
        elif owner is None and by_file_name and _named_kind("", name):
            # Koordynator wysyła protokoły kilku osób jednym mailem („PROTOKÓŁ_ Imię
            # Nazwisko_WRZESIEŃ 2026.pdf”): plik idzie do jedynej osoby z jego nazwy,
            # a rodzaj też musi wynikać z nazwy pliku, nie z tematu (próba IX–X 2026:
            # 3 osobo-miesiące Orlenu bez rozliczenia). Literówka w imieniu: osoba
            # wśród klientów z portfela DL-a z wątku.
            named = await identity.resolve_named_in_text(
                db, name, today=today
            ) or await identity.resolve_named_in_scope(
                db, name, client_ids=staff_clients, today=today
            )
            owner = named.id if named is not None else None
        elif owner is None and sender_clients and _named_kind("", name):
            named = await identity.resolve_named_at_client(
                db, name, client_ids=sender_clients, today=today
            )
            if named is not None:
                owner = named.id
                by_file[named.id] = named
        if (
            owner is None
            and indirect is None
            and (company or sender_clients)
            and _named_kind(subject, name)
        ):
            # Numer umowy wykonawczej w nazwie pliku albo w temacie („do umowy
            # CeZ/177/2026”) wskazuje kontrakt, gdy imię różni się od kartoteki (próba
            # IX–X 2026, CeZ 668). Numer z nazwy pliku wygrywa z tematem.
            by_number = await _agreement_contract(
                db,
                name,
                subject,
                client_ids=None if company else sender_clients,
                today=today,
            )
            if by_number is not None:
                owner = by_number.id
                by_file[by_number.id] = by_number
        if owner is None:
            # Raport Polkomtelu albo rozliczenie Cyfrowego Polsatu („.xls”): osoba ma
            # kontrakt w obu spółkach, więc kontrakt wybiera numer zamówienia z pliku
            # (próba IX–X 2026: Polkomtel 471 IX i X, Cyfrowy Polsat 634 X).
            sheet = await asyncio.to_thread(timesheet_plus.parse, content)
            from_sheet = (
                await identity.resolve_from_sheet(db, sheet, sender=sender, today=today)
                if sheet is not None
                else None
            )
            if from_sheet is not None:
                owner = from_sheet.id
                by_file[from_sheet.id] = from_sheet
        # Odczyt PDF-a to praca CPU: poza pętlą zdarzeń, jak odczyt RCP w rozliczeniu.
        kind = await asyncio.to_thread(kind_of_file, subject, name, content)
        if owner is None and kind == "report" and not guessed:
            # Adres wskazuje dwa kontrakty osoby po zmianie klienta: raport z okresem
            # w nazwie albo temacie idzie do jedynego, który działa w tym miesiącu
            # (próba IX–X 2026, VeloBank 466 i 467). Okres z daty maila nie
            # rozstrzyga, bo plik bywa spóźnionym raportem poprzedniego kontraktu.
            # Faktura też nie: numer niesie miesiąc wystawienia, a ostatnia faktura
            # za poprzedni kontrakt przychodzi po jego końcu.
            in_month = await identity.resolve_sender_in_month(
                db, sender, year=year, month=month, today=today
            )
            if in_month is not None:
                owner = in_month.id
                by_file[in_month.id] = in_month
        if owner is None and report_owner is not None and kind == "report":
            # Drugi kontrakt jest u klienta z raportem T4T: raport godzin z poczty
            # należy do tego kontraktu, faktura czeka na człowieka (próba IX–X 2026).
            owner = report_owner.id
        try:
            stored = await documents.store(
                db,
                contract_id=owner,
                kind=kind,
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
        if stored.duplicate and owner is not None and owner == contract_id:
            known += 1
    body_owner = contract or (indirect if indirect_created else None)
    if body_owner is None and indirect_created and len(by_file) == 1:
        body_owner = next(iter(by_file.values()))
    if (
        (created or known)
        and body_owner is not None
        and kesu.parse_jira(subject, "") is None
    ):
        # Akceptacja klienta przekazana dalej (PKO): treść maila to dowód godzin.
        # Także przy pliku, który już był: konsultant przekazuje akceptację
        # kierownika z tym samym Time Sheet (próba IX–X 2026, akceptacja z 13.10
        # do pliku z 30.09 przepadała, bo żaden plik nie był nowy).
        created += await _store_mail_body(
            db,
            mailbox,
            message,
            body_owner,
            subject=subject,
            received=received,
            now=now,
        )
    return created + time_report.versions + client_report, skipped


async def _agreement_contract(
    db: AsyncSession,
    name: str,
    subject: str,
    *,
    client_ids: Optional[frozenset[int]],
    today: date,
) -> Optional[Contract]:
    """Kontrakt z numeru umowy wykonawczej: z nazwy pliku, a bez numeru w niej z tematu.

    Pełne imię i nazwisko innej osoby w temacie albo nazwie pliku = nikt. Samo inne
    imię nie przeszkadza: CeZ pisze w temacie zdrobnienie albo inne imię niż kartoteka."""

    text = name if identity.agreement_numbers(name) else subject
    found = await identity.resolve_by_agreement(
        db, text, today=today, client_ids=client_ids
    )
    if found is None:
        return None
    named = await identity.resolve_named_in_text(db, f"{subject} {name}", today=today)
    if named is not None and named.candidate_id != found.candidate_id:
        return None
    return found


async def _report_people(
    db: AsyncSession,
    report: report_ca.CaReport | protocol_collective.Protocol,
    *,
    sender: str,
    state: portal_settings.PortalSettings,
    today: date,
) -> list[Contract]:
    """Kontrakty osób z raportu albo protokołu zbiorczego, wszystkie u jednego klienta.

    Osoba po imieniu i nazwisku z wiersza raportu (w protokole PFRON z rolą, w
    protokole jednej osoby z tekstu tabeli). Osoby u dwóch klientów albo
    nadawca spoza firmy i spoza domeny tego klienta = nikt (raport czeka na
    człowieka): arkusz może przysłać każdy, więc nie wskazuje nim osób sam."""

    hits: list[Contract] = []
    for person in report.people:
        contract = await identity.resolve_named_in_text(db, person.name, today=today)
        if contract is not None and contract.id not in {c.id for c in hits}:
            hits.append(contract)
    clients = {c.client_id for c in hits}
    if len(clients) != 1:
        if hits:
            logger.warning(
                "rozliczenia: raport zbiorczy z osobami u %d klientów, czeka na człowieka",
                len(clients),
            )
        return []
    client_id = next(iter(clients))
    if not identity.is_company_address(sender) and client_id not in (
        await identity.client_ids_for_sender(db, sender)
    ):
        return []
    if len(hits) < len(report.people):
        logger.info(
            "rozliczenia: raport zbiorczy, %d z %d osób bez kontraktu",
            len(report.people) - len(hits),
            len(report.people),
        )
    return sorted(
        (c for c in hits if state.any_sender or state.open_for(c.id)),
        key=lambda c: c.id,
    )


async def _thread_client_address(
    db: AsyncSession,
    mailbox: Optional[SettlementsMailbox],
    message: dict[str, Any],
    *,
    client_id: int,
) -> Optional[str]:
    """Adres klienta z wątku maila wysłanego z adresu firmy: adresat albo nadawca
    cytatu „Od:”/„From:” z domeny klienta (``identity.client_ids_for_sender``).

    Protokół odbioru CeZ przychodzi na rozliczenia@ zawsze od nas: PM podpisuje
    protokół od CeZ i odsyła go do CeZ z DW rozliczenia@ albo przekazuje dalej
    (przegląd skrzynek 24.11.2026). Decyzja Artura z 24.11.2026: taki protokół jest
    od klienta, gdy CeZ jest w wątku; PDF z adresu firmy bez klienta w wątku nie."""

    addresses = [
        identity.normalize_email((item.get("emailAddress") or {}).get("address"))
        for field in ("toRecipients", "ccRecipients")
        for item in message.get(field) or []
        if isinstance(item, dict)
    ]
    for address in addresses:
        if address and client_id in await identity.client_ids_for_sender(db, address):
            return address
    inner = await _forwarded(mailbox, message) if mailbox is not None else None
    for address in inner.senders if inner else ():
        if address and client_id in await identity.client_ids_for_sender(db, address):
            return address
    return None


async def _store_client_reports(
    db: AsyncSession,
    files: list[dict[str, Any]],
    message: dict[str, Any],
    *,
    mailbox: Optional[SettlementsMailbox] = None,
    sender: str,
    received: datetime,
    state: portal_settings.PortalSettings,
    today: date,
    now: datetime,
) -> tuple[int, set[int]]:
    """Raport zbiorczy klienta jako raport każdej osoby z dokumentu.

    (nowe, indeksy wczytanych plików). Ten sam plik u każdej osoby; czytnik
    rozliczenia bierze z niego wiersz osoby: arkusz Credit Agricole
    (``client_settlements/report_ca``) i protokół odbioru CeZ albo PFRON w PDF
    (``client_settlements/protocol_collective``). Miesiąc z dokumentu, nie
    z tematu; protokół PFRON go nie ma, więc bierzemy okres z nazwy pliku albo
    tematu, a bez niego (okres zgadnięty z daty maila) plik idzie zwykłą ścieżką."""

    created = 0
    consumed: set[int] = set()
    message_id = str(message["id"])[:512]
    subject = str(message.get("subject") or "")
    for index, attachment in enumerate(files):
        name = str(attachment.get("name") or "")
        raw = attachment.get("contentBytes")
        lower = name.lower()
        if (
            not _is_document(attachment)
            or not lower.endswith((".xlsx", ".xls", ".pdf"))
            or not isinstance(raw, str)
        ):
            continue
        try:
            content = base64.b64decode(raw, validate=True)
        except ValueError:
            continue
        if lower.endswith((".xlsx", ".xls")):
            # Wykaz grupy Polkomtel / Cyfrowy Polsat z wierszami kilku kontraktów
            # (dwie osoby albo jedna osoba w obu spółkach, próba VI–VIII 2026): plik
            # u każdego kontraktu. Jeden kontrakt idzie zwykłą ścieżką.
            sheet = await asyncio.to_thread(timesheet_plus.parse, content)
            if sheet is not None and sheet.month is not None:
                owners = [
                    c
                    for c in await identity.resolve_sheet_contracts(
                        db, sheet, sender=sender, today=today
                    )
                    if state.any_sender or state.open_for(c.id)
                ]
                if len(owners) > 1:
                    year, month = (int(part) for part in sheet.month.split("-"))
                    for position, contract in enumerate(owners):
                        stored = await documents.store(
                            db,
                            contract_id=contract.id,
                            kind="report",
                            year=year,
                            month=month,
                            content=content,
                            file_name=name or None,
                            channel="mailbox",
                            now=now,
                            graph_message_id=message_id if position == 0 else None,
                            sender_email=sender[:320] or None,
                        )
                        created += 0 if stored.duplicate else 1
                    consumed.add(index)
                    continue
            if lower.endswith(".xls"):
                continue
        report: report_ca.CaReport | protocol_collective.Protocol | None
        if lower.endswith(".xlsx"):
            report = await asyncio.to_thread(report_ca.parse, content, report_ca.XLSX)
            period = report.month if report is not None else None
        else:
            report = await asyncio.to_thread(
                protocol_collective.parse, content, protocol_collective.PDF
            )
            period = report.month if report is not None else None
            if report is not None and period is None:
                year, month, guessed = period_for(subject, name, received.date())
                period = None if guessed else f"{year}-{month:02d}"
        if report is None or period is None:
            continue
        people = await _report_people(
            db, report, sender=sender, state=state, today=today
        )
        if not people:
            continue
        year, month = (int(part) for part in period.split("-"))
        # Nadawca dokumentu: przy protokole wysłanym z adresu firmy — klient z wątku
        # (faktura CeZ sprawdza protokół od klienta, ``client_invoicing/period_checks``).
        author = sender
        if isinstance(report, protocol_collective.Protocol) and (
            identity.is_company_address(sender)
        ):
            author = (
                await _thread_client_address(
                    db, mailbox, message, client_id=people[0].client_id
                )
                or sender
            )
        for position, contract in enumerate(people):
            stored = await documents.store(
                db,
                contract_id=contract.id,
                kind="report",
                year=year,
                month=month,
                content=content,
                file_name=name or None,
                channel="mailbox",
                now=now,
                # Para (mail, plik) jest unikalna: identyfikator maila ma pierwsza kopia.
                graph_message_id=message_id if position == 0 else None,
                sender_email=author[:320] or None,
            )
            if (
                stored.duplicate
                and author != sender
                and identity.is_company_address(stored.document.sender_email or "")
            ):
                # Ten sam podpisany protokół przyszedł wcześniej bez CeZ w wątku.
                stored.document.sender_email = author[:320]
            created += 0 if stored.duplicate else 1
        consumed.add(index)
    return created, consumed


async def _store_hours_summary(
    db: AsyncSession,
    mailbox: SettlementsMailbox,
    message: dict[str, Any],
    *,
    state: portal_settings.PortalSettings,
    today: date,
    now: datetime,
) -> Optional[int]:
    """Zestawienie godzin zaakceptowanych przez klienta od koordynatora (CeZ, decyzja
    Artura z 23.11.2026) jako raport każdej osoby z liczbą godzin.

    ``None`` = to nie zestawienie, mail idzie dalej zwykłą ścieżką. Tylko z adresu
    firmy i z tematem rozliczenia; osoby jak w raporcie zbiorczym (jeden klient).
    Osoba z „czekamy” nic nie dostaje. Okres z tematu, inaczej z poczty, ale nie
    zgadnięty z daty maila. Ten sam ``.eml`` u każdej osoby; rozliczenie bierze
    z niego jej wiersz (``client_settlements/hours_summary``)."""

    sender = _sender(message)
    subject = str(message.get("subject") or "")
    fetch = getattr(mailbox, "mime", None)
    if (
        fetch is None
        or not identity.is_company_address(sender)
        or not _BODY_SUBJECT.search(subject)
    ):
        return None
    try:
        content = await fetch(str(message["id"]))
    except (GraphRequestError, AppOnlyTokenUnavailable) as exc:
        logger.info("rozliczenia@: MIME zestawienia pominięty (%s)", type(exc).__name__)
        return None
    if not content:
        return None
    summary = await asyncio.to_thread(hours_summary.parse, content, mail_text.EML)
    if summary is None:
        return await _store_split_table(
            db, message, content, sender=sender, state=state, today=today, now=now
        )
    received = _parse_time(message.get("receivedDateTime")) or now
    year, month, guessed = period_for(subject, "", received.date())
    if summary.month is not None:
        year, month = (int(part) for part in summary.month.split("-"))
    elif guessed:
        return None
    people = await _report_people(db, summary, sender=sender, state=state, today=today)
    if not people:
        return None
    created = 0
    message_id = str(message["id"])[:512]
    for position, contract in enumerate(people):
        try:
            stored = await documents.store(
                db,
                contract_id=contract.id,
                kind="report",
                year=year,
                month=month,
                content=content,
                file_name=(subject.strip()[:120] or "zestawienie") + ".eml",
                channel="mailbox",
                now=now,
                graph_message_id=message_id if position == 0 else None,
                sender_email=sender[:320] or None,
            )
        except PortalError as exc:
            logger.info("rozliczenia@: zestawienie pominięte (%s)", type(exc).__name__)
            return created
        created += 0 if stored.duplicate else 1
    return created


async def _store_split_table(
    db: AsyncSession,
    message: dict[str, Any],
    content: bytes,
    *,
    sender: str,
    state: portal_settings.PortalSettings,
    today: date,
    now: datetime,
) -> Optional[int]:
    """Tabela klienta „osoba × numer zamówienia” z MD w treści maila jako raport
    każdej osoby z tabeli (Polkomtel IX 2026: koordynatorka przekazuje z adresu
    firmy zestawienie od klienta, bez pliku; dotąd nie trafiało do nikogo).

    Klient to ten, do którego należą numery zamówień z nagłówka, a tabelę musi
    napisać ktoś z jego domeny (cytat nad tabelą). Osobę z wiersza szukamy tylko
    wśród kontraktów tego klienta. Okres z tematu albo tabeli, nie zgadnięty
    z daty maila. ``None`` = to nie taka tabela albo nikogo nie rozpoznaliśmy:
    mail idzie dalej zwykłą ścieżką. Rozliczenie bierze z niej wiersz osoby
    (``client_settlements/order_split``)."""

    split = await asyncio.to_thread(order_split.parse, content, mail_text.EML)
    if split is None or split.kind != order_split.TABLE:
        return None
    keys = frozenset(
        key
        for row in split.rows
        for part in row.parts
        if (key := order_split.order_key(part.order))
    )
    client_id = await identity.split_client(db, keys)
    if client_id is None or client_id not in await identity.client_ids_for_sender(
        db, order_split.author_address(split)
    ):
        return None
    subject = str(message.get("subject") or "")
    received = _parse_time(message.get("receivedDateTime")) or now
    year, month, guessed = period_for(subject, "", received.date())
    if split.month is not None:
        year, month = (int(part) for part in split.month.split("-"))
    elif guessed:
        return None
    people: dict[int, Contract] = {}
    for row in split.rows:
        mine = frozenset(
            key for part in row.parts if (key := order_split.order_key(part.order))
        )
        contract = await identity.resolve_split_row(
            db, row.person or "", client_id=client_id, order_keys=mine, today=today
        )
        if contract is not None and (state.any_sender or state.open_for(contract.id)):
            people[contract.id] = contract
    if not people:
        return None
    created = 0
    message_id = str(message["id"])[:512]
    for position, contract_id in enumerate(sorted(people)):
        try:
            stored = await documents.store(
                db,
                contract_id=contract_id,
                kind="report",
                year=year,
                month=month,
                content=content,
                file_name=(subject.strip()[:120] or "zestawienie") + ".eml",
                channel="mailbox",
                now=now,
                # Para (mail, plik) jest unikalna: identyfikator maila ma pierwsza kopia.
                graph_message_id=message_id if position == 0 else None,
                sender_email=sender[:320] or None,
            )
        except PortalError as exc:
            logger.info(
                "rozliczenia@: tabela zamówień pominięta (%s)", type(exc).__name__
            )
            return created
        created += 0 if stored.duplicate else 1
    return created


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
    tylko wtedy, gdy akceptuje; zapis sam zaznacza akceptację osób. Liczba (także 0
    przy duplikacie) — mail zapisany jako akceptacja, koniec czytania. ``None`` —
    zwykła ścieżka: nadawca spoza takiej domeny albo mail z niej, który nie jest
    akceptacją. Z domeny banku piszą też konsultanci ze skrzynką u klienta (KCP
    w załączniku), a odmowa klienta ma trafić do ludzi; ``0`` kończył oba maile
    bez śladu (audyt 24.11.2026)."""

    from app.services.client_settlements import client_acceptance

    sender = _sender(message)
    received = _parse_time(message.get("receivedDateTime")) or now
    year, month, guessed = period_for(subject, "", received.date())
    if not await client_acceptance.is_client_domain(db, sender, f"{year}-{month:02d}"):
        return None
    fetch = getattr(mailbox, "mime", None)
    if fetch is None:
        return None
    try:
        content = await fetch(str(message["id"]))
        reply = client_acceptance.read_reply(content or b"", "message/rfc822")
        if not content or reply is None or not reply.accepted:
            return None
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
        return None
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
    ``.eml``. Przy ``proof.excel_with_mail`` albo ``extra.mail_accept`` tylko mail,
    w którego wątku pisze klient (``_client_wrote``): konsultant ERSTE i Polkomtelu
    przekazuje Time Sheet razem z odpowiedzią kierownika („Potwierdzam”), a bez
    zapisanej treści kontrola pisała „Brak maila z akceptacją godzin” (próba IX–X
    2026). Bez tematów KEŚU: tam akceptacją jest mail automatu Jiry, a każdy dodatkowy
    mail miesiąca zmienia źródło KEŚU. U pozostałych klientów treści maila nie
    zbieramy."""

    from app.services.client_settlements import service as settlements

    year, month, _guessed = period_for(subject, "", received.date())
    rules = await settlements.rules_for(db, contract.client_id, f"{year}-{month:02d}")
    content: Optional[bytes] = None
    if rules["proof.accept_has_hours"]["level"] == "off":
        fetch = getattr(mailbox, "mime", None)
        if (
            fetch is None
            or kesu.is_kesu_subject(subject)
            or all(
                rules[key]["level"] == "off" for key in settlements.CLIENT_MAIL_RULES
            )
        ):
            return 0
        try:
            content = await fetch(str(message["id"]))
        except (GraphRequestError, AppOnlyTokenUnavailable) as exc:
            logger.info("rozliczenia@: treść maila pominięta (%s)", type(exc).__name__)
            return 0
        if not content or not await _client_wrote(db, content, contract, rules):
            return 0
    return await _store_eml(
        db,
        mailbox,
        message,
        contract.id,
        subject=subject,
        received=received,
        now=now,
        content=content,
    )


async def _client_wrote(
    db: AsyncSession,
    content: bytes,
    contract: Contract,
    rules: dict[str, dict[str, Any]],
) -> bool:
    """W wątku maila pisze klient, a nie sam konsultant z kontraktu.

    Domeny klienta jak w kontrolach pliku (``service.acceptance_senders``). Skrzynka
    konsultanta u klienta (``imie.nazwisko@kir.pl``, ERSTE, PKO) jest w domenie
    klienta, ale jego własny mail z fakturą to nie akceptacja (próba IX–X 2026):
    liczy się wiadomość kogoś, kogo czytnik nie rozpoznaje jako tego konsultanta."""

    from app.services.client_settlements import acceptance_mail
    from app.services.client_settlements import service as settlements

    senders = await settlements.acceptance_senders(db, contract.client_id, rules)
    messages = await asyncio.to_thread(
        acceptance_mail.read, content, acceptance_mail.EML
    )
    today = business_today()
    for found in messages:
        if not found.sender or not senders.accepts_from(found.sender):
            continue
        if contract.id not in await identity.sender_contract_ids(
            db, found.sender, today=today
        ):
            return True
    return False


async def _store_client_acceptance(
    db: AsyncSession,
    mailbox: SettlementsMailbox,
    message: dict[str, Any],
    acceptance: dict[str, frozenset[int]],
    *,
    subject: str,
    state: portal_settings.PortalSettings,
    today: date,
    now: datetime,
) -> tuple[int, int]:
    """Akceptacja klienta w samej treści maila, bez załącznika (próba IX–X 2026).

    Nadawca z domeny klienta z regułą akceptacji mailowej
    (``support_mail_route.acceptance_clients``), osoba z tematu wątku wśród kontraktów
    tego klienta. Mail zapisujemy jako ``.eml``: z niego czytają ``proof.accept_has_hours``
    i ``proof.excel_with_mail``. Nieznana osoba = karta do ręcznego przypisania (jak nieznany
    nadawca), w pilotażu pomijamy."""

    clients = acceptance.get(support_mail_route.sender_domain(message))
    if not clients:
        return 0, 0
    contract = await identity.resolve_named_for_clients(
        db, subject, clients, settings=state, today=today
    )
    received = _parse_time(message.get("receivedDateTime")) or now
    content: Optional[bytes] = None
    if contract is None:
        # Konsultant przekazuje akceptację kierownika ze swojej skrzynki u klienta,
        # bez nazwiska w temacie („PD: akcept rozliczenia”, próba IX–X 2026, ERSTE 479):
        # nadawca to jego adres z kontraktu, więc mail jest jego, o ile w wątku pisze
        # kierownik. Temat z imieniem albo nazwiskiem innej osoby (także
        # niejednoznacznej) i sam mail konsultanta zostają kartą do przypisania.
        own = await identity.resolve_sender(
            db, _sender(message), settings=state, today=today
        )
        fetch = getattr(mailbox, "mime", None)
        if (
            own is not None
            and fetch is not None
            and own.client_id in clients
            and not await identity.names_someone_else(db, subject, own, today=today)
        ):
            from app.services.client_settlements import service as settlements

            year, month, _guessed = period_for(subject, "", received.date())
            try:
                content = await fetch(str(message["id"]))
            except (GraphRequestError, AppOnlyTokenUnavailable) as exc:
                logger.info(
                    "rozliczenia@: treść maila pominięta (%s)", type(exc).__name__
                )
                return 0, 0
            rules = await settlements.rules_for(
                db, own.client_id, f"{year}-{month:02d}"
            )
            if content and await _client_wrote(db, content, own, rules):
                contract = own
    if contract is None and not state.any_sender:
        return 0, 1
    made = await _store_eml(
        db,
        mailbox,
        message,
        contract.id if contract else None,
        subject=subject,
        received=received,
        now=now,
        content=content,
    )
    return made, 0


def _thread_topic(subject: str) -> str:
    return " ".join(_THREAD_PREFIX.sub("", subject or "").split()).casefold()


def is_reply_to_sent(message: dict[str, Any]) -> bool:
    """Odpowiedź bez pliku z obcego adresu w wątku rozliczenia (próba IX–X 2026, BNP CIB).

    Koordynator wysyła klientowi „Zestawienie godzin 2026.09 … - osoba” z plikiem, a klient
    odpisuje „Potwierdzam zestawienie”. Plik jest tylko w naszych Wysłanych, więc taka
    odpowiedź prowadzi do naszego maila (``_store_reply_to_sent``). Router dalej oddaje ją
    czytnikowi spraw, tak jak mail bez pliku z adresu firmy.
    """

    if message.get("hasAttachments"):
        return False
    subject = str(message.get("subject") or "")
    sender = _sender(message)
    if "@" not in sender or identity.is_company_address(sender):
        return False
    return bool(_REPLY_SUBJECT.match(subject)) and bool(
        _REPORT.search(_thread_topic(subject))
    )


def _answered_mail(
    reply: dict[str, Any], sent: list[dict[str, Any]], *, received: datetime
) -> Optional[dict[str, Any]]:
    """Nasz mail, na który odpowiada klient: ten sam temat bez „RE:”/„[EXTERNAL]”, adresat
    z domeny nadawcy odpowiedzi, wysłany do ``REPLY_WINDOW`` wcześniej, z plikiem.

    Nagłówki wątku nie wystarczają: Outlook z IMAP zapisuje w Wysłanych kopię pod innym
    Message-ID niż wysłany mail (archiwum 2024–2026: 0 trafień In-Reply-To), a odpowiedź
    przekazuje dalej przełożony z tej samej domeny. Przy kilku kandydatach wygrywa ten sam
    wątek (``conversationId``), potem najpóźniejszy.
    """

    topic = _thread_topic(str(reply.get("subject") or ""))
    domain = support_mail_route.sender_domain(reply)
    found: list[tuple[bool, datetime, dict[str, Any]]] = []
    for ours in sent:
        moment = _parse_time(ours.get("sentDateTime"))
        if moment is None or not (received - REPLY_WINDOW <= moment < received):
            continue
        if not ours.get("hasAttachments") or not identity.is_company_address(
            _sender(ours)
        ):
            continue
        if _thread_topic(str(ours.get("subject") or "")) != topic:
            continue
        domains = {a.rpartition("@")[2] for a in support_mail_route.recipients(ours)}
        if domain not in domains:
            continue
        thread = bool(reply.get("conversationId")) and (
            ours.get("conversationId") == reply.get("conversationId")
        )
        found.append((thread, moment, ours))
    return max(found, key=lambda item: item[:2])[2] if found else None


def _client_part(body: str) -> str:
    """Treść odpowiedzi nad cytatem naszego maila: to pisał klient (także przełożony,
    który przekazał akceptację dalej), a pod spodem jest nasza prośba."""

    for match in _QUOTED_FROM.finditer(body or ""):
        if any(
            identity.is_company_address(a) for a in _ADDRESS.findall(match.group(1))
        ):
            return body[: match.start()]
    return body or ""


async def _store_reply_to_sent(
    db: AsyncSession,
    mailbox: SettlementsMailbox,
    message: dict[str, Any],
    *,
    state: portal_settings.PortalSettings,
    today: date,
    now: datetime,
) -> Optional[int]:
    """Akceptacja klienta do naszego maila z Wysłanych: plik z naszego maila i ``.eml``
    odpowiedzi u osoby z tematu naszego maila (jedna osoba albo nikt). ``None`` = to nie
    odpowiedź na nasz mail z osobą albo nie akceptacja; zwykła ścieżka decyduje dalej.

    Obcy adres nie wskazuje osoby swoim tematem: osobę daje tylko temat, który napisaliśmy
    my, i tylko dla domeny, do której ten mail poszedł."""

    from app.services.client_settlements import client_acceptance, mail_text

    find = getattr(mailbox, "sent_messages", None)
    fetch = getattr(mailbox, "mime", None)
    if find is None or fetch is None:
        return None
    received = _parse_time(message.get("receivedDateTime")) or now
    try:
        sent = await find(received - REPLY_WINDOW)
        ours = _answered_mail(message, sent, received=received)
        if ours is None:
            return None
        our_subject = str(ours.get("subject") or "")
        contract = await identity.resolve_named_in_text(db, our_subject, today=today)
        if contract is None:
            # „Potwierdzenie godzin R.Nazwisko” (Bosch, próba IX–X 2026): sam inicjał
            # imienia, więc osoba tylko wśród kontraktów klienta z domeny odpowiedzi.
            contract = await identity.resolve_named_for_clients(
                db,
                our_subject,
                await identity.client_ids_for_sender(db, _sender(message)),
                settings=state,
                today=today,
            )
        if contract is None:
            return None
        raw = await fetch(str(message["id"]))
        mail = mail_text.read(raw or b"", mail_text.EML)
        if mail is None or not client_acceptance.accepts(_client_part(mail.body)):
            return None
        files = await mailbox.attachments(str(ours["id"]))
    except (GraphRequestError, AppOnlyTokenUnavailable) as exc:
        logger.info("rozliczenia@: Wysłane pominięte (%s)", type(exc).__name__)
        return None
    sent_on = (_parse_time(ours.get("sentDateTime")) or received).date()
    created = 0
    for attachment in files:
        if not _is_document(attachment):
            continue
        data = attachment.get("contentBytes")
        if not isinstance(data, str):
            continue
        try:
            content = base64.b64decode(data, validate=True)
        except ValueError:
            continue
        name = str(attachment.get("name") or "")
        kind = await asyncio.to_thread(kind_of_file, our_subject, name, content)
        created += await _store_found(
            db,
            contract_id=contract.id,
            kind=kind,
            period=period_for(our_subject, name, sent_on),
            content=content,
            file_name=name or None,
            message_id=str(ours["id"]),
            sender=_sender(ours),
            now=now,
        )
    created += await _store_found(
        db,
        contract_id=contract.id,
        kind="report",
        period=period_for(our_subject, "", sent_on),
        content=raw or b"",
        file_name=(str(message.get("subject") or "").strip()[:120] or "akceptacja")
        + ".eml",
        message_id=str(message["id"]),
        sender=_sender(message),
        now=now,
    )
    return created


async def _store_found(
    db: AsyncSession,
    *,
    contract_id: int,
    kind: str,
    period: tuple[int, int, bool],
    content: bytes,
    file_name: Optional[str],
    message_id: str,
    sender: str,
    now: datetime,
) -> int:
    year, month, guessed = period
    try:
        stored = await documents.store(
            db,
            contract_id=contract_id,
            kind=kind,
            year=year,
            month=month,
            content=content,
            file_name=file_name,
            channel="mailbox",
            now=now,
            period_guessed=guessed,
            graph_message_id=message_id[:512],
            sender_email=sender[:320] or None,
        )
    except PortalError:
        return 0
    return 0 if stored.duplicate else 1


def is_body_only_settlement(message: dict[str, Any]) -> bool:
    """Mail bez pliku, w którym akceptacja godzin stoi w treści (próba IX–X 2026).

    Tylko z adresu firmy (koordynator, skrzynka firmowa konsultanta), bo temat i treść
    może napisać każdy, i tylko z tematem rozliczenia. Router dalej oddaje taki mail
    czytnikowi spraw (decyzja Artura z 23.11.2026): jest i sprawą, i dokumentem.
    """

    if message.get("hasAttachments"):
        return False
    subject = str(message.get("subject") or "")
    if kesu.parse_jira(subject, "") is not None:
        return False
    return identity.is_company_address(_sender(message)) and bool(
        _BODY_SUBJECT.search(subject)
    )


def is_body_only_declaration(message: dict[str, Any]) -> bool:
    """Mail bez pliku z adresu firmy z tematem faktury („Faktura wrzesień”): u klienta
    z regułą ``report.consultant_declaration`` treść niesie deklarację dni pracy
    („We wrześniu nie miałam dni wolnych”). Klienta sprawdza ``_store_declaration``.
    Jak przy ``is_body_only_settlement`` mail zostaje też sprawą."""

    if message.get("hasAttachments") or is_body_only_settlement(message):
        return False
    subject = str(message.get("subject") or "")
    if kesu.parse_jira(subject, "") is not None:
        return False
    return identity.is_company_address(_sender(message)) and bool(
        _INVOICE.search(subject)
    )


async def _store_declaration(
    db: AsyncSession,
    mailbox: SettlementsMailbox,
    message: dict[str, Any],
    declaring: frozenset[int],
    *,
    state: portal_settings.PortalSettings,
    today: date,
    now: datetime,
) -> int:
    """Treść maila jako ``.eml`` osoby, tylko gdy nadawcą jest sam konsultant,
    a jego klient ma regułę deklaracji. Osoby z tematu nie bierzemy: deklaracja
    od koordynatora o kimś innym nie jest deklaracją konsultanta."""

    contract = await identity.resolve_sender(
        db, _sender(message), settings=state, today=today
    )
    if contract is None or contract.client_id not in declaring:
        return 0
    subject = str(message.get("subject") or "")
    received = _parse_time(message.get("receivedDateTime")) or now
    return await _store_eml(
        db, mailbox, message, contract.id, subject=subject, received=received, now=now
    )


async def _store_body_only(
    db: AsyncSession,
    mailbox: SettlementsMailbox,
    message: dict[str, Any],
    *,
    state: portal_settings.PortalSettings,
    today: date,
    now: datetime,
) -> int:
    """Treść maila bez pliku jako ``.eml`` osoby: nadawca (skrzynka firmowa konsultanta)
    albo jedna osoba z tematu. Dwie różne osoby albo nikt = nic nie zapisujemy, bo
    dokument bez osoby z samej treści byłby dla Finansów pustą kartą."""

    sender = _sender(message)
    subject = str(message.get("subject") or "")
    by_sender = await identity.resolve_sender(db, sender, settings=state, today=today)
    if by_sender is None and not state.any_sender:
        return 0
    named = await identity.resolve_named_in_text(db, subject, today=today)
    if (
        by_sender is not None
        and named is not None
        and (named.candidate_id != by_sender.candidate_id)
    ):
        return 0
    contract = by_sender or named
    if contract is None:
        return 0
    received = _parse_time(message.get("receivedDateTime")) or now
    return await _store_eml(
        db, mailbox, message, contract.id, subject=subject, received=received, now=now
    )


async def _store_eml(
    db: AsyncSession,
    mailbox: SettlementsMailbox,
    message: dict[str, Any],
    contract_id: Optional[int],
    *,
    subject: str,
    received: datetime,
    now: datetime,
    content: Optional[bytes] = None,
) -> int:
    """Cały mail jako ``.eml``; ``content`` = MIME już pobrany (bez drugiego zapytania)."""

    fetch = getattr(mailbox, "mime", None)
    if fetch is None and content is None:
        return 0
    year, month, guessed = period_for(subject, "", received.date())
    try:
        if content is None:
            content = await fetch(str(message["id"]))
        if not content:
            return 0
        stored = await documents.store(
            db,
            contract_id=contract_id,
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
        # Licznik i porzucone zostają obok kodu błędu: inaczej po awarii Graph
        # porzucony mail wracałby w ``OVERLAP`` i dostawał drugą kartę.
        kept = _failing_state(*_failing_message(current))
        error = f"{code};{kept}" if kept else code
        await _write_state(db, now=moment, status="error", error=error)
        return {"status": "error", "reason": code}
    created = skipped = failed = abandoned = 0
    newest = seen
    failing_key, failing_count, abandoned_keys = _failing_message(current)
    # Porzucone, które już wyszły z zakładki ``OVERLAP``, nie wrócą: nie trzymamy ich.
    listed = {_message_key(m) for m in messages}
    abandoned_keys = [k for k in abandoned_keys if k in listed]
    acceptance = await support_mail_route.acceptance_clients(db)
    declaring = await support_mail_route.declaration_clients(db)
    for message in messages:
        if (
            route
            and not support_mail_route.is_settlements_mail(message, route)
            and not support_mail_route.is_client_acceptance_mail(
                message, route, acceptance.keys()
            )
            and not (
                support_mail_route.recipients(message) & route
                and (
                    is_body_only_settlement(message)
                    or (declaring and is_body_only_declaration(message))
                    or (state.any_sender and is_reply_to_sent(message))
                )
            )
        ):
            # Sprawa dla czytnika spraw: znacznik idzie dalej, nic nie zapisujemy.
            received = _parse_time(message.get("receivedDateTime"))
            if received and (newest is None or received > newest):
                newest = received
            continue
        key = _message_key(message)
        if key in abandoned_keys:
            # Porzucona w poprzednim biegu (alarm i karta poszły), a wraca w zakładce
            # ``OVERLAP``: nie czytamy jej znowu, bo zablokowałaby nowsze maile.
            # Lista porzuconych jest osobno od licznika, bo inny padający mail
            # nadpisywał licznik i porzucony wracał w kółko (przegląd PR #3953).
            received = _parse_time(message.get("receivedDateTime"))
            if received and (newest is None or received > newest):
                newest = received
            continue
        try:
            async with db.begin_nested():
                made, ignored = await _ingest_message(
                    db,
                    reader,
                    message,
                    state=state,
                    today=today,
                    now=moment,
                    acceptance=acceptance,
                    declaring=declaring,
                )
            created += made
            skipped += ignored
            if key == failing_key:
                failing_key, failing_count = None, 0
        except Exception as exc:  # noqa: BLE001 — jedna wiadomość nie zatrzymuje reszty
            if not _transient(exc):
                failing_count = (failing_count if key == failing_key else 0) + 1
                failing_key = key
            attempts = failing_count if key == failing_key else 0
            if attempts < MAX_MESSAGE_ATTEMPTS:
                failed += 1
                logger.warning(
                    "consultant_portal_mailbox: message failed (%s), attempt %d/%d",
                    type(exc).__name__,
                    attempts,
                    MAX_MESSAGE_ATTEMPTS,
                )
                # Znacznik nie idzie poza pierwszą porażkę: spróbujemy jej ponownie.
                break
            # Ten sam mail pada bieg po biegu: znacznik idzie dalej, żeby jeden mail
            # nie zatrzymał czytnika na zawsze. Alarm (Sentry z logu ERROR) i karta
            # z całym mailem do ręcznego przypisania, żeby nie przepadł bez śladu.
            abandoned += 1
            logger.error(
                "consultant_portal_mailbox: message abandoned after %d attempts (%s)",
                attempts,
                type(exc).__name__,
            )
            created += await _store_abandoned(
                db, reader, message, state=state, now=moment
            )
            abandoned_keys = (abandoned_keys + [key])[-MAX_ABANDONED_KEYS:]
            failing_key, failing_count = None, 0
        received = _parse_time(message.get("receivedDateTime"))
        if received and (newest is None or received > newest):
            newest = received
    run_status = "partial" if failed or abandoned else "ok"
    await _write_state(
        db,
        now=moment,
        status=run_status,
        error=_failing_state(failing_key, failing_count, abandoned_keys),
        seen=newest,
    )
    return {
        "status": run_status,
        "messages": len(messages),
        "created": created,
        "skipped": skipped,
        "failed": failed,
        "abandoned": abandoned,
    }


#: Tyle biegów z rzędu (co 15 min) ten sam mail może zatrzymywać znacznik. Awaria
#: Graph albo bazy (``_transient``) się nie liczy: po niej mail czyta się normalnie.
MAX_MESSAGE_ATTEMPTS = 5
#: Licznik porażek trzymamy w ``last_error`` (bez migracji): skrót id maila i liczba.
_FAILING_PREFIX = "message_failed:"
#: Obok, po ``;``, skróty porzuconych maili, które jeszcze wracają w ``OVERLAP``.
_ABANDONED_PREFIX = "message_abandoned:"
#: Tyle porzuconych naraz mieści ``last_error`` (``String(200)``) obok licznika.
MAX_ABANDONED_KEYS = 8


def _message_key(message: dict[str, Any]) -> str:
    """Skrót id maila z Graph: krótki i bez treści maila w stanie czytnika."""

    return hashlib.sha256(str(message.get("id") or "").encode()).hexdigest()[:16]


def _failing_message(
    state: Optional[CpMailboxState],
) -> tuple[Optional[str], int, list[str]]:
    """Mail, który teraz pada (skrót i liczba biegów), i lista porzuconych."""

    error = state.last_error if state else None
    key: Optional[str] = None
    count = 0
    abandoned: list[str] = []
    for part in (error or "").split(";"):
        if part.startswith(_FAILING_PREFIX):
            raw_key, _, raw_count = part[len(_FAILING_PREFIX) :].partition(":")
            key = raw_key or None
            count = int(raw_count) if raw_count.isdigit() else 0
        elif part.startswith(_ABANDONED_PREFIX):
            abandoned = [k for k in part[len(_ABANDONED_PREFIX) :].split(",") if k]
    return key, count, abandoned


def _failing_state(
    key: Optional[str], count: int, abandoned: list[str]
) -> Optional[str]:
    parts = []
    if key:
        parts.append(f"{_FAILING_PREFIX}{key}:{count}")
    if abandoned:
        parts.append(_ABANDONED_PREFIX + ",".join(abandoned[-MAX_ABANDONED_KEYS:]))
    return ";".join(parts) or None


def _transient(exc: Exception) -> bool:
    """Awaria po stronie Graph albo połączenia z bazą, nie wina samego maila."""

    if isinstance(exc, GraphRequestError):
        return exc.status == 429 or exc.status >= 500
    return isinstance(
        exc,
        (
            AppOnlyTokenUnavailable,
            OperationalError,
            InterfaceError,
            TimeoutError,
            httpx.TransportError,
        ),
    )


async def _store_abandoned(
    db: AsyncSession,
    mailbox: SettlementsMailbox,
    message: dict[str, Any],
    *,
    state: portal_settings.PortalSettings,
    now: datetime,
) -> int:
    """Porzucony mail jako ``.eml`` bez kontraktu: karta do ręcznego przypisania.
    W pilotażu kart bez osoby nie robimy (jak przy nieznanym nadawcy), zostaje alarm."""

    if not state.any_sender:
        return 0
    try:
        async with db.begin_nested():
            return await _store_eml(
                db,
                mailbox,
                message,
                None,
                subject=str(message.get("subject") or ""),
                received=_parse_time(message.get("receivedDateTime")) or now,
                now=now,
            )
    except Exception as exc:  # noqa: BLE001 — karta nie może znowu zatrzymać czytnika
        logger.warning(
            "consultant_portal_mailbox: card for abandoned message failed (%s)",
            type(exc).__name__,
        )
        return 0


async def status(db: AsyncSession) -> dict[str, Any]:
    row = await db.scalar(select(CpMailboxState).where(CpMailboxState.id == 1))
    return {
        "configured": mailbox_upn() is not None,
        "last_run_at": row.last_run_at.isoformat() if row and row.last_run_at else None,
        "last_status": row.last_status if row else None,
        "last_error": _public_error(row.last_error) if row else None,
    }


def _public_error(error: Optional[str]) -> Optional[str]:
    """Kod błędu dla ekranu bez wewnętrznego licznika porażek i porzuconych maili."""

    parts = [
        part
        for part in (error or "").split(";")
        if part and not part.startswith((_FAILING_PREFIX, _ABANDONED_PREFIX))
    ]
    return ";".join(parts) or None
