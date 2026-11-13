"""Mail akceptujący przy RCP (roadmapa E2.3): nadawcy i daty wiadomości. Bez bazy.

Konsultant przysyła akceptację przełożonego zwykle jako przekazany dalej
łańcuch („FW: FW: TS …”), więc data samego pliku to data przekazania, a nie
zgody. Czytamy więc każdą wiadomość łańcucha: nagłówek pliku (``.eml``,
``.msg``) oraz bloki „From/Od … Sent/Wysłano/Data …” w treści i w wydruku PDF.
Kontrolę (data zgody przed pracą dodatkową, domena nadawcy) robi
``rcp_checks.evaluate``; tu tylko odczyt.

``.msg`` i ``.eml`` czyta wspólny czytnik ``mail_file`` (kontener OLE bez
zależności, z E6.3 Aliora): nadawca, nagłówki transportowe z datą i treść.
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
from email.utils import parsedate_to_datetime
from typing import Iterable, Optional

from app.services.client_settlements import mail_file

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


def _from_mail_file(content: bytes, mime: str) -> list[MailMessage]:
    mail = mail_file.read(content, mime)
    if mail is None:
        return []
    headers = BytesParser(policy=policy.default).parsebytes(
        mail.headers.encode("utf-8", "ignore"), headersonly=True
    )
    outer = MailMessage(
        _address(mail.sender) or _address(str(headers.get("From", ""))),
        parse_date(str(headers.get("Date", ""))),
    )
    body = mail.body
    if "<html" in body[:500].lower() or "<body" in body[:2000].lower():
        body = _html_text(body)
    return [outer, *quoted_messages(body)]


def _from_pdf(content: bytes) -> list[MailMessage]:
    import pdfplumber

    with pdfplumber.open(io.BytesIO(content)) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages[:10])
    return quoted_messages(text)


def read(content: bytes, mime: str) -> list[MailMessage]:
    """Wiadomości z pliku maila; plik nie do odczytu = pusta lista (sprawdza człowiek)."""

    try:
        if mime in (EML, MSG):
            return _from_mail_file(content, mime)
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
