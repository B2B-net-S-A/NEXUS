"""Mail akceptacji (``.msg`` z Outlooka, ``.eml``): odczyt, HTML i kontrola treści.

Roadmapa E6.1 (PKO). Klient przyjmuje akceptację wyłącznie jako HTML, więc
NEXUS składa plik HTML z nagłówków i treści maila. Treść HTML z maila nie
przechodzi dalej: piszemy własny dokument z tekstu (bez skryptów, obrazków
i stylów nadawcy), a pobranie zawsze idzie jako załącznik.

Kontrola ``proof.accept_has_hours`` (instrukcja PKO z 13.11.2026 i odpowiedzi
z 12.11): w treści wątku musi być liczba godzin albo MD i rozliczany miesiąc,
a ktoś musi ją zaakceptować. Liczba bywa tylko w cytowanej prośbie, a odpowiedź
to „Potwierdzam godziny za miesiąc październik”, dlatego czytamy cały wątek.
Prośby nadpisywane co miesiąc: liczy się akceptacja za rozliczany miesiąc.
Akceptować może ktoś inny niż koordynator, ale zawsze ktoś od klienta: słowo
akceptacji liczy się tylko w wiadomości z domeny klienta, samej albo zacytowanej
w wątku (przegląd skrzynek Finansów z 23.11.2026: wewnętrzne zestawienie
„Zaakceptowane godziny … 160 h” z adresu firmy wyglądało jak akceptacja).

Bez bazy. ``.msg`` czyta ``olefile`` (kontener OLE, bez uruchamiania czegokolwiek).
"""

from __future__ import annotations

import email
import email.policy
import io
import logging
import re
import struct
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from email.message import EmailMessage
from html import escape, unescape
from typing import Optional

from app.core.mime_attachments import attachment_parts

logger = logging.getLogger(__name__)

MSG = "application/vnd.ms-outlook"
EML = "message/rfc822"
MAIL_MIMES = (MSG, EML)
#: Treść maila do kontroli i HTML; dłuższe wątki ucinamy (stopki, historia).
MAX_TEXT = 200_000
#: Załączniki z maila do rozpoznania (arkusz od klienta w przekazanym mailu).
MAX_ATTACHMENTS = 20
#: Mail w mailu: ile poziomów załączonych maili czytamy (plik z zewnątrz).
MAX_NESTED = 2
OLE_HEADER = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

MONTHS_NOMINATIVE = (
    "styczeń",
    "luty",
    "marzec",
    "kwiecień",
    "maj",
    "czerwiec",
    "lipiec",
    "sierpień",
    "wrzesień",
    "październik",
    "listopad",
    "grudzień",
)
#: Rdzenie nazw miesięcy we wszystkich przypadkach („październiku”, „lipca”).
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
_MONTH_WORD = re.compile(
    r"(?<![\w])(" + "|".join(f"(?:{s})" for s in _MONTH_STEMS) + r")\w*"
    r"(?:\s+(20\d{2}))?",
    re.IGNORECASE,
)
_MONTH_NUMERIC = re.compile(r"(?<![\d./-])(0?[1-9]|1[0-2])\s*[./-]\s*(20\d{2})(?![\d])")
_MONTH_ISO = re.compile(r"(?<![\d])(20\d{2})-(0[1-9]|1[0-2])(?![\d-])")
_NUMBER = r"(\d{1,3}(?:[.,]\d{1,3})?)"
_HOURS = (
    re.compile(_NUMBER + r"\s*(?:h\b|godz)", re.IGNORECASE),
    re.compile(r"godzin\w*[^\d\n]{0,60}?" + _NUMBER + r"(?![\d.,:]*\d)", re.IGNORECASE),
)
_MD = re.compile(_NUMBER + r"\s*(?:md\b|man[- ]?days?|osobodni)", re.IGNORECASE)
#: Akceptacja managera po angielsku (Nordea, T4T): „please approve the 102 hours”,
#: „October 2026”. Tylko na żądanie, żeby nie zmieniać kontroli PKO i BIK.
_HOURS_EN = re.compile(_NUMBER + r"\s*(?:hours?|hrs?)\b", re.IGNORECASE)
MONTHS_EN = (
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)
_MONTH_EN = re.compile(
    r"(?<![\w])(" + "|".join(MONTHS_EN) + r")(?![\w])(?:\s+(20\d{2}))?",
    re.IGNORECASE,
)
#: Pierwsza osoba: „Proszę o potwierdzenie” to prośba, „Potwierdzam” to akceptacja.
_APPROVED = re.compile(
    r"\b(potwierdzam|akceptuj[eę]|zatwierdzam|zaakceptowa(?:łem|łam|no|ne)|"
    r"approved?|accepted|confirmed?)\b",
    re.IGNORECASE,
)
#: Linie nagłówków w cytowanym wątku: daty wysłania to nie miesiąc rozliczenia.
_HEADER_LINE = re.compile(
    r"^\s*(?:data|date|sent|wysłano|wysłane|od|from|do|to|dw|cc|temat|subject)\s*:",
    re.IGNORECASE,
)
#: Początek zacytowanej wiadomości: „From:”/„Od:” z nadawcą (Outlook, Gmail, wydruk).
_QUOTED_FROM = re.compile(
    r"^\s*>?\s*\*?(?:from|od|nadawca)\s*:\s*\*?\s*(.+)$", re.IGNORECASE
)
_ADDRESS = re.compile(r"[\w.+'-]+@([\w-]+(?:\.[\w-]+)+)")


