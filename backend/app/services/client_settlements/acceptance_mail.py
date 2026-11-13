"""Mail akceptujący przy RCP (roadmapa E2.3): nadawcy i daty wiadomości. Bez bazy.

Konsultant przysyła akceptację przełożonego zwykle jako przekazany dalej
łańcuch („FW: FW: TS …”), więc data samego pliku to data przekazania, a nie
zgody. Czytamy więc każdą wiadomość łańcucha: nagłówek pliku (``.eml``,
``.msg``) oraz bloki „From/Od … Sent/Wysłano/Data …” w treści i w wydruku PDF.
Kontrolę (data zgody przed pracą dodatkową, domena nadawcy) robi
``rcp_checks.evaluate``; tu tylko odczyt.

``.msg`` (Outlook) czyta ``olefile`` (BSD, decyzja Artura z 13.11.2026):
nadawca, nagłówki transportowe z datą i treść tekstowa wiadomości.
"""

from __future__ import annotations

import html
import io
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime
from email import policy
from email.parser import BytesParser
from email.utils import parseaddr, parsedate_to_datetime
from typing import Iterable, Optional

logger = logging.getLogger(__name__)

PDF = "application/pdf"
MSG = "application/vnd.ms-outlook"
EML = "message/rfc822"
MIMES = (PDF, MSG, EML)

_FROM = re.compile(r"^\s*\*?(?:from|od|nadawca)\s*:\s*\*?\s*(.+)$", re.IGNORECASE)
_SENT = re.compile(
    r"^\s*\*?(?:sent|wysłano|wysłane|date|data)\s*:\s*\*?\s*(.+)$", re.IGNORECASE
)
_EMAIL = re.compile(r"[\w.+'-]+@([\w-]+(?:\.[\w-]+)+)")
_LOOKAHEAD = 5

_PL_MONTHS = {
    "stycznia": 1,
    "lutego": 2,
    "marca": 3,
    "kwietnia": 4,
    "maja": 5,
    "czerwca": 6,
    "lipca": 7,
    "sierpnia": 8,
    "września": 9,
    "października": 10,
    "listopada": 11,
    "grudnia": 12,
}
_EN_MONTHS = {
    name: index
    for index, name in enumerate(
        (
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
        ),
        start=1,
    )
}
_EN_DATE = re.compile(
    r"([a-z]+)\s+(\d{1,2}),?\s+(\d{4})(?:[, ]+(?:at\s+)?(\d{1,2}):(\d{2})(?::\d{2})?\s*([ap]\.?m\.?)?)?",
    re.IGNORECASE,
)
_DAY_FIRST = re.compile(
    r"(\d{1,2})\s+([a-ząćęłńóśźż]+)\s+(\d{4})(?:[, ]+(\d{1,2}):(\d{2}))?",
    re.IGNORECASE,
)
_NUMERIC = re.compile(r"(\d{1,2})[./](\d{1,2})[./](\d{4})(?:[, ]+(\d{1,2}):(\d{2}))?")
_ISO = re.compile(r"(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{1,2}):(\d{2}))?")


@dataclass(frozen=True)
class MailMessage:
    """Jedna wiadomość łańcucha: adres nadawcy i dzień wysłania (bez strefy)."""

    sender: Optional[str]
    sent_on: Optional[date]

    @property
    def domain(self) -> Optional[str]:
        if not self.sender or "@" not in self.sender:
            return None
        return self.sender.rsplit("@", 1)[1].lower()


def _clock(
    hour: Optional[str], minute: Optional[str], ampm: Optional[str]
) -> tuple[int, int]:
    h = int(hour) if hour else 0
    m = int(minute) if minute else 0
    marker = (ampm or "").lower().replace(".", "")
    if marker == "pm" and h < 12:
        h += 12
    if marker == "am" and h == 12:
        h = 0
    return h, m


def parse_date(text: str) -> Optional[date]:
    """Data z nagłówka maila: RFC 2822, „Monday, November 2, 2026 4:54 PM”,
    „02.11.2026 17:53 CET”, „2 listopada 2026 16:54”, „2026-11-02 16:54”."""

    raw = " ".join((text or "").split())
    if not raw:
        return None
    try:
        return parsedate_to_datetime(raw).date()
    except (TypeError, ValueError, IndexError):
        pass
    candidates: list[datetime] = []
    for match in _EN_DATE.finditer(raw):
        month = _EN_MONTHS.get(match.group(1).lower())
        if month:
            h, m = _clock(match.group(4), match.group(5), match.group(6))
            candidates.append(
                datetime(int(match.group(3)), month, int(match.group(2)), h, m)
            )
            break
    if not candidates:
        for match in _DAY_FIRST.finditer(raw):
            word = match.group(2).lower()
            month = _PL_MONTHS.get(word) or _EN_MONTHS.get(word)
            if month:
                candidates.append(
                    datetime(int(match.group(3)), month, int(match.group(1)))
                )
                break
    if not candidates:
        match = _ISO.search(raw)
        if match:
            candidates.append(
                datetime(int(match.group(1)), int(match.group(2)), int(match.group(3)))
            )
    if not candidates:
        match = _NUMERIC.search(raw)
        if match:
            candidates.append(
                datetime(int(match.group(3)), int(match.group(2)), int(match.group(1)))
            )
    for found in candidates:
        try:
            return found.date()
        except ValueError:
            continue
    return None


