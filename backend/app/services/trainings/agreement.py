"""Umowa szkoleniowa B2B: dane trenera, kontekst wzoru, DOCX → PDF i zamrożenie.

Wzór „Umowa B2B - Szkolenia” (decyzja Artura 13.11.2026) leży jako szablon
docxtpl ``templates/contract/umowa_szkoleniowa_pl.docx`` — buduje go
``scripts/build_training_agreement_template.py``. Załącznik nr 1 wypełniają
pola ``trainings`` (dane szkolenia, agenda, pliki, prawa, kwoty A–E).

Umowa przenosi autorskie prawa majątkowe (§ 8), więc § 17 wymaga podpisu
własnoręcznego albo kwalifikowanego obu stron. Podpisuje się PDF z tego
samego Worda, zamrożony odciskiem przy generowaniu (jak umowa B2B,
``podpis-umowy-b2b-w-nexusie.md``) — podpisy dopisują się na końcu pliku,
więc po podpisie trenera umowy nie da się już wygenerować ponownie.
"""

from __future__ import annotations

import hashlib
import io
import os
import re
from collections.abc import Mapping
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

from docxtpl import DocxTemplate
from jinja2 import Environment
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.docx_metadata import clear_app_properties, clear_author_metadata
from app.core.scheduling import business_date
from app.models.b2b_generated_contract import B2BGeneratedContract
from app.models.candidate import Candidate
from app.models.contract import Contract
from app.models.training import Training
from app.services import storage_service
from app.services.b2b_contract_filename import _ascii_words, _surname_first
from app.services.b2b_contract_generator.formatting import pl_date
from app.services.b2b_contract_generator.gender import is_female
from app.services.b2b_contract_generator.number_words import pln_words_with_fraction
from app.services.cv_pdf_preview import PdfPreviewUnavailable, pdf_from_docx
from app.services.trainings.errors import TrainingError

TEMPLATE_PATH = (
    Path(__file__).resolve().parents[2]
    / "templates"
    / "contract"
    / "umowa_szkoleniowa_pl.docx"
)
#: Katalog plików szkoleń pod ``STORAGE_ROOT``: ``trainings/<id>/agreement/``.
SUBDIR = "trainings"

PARTNER_KEYS: tuple[str, ...] = (
    "full_name",
    "company",
    "address",
    "postal_city",
    "nip",
    "regon",
    "phone",
    "email",
)
#: Poza kluczami z ``PARTNER_KEYS`` migawka trzyma formy do komparycji, gdy
#: NEXUS je zna z umowy B2B: płeć („Panem/Panią”) i narzędnik imienia.
EXTRA_KEYS: tuple[str, ...] = ("gender", "name_instrumental")
PARTNER_REQUIRED: tuple[str, ...] = ("full_name", "company", "address", "nip", "email")
PARTNER_LABELS: dict[str, str] = {
    "full_name": "imię i nazwisko",
    "company": "nazwa firmy",
    "address": "adres działalności",
    "nip": "NIP",
    "email": "adres e-mail",
}

UNSET = "do ustalenia"
NOT_APPLICABLE = "nie dotyczy"
NONE_LISTED = "brak"
EXAM_NONE = "Szkolenie nie kończy się egzaminem."
EXAM_TEST = "Szkolenie kończy się testem wiedzy uczestników, bez egzaminu."

MSG_WRONG_STATUS = "Umowę generuje się dla szkolenia z przyjętą wyceną."
MSG_TRAINER_SIGNED = (
    "Trener już podpisał umowę, więc nie można jej wygenerować ponownie."
)
MSG_FEES = "Wycena nie ma kwot. Uzupełnij wynagrodzenie w pozycjach A–E."
MSG_PDF = "Nie udało się teraz przygotować PDF-a umowy. Spróbuj za kilka minut."