@dataclass
class Mail:
    subject: str = ""
    sender: str = ""
    to: str = ""
    cc: str = ""
    sent_at: Optional[datetime] = None
    body: str = ""
    attachments: list[tuple[str, bytes]] = field(default_factory=list)
    #: Maile załączone do tego maila, już odczytane. Konsultant dołącza akceptację
    #: klienta jako plik ``.msg`` albo ``.eml`` (PKO, próba IX–X 2026).
    attached: list["Mail"] = field(default_factory=list)

    @property
    def text(self) -> str:
        return f"{self.subject}\n{self.body}"


def thread(mail: "Mail") -> list["Mail"]:
    """Mail i wszystkie maile do niego załączone, najpierw zewnętrzny."""

    found = [mail]
    for inner in mail.attached:
        found.extend(thread(inner))
    return found


def _attached_mail(name: str, data: bytes, depth: int) -> Optional["Mail"]:
    """Załącznik, który sam jest mailem: ``.msg`` z Outlooka albo ``.eml``."""

    if depth >= MAX_NESTED:
        return None
    lowered = name.lower()
    try:
        if lowered.endswith(".msg") and data.startswith(OLE_HEADER):
            return _read_msg(data, depth + 1)
        if lowered.endswith(".eml"):
            return _read_eml(data, depth + 1)
    except Exception as exc:  # noqa: BLE001 — zły załącznik nie psuje maila
        logger.info("mail_text: załączony mail nieczytelny (%s)", type(exc).__name__)
    return None


def _attached_part(part: EmailMessage, depth: int) -> Optional["Mail"]:
    """Część ``message/rfc822``: mail w środku jako osobny mail."""

    inner = part.get_payload(0) if part.is_multipart() else None
    if inner is None:
        return None
    try:
        raw = inner.as_bytes()
    except (ValueError, TypeError, LookupError) as exc:
        logger.info("mail_text: załączony mail nieczytelny (%s)", type(exc).__name__)
        return None
    return _attached_mail("zalacznik.eml", raw, depth)


# ── Odczyt ───────────────────────────────────────────────────────────────────


def _filetime(raw: bytes) -> Optional[datetime]:
    try:
        (value,) = struct.unpack("<Q", raw[:8])
    except struct.error:
        return None
    if value == 0:
        return None
    # dzień UTC celowo: FILETIME z Outlooka liczy od 1601-01-01 w UTC.
    return datetime(1601, 1, 1, tzinfo=timezone.utc) + timedelta(
        microseconds=value // 10
    )


