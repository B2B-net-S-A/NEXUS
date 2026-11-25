"""Wzory bazowe „Zacznij od istniejącego wzoru” i lista pól z gotowego szablonu.

Baza to szablon docxtpl z repo (dziś: „Umowa B2B — szkolenia”) albo
zatwierdzony wzór własny. Z pliku bazy ``sandbox.discover`` zbiera ścieżki,
a ``fields_from_paths`` układa z nich listę pól: etykieta, rodzaj, grupa
i źródło z podpowiedzi poniżej (nieznana ścieżka = pole tekstowe „ręcznie”,
człowiek poprawia etykietę w kroku „Szkic i pola”). To, co liczy kod
(``company.*``, ``g.*``, słownie kwot), nie jest polem.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from app.services.custom_templates.fields import (
    MONEY_WORDS_SUFFIX,
    RESERVED_ROOTS,
    CustomField,
    ItemKey,
)
from app.services.custom_templates.sandbox import Validation

TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "templates"


@dataclass(frozen=True)
class BaseTemplate:
    key: str
    label: str
    description: str
    path: Path
    kind: str = "contract"


BASES: tuple[BaseTemplate, ...] = (
    BaseTemplate(
        key="training_agreement",
        label="Umowa B2B — szkolenia",
        description=(
            "Umowa o współpracę B2B w zakresie usług szkoleniowych z agendą "
            "(Załącznik nr 1) i klauzulą RODO (Załącznik nr 2). Dziś: szkolenie zdalne."
        ),
        path=TEMPLATES_DIR / "contract" / "umowa_szkoleniowa_pl.docx",
    ),
)
BASES_BY_KEY = {b.key: b for b in BASES}

#: Podpowiedzi dla znanych ścieżek: (etykieta, rodzaj, źródło, wymagane).
HINTS: dict[str, tuple[str, str, str, bool]] = {
    "agreement_date": ("Data umowy", "date", "manual", True),
    "document_date": ("Data dokumentu", "date", "manual", True),
    "company_email": ("E-mail spółki do korespondencji", "email", "manual", False),
    "partner.gender": ("Płeć Partnera (formy Pan/Pani)", "gender", "candidate", True),
    "partner.name": ("Imię i nazwisko", "text", "candidate", True),
    "partner.name_instrumental": (
        "Imię i nazwisko — narzędnik („z Panem …”)",
        "text",
        "candidate",
        True,
    ),
    "partner.company": ("Firma (CEIDG)", "text", "ceidg", True),
    "partner.legal_name": ("Firma (CEIDG)", "text", "ceidg", True),
    "partner.address": ("Adres firmy — ulica", "text", "ceidg", True),
    "partner.business_address": ("Adres firmy", "text", "ceidg", True),
    "partner.postal_city": ("Adres firmy — kod i miejscowość", "text", "ceidg", False),
    "partner.nip": ("NIP", "text", "ceidg", True),
    "partner.regon": ("REGON", "text", "ceidg", False),
    "partner.email": ("E-mail Partnera", "email", "candidate", False),
    "partner.phone": ("Telefon Partnera", "text", "candidate", False),
    "client.name": ("Klient", "text", "clients", True),
    "t.title": ("Tytuł szkolenia", "text", "manual", True),
    "t.topic": ("Temat szkolenia", "text", "manual", False),
    "t.date": ("Data szkolenia (tekst)", "text", "manual", False),
    "t.hours": ("Godziny", "text", "manual", False),
    "t.duration": ("Czas trwania", "text", "manual", False),
    "t.platform": ("Platforma", "text", "manual", False),
    "t.participants": ("Liczba uczestników", "text", "manual", False),
    "t.schedule": ("Termin(y) szkolenia", "textarea", "manual", True),
    "t.participant_materials": (
        "Materiały dla uczestników",
        "textarea",
        "manual",
        False,
    ),
    "exam_text": ("Test wiedzy", "textarea", "manual", False),
    "extra_terms": ("Dodatkowe ustalenia", "textarea", "manual", False),
    "rights.works": ("Utwory objęte przeniesieniem praw", "textarea", "manual", False),
    "rights.own": ("Materiały własne Partnera", "textarea", "manual", False),
    "rights.third_party": ("Materiały osób trzecich", "textarea", "manual", False),
    "fees.prep": ("Wynagrodzenie — przygotowanie", "money", "manual", False),
    "fees.delivery": ("Wynagrodzenie — przeprowadzenie", "money", "manual", False),
    "fees.presentation": ("Wynagrodzenie — prezentacja", "money", "manual", False),
    "fees.audio": ("Wynagrodzenie — nagrania audio/wideo", "money", "manual", False),
    "fees.rights": ("Wynagrodzenie — prawa autorskie", "money", "manual", False),
    "fees.total": ("Wynagrodzenie łącznie netto", "money", "manual", True),
    "deliv.materials.flag": (
        "Materiały szkoleniowe (TAK / NIE)",
        "text",
        "manual",
        False,
    ),
    "deliv.materials.due": ("Materiały szkoleniowe — termin", "text", "manual", False),
    "deliv.materials.format": (
        "Materiały szkoleniowe — format",
        "text",
        "manual",
        False,
    ),
    "deliv.presentation.flag": ("Prezentacja (TAK / NIE)", "text", "manual", False),
    "deliv.audio.flag": ("Nagrania audio/wideo (TAK / NIE)", "text", "manual", False),
    "deliv.files_due": ("Termin przekazania plików", "text", "manual", False),
    "deliv.files_format": ("Format plików", "text", "manual", False),
    "deliv.other": ("Inne pliki", "text", "manual", False),
}

#: Grupa formularza po pierwszym członie ścieżki.
GROUPS: dict[str, str] = {
    "partner": "Partner",
    "client": "Klient",
    "t": "Szkolenie",
    "agenda": "Szkolenie",
    "fees": "Pieniądze",
    "deliv": "Utwory i materiały",
    "rights": "Utwory i materiały",
}

_LIST_LABELS = {"agenda": "Agenda (moduły)"}
_ITEM_LABELS = {"no": "Nr", "text": "Treść", "title": "Tytuł"}
_DATE_HINT = re.compile(r"(^|[._])(date|data|day)($|[._])|_on$")
_MONEY_HINT = re.compile(r"(^fees\.|amount|kwota|stawka|rate|fee|price|limit_)")


def _humanize(path: str) -> str:
    leaf = path.split(".")[-1].replace("_", " ").strip()
    return leaf[:1].upper() + leaf[1:] if leaf else path


def fields_from_paths(found: Validation) -> list[CustomField]:
    """Lista pól z odkrytych ścieżek (``sandbox.discover``)."""
    used = set(found.used)
    computed_words = {u for u in used if u.endswith(MONEY_WORDS_SUFFIX)}
    money = {u.removesuffix(MONEY_WORDS_SUFFIX) for u in computed_words}
    needs_gender = any(u.split(".")[0] == "g" for u in used)
    paths = sorted(
        u
        for u in used
        if u.split(".")[0] not in RESERVED_ROOTS and u not in computed_words
    )
    if needs_gender and not any(p.endswith(".gender") or p == "gender" for p in paths):
        paths.insert(0, "partner.gender")
    # Ścieżka będąca „katalogiem” innej (``{% if partner %}`` obok
    # ``partner.nip``) nie jest polem.
    prefixes = {
        ".".join(p.split(".")[:n]) for p in paths for n in range(1, p.count(".") + 1)
    }
    out: list[CustomField] = []
    for path in paths:
        if path in prefixes or path in found.lists:
            continue
        label, kind, source, required = HINTS.get(path, ("", "", "manual", False))
        if not kind:
            if path in money or _MONEY_HINT.search(path):
                kind = "money"
            elif _DATE_HINT.search(path):
                kind = "date"
            elif "email" in path:
                kind = "email"
            else:
                kind = "text"
        if path in money:
            kind = "money"
        out.append(
            CustomField(
                key=path,
                label=label or _humanize(path),
                kind=kind,
                group=GROUPS.get(path.split(".")[0], "Dokument"),
                source=source,
                required=required,
            )
        )
    for name, keys in sorted(found.lists.items()):
        if name.split(".")[0] in RESERVED_ROOTS:
            continue
        out.append(
            CustomField(
                key=name,
                label=_LIST_LABELS.get(name, _humanize(name)),
                kind="list",
                group=GROUPS.get(name.split(".")[0], "Dokument"),
                item_keys=tuple(
                    ItemKey(k, _ITEM_LABELS.get(k, _humanize(k))) for k in sorted(keys)
                ),
            )
        )
    order = list(GROUPS.values())
    out.sort(key=lambda f: order.index(f.group) if f.group in order else -1)
    return out