_DELIVERABLE_LABELS = {
    "materials": "materiały dla uczestników",
    "presentation": "prezentacja",
    "audio": "pliki audio",
}
# Imiona męskie zakończone na „a” (reszta takich imion jest żeńska).
_MALE_A = frozenset({"kuba", "barnaba", "bonawentura", "kosma", "jarema", "dyzma"})
_POSTAL = re.compile(r"^(?P<street>.*?)[,\s]+(?P<postal>\d{2}-\d{3}\s+\S.*)$")


# ── Dane trenera ─────────────────────────────────────────────────────────────


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _first(*values: Any) -> str:
    for value in values:
        text = _text(value)
        if text:
            return text
    return ""


def split_address(address: str) -> tuple[str, str]:
    """„ul. Prosta 1, 00-001 Warszawa” → („ul. Prosta 1”, „00-001 Warszawa”).

    Bez kodu pocztowego cały adres zostaje w pierwszej części."""
    text = " ".join(_text(address).split())
    match = _POSTAL.match(text)
    if not match or not match.group("street").strip(" ,"):
        return text, ""
    return match.group("street").strip(" ,"), match.group("postal").strip()


def partner_from_sources(
    *,
    contract: Any,
    generated: Any = None,
    candidate: Any = None,
) -> dict[str, str]:
    """Najlepsze dane firmy trenera: umowa B2B z Generatora (``render_payload``,
    potem kolumny wiersza rejestru), potem karta kandydata. E-mail i telefon
    najpierw z kontraktu — tym adresem trener loguje się do panelu."""
    payload: Mapping[str, Any] = (
        (getattr(generated, "render_payload", None) or {}) if generated else {}
    )
    candidate_name = (
        " ".join(_text(getattr(candidate, k, "")) for k in ("name", "lastname")).strip()
        if candidate is not None
        else ""
    )
    full_name = _first(
        payload.get("partner_name"),
        getattr(generated, "partner_name", None),
        candidate_name,
    )
    address, postal_city = split_address(
        _first(
            payload.get("partner_business_address"),
            getattr(candidate, "business_address", None),
        )
    )
    partner = {
        "full_name": full_name,
        "company": _first(
            payload.get("partner_legal_name"),
            getattr(generated, "partner_legal_name", None),
            getattr(candidate, "legal_name", None),
        ),
        "address": address,
        "postal_city": postal_city,
        "nip": _first(
            payload.get("partner_nip"),
            getattr(generated, "partner_nip", None),
            getattr(candidate, "nip", None),
        ),
        "regon": _first(
            payload.get("partner_regon"), getattr(candidate, "regon", None)
        ),
        "phone": _first(
            getattr(contract, "candidate_phone", None),
            payload.get("partner_phone"),
            getattr(candidate, "phone", None),
        ),
        "email": _first(
            getattr(contract, "candidate_email", None),
            payload.get("partner_email"),
            getattr(candidate, "email", None),
        ),
    }
    # Formy z umowy B2B tylko wtedy, gdy dotyczą tej samej osoby.
    same_person = _text(payload.get("partner_name")) == full_name and full_name
    partner["gender"] = _text(payload.get("gender")) if same_person else ""
    partner["name_instrumental"] = (
        _text(payload.get("partner_instrumental")) if same_person else ""
    )
    return partner


async def partner_from_contract(db: AsyncSession, contract_id: int) -> dict[str, str]:
    """Dane trenera z NEXUSA dla kontraktu (klucze ``PARTNER_KEYS`` + ``EXTRA_KEYS``,
    brak = pusty napis). Umowa z Generatora tego kontraktu, a bez niej najnowsza
    umowa tej osoby."""
    contract = await db.get(Contract, contract_id)
    if contract is None:
        return {key: "" for key in (*PARTNER_KEYS, *EXTRA_KEYS)}
    newest = (
        select(B2BGeneratedContract).order_by(B2BGeneratedContract.id.desc()).limit(1)
    )
    generated = await db.scalar(
        newest.where(B2BGeneratedContract.contract_id == contract.id)
    )
    if generated is None and contract.candidate_id is not None:
        generated = await db.scalar(
            newest.where(B2BGeneratedContract.candidate_id == contract.candidate_id)
        )
    candidate = (
        await db.get(Candidate, contract.candidate_id)
        if contract.candidate_id
        else None
    )
    return partner_from_sources(
        contract=contract, generated=generated, candidate=candidate
    )