def _read_msg(content: bytes, depth: int = 0) -> Optional[Mail]:
    import olefile

    try:
        ole = olefile.OleFileIO(io.BytesIO(content))
    except (OSError, ValueError):
        return None
    try:

        def stream(path: str) -> Optional[bytes]:
            try:
                return ole.openstream(path).read() if ole.exists(path) else None
            except OSError:
                return None

        def prop(tag: str, root: str = "") -> str:
            unicode = stream(f"{root}__substg1.0_{tag}001F")
            if unicode is not None:
                return unicode.decode("utf-16-le", "replace").rstrip("\x00")
            legacy = stream(f"{root}__substg1.0_{tag}001E")
            if legacy is not None:
                return legacy.decode("cp1250", "replace").rstrip("\x00")
            return ""

        mail = Mail(
            subject=prop("0037"),
            sender=_sender(prop("0C1A"), prop("5D01") or prop("0C1F") or prop("0065")),
            to=prop("0E04"),
            cc=prop("0E03"),
            body=prop("1000")[:MAX_TEXT],
        )
        properties = stream("__properties_version1.0") or b""
        # Nagłówek wiadomości ma 32 bajty, potem wpisy po 16: znacznik, flagi, wartość.
        for offset in range(32, len(properties) - 15, 16):
            tag = struct.unpack("<I", properties[offset : offset + 4])[0]
            if tag in (0x00390040, 0x0E060040):  # czas wysłania, czas doręczenia
                found = _filetime(properties[offset + 8 : offset + 16])
                if found is not None and (mail.sent_at is None or tag == 0x00390040):
                    mail.sent_at = found
        roots = sorted(
            {entry[0] for entry in ole.listdir() if entry[0].startswith("__attach")}
        )
        for root in roots[:MAX_ATTACHMENTS]:
            data = stream(f"{root}/__substg1.0_37010102")
            name = prop("3707", f"{root}/") or prop("3704", f"{root}/")
            if data:
                mail.attachments.append((name or "zalacznik", data))
    finally:
        ole.close()
    for name, data in mail.attachments:
        inner = _attached_mail(name, data, depth)
        if inner is not None:
            mail.attached.append(inner)
    return mail


def _sender(name: str, address: str) -> str:
    address = address if "@" in address else ""
    if name and address and address.lower() not in name.lower():
        return f"{name} <{address}>"
    return name or address


def _html_to_text(html: str) -> str:
    text = re.sub(r"(?is)<(style|script|head)\b.*?</\1>", " ", html)
    text = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</h\d>|</li>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text).replace("\xa0", " ")
    return re.sub(r"[ \t]+", " ", text)


def _read_eml(content: bytes, depth: int = 0) -> Optional[Mail]:
    try:
        message = email.message_from_bytes(content, policy=email.policy.default)
    except (ValueError, TypeError, LookupError):
        return None
    mail = Mail(
        subject=str(message.get("subject") or ""),
        sender=str(message.get("from") or ""),
        to=str(message.get("to") or ""),
        cc=str(message.get("cc") or ""),
    )
    try:
        mail.sent_at = message["date"].datetime if message["date"] else None
    except (AttributeError, TypeError, ValueError):
        mail.sent_at = None
    try:
        part = message.get_body(preferencelist=("plain", "html"))
        if part is not None:
            body = part.get_content()
            mail.body = (
                _html_to_text(body) if part.get_content_subtype() == "html" else body
            )[:MAX_TEXT]
        for attachment in attachment_parts(message)[:MAX_ATTACHMENTS]:
            if attachment.get_content_type() == "message/rfc822":
                # Mail dołączony jako element (Outlook „Załącz element”).
                found = _attached_part(attachment, depth)
                if found is not None:
                    mail.attached.append(found)
                continue
            data = attachment.get_payload(decode=True)
            if isinstance(data, bytes) and data:
                name = attachment.get_filename() or "zalacznik"
                mail.attachments.append((name, data))
                found = _attached_mail(name, data, depth)
                if found is not None:
                    mail.attached.append(found)
    except (KeyError, LookupError, ValueError, TypeError) as exc:
        logger.info("mail_text: część maila nieczytelna (%s)", type(exc).__name__)
    return mail


