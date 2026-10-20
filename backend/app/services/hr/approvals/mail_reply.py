"""Odpowiedź mailem na zgodę: znacznik w temacie i rozpoznanie decyzji (etap 2, 20.10.2026).

Decyzja Artura 20.10.2026: odpowiedź „approved” na mail o zgodzie zatwierdza
zgodę w NEXUSIE. Mail do decydującego ma wtedy Reply-To na skrzynkę, którą
czyta ``mail_reader.py`` (``HR_APPROVALS_REPLY_MAILBOX``), i znacznik
``[Zgoda <id>/<kod>]`` w temacie.

* **Kod** to HMAC z ``SECRET_KEY`` po numerze zgody i chwili jej wysłania
  (``submitted_at``). Sam numer wpisany w temat nic nie zatwierdzi, a stara
  odpowiedź nie zatwierdzi zgody poprawionej przez autora (poprawka zmienia
  ``submitted_at``, więc i kod).
* **Zatwierdza tylko samo słowo** w pierwszej linii nowej treści
  (``APPROVE_WORDS``, wielkość liter i końcowe „.”/„!” bez znaczenia); dalej
  może być najwyżej podpis. „not approved”, „ok?”, „ok, ale do 500 zł” — nie.
* **Cytat poprzedniego maila się nie liczy**: HTML ucinamy na znacznikach
  podpisu i cytatu Outlooka, tekst — na nagłówkach „Od:”/„From:”,
  „W dniu … napisał”, liniach z „>”.
* Każda inna niepusta treść wraca do autora jako pytanie (decyzja Artura
  20.10.2026: wariant „Pytanie do autora”).
"""

from __future__ import annotations

import hashlib
import hmac
import html
import re
from base64 import b32encode
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Optional

from app.core.config import settings
from app.services.hr_approvals_schema import NOTE_MAX_LENGTH

MARKER_RE = re.compile(r"\[Zgoda (\d{1,9})/([A-Z2-7]{8})\]")
CODE_LENGTH = 8

#: Słowa, które zatwierdzają (cała pierwsza linia, bez znaczenia wielkość liter).
APPROVE_WORDS = frozenset(
    {
        "approved",
        "approve",
        "ok",
        "okay",
        "okej",
        "zgoda",
        "tak",
        "zatwierdzam",
        "akceptuję",
        "akceptuje",
    }
)


def reply_mailbox() -> Optional[str]:
    """Skrzynka na odpowiedzi albo ``None``, gdy etap 2 jest wyłączony."""

    if not settings.HR_APPROVALS_MAIL_REPLY_ENABLED:
        return None
    return (settings.HR_APPROVALS_REPLY_MAILBOX or "").strip() or None


def reply_code(request_id: int, submitted_at: datetime) -> str:
    message = f"hr-approval-reply:{request_id}:{submitted_at.timestamp():.6f}"
    digest = hmac.new(
        settings.SECRET_KEY.encode("utf-8"), message.encode("utf-8"), hashlib.sha256
    ).digest()
    return b32encode(digest).decode("ascii")[:CODE_LENGTH]


def marker(request_id: int, submitted_at: datetime) -> str:
    return f"[Zgoda {request_id}/{reply_code(request_id, submitted_at)}]"


def find_marker(*texts: Optional[str]) -> Optional[tuple[int, str]]:
    """(numer zgody, kod) z pierwszego tekstu, który ma znacznik."""

    for value in texts:
        found = MARKER_RE.search(value or "")
        if found:
            return int(found.group(1)), found.group(2)
    return None


def code_matches(request_id: int, submitted_at: datetime, code: str) -> bool:
    return hmac.compare_digest(reply_code(request_id, submitted_at), code)


# ── Nowa treść odpowiedzi (bez cytatu i podpisu) ─────────────────────────────

# Od tego miejsca w HTML jest już podpis albo cytat: podpis Outlooka (nowy,
# web, mobilny, desktop „_MailAutoSig”), separator odpowiedzi Outlooka, cytat
# Gmaila i Apple Mail, linia pozioma przed nagłówkiem cytatu.
_HTML_CUT = re.compile(
    r"<div[^>]*\bid=\"(?:x_)?(?:appendonsend|divRplyFwdMsg|Signature|"
    r"ms-outlook-mobile-signature|mail-editor-reference-message-container)\""
    r"|<[^>]*\b(?:name|id)=\"_MailAutoSig\""
    r"|<blockquote\b"
    r"|<div[^>]*\bclass=\"[^\"]*gmail_quote"
    r"|<hr\b",
    re.IGNORECASE,
)
_HTML_DROP = re.compile(
    r"<(head|style|script)\b.*?</\1\s*>|<!--.*?-->", re.IGNORECASE | re.DOTALL
)
_HTML_BREAK = re.compile(
    r"<\s*/?\s*(?:br|p|div|tr|li|h[1-6]|table)\b[^>]*>", re.IGNORECASE
)
_HTML_TAG = re.compile(r"<[^>]+>")