def clean_partner(partner: Mapping[str, Any]) -> dict[str, str]:
    """Migawka do ``trainings.partner``: znane klucze, przycięte napisy."""
    return {key: _text(partner.get(key)) for key in (*PARTNER_KEYS, *EXTRA_KEYS)}


def missing_partner_fields(partner: Mapping[str, Any]) -> list[str]:
    """Polskie nazwy brakujących pól wymaganych do umowy."""
    return [
        PARTNER_LABELS[key] for key in PARTNER_REQUIRED if not _text(partner.get(key))
    ]


# ── Kontekst wzoru ───────────────────────────────────────────────────────────


def format_money(amount: Optional[Decimal]) -> str:
    """Polski zapis kwoty: 6200 → „6 200,00” (twarda spacja, bez łamania)."""
    value = Decimal(amount or 0).quantize(Decimal("0.01"))
    return f"{value:,.2f}".replace(",", " ").replace(".", ",")


def fees_total(training: Training) -> Decimal:
    return sum(
        (
            Decimal(fee or 0)
            for fee in (
                training.fee_prep,
                training.fee_delivery,
                training.fee_presentation,
                training.fee_audio,
                training.fee_rights,
            )
        ),
        Decimal(0),
    )


def _days(n: int) -> str:
    return "1 dzień" if n == 1 else f"{n} dni"


def due_text(due_days: Any, session_date: Optional[date]) -> str:
    """Termin przekazania względem dnia szkolenia: ujemny = przed, 0 = w dniu,
    dodatni = po; z datą, gdy szkolenie ma termin."""
    if due_days is None or due_days == "":
        return UNSET
    days = int(due_days)
    if days == 0:
        text = "w dniu szkolenia"
    elif days < 0:
        text = f"{_days(-days)} przed szkoleniem"
    else:
        text = f"{_days(days)} po szkoleniu"
    if session_date is not None:
        text += f" (do {pl_date(session_date + timedelta(days=days))} r.)"
    return text


def _duration(minutes: Any) -> str:
    if not minutes:
        return ""
    hours, rest = divmod(int(minutes), 60)
    if not hours:
        return f"{rest} min"
    return f"{hours} godz." + (f" {rest} min" if rest else "")


def _female(partner: Mapping[str, Any]) -> bool:
    gender = _text(partner.get("gender"))
    if gender:
        return is_female(gender)
    words = _text(partner.get("full_name")).split()
    first = words[0].lower() if words else ""
    return first.endswith("a") and first not in _MALE_A


def _forms(partner: Mapping[str, Any]) -> dict[str, str]:
    if _female(partner):
        return {"pan": "Panią", "prowadzacy": "prowadzącą", "zwany": "zwana"}
    return {"pan": "Panem", "prowadzacy": "prowadzącym", "zwany": "zwany"}


def _deliverables(training: Training) -> dict[str, Any]:
    items = [d for d in (training.deliverables or []) if isinstance(d, Mapping)]
    by_key = {
        key: next((d for d in items if d.get("key") == key), None)
        for key in _DELIVERABLE_LABELS
    }
    others = [d for d in items if d.get("key") == "other" and d.get("required")]
    wanted: list[tuple[str, Mapping[str, Any]]] = [
        (label, by_key[key])
        for key, label in _DELIVERABLE_LABELS.items()
        if by_key[key] and by_key[key].get("required")
    ]
    wanted += [(_text(d.get("label")) or "inne pliki", d) for d in others]

    def summary(field: str) -> str:
        if not wanted:
            return NOT_APPLICABLE
        values = [
            (label, _text(item.get("format")) or UNSET)
            if field == "format"
            else (label, due_text(item.get("due_days"), training.session_date))
            for label, item in wanted
        ]
        if len({v for _, v in values}) == 1:
            return values[0][1]
        return "; ".join(f"{label}: {value}" for label, value in values)

    def entry(key: str) -> dict[str, str]:
        item = by_key[key]
        required = bool(item and item.get("required"))
        return {
            "flag": "TAK" if required else "NIE",
            "format": (_text(item.get("format")) or UNSET)
            if required
            else NOT_APPLICABLE,
            "due": due_text(item.get("due_days"), training.session_date)
            if required
            else NOT_APPLICABLE,
        }

    return {
        **{key: entry(key) for key in _DELIVERABLE_LABELS},
        "other": "; ".join(_text(d.get("label")) or "inne pliki" for d in others)
        or NONE_LISTED,
        "files_format": summary("format"),
        "files_due": summary("due"),
        "_works": [label for label, _ in wanted],
    }


