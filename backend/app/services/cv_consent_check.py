"""Czy zrzut zgody RODO pasuje do kandydata i rekrutacji (F37, 0529).

Zgłoszenie Martyny 27.10.2026: pod CV dla PKO BP trafiały złe zrzuty —
plakat rekrutacyjny, prośba rekrutera o zgodę bez odpowiedzi kandydata,
zgoda innej osoby albo z innego zapytania ofertowego (ZOB). Pomiar na 121
zrzutach z produkcji: 11 złych, a QC sprawdzało tylko, czy obraz jest.

Podział pracy:

* model (``AIFeatureKey.consent_screenshot_check``) PRZEPISUJE z obrazu
  nagłówek maila (nadawca, adresaci, data, temat) i akapit zgody; niczego
  nie ocenia i nie dostaje danych kandydata z bazy,
* kod wyciąga z przepisanego tekstu numer ZOB i nazwisko („Ja, X, wyrażam
  zgodę”) i porównuje je z rekrutacją oraz kandydatem (``assess`` — czysta
  funkcja, testowana bez sieci),
* ten sam plik pod CV innego kandydata wykrywa sam kod (skrót obrazu).

Wynik jest podpowiedzią (decyzja Artura 27.10.2026, wariant A): zrzut, który
nie pasuje, rekruter może zapisać z powodem, a Delivery Lead widzi to w QC CV.
Awaria modelu = ``status: "unavailable"`` — zgoda przechodzi, sprawdza DL.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import func, select
from starlette.concurrency import run_in_threadpool

from app.models.ai_feature import AIFeatureKey
from app.services.ai_models import fallbacks_for, model_for

logger = logging.getLogger(__name__)

CHECK_VERSION = "consent_check:v1"
# Mail sprzed otwarcia rekrutacji o więcej niż tyle dni = zgoda z innego
# zapytania. Zapas na rekrutację założoną dzień–dwa po zapytaniu klienta.
OLD_MAIL_GRACE_DAYS = 3
TEXT_MAX = 2000
OVERRIDE_REASON_MIN = 5
OVERRIDE_REASON_MAX = 300

PROMPT = """Na obrazie jest zrzut ekranu, który rekruter wgrał jako mail ze zgodą kandydata na przetwarzanie danych przez klienta „{client}”.
Przepisz dokładnie to, co widać — niczego nie oceniaj, nie poprawiaj i nie zgaduj.
Zwróć WYŁĄCZNIE obiekt JSON:
{{"is_email": true gdy to zrzut wiadomości e-mail, inaczej false,
 "sender_name": nazwa nadawcy z nagłówka wiadomości na górze zrzutu (pole „Od”/„From” albo nazwa nad polem „Do”) albo null — nigdy z treści zgody,
 "sender_email": adres nadawcy z nagłówka albo null,
 "recipients": lista nazw albo adresów z pola „Do”/„To” nagłówka (pusta, gdy ich nie widać),
 "mail_date": data wiadomości z nagłówka jako "RRRR-MM-DD" albo null,
 "subject": temat wiadomości albo null,
 "consent_text": dosłownie przepisany akapit zgody (zwykle zaczyna się od „Ja, …, wyrażam zgodę”) albo null, gdy na zrzucie nie ma zgody}}