def read(content: bytes, mime: str) -> Optional[Mail]:
    """Mail z pliku; ``None``, gdy plik nie jest mailem albo jest uszkodzony."""

    try:
        if mime == MSG:
            return _read_msg(content)
        if mime == EML:
            return _read_eml(content)
    except Exception as exc:  # noqa: BLE001 — uszkodzony plik nie blokuje przyjęcia
        logger.info("mail_text: odczyt nie wyszedł (%s)", type(exc).__name__)
    return None


# ── HTML dla klienta ─────────────────────────────────────────────────────────


def to_html(mail: Mail) -> str:
    """Akceptacja jako samodzielny plik HTML: nagłówki i treść, bez treści HTML nadawcy."""

    when = mail.sent_at.astimezone().strftime("%d.%m.%Y %H:%M") if mail.sent_at else ""
    headers = [
        ("Od", mail.sender),
        ("Do", mail.to),
        ("DW", mail.cc),
        ("Data", when),
        ("Temat", mail.subject),
    ]
    rows = "".join(
        f"<tr><th>{escape(label)}:</th><td>{escape(value)}</td></tr>"
        for label, value in headers
        if value
    )
    paragraphs = "".join(
        f"<p>{escape(block).replace(chr(10), '<br>')}</p>"
        for block in re.split(r"\n\s*\n", mail.body.replace("\r\n", "\n").strip())
        if block.strip()
    )
    return (
        "<!DOCTYPE html><html lang='pl'><head><meta charset='utf-8'>"
        f"<title>{escape(mail.subject or 'Akceptacja')}</title><style>"
        "body{font-family:Calibri,Arial,sans-serif;font-size:11pt;color:#111;margin:24px}"
        "table{border-collapse:collapse;margin-bottom:12px}"
        "th{text-align:left;padding:2px 10px 2px 0;color:#444;font-weight:600;vertical-align:top}"
        "td{padding:2px 0}p{margin:0 0 10px}"
        "</style></head><body>"
        f"<table>{rows}</table><hr>{paragraphs}</body></html>"
    )


def html_name(mail: Mail, fallback: str) -> str:
    base = re.sub(r"[^\w.-]+", "_", mail.subject or fallback, flags=re.UNICODE)
    return (base.strip("_")[:120] or "akceptacja") + ".html"


# ── Kontrola akceptacji ──────────────────────────────────────────────────────


def _dec(raw: str) -> Optional[Decimal]:
    try:
        return Decimal(raw.replace(",", "."))
    except InvalidOperation:
        return None


def _month_index(word: str) -> Optional[int]:
    lowered = word.lower()
    for index, stem in enumerate(_MONTH_STEMS):
        if re.match(stem, lowered):
            return index + 1
    return None


@dataclass(frozen=True)
class Acceptance:
    hours: tuple[Decimal, ...]
    md: tuple[Decimal, ...]
    #: Miesiące z treści (``RRRR-MM``); nazwa bez roku bierze rok rozliczenia.
    months: frozenset[str]
    approved: bool


def read_acceptance(text: str, month: str, *, english: bool = False) -> Acceptance:
    year = int(month.split("-")[0])
    lines = [line for line in text.splitlines() if not _HEADER_LINE.match(line)]
    body = "\n".join(lines)
    months: set[str] = set()
    for match in _MONTH_NUMERIC.finditer(body):
        months.add(f"{match.group(2)}-{int(match.group(1)):02d}")
    for match in _MONTH_ISO.finditer(body):
        months.add(f"{match.group(1)}-{match.group(2)}")
    for match in _MONTH_WORD.finditer(body):
        index = _month_index(match.group(1))
        if index is None or match.group(1).lower() == "mar" and not match.group(2):
            continue  # „mar” bez roku to zwykle inne słowo
        months.add(f"{match.group(2) or year}-{index:02d}")
    if english:
        for match in _MONTH_EN.finditer(body):
            # „may” bez roku to zwykle czasownik.
            if match.group(1).lower() == "may" and not match.group(2):
                continue
            index = MONTHS_EN.index(match.group(1).lower()) + 1
            months.add(f"{match.group(2) or year}-{index:02d}")
    patterns = (*_HOURS, _HOURS_EN) if english else _HOURS
    hours = tuple(
        value
        for pattern in patterns
        for found in pattern.finditer(body)
        if (value := _dec(found.group(1))) is not None and 0 < value <= 400
    )
    md = tuple(
        value
        for found in _MD.finditer(body)
        if (value := _dec(found.group(1))) is not None and 0 < value <= 31
    )
    return Acceptance(
        hours=hours,
        md=md,
        months=frozenset(months),
        approved=bool(_APPROVED.search(body)),
    )