def _agenda(training: Training) -> list[dict[str, Any]]:
    rows = []
    for item in training.agenda or []:
        if not isinstance(item, Mapping) or not _text(item.get("title")):
            continue
        title = _text(item.get("title"))
        length = _duration(item.get("minutes"))
        rows.append(
            {
                "no": len(rows) + 1,
                "title": title,
                "duration": length,
                "text": f"{title} ({length})" if length else title,
            }
        )
    return rows


def build_context(
    training: Training,
    partner: Mapping[str, Any],
    *,
    company_email: str,
    agreement_date: date,
) -> dict[str, Any]:
    """Wszystko, czego potrzebuje wzór — same napisy i listy, bez ``None``."""
    data = clean_partner(partner)
    data["name_instrumental"] = data["name_instrumental"] or data["full_name"]
    session = pl_date(training.session_date) if training.session_date else ""
    hours = (
        f"{training.time_from}–{training.time_to}"
        if training.time_from and training.time_to
        else _text(training.time_from)
    )
    if session:
        schedule = f"{session} r." + (f", w godzinach {hours}" if hours else "")
    else:
        schedule = "w terminie wskazanym w Załączniku nr 1"
    deliverables = _deliverables(training)
    works = ["program i agenda szkolenia", *deliverables.pop("_works")]
    total = fees_total(training)
    return {
        "agreement_number": training.agreement_number or "",
        "agreement_date": pl_date(agreement_date),
        "company_email": _text(company_email),
        "partner": data,
        "g": _forms(data),
        "t": {
            "title": _text(training.title),
            "topic": _text(training.topic) or _text(training.title),
            "date": f"{session} r." if session else UNSET,
            "hours": hours or UNSET,
            "duration": _duration(training.duration_minutes) or UNSET,
            "platform": _text(training.platform) or UNSET,
            "participants": str(training.expected_participants)
            if training.expected_participants
            else UNSET,
            "schedule": schedule,
            "participant_materials": _text(training.participant_materials)
            or NONE_LISTED,
        },
        "agenda": _agenda(training),
        "deliv": deliverables,
        "rights": {
            "works": "; ".join(works),
            "own": _text(training.own_materials) or NONE_LISTED,
            "third_party": _text(training.third_party_materials) or NONE_LISTED,
        },
        "fees": {
            "prep": format_money(training.fee_prep),
            "delivery": format_money(training.fee_delivery),
            "presentation": format_money(training.fee_presentation),
            "audio": format_money(training.fee_audio),
            "rights": format_money(training.fee_rights),
            "total": format_money(total),
            "total_words": pln_words_with_fraction(float(total)),
        },
        "exam_text": EXAM_TEST if training.knowledge_test else EXAM_NONE,
        "extra_terms": _text(training.extra_terms) or "Brak.",
    }


# ── Render ───────────────────────────────────────────────────────────────────


def jinja_env(**options: Any) -> Environment:
    return Environment(autoescape=True, **options)