def _address(text: str) -> Optional[str]:
    match = _EMAIL.search(text or "")
    return match.group(0).lower() if match else None


def quoted_messages(text: str) -> list[MailMessage]:
    """Bloki nagłówków w treści: „From/Od” i najbliższe „Sent/Wysłano/Data”."""

    lines = (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    found: list[MailMessage] = []
    for index, line in enumerate(lines):
        head = _FROM.match(line)
        if not head:
            continue
        sender = _address(head.group(1))
        sent_on = None
        for follow in lines[index + 1 : index + 1 + _LOOKAHEAD]:
            if _FROM.match(follow):
                break
            sent = _SENT.match(follow)
            if sent:
                sent_on = parse_date(sent.group(1))
                if sent_on:
                    break
        if sender or sent_on:
            found.append(MailMessage(sender, sent_on))
    return found


def _html_text(markup: str) -> str:
    markup = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", markup)
    markup = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>", "\n", markup)
    return html.unescape(re.sub(r"<[^>]+>", " ", markup))


def _from_eml(content: bytes) -> list[MailMessage]:
    message = BytesParser(policy=policy.default).parsebytes(content)
    outer_date = None
    try:
        outer_date = parsedate_to_datetime(str(message.get("Date", ""))).date()
    except (TypeError, ValueError, IndexError):
        outer_date = None
    outer = MailMessage(
        _address(parseaddr(str(message.get("From", "")))[1]), outer_date
    )
    body = message.get_body(preferencelist=("plain", "html"))
    text = ""
    if body is not None:
        try:
            text = body.get_content()
        except (LookupError, ValueError):
            text = ""
        if body.get_content_subtype() == "html":
            text = _html_text(text)
    return [outer, *quoted_messages(text)]


def _stream_text(ole, name: str) -> str:
    if ole.exists(f"{name}001F"):
        return (
            ole.openstream(f"{name}001F")
            .read()
            .decode("utf-16-le", "ignore")
            .rstrip("\x00")
        )
    if ole.exists(f"{name}001E"):
        return (
            ole.openstream(f"{name}001E")
            .read()
            .decode("cp1250", "ignore")
            .rstrip("\x00")
        )
    return ""


def _from_msg(content: bytes) -> list[MailMessage]:
    import olefile

    if not olefile.isOleFile(io.BytesIO(content)):
        return []
    with olefile.OleFileIO(io.BytesIO(content)) as ole:
        sender = (
            _stream_text(ole, "__substg1.0_5D01")  # PR_SENDER_SMTP_ADDRESS
            or _stream_text(ole, "__substg1.0_0C1F")  # PR_SENDER_EMAIL_ADDRESS
            or _stream_text(ole, "__substg1.0_0065")  # PR_SENT_REPRESENTING_EMAIL
        )
        headers = _stream_text(ole, "__substg1.0_007D")  # PR_TRANSPORT_MESSAGE_HEADERS
        body = _stream_text(ole, "__substg1.0_1000")  # PR_BODY
        if not body and ole.exists("__substg1.0_10130102"):  # PR_HTML
            raw = ole.openstream("__substg1.0_10130102").read()
            body = _html_text(raw.decode("utf-8", "ignore"))
    outer_date = None
    if headers:
        parsed = BytesParser(policy=policy.default).parsebytes(
            headers.encode("utf-8", "ignore"), headersonly=True
        )
        outer_date = parse_date(str(parsed.get("Date", "")))
        sender = (
            sender
            if "@" in (sender or "")
            else parseaddr(str(parsed.get("From", "")))[1]
        )
    outer = MailMessage(_address(sender or ""), outer_date)
    return [outer, *quoted_messages(body)]


def _from_pdf(content: bytes) -> list[MailMessage]:
    import pdfplumber

    with pdfplumber.open(io.BytesIO(content)) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages[:10])
    return quoted_messages(text)


def read(content: bytes, mime: str) -> list[MailMessage]:
    """Wiadomości z pliku maila; plik nie do odczytu = pusta lista (sprawdza człowiek)."""

    try:
        if mime == EML:
            return _from_eml(content)
        if mime == MSG:
            return _from_msg(content)
        if mime == PDF:
            return _from_pdf(content)
    except Exception as exc:  # noqa: BLE001 — zły plik nie blokuje rozliczenia
        logger.warning(
            "rozliczenia: mail akceptujący nieczytelny (%s)", type(exc).__name__
        )
    return []


def domains(raw: str) -> tuple[str, ...]:
    """Parametr reguły „domena”: jedna albo kilka po przecinku, bez „@”."""

    return tuple(
        part.strip().lstrip("@").lower()
        for part in (raw or "").split(",")
        if part.strip()
    )


def from_domain(
    messages: Iterable[MailMessage], allowed: tuple[str, ...]
) -> list[MailMessage]:
    """Wiadomości z domeny klienta — dokładnie, bez poddomen: w BNP konsultant
    pisze z konta ``external.`` w domenie banku, a zgodę daje pracownik banku."""

    return [m for m in messages if m.domain and m.domain in allowed]


def acceptance_date(
    messages: Iterable[MailMessage], allowed: tuple[str, ...]
) -> Optional[date]:
    """Najwcześniejsza data wiadomości od akceptującego (z domeny klienta, a bez
    domeny w regule — z całego łańcucha)."""

    pool = from_domain(messages, allowed) if allowed else list(messages)
    dates = [m.sent_on for m in pool if m.sent_on is not None]
    return min(dates) if dates else None
