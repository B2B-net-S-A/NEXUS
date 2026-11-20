"""Przekazany mail na rozliczenia@: kto napisał pierwotnie i co było w środku.

Koordynatorzy i klienci przesyłają dalej raporty konsultantów, raz w treści
(„From:/Od:” nad cytatem), raz jako załączony mail (Graph ``itemAttachment``,
którego plików lista załączników nie zwraca). W próbie IX–XI 2026 ok. 230
dokumentów przyszło przekazanych, ok. 50 maili jako załącznik przepadało.
Czytamy cały MIME wiadomości, bo tylko on niesie oba kształty.
"""

from __future__ import annotations

import base64
import email
import email.policy
import html
import re
from dataclasses import dataclass
from email.message import EmailMessage, Message
from email.utils import getaddresses

from app.services.consultant_portal.identity import normalize_email

FILE_ATTACHMENT = "#microsoft.graph.fileAttachment"
ITEM_ATTACHMENT = "#microsoft.graph.itemAttachment"

# Nagłówek cytatu Outlooka, Gmaila i Thunderbirda po polsku, angielsku i niemiecku.
_HEADER_LINE = re.compile(
    r"^[\s>*]*(?:from|od|von|de)\s*:\s*(.+)$", re.IGNORECASE | re.MULTILINE
)
_ADDRESS = re.compile(r"[\w.+'-]+@[\w-]+(?:\.[\w-]+)+")
_TAG = re.compile(r"<[^>]*>")
_MAX_DEPTH = 3


@dataclass(frozen=True)
class Forwarded:
    senders: tuple[str, ...]
    files: tuple[dict, ...]


def _text(message: Message) -> str:
    if not isinstance(message, EmailMessage):
        return ""
    body = message.get_body(preferencelist=("plain", "html"))
    if body is None:
        return ""
    try:
        content = body.get_content()
    except (LookupError, ValueError):
        return ""
    if body.get_content_type() == "text/html":
        content = html.unescape(_TAG.sub("\n", content))
    return content


def _quoted_senders(text: str) -> list[str]:
    out: list[str] = []
    for line in _HEADER_LINE.findall(text):
        out.extend(normalize_email(a) for a in _ADDRESS.findall(line))
    return out


def _walk(message: Message, depth: int, senders: list[str], files: list[dict]) -> None:
    senders.extend(_quoted_senders(_text(message)))
    if not isinstance(message, EmailMessage):
        return
    for part in message.iter_attachments():
        if part.get_content_type() == "message/rfc822":
            inner = part.get_payload(0) if part.is_multipart() else None
            if inner is None or depth >= _MAX_DEPTH:
                continue
            for _, address in getaddresses(
                [str(v) for v in inner.get_all("From") or []]
            ):
                if address:
                    senders.append(normalize_email(address))
            _walk(inner, depth + 1, senders, files)
            continue
        if depth == 0:
            # Pliki samego maila zwraca już lista załączników Graph.
            continue
        payload = part.get_payload(decode=True)
        if not payload:
            continue
        files.append(
            {
                "@odata.type": FILE_ATTACHMENT,
                "name": part.get_filename() or "",
                "isInline": False,
                "contentBytes": base64.b64encode(payload).decode("ascii"),
            }
        )


def parse(raw: bytes) -> Forwarded:
    """Adresy pierwotnych nadawców (od najbliższego) i pliki z załączonych maili."""

    message = email.message_from_bytes(raw, policy=email.policy.default)
    senders: list[str] = []
    files: list[dict] = []
    _walk(message, 0, senders, files)
    own = normalize_email(
        next((a for _, a in getaddresses([str(message.get("From") or "")]) if a), "")
    )
    unique = tuple(dict.fromkeys(a for a in senders if a and a != own))
    return Forwarded(senders=unique, files=tuple(files))