# Linia, od której zaczyna się cytat poprzedniego maila w tekście.
_QUOTE_LINE = re.compile(
    r"^(?:>"
    r"|-{2,}\s*(?:original message|oryginalna wiadomo|wiadomo\w* oryginaln"
    r"|forwarded message|przekazana wiadomo)"
    r"|_{10,}"
    r"|(?:from|od|sent|wys[łl]ane|wys[łl]ano):\s"
    r"|on .+ wrote:?$"
    r"|(?:w dniu|dnia) .+ (?:pisze|napisa[łl]\S*):?$"
    r"|(?:sent from|wys[łl]ano z|get outlook|pobierz outlook))",
    re.IGNORECASE,
)
# Zwrot przed podpisem; po nim w tej samej linii najwyżej imię podpisującego
# („Pozdrawiam, Artur”), inaczej to treść („Dzięki, ale do 500 zł”).
_SIGN_OFF = re.compile(
    r"^(?:--|pozdrawiam|pozdrowienia|pozdr|best regards|kind regards|regards"
    r"|best|cheers|dzi[ęe]ki|dzi[ęe]kuj[ęe]|thanks|thank you)(?:[\s,.!]+(.*))?$",
    re.IGNORECASE,
)


def new_text(content: Optional[str], content_type: Optional[str]) -> str:
    """Tekst napisany w tej odpowiedzi — przed podpisem i cytatem."""

    raw = (content or "").replace("\x00", "")
    if (content_type or "").lower() == "html":
        raw = _HTML_DROP.sub("", raw)
        cut = _HTML_CUT.search(raw)
        if cut:
            raw = raw[: cut.start()]
        raw = html.unescape(_HTML_TAG.sub("", _HTML_BREAK.sub("\n", raw)))
    lines: list[str] = []
    for line in raw.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        cleaned = " ".join(line.replace("\xa0", " ").split())
        if _QUOTE_LINE.match(cleaned):
            break
        lines.append(cleaned)
    return "\n".join(line for line in lines if line)


@dataclass(frozen=True)
class Reply:
    kind: Literal["approve", "other", "empty"]
    text: str = ""


def _normalized(line: str) -> str:
    return line.strip().rstrip(".! ").strip().lower()


def _is_signature_start(line: str, signer_names: set[str]) -> bool:
    if _QUOTE_LINE.match(line.strip()):
        # „Sent from Outlook for iOS” i nagłówek cytatu — dalej nic nowego.
        return True
    sign_off = _SIGN_OFF.match(line.strip())
    if sign_off:
        rest = _normalized(sign_off.group(1) or "")
        return not rest or rest in signer_names
    return _normalized(line) in signer_names


def classify(text: str, *, signer_name: Optional[str] = None) -> Reply:
    """„approve” (samo słowo), „other” (pytanie do autora) albo „empty”."""

    names: set[str] = set()
    if signer_name and signer_name.strip():
        full = " ".join(signer_name.split()).lower()
        names = {full, full.split(" ")[0]}
    meaningful: list[str] = []
    for line in text.split("\n"):
        if not line.strip():
            continue
        if _is_signature_start(line, names):
            break
        meaningful.append(line.strip())
    if not meaningful:
        return Reply("empty")
    if len(meaningful) == 1 and _normalized(meaningful[0]) in APPROVE_WORDS:
        return Reply("approve", meaningful[0])
    note = "\n".join(meaningful)
    if len(note) > NOTE_MAX_LENGTH:
        note = note[: NOTE_MAX_LENGTH - 1].rstrip() + "…"
    return Reply("other", note)


__all__ = [
    "APPROVE_WORDS",
    "MARKER_RE",
    "Reply",
    "classify",
    "code_matches",
    "find_marker",
    "marker",
    "new_text",
    "reply_code",
    "reply_mailbox",
]