@dataclass(frozen=True)
class Verdict:
    ok: bool
    title: str
    detail: Optional[str] = None
    #: Adresy akceptujących u klienta z prośby bez odpowiedzi („Do:”, „DW:”),
    #: dla informacji zwrotnej (``client_settlements/feedback``).
    acceptors: tuple[str, ...] = ()


@dataclass(frozen=True)
class Senders:
    """Kto może zaakceptować: domeny klienta i domeny firmy (rozliczenia@, SSO).

    Klient bez znanych domen (brak kontaktów i domeny w regułach): akceptuje
    każdy adres spoza domen firmy. Nadawca bez adresu nie akceptuje nigdy.

    Projekt FIX (``Contract.engagement_model == fixed``): ``client`` to domeny
    firmy, a ``who`` nazywa akceptującego w uwagach („PM-a firmy”).

    ``consultant``: adresy samego konsultanta kontraktu
    (``service._without_consultant``). Jego skrzynka u klienta bywa w domenie
    klienta, tej samej co kierownika, ale on sam swoich godzin nie akceptuje."""

    client: frozenset[str] = frozenset()
    own: frozenset[str] = frozenset()
    who: str = "klienta"
    #: Imiona i nazwiska osób klienta (kontakty klienta w NEXUS-ie): nadawca
    #: zrzutu ekranu akceptacji, na którym nie widać adresu (``judge_screenshot``).
    people: frozenset[str] = frozenset()
    consultant: frozenset[str] = frozenset()

    def is_consultant(self, address: Optional[str]) -> bool:
        match = _ADDRESS.search(address or "")
        return match is not None and match.group(0).lower() in self.consultant

    def accepts_from(self, address: Optional[str]) -> bool:
        match = _ADDRESS.search(address or "")
        if match is None or match.group(0).lower() in self.consultant:
            return False
        domain = match.group(1).lower()
        if self.client:
            return domain in self.client  # dokładnie, bez poddomen (BNP ``external.``)
        return domain not in self.own


def _messages(mail: Mail) -> list[tuple[Optional[str], str]]:
    """Wiadomości wątku: nadawca i tekst. Pierwsza to sam mail (z tematem),
    kolejne zaczynają się od „From:”/„Od:” z adresem w treści. Linia „Od: 01.10
    do 31.10” bez adresu to zdanie tej samej wiadomości, nie nagłówek cytatu."""

    found: list[tuple[Optional[str], list[str]]] = [(mail.sender, [mail.subject])]
    for line in mail.body.splitlines():
        head = _QUOTED_FROM.match(line)
        if head and _ADDRESS.search(head.group(1)):
            found.append((head.group(1), []))
            continue
        found[-1][1].append(line)
    return [(sender, "\n".join(lines)) for sender, lines in found]


def _approved_by(mail: Mail, senders: Senders, *, consultant: bool = False) -> bool:
    """Słowo akceptacji w wiadomości akceptującego; ``consultant``: samego konsultanta."""

    for sender, text in _messages(mail):
        lines = [line for line in text.splitlines() if not _HEADER_LINE.match(line)]
        who = (
            senders.is_consultant(sender)
            if consultant
            else senders.accepts_from(sender)
        )
        if who and _APPROVED.search("\n".join(lines)):
            return True
    return False


def addresses(mails: list[Mail]) -> set[str]:
    """Adresy nadawców wszystkich wiadomości: sam mail i cytaty „From:” z adresem."""

    return {
        match.group(0).lower()
        for mail in mails
        for sender, _text in _messages(mail)
        if (match := _ADDRESS.search(sender or "")) is not None
    }


#: „Do:”/„DW:” w cytowanej prośbie (Outlook i Gmail, po polsku i po angielsku).
_RECIPIENT_LINE = re.compile(
    r"^\s*>?\s*\*?(?:to|do|cc|dw|kopia)\s*:\s*\*?(.+)$", re.IGNORECASE
)