Gdy na zrzucie jest kilka wiadomości (odpowiedź z cytatem), nadawca i data to wiadomość na samej górze, a consent_text to akapit zgody z dowolnej z nich."""


@dataclass(frozen=True)
class Subject:
    """Z czym porównujemy zrzut: kandydat, klient i rekrutacja."""

    candidate_id: Optional[int]
    first_name: str
    last_name: str
    emails: tuple[str, ...]
    client_name: str
    # Numer zapytania ofertowego bez prefiksu „ZOB-”; None = rekrutacja go
    # nie ma i numeru nie sprawdzamy.
    expected_zob: Optional[str]
    opened_on: Optional[date]

    @classmethod
    def unknown(cls) -> "Subject":
        return cls(None, "", "", (), "", None, None)

    @property
    def full_name(self) -> str:
        return " ".join(p for p in (self.first_name, self.last_name) if p).strip()


# ── Tekst ────────────────────────────────────────────────────────────────────

_SPECIAL = str.maketrans({"ł": "l", "Ł": "L", "ø": "o", "Ø": "O", "đ": "d", "Đ": "D"})


def fold(text: str) -> str:
    """Małe litery bez polskich znaków — „SKRZECZYŃSKI” == „Skrzeczynski”."""
    decomposed = unicodedata.normalize("NFKD", (text or "").translate(_SPECIAL))
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def _tokens(text: str) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9]+", fold(text)) if t]


def _zob(value: str) -> str:
    return (value or "").lstrip("0") or "0"


# Bez granicy słowa przed „ZOB”: zgody bywają pisane „nrZOB-2984” (pomiar 27.10).
_ZOB_RE = re.compile(r"ZOB[\W_]{0,3}(\d+)", re.IGNORECASE)
_NAME_RE = re.compile(
    r"\bja\s*,?\s+(.{3,80}?)\s*,?\s+wyra[zż]am\s+zgod", re.IGNORECASE | re.DOTALL
)
_CONSENT_RE = re.compile(r"wyra[zż]am\s+zgod|zgod[aęy]\s+na\s+przetwarzanie", re.I)
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_CLIENT_STOP = {"sa", "s", "a", "sp", "z", "o", "oo", "spolka", "akcyjna", "group"}


def zob_numbers(*texts: Optional[str]) -> list[str]:
    found: list[str] = []
    for text in texts:
        for number in _ZOB_RE.findall(text or ""):
            if _zob(number) not in found:
                found.append(_zob(number))
    return found


def consent_name(text: Optional[str]) -> Optional[str]:
    match = _NAME_RE.search(" ".join((text or "").split()))
    if not match:
        return None
    name = re.sub(r"[*_„”\"]", "", match.group(1)).strip(" ,")
    return name or None


def name_matches(text: Optional[str], subject: Subject, *, lenient: bool) -> bool:
    """Czy tekst to imię i nazwisko kandydata.

    Nazwisko musi stać w całości (każdy człon dwuczłonowego), imię wystarczy
    po trzech pierwszych literach („Maciek” ↔ „Maciej”). ``lenient`` (nazwa
    nadawcy w skrzynce): samo imię też wystarcza — ludzie podpisują skrzynkę
    „Filip”, a nazwisko widać dopiero w treści zgody.
    """
    words = _tokens(text or "")
    if not words:
        return False
    last = _tokens(subject.last_name)
    first = _tokens(subject.first_name)
    first_ok = bool(first) and any(w[:3] == first[0][:3] for w in words)
    if last and all(any(_close(part, w) for w in words) for part in last):
        return first_ok or not first
    return lenient and len(words) == 1 and first_ok


def _close(expected: str, word: str) -> bool:
    """Ta sama część nazwiska; od 5 liter wolno pomylić jedną („Pawluk”/„Pawlak”)."""
    if expected == word:
        return True
    if len(expected) < 5 or abs(len(expected) - len(word)) > 1:
        return False
    previous = list(range(len(word) + 1))
    for i, a in enumerate(expected, 1):
        current = [i]
        for j, b in enumerate(word, 1):
            current.append(
                min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (a != b))
            )
        previous = current
    return previous[-1] <= 1


def _email_matches(text: Optional[str], subject: Subject) -> bool:
    mine = {fold(e).strip() for e in subject.emails if e}
    return any(fold(e) in mine for e in _EMAIL_RE.findall(text or ""))


def _client_named(text: str, client: str) -> bool:
    words = set(_tokens(text))
    wanted = [t for t in _tokens(client) if t not in _CLIENT_STOP and len(t) >= 2]
    return not wanted or any(t in words for t in wanted)


def _parse_date(raw: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(raw)[:10]) if raw else None
    except ValueError:
        return None


def _text(raw: Any, limit: int = 300) -> Optional[str]:
    if raw is None or isinstance(raw, (dict, list, bool)):
        return None
    value = " ".join(str(raw).split())[:limit]
    return value or None


def parse_reply(text: str) -> Optional[dict[str, Any]]:
    """Odczyt modelu → słownik pól; śmieci w odpowiedzi = ``None``."""
    start, end = (text or "").find("{"), (text or "").rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        raw = json.loads(text[start : end + 1])
    except ValueError:
        return None
    if not isinstance(raw, dict):
        return None
    recipients = raw.get("recipients")
    return {
        "is_email": raw.get("is_email") is True,
        "sender_name": _text(raw.get("sender_name")),
        "sender_email": _text(raw.get("sender_email")),
        "recipients": [
            r
            for r in (
                _text(x) for x in (recipients if isinstance(recipients, list) else [])
            )
            if r
        ][:10],
        "mail_date": (
            d.isoformat() if (d := _parse_date(raw.get("mail_date"))) else None
        ),
        "subject": _text(raw.get("subject")),
        "consent_text": _text(raw.get("consent_text"), TEXT_MAX),
    }


# ── Werdykt ──────────────────────────────────────────────────────────────────


def _pl(day: date) -> str:
    return day.strftime("%d.%m.%Y")


def assess(
    reading: Optional[dict[str, Any]],
    subject: Subject,
    *,
    duplicate: bool = False,
    today: Optional[date] = None,
) -> dict[str, Any]:
    """Porównaj odczyt z rekrutacją. Czysta funkcja — bez bazy i sieci.

    ``problems`` i ``passed`` to zdania dla rekrutera (karta) i DL-a (QC).
    """
    problems: list[dict[str, str]] = []
    passed: list[dict[str, str]] = []
    if duplicate:
        problems.append(
            {
                "code": "duplicate",
                "detail": "Ten sam plik jest już pod CV innego kandydata.",
            }
        )
    if reading is None:
        # Duplikat wykrywa sam kod, więc obowiązuje także bez odczytu modelu.
        return _result(
            "mismatch" if problems else "unavailable", problems, passed, None
        )

    consent = reading.get("consent_text") or ""
    if not _CONSENT_RE.search(consent):
        problems.append(
            {
                "code": "not_consent",
                "detail": "Na zrzucie nie ma maila ze zgodą na przetwarzanie danych.",
            }
        )
        return _result("mismatch", problems, passed, reading)

    who = subject.full_name or "kandydat"
    if subject.last_name:
        _person_checks(reading, subject, who, problems, passed)
    _document_checks(reading, subject, problems, passed, today)
    return _result("mismatch" if problems else "ok", problems, passed, reading)


def _person_checks(reading, subject: Subject, who: str, problems, passed) -> None:
    """Nadawca i nazwisko w zgodzie — tylko, gdy znamy kandydata."""
    consent = reading.get("consent_text") or ""
    sender = reading.get("sender_name") or reading.get("sender_email")
    header = " ".join(
        filter(None, (reading.get("sender_name"), reading.get("sender_email")))
    )
    sender_is_candidate = _email_matches(header, subject) or name_matches(
        reading.get("sender_name"), subject, lenient=True
    )
    candidate_is_recipient = any(
        _email_matches(r, subject) or name_matches(r, subject, lenient=False)
        for r in reading.get("recipients") or []
    )
    if candidate_is_recipient and not _email_matches(header, subject):
        # Mail DO kandydata to prośba o zgodę, nie jego odpowiedź — także gdy
        # model wziął nazwę „nadawcy” z treści zgody (przypadek 2972).
        problems.append(
            {
                "code": "recruiter_request",
                "detail": "To prośba o zgodę wysłana do kandydata"
                + (
                    f" (nadawca: {sender})"
                    if sender and not sender_is_candidate
                    else ""
                )
                + ", a nie jego odpowiedź.",
            }
        )
    elif not reading.get("is_email") or not sender:
        problems.append(
            {
                "code": "no_sender",
                "detail": "Na zrzucie nie widać nagłówka maila z nadawcą — zrób zrzut "
                "razem z nagłówkiem (od kogo, do kogo, data).",
            }
        )
    elif sender_is_candidate:
        passed.append({"code": "sender", "detail": f"Nadawca: {who}"})
    else:
        problems.append(
            {
                "code": "sender_not_candidate",
                "detail": f"Nadawca maila ({sender}) to nie {who}.",
            }
        )

    named = consent_name(consent)
    if named and not name_matches(named, subject, lenient=False):
        problems.append(
            {
                "code": "wrong_person",
                "detail": f"W treści zgody jest {named}, a kandydat to {who}.",
            }
        )
    elif named:
        passed.append({"code": "name", "detail": f"{who} w treści zgody"})


def _document_checks(
    reading, subject: Subject, problems, passed, today: Optional[date]
) -> None:
    """Klient, numer ZOB i data maila."""
    consent = reading.get("consent_text") or ""
    if not _client_named(consent, subject.client_name):
        problems.append(
            {
                "code": "other_client",
                "detail": f"Zgoda nie wymienia klienta {subject.client_name}.",
            }
        )

    if subject.expected_zob:
        expected = _zob(subject.expected_zob)
        found = zob_numbers(consent, reading.get("subject"))
        if not found:
            problems.append(
                {
                    "code": "no_zob",
                    "detail": "W zgodzie nie ma numeru zapytania ofertowego "
                    f"(ta rekrutacja: ZOB-{expected}).",
                }
            )
        elif expected not in found:
            listed = ", ".join(f"ZOB-{n}" for n in found)
            problems.append(
                {
                    "code": "wrong_zob",
                    "detail": f"Zgoda dotyczy {listed}, a ta rekrutacja to ZOB-{expected}.",
                }
            )
        else:
            passed.append(
                {"code": "zob", "detail": f"ZOB-{expected} zgadza się z rekrutacją"}
            )

    mailed = _parse_date(reading.get("mail_date"))
    if mailed and subject.opened_on:
        if mailed < subject.opened_on - timedelta(days=OLD_MAIL_GRACE_DAYS):
            problems.append(
                {
                    "code": "old_date",
                    "detail": f"Mail z {_pl(mailed)}, sprzed otwarcia rekrutacji "
                    f"({_pl(subject.opened_on)}).",
                }
            )
        elif today is None or mailed <= today + timedelta(days=1):
            passed.append(
                {
                    "code": "date",
                    "detail": f"Mail z {_pl(mailed)}, po otwarciu rekrutacji "
                    f"({_pl(subject.opened_on)})",
                }
            )


def _result(status, problems, passed, reading) -> dict[str, Any]:
    out: dict[str, Any] = {
        "version": CHECK_VERSION,
        "status": status,
        "problems": problems,
        "passed": passed,
    }
    if reading is not None:
        # Bez treści zgody — nagłówek wystarcza DL-owi, a obraz i tak leży przy CV.
        out["reading"] = {
            k: reading.get(k)
            for k in ("sender_name", "sender_email", "mail_date", "subject")
        }
        out["reading"]["zob"] = [
            f"ZOB-{n}"
            for n in zob_numbers(reading.get("consent_text"), reading.get("subject"))
        ]
    return out


def with_override(check: dict[str, Any], reason: str, user_id: int) -> dict[str, Any]:
    """Zrzut, który nie pasuje, zapisany mimo to — powód widzi DL w QC CV."""
    return {
        **check,
        "override": {
            "reason": reason,
            "by": user_id,
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        },
    }


def clean_override_reason(raw: Optional[str]) -> Optional[str]:
    value = " ".join((raw or "").split())
    if not value:
        return None
    if len(value) < OVERRIDE_REASON_MIN:
        raise ValueError(
            f"Napisz powód w kilku słowach (co najmniej {OVERRIDE_REASON_MIN} znaków)."
        )
    return value[:OVERRIDE_REASON_MAX]


# ── Wywołanie i baza ─────────────────────────────────────────────────────────


def _call_model(image: bytes, mime: str, client: str) -> str:
    from app.services.claude_client import call_claude, text_of  # noqa: PLC0415

    message = call_claude(
        model=model_for(AIFeatureKey.consent_screenshot_check),
        fallback_models=list(fallbacks_for(AIFeatureKey.consent_screenshot_check)),
        max_tokens=1200,
        temperature=0,
        thinking={"type": "disabled"},
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": mime,
                            "data": base64.b64encode(image).decode("ascii"),
                        },
                    },
                    {"type": "text", "text": PROMPT.format(client=client or "klient")},
                ],
            }
        ],
    )
    return text_of(message)


async def used_for_other_candidate(
    db, image: bytes, candidate_id: Optional[int]
) -> bool:
    """Czy ten sam plik leży już pod CV innego kandydata (bez AI)."""
    if candidate_id is None:
        return False
    from app.models.candidate_stage_cv import CandidateStageCV  # noqa: PLC0415
    from app.models.cv_generated_document import CvGeneratedDocument  # noqa: PLC0415

    digest = hashlib.md5(image, usedforsecurity=False).hexdigest()
    for model, column in (
        (CvGeneratedDocument, CvGeneratedDocument.consent_content),
        (CandidateStageCV, CandidateStageCV.branded_consent_content),
    ):
        found = await db.scalar(
            select(model.id)
            .where(
                column.is_not(None),
                func.md5(column) == digest,
                model.candidate_id.is_not(None),
                model.candidate_id != candidate_id,
            )
            .limit(1)
        )
        if found is not None:
            return True
    return False


async def check_screenshot(
    db, *, image: bytes, mime: str, subject: Subject, user_id: int
) -> dict[str, Any]:
    """Odczyt modelu + porównanie z rekrutacją. Nigdy nie rzuca."""
    from app.core.scheduling import business_today  # noqa: PLC0415
    from app.services.ai_quota import ai_feature  # noqa: PLC0415

    reading: Optional[dict[str, Any]] = None
    try:
        async with ai_feature(
            db, AIFeatureKey.consent_screenshot_check, user_id=user_id
        ):
            reply = await run_in_threadpool(
                _call_model, image, mime, subject.client_name
            )
        reading = parse_reply(reply)
    except Exception as exc:  # noqa: BLE001 — wynik AI to dodatek, zgoda przechodzi
        logger.warning("[consent_check] odczyt nieudany (%s)", type(exc).__name__)
    try:
        duplicate = await used_for_other_candidate(db, image, subject.candidate_id)
    except Exception as exc:  # noqa: BLE001 — jak wyżej
        logger.warning(
            "[consent_check] duplikat niesprawdzony (%s)", type(exc).__name__
        )
        duplicate = False
    return assess(reading, subject, duplicate=duplicate, today=business_today())


__all__ = [
    "CHECK_VERSION",
    "Subject",
    "assess",
    "check_screenshot",
    "clean_override_reason",
    "consent_name",
    "name_matches",
    "parse_reply",
    "used_for_other_candidate",
    "with_override",
    "zob_numbers",
]