def render_docx(context: dict[str, Any]) -> bytes:
    """DOCX umowy. Znak nowej linii w polu tekstowym staje się złamaniem
    wiersza (docxtpl), ``&``/``<`` są escapowane (``autoescape``)."""
    template = DocxTemplate(str(TEMPLATE_PATH))
    template.render(context, jinja_env=jinja_env())
    # Plik idzie do trenera: bez autora z szablonu.
    clear_author_metadata(template.docx)
    buffer = io.BytesIO()
    template.save(buffer)
    return clear_app_properties(buffer.getvalue())


async def render_pdf(context: dict[str, Any]) -> bytes:
    """PDF tym samym konwerterem co umowa B2B (LibreOffice, kolejka w wątku)."""
    return await pdf_from_docx(render_docx(context))


# ── Pliki ────────────────────────────────────────────────────────────────────


def store_file(training_id: int, name: str, data: bytes) -> str:
    """Zapis pod ``trainings/<id>/agreement/<name>``; zwraca ścieżkę względną."""
    relative = f"{SUBDIR}/{int(training_id)}/agreement/{name}"
    target = Path(storage_service.STORAGE_ROOT) / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{target.name}.part")
    temporary.write_bytes(data)
    os.replace(temporary, target)
    return relative


def read_file(relative: str) -> bytes:
    """Plik szkolenia spod ``STORAGE_ROOT/trainings`` (bez wyjścia poza katalog)."""
    root = Path(storage_service.STORAGE_ROOT).resolve()
    path = (root / relative).resolve()
    try:
        path.relative_to(root / SUBDIR)
    except ValueError:
        raise FileNotFoundError("poza katalogiem szkoleń") from None
    return path.read_bytes()


def file_name(training: Training, *, suffix: str = "") -> str:
    """„Umowa szkoleniowa SZK-12-2026 Kowalski Jan.pdf” — bez polskich znaków,
    jak nazwy umów B2B (``b2b_contract_filename``)."""
    number = re.sub(r"\s*/\s*", "-", _text(training.agreement_number))
    person = _text((training.partner or {}).get("full_name"))
    parts = [
        "Umowa szkoleniowa",
        _ascii_words(number),
        _ascii_words(_surname_first(person)),
        _ascii_words(suffix),
    ]
    return f"{' '.join(p for p in parts if p)}.pdf"


# ── Generowanie ──────────────────────────────────────────────────────────────


async def generate(
    db: AsyncSession,
    training: Training,
    *,
    partner: Mapping[str, Any],
    company_email: str,
    now: datetime,
) -> None:
    """Numer, migawka danych trenera i zamrożony PDF umowy. Nie commituje.

    Ponowne generowanie (poprawka danych) tylko przed podpisem trenera — nowy
    PDF zastępuje zamrożony, numer umowy zostaje. ``db`` zostaje w sygnaturze
    dla spójności ścieżki (wszystko, czego trzeba, jest w ``training``)."""
    if training.status != "accepted":
        raise TrainingError(409, MSG_WRONG_STATUS, "wrong_status")
    if training.trainer_signed_at is not None or training.trainer_signed_pdf_path:
        raise TrainingError(409, MSG_TRAINER_SIGNED, "already_signed")
    missing = missing_partner_fields(partner)
    if missing:
        raise TrainingError(
            422,
            "Brakuje danych trenera do umowy: " + ", ".join(missing) + ".",
            "partner_incomplete",
        )
    if fees_total(training) <= 0:
        raise TrainingError(422, MSG_FEES, "fees_missing")
    today = business_date(now)
    snapshot = clean_partner(partner)
    if not training.agreement_number:
        training.agreement_number = f"SZK/{training.id}/{today.year}"
    context = build_context(
        training, snapshot, company_email=company_email, agreement_date=today
    )
    try:
        pdf = await render_pdf(context)
    except PdfPreviewUnavailable as error:
        raise TrainingError(503, MSG_PDF, "pdf_unavailable") from error
    digest = hashlib.sha256(pdf).hexdigest()
    training.partner = snapshot
    training.agreement_pdf_path = store_file(
        training.id, f"umowa-{digest[:16]}.pdf", pdf
    )
    training.agreement_pdf_sha256 = digest
    training.agreement_generated_at = now