def request_recipients(mail: Mail, senders: Senders) -> tuple[str, ...]:
    """Adresaci prośby o akceptację, którzy mogą ją zaakceptować (domena klienta,
    bez konsultanta): nagłówki maila i linie „Do:”/„DW:” cytowanego wątku."""

    raw = [mail.to, mail.cc]
    raw.extend(
        head.group(1)
        for line in mail.body.splitlines()
        if (head := _RECIPIENT_LINE.match(line)) is not None
    )
    out: list[str] = []
    for text in raw:
        for match in _ADDRESS.finditer(text or ""):
            address = match.group(0).lower()
            if address not in out and senders.accepts_from(address):
                out.append(address)
    return tuple(out)


def approved(mails: list[Mail], senders: Senders) -> bool:
    """Słowo akceptacji w którejś wiadomości od akceptującego (``senders``)."""

    return any(_approved_by(mail, senders) for mail in mails)


def _fmt(value: Decimal) -> str:
    return f"{value.normalize():f}".replace(".", ",")


def month_label(month: str) -> str:
    year, mon = (int(x) for x in month.split("-"))
    return f"{MONTHS_NOMINATIVE[mon - 1]} {year}"


#: Pierwsze słowo linii listy adresatów na zrzucie Outlooka („Do”, „DW”).
_RECIPIENT_LABELS = frozenset({"do", "to", "dw", "cc", "udw", "bcc"})


def _folded_words(text: str) -> list[str]:
    raw = unicodedata.normalize("NFKD", text.replace("ł", "l").replace("Ł", "L"))
    return re.findall(r"[a-z]+", raw.encode("ascii", "ignore").decode().lower())


def sender_on_screen(text: str, people: frozenset[str]) -> bool:
    """Ktoś z ``people`` w linii zrzutu, która nie jest listą adresatów: nadawca
    w nagłówku Outlooka albo podpis pod treścią. Śmieci OCR na początku linii
    („4zP Nowak Anna”) nie przeszkadzają; jednowyrazowa nazwa nie wystarcza."""

    names = [set(_folded_words(person)) for person in people]
    names = [name for name in names if len(name) >= 2]
    for line in text.splitlines():
        words = _folded_words(line)
        if not words or _RECIPIENT_LABELS & set(words[:3]):
            continue
        present = set(words)
        if any(name <= present for name in names):
            return True
    return False


def judge_screenshot(
    text: str,
    *,
    month: str,
    hours: Optional[Decimal],
    md: Optional[Decimal],
    people: frozenset[str],
) -> Optional[Verdict]:
    """Akceptacja z tekstu zrzutu ekranu (OCR), decyzja Artura z 24.11.2026:
    słowo akceptacji, rozliczany miesiąc, liczba godzin albo MD równa dowodowi
    i nadawca z ``people`` (koordynator z Time Sheet, kontakt klienta).
    Bez liczby zrzut nie wystarcza. ``None`` = zrzut nie jest akceptacją."""

    found = read_acceptance(text, month)
    if not found.approved or month not in found.months:
        return None
    if hours is not None and any(abs(h - hours) < Decimal("0.01") for h in found.hours):
        amount = f"{_fmt(hours)} h"
    elif md is not None and any(abs(m - md) < Decimal("0.01") for m in found.md):
        amount = f"{_fmt(md)} MD"
    else:
        return None
    if not sender_on_screen(text, people):
        return None
    return Verdict(
        True,
        f"Akceptacja ze zrzutu ekranu: {amount} za {month_label(month)}",
        "Odczyt OCR obrazu z maila. Nadawca: osoba klienta z Time Sheet albo "
        "z kontaktów klienta. Do paczki dla klienta idzie obraz.",
    )


def judge(
    mails: list[Mail],
    *,
    month: str,
    hours: Optional[Decimal],
    md: Optional[Decimal],
    senders: Senders,
    sheet_month: Optional[str] = None,
) -> Verdict:
    """Najlepsza akceptacja z maili miesiąca za ``month`` (godziny i MD z dowodu).

    Liczba i miesiąc mogą stać w dowolnej wiadomości wątku (zwykle w naszej
    prośbie), słowo akceptacji tylko w wiadomości od klienta (``senders``).

    Samo „Akceptuję” od klienta bez liczby wystarcza, gdy godziny są w Time Sheet
    za rozliczany miesiąc (``sheet_month``; decyzja Artura z 23.11.2026, PKO i BIK)."""

    if not mails:
        return Verdict(
            False,
            "Brak maila z akceptacją",
            "Dołącz mail akceptującego (MSG albo EML) z liczbą godzin za miesiąc.",
        )
    verdicts: list[Verdict] = []
    sheet_verdict: Optional[Verdict] = None
    for mail in mails:
        found = read_acceptance(mail.text, month)
        numbers = bool(found.hours or found.md)
        from_sheet = (hours is not None or md is not None) and sheet_month == month
        if (
            not numbers
            and from_sheet
            and found.approved
            and (not found.months or month in found.months)
            and _approved_by(mail, senders)
        ):
            # Zapas: akceptacja z liczbą w innym mailu miesiąca ma pierwszeństwo.
            proof = f"{_fmt(hours)} h" if hours is not None else f"{_fmt(md or 0)} MD"
            sheet_verdict = sheet_verdict or Verdict(
                True,
                "Akceptacja bez liczby, godziny z TS",
                f"Klient zaakceptował bez liczby godzin; w Time Sheet za "
                f"{month_label(month)}: {proof}.",
            )
            continue
        if not numbers:
            verdicts.append(
                Verdict(
                    False,
                    "Akceptacja bez liczby godzin lub MD",
                    "Mail do akceptującego musi mieć w treści liczbę godzin do akceptacji.",
                )
            )
            continue
        if month not in found.months:
            other = ", ".join(month_label(m) for m in sorted(found.months)) or None
            verdicts.append(
                Verdict(
                    False,
                    "Akceptacja za inny miesiąc"
                    if other
                    else "Akceptacja bez rozliczanego miesiąca",
                    f"W mailu: {other}." if other else "W mailu nie ma miesiąca.",
                )
            )
            continue
        if not found.approved:
            verdicts.append(
                Verdict(
                    False,
                    "Mail bez odpowiedzi akceptującego",
                    "Jest prośba o akceptację, ale nie ma potwierdzenia.",
                    acceptors=request_recipients(mail, senders),
                )
            )
            continue
        if not _approved_by(mail, senders):
            where = (
                f"z domeny {senders.who} (" + ", ".join(sorted(senders.client)) + ")"
                if senders.client
                else f"z adresu {senders.who}"
            )
            detail = (
                "Potwierdzenie w mailu napisał sam konsultant ze swojej skrzynki. "
                "Konsultant nie akceptuje własnych godzin, potrzebna jest "
                f"akceptacja {senders.who}."
                if _approved_by(mail, senders, consultant=True)
                else f"Potwierdzenie w mailu nie pochodzi {where}. Nasze zestawienie "
                f"albo przekazanie bez cytatu odpowiedzi {senders.who} nie jest "
                "akceptacją."
            )
            verdicts.append(Verdict(False, f"Brak akceptacji {senders.who}", detail))
            continue
        matches_hours = hours is not None and any(
            abs(h - hours) < Decimal("0.01") for h in found.hours
        )
        matches_md = md is not None and any(
            abs(m - md) < Decimal("0.01") for m in found.md
        )
        if (hours is not None or md is not None) and not (matches_hours or matches_md):
            said = (
                f"{_fmt(found.hours[0])} h"
                if found.hours
                else f"{_fmt(found.md[0])} MD"
            )
            proof = f"{_fmt(hours)} h" if hours is not None else f"{_fmt(md or 0)} MD"
            verdicts.append(
                Verdict(
                    False,
                    "Inna liczba godzin w akceptacji niż w Time Sheet",
                    f"W mailu {said}, w Time Sheet {proof}.",
                )
            )
            continue
        amount = (
            f"{_fmt(found.hours[0])} h" if found.hours else f"{_fmt(found.md[0])} MD"
        )
        return Verdict(True, f"Akceptacja: {amount} za {month_label(month)}")
    return sheet_verdict or verdicts[0]
