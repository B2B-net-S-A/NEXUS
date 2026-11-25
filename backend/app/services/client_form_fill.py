"""Formularz CV klienta: wartości pól z CV, screeningu i notatek (0522, PR 2).

Pola wzoru odczytał kod (``client_form_structure``). Tu model wpisuje do nich
fakty o kandydacie — podział pracy jak w odczytach „znajdź i zacytuj” (F25,
``debrief_from_text``):

* model zwraca każdą wartość z DOSŁOWNYM cytatem z CV albo notatek,
* KOD odrzuca wartość bez cytatu ze źródła, „TAK/NIE” spoza tych dwóch słów,
  ocenę w skali, której liczby nie ma w cytacie, wartość z e-mailem albo
  telefonem, datę i okres, których nie ma w cytacie, certyfikat „w trakcie”
  i opis wielokrotnie dłuższy od swoich cytatów. Imię i nazwisko wpisuje kod z profilu.

Czego zabrakło, zostaje puste i rekruter to uzupełnia — ocen 1–10 i numerów
certyfikatów zwykle nie ma w żadnym źródle. Model jest dodatkiem: błąd albo
brak klucza = formularz z samym imieniem i nazwiskiem do uzupełnienia ręcznie.
Do logu idą liczby, nie treść.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Optional

from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_today
from app.models.ai_feature import AIFeatureKey
from app.services import client_form_structure
from app.services.ai_models import model_chain_for
from app.services.ai_quota import ai_feature
from app.services.cv_ongoing import ONGOING_WORDS
from app.services.cv_qc import _json_object
from app.services.interview_slot_mail import _norm, _quote_in_text
from app.services.llm_prompts import CLIENT_FORM_FILL
from app.services.llm_providers import api_key_configured
from app.services.prompt_fencing import fence, json_for_prompt

logger = logging.getLogger(__name__)

FEATURE = AIFeatureKey.client_form_fill
CV_MAX = 30_000
NOTES_MAX = 15_000
VALUE_MAX = 1_500
EXTRA_ROWS_MAX = 10
QUOTE_PARTS_MAX = 8
# Tyle znaków może stać między kolejnymi liniami cytatu (``_lines_in_order``):
# kolumna boczna („Analytical Thinking & Problem-Solving”) albo stopka strony
# z klauzulą RODO (ok. 230 znaków w CV z Testera CEZ, 19.11.2026).
LINE_GAP_MAX = 400
ROWS_PARSED_MAX = 60

SOURCE_CV = "cv"
SOURCE_NOTES = "notes"
SOURCE_PROFILE = "profile"
SOURCE_RECRUITER = "recruiter"

MSG_UNAVAILABLE = (
    "Nie udało się wypełnić formularza automatycznie — uzupełnij pola ręcznie."
)

NAME_LABEL = re.compile(r"imi[eę]\s+i\s+nazwisko", re.IGNORECASE)
CITY_LABEL = re.compile(r"miejsce\s+zamieszkania", re.IGNORECASE)
# „Firma:” w tabeli punktowej to wykonawca, czyli my — nie pracodawca osoby.
VENDOR_LABEL = re.compile(r"^\s*(firma|wykonawca)\s*$", re.IGNORECASE)
VENDOR_NAME = "B2B.net S.A."
RULES_MAX = 15_000
_POINTS = re.compile(r"^\s*(\d{1,3})(?:\s*(?:pkt|punkt\w*))?\.?\s*$", re.IGNORECASE)
YES_NO_LABEL = re.compile(r"tak\s*/\s*nie", re.IGNORECASE)
SCALE_LABEL = re.compile(r"skali|\b1\s*[-–]\s*10\b", re.IGNORECASE)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_PHONE = re.compile(r"\+?\d[\d \-]{7,}\d")
# Daty idą do klienta w przetargu, więc kod sprawdza je sam (staging 19.11.2026:
# „Data wydania” = „1,5 roku”, „Okres pracy” z miesiącem, którego CV nie podaje).
DATE_LABEL = re.compile(r"\bdata\b", re.IGNORECASE)
PERIOD_LABEL = re.compile(r"\bokres\b", re.IGNORECASE)
_DATE = r"(?:(0[1-9]|1[0-2])\.)?((?:19|20)\d{2})"
_DATE_VALUE = re.compile(rf"^{_DATE}$")
_PERIOD_VALUE = re.compile(rf"^{_DATE}\s*[-–—]\s*(?:{_DATE}|(obecnie))$", re.IGNORECASE)
_ONGOING = re.compile(
    # Wspólna lista plus luźne rdzenie („obecnym”, „dzisiejszego”, „since 2021”).
    rf"\b{ONGOING_WORDS}\b|obecn|dzi[sś]|present|current|since|\bod\b",
    re.IGNORECASE,
)
_MONTH_NAMES = (
    ("sty", "jan"),
    ("lut", "feb"),
    ("mar",),
    ("kwi", "apr"),
    ("maj", "may"),
    ("cze", "jun"),
    ("lip", "jul"),
    ("sie", "aug"),
    ("wrz", "sep"),
    ("paź", "paz", "oct"),
    ("lis", "nov"),
    ("gru", "dec"),
)
# Certyfikat „w trakcie”/„preparing for exam” to brak certyfikatu.
CERTIFICATE_LABEL = re.compile(r"certyfikat|certificat", re.IGNORECASE)
_NOT_OBTAINED = re.compile(
    r"w\s+trakcie|przygotow|preparing|in\s+progress|planowan|planned|zamierzam",
    re.IGNORECASE,
)
# Opis to przekład czynności z CV, więc kod nie porówna go z cytatem słowo
# w słowo — ale opis wielokrotnie dłuższy od cytatów mówi o rzeczach bez
# pokrycia (staging 19.11.2026: 7 opisów z jednym krótkim cytatem, cytat =
# 11–18 % długości wartości; w rzetelnych odpowiedziach 51–197 %).
DESCRIPTION_LABEL = re.compile(r"\bopis\b", re.IGNORECASE)
QUOTE_SHARE_MIN = 0.4


@dataclass(frozen=True)
class Sources:
    cv: str
    notes: str
    # 0525: tekst „Szczegółowego opisu oceny” z Plików rekrutacji (zał. 5 CEZ)
    # — zasady punktacji tabeli punktowej. Pusty = pola punktów zostają puste.
    rules: str = ""


def _short(value: Any, limit: int = VALUE_MAX) -> Optional[str]:
    # Model oddaje punkty i lata liczbą (2, a nie "2") — to też wartość.
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        value = str(int(value)) if float(value).is_integer() else str(value)
    if not isinstance(value, str):
        return None
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in value.splitlines()]
    text = "\n".join(line for line in lines if line)
    return text[:limit] or None


def _lines_in_order(quote: Any, text: str) -> Optional[str]:
    """Wielowierszowy cytat, którego linie stoją w źródle po kolei i blisko siebie.

    Dwukolumnowy PDF wstawia kolumnę boczną w środek punktu CV — osobną linią
    albo na początku tej samej linii („…based on existing” / „Collaboration
    & Communication specifications,”; staging 19.11.2026: opis Asseco i okres
    pracy odrzucone), a stopka strony — między dwie linie punktu. Model cytuje
    punkt w całości, więc cytat nie stoi w źródle jednym ciągiem. Każda linia musi stać w źródle dosłownie, w kolejności
    cytatu i najwyżej ``LINE_GAP_MAX`` znaków za poprzednią — linie z różnych
    miejsc CV nie składają się w jeden cytat.
    """
    if not isinstance(quote, str):
        return None
    quote = quote.strip().strip("„”\"'")
    lines = [_norm(line) for line in quote.splitlines() if line.strip()]
    if len(lines) < 2 or any(len(line) < 3 for line in lines):
        return None
    source = _norm(text)
    start = source.find(lines[0])
    while start != -1:
        end = start + len(lines[0])
        for line in lines[1:]:
            at = source.find(line, end, end + LINE_GAP_MAX + len(line))
            if at == -1:
                break
            end = at + len(line)
        else:
            return quote
        start = source.find(lines[0], start + 1)
    return None


def _grounded_one(quote: Any, sources: Sources) -> tuple[Optional[str], Optional[str]]:
    for source, text in ((SOURCE_CV, sources.cv), (SOURCE_NOTES, sources.notes)):
        found = _quote_in_text(quote, text)
        if found is None:
            found = _lines_in_order(quote, text)
        if found is not None:
            return source, found
    return None, None


def _grounded(quote: Any, sources: Sources) -> tuple[Optional[str], Optional[str]]:
    """(źródło, cytat) — cytat musi stać w CV albo w notatkach.

    Cytat może być listą fragmentów: tekst CV z dwukolumnowego PDF-a przeplata
    punkty z kolumną boczną, więc opis złożony z kilku punktów nie stoi w CV
    jednym ciągiem (staging 26.10.2026: 3 z 4 odrzuconych wartości). Każdy
    fragment musi stać w źródle osobno.
    """
    if isinstance(quote, list):
        found = [_grounded_one(part, sources) for part in quote[:QUOTE_PARTS_MAX]]
        if not found or any(part is None for _, part in found):
            return None, None
        source = (
            SOURCE_CV if any(src == SOURCE_CV for src, _ in found) else SOURCE_NOTES
        )
        return source, " … ".join(part for _, part in found if part)
    return _grounded_one(quote, sources)


def _contact(value: str) -> bool:
    """E-mail albo numer telefonu (9+ cyfr — okres „2019 - 2023” to nie telefon)."""
    if _EMAIL.search(value):
        return True
    return any(
        sum(ch.isdigit() for ch in match.group(0)) >= 9
        for match in _PHONE.finditer(value)
    )


def _date_in_quote(month: Optional[str], year: str, quote: str) -> bool:
    """Rok (i miesiąc, gdy wartość go ma) stoi w cytacie — nic nie jest dopisane."""
    text = quote.lower()
    if not re.search(rf"(?<!\d){year}(?!\d)", text):
        return False
    if month is None:
        return True
    number = rf"0?{int(month)}"
    if re.search(rf"(?<!\d){number}\s*[./-]\s*{year}(?!\d)", text) or re.search(
        rf"(?<!\d){year}\s*[./-]\s*{number}(?!\d)", text
    ):
        return True
    names = "|".join(_MONTH_NAMES[int(month) - 1])
    return bool(re.search(rf"\b(?:{names})\w*\.?\s*{year}(?!\d)", text))


def _checked_date(label: str, value: str, quote: str) -> Optional[bool]:
    """``True``/``False`` dla pól z datą („Data …”, „Okres …”), ``None`` dla reszty."""
    if PERIOD_LABEL.search(label):
        match = _PERIOD_VALUE.match(value.strip())
        if match is None:
            return False
        start_month, start_year, end_month, end_year, ongoing = match.groups()
        if not _date_in_quote(start_month, start_year, quote):
            return False
        if ongoing:
            return bool(_ONGOING.search(quote))
        return _date_in_quote(end_month, end_year, quote)
    if DATE_LABEL.search(label):
        match = _DATE_VALUE.match(value.strip())
        return match is not None and _date_in_quote(*match.groups(), quote)
    return None


def _checked_value(
    label: str,
    value: str,
    quote: str,
    max_points: Optional[int] = None,
    context: str = "",
) -> Optional[str]:
    """Wartość po kontrolach kodu albo ``None`` (pole zostaje do uzupełnienia).

    ``context`` to nazwa wiersza i sekcji pola — po niej kod poznaje wiersz
    certyfikatu, gdy kolumna nazywa się tylko „Instytucja wydająca”.
    """
    if _contact(value):
        return None
    # „NIE” albo 0 pkt przy certyfikacie „w trakcie” to prawda — reszta nie.
    if (
        CERTIFICATE_LABEL.search(f"{label} {context}")
        and _NOT_OBTAINED.search(f"{value} {quote}")
        and value.strip().upper() not in ("NIE", "0")
    ):
        return None
    if max_points is not None:
        # Wynik w tabeli punktowej: liczba całkowita od 0 do maksimum wiersza.
        match = _POINTS.match(value)
        if match is None or int(match.group(1)) > max_points:
            return None
        return match.group(1)
    dated = _checked_date(label, value, quote)
    if dated is not None:
        return value if dated else None
    if YES_NO_LABEL.search(label):
        word = value.strip().upper()
        return word if word in ("TAK", "NIE") else None
    if SCALE_LABEL.search(label):
        number = value.strip()
        if not number.isdigit() or not 1 <= int(number) <= 10:
            return None
        return number if re.search(rf"(?<!\d){number}(?!\d)", quote) else None
    if DESCRIPTION_LABEL.search(label) and len(quote) < QUOTE_SHARE_MIN * len(value):
        return None
    return value


# Tyle razy kod zdejmuje nawias zamykający obiekt przed „, "klucz"”.
EARLY_CLOSE_REPAIRS = 3


def parse_answer(raw: str) -> dict[str, Any]:
    """JSON odpowiedzi modelu; naprawia obiekt zamknięty za wcześnie.

    Staging 23.11.2026 (CEZ 789225): 2 z 3 odpowiedzi kończyły ``extra_rows``
    nawiasem głównego obiektu i pisały dalej (``…]}, "roles": […]}``).
    ``json.loads`` padał na „Extra data”, więc formularz zostawał z samym
    imieniem. Gdy za zamkniętym obiektem stoi przecinek, kod zdejmuje ten
    nawias i czyta dalej — inny błąd składni zostaje błędem.
    """
    text = raw
    for _ in range(EARLY_CLOSE_REPAIRS):
        try:
            return _json_object(text)
        except json.JSONDecodeError as exc:
            rest = exc.doc[exc.pos :].lstrip()
            head = exc.doc[: exc.pos].rstrip()
            if not (
                exc.msg.startswith("Extra data")
                and rest.startswith(",")
                and head.endswith("}")
            ):
                raise
            text = head[:-1] + exc.doc[exc.pos :]
    return _json_object(text)


def name_fields(structure: dict[str, Any]) -> list[str]:
    return _line_fields(structure, NAME_LABEL)


def _line_fields(structure: dict[str, Any], pattern: re.Pattern[str]) -> list[str]:
    return [
        item["id"]
        for item in structure.get("fields") or []
        if item.get("kind") == "line" and pattern.search(item.get("label") or "")
    ]


def extendable_tables(structure: dict[str, Any]) -> list[dict[str, Any]]:
    """Tabele z „…”: kolumny wiersza wzorcowego (``c<kolumna>`` → etykieta).

    Kontynuacja sekcji (druga tabela „Doświadczenia zawodowego” CEZ) nie rośnie:
    pełna lista stanowisk idzie do pierwszej tabeli, a dopisane wiersze w obu
    rozbijałyby kolejność od najnowszego (staging 23.11.2026).
    """
    continued = client_form_structure.continued_tables(structure)
    return [
        {
            "table": table["index"],
            "title": table.get("title"),
            "columns": table.get("columns") or {},
        }
        for table in structure.get("tables") or []
        if table.get("extendable")
        and table.get("template_row") is not None
        and int(table["index"]) not in continued
    ]


def check_parse(
    raw: str,
    *,
    structure: dict[str, Any],
    sources: Sources,
    candidate_name: str,
    candidate_city: str = "",
    today: Optional[date] = None,
) -> dict[str, Any]:
    """Odpowiedź modelu → wartości, które przeszły kontrolę kodu. Czysta funkcja.

    Imię i nazwisko oraz miejsce zamieszkania (gdy profil je zna) wpisuje kod
    z profilu — model ich nie nadpisuje. Lata doświadczenia (i punkty z lat)
    liczy ``client_form_years`` ze stanowisk, które model zacytował.
    """
    labels = {
        item["id"]: item.get("label") or "" for item in structure.get("fields") or []
    }
    contexts = {
        item["id"]: " ".join(
            item.get(key) or "" for key in ("row_label", "section", "table")
        )
        for item in structure.get("fields") or []
    }
    limits = {
        item["id"]: int(item["max_points"])
        for item in structure.get("fields") or []
        if item.get("max_points") is not None
    }
    profile = {
        **{field_id: candidate_name for field_id in name_fields(structure)},
        **{field_id: VENDOR_NAME for field_id in _line_fields(structure, VENDOR_LABEL)},
        **{
            field_id: candidate_city for field_id in _line_fields(structure, CITY_LABEL)
        },
    }
    profile = {
        field_id: value.strip() for field_id, value in profile.items() if value.strip()
    }
    names = set(profile)
    fields: dict[str, dict[str, Any]] = {
        field_id: {"value": value, "source": SOURCE_PROFILE, "quote": None}
        for field_id, value in profile.items()
    }
    dropped = 0
    data = parse_answer(raw) if raw else {}
    for item in data.get("fields") or []:
        if not isinstance(item, dict) or item.get("id") not in labels:
            dropped += 1
            continue
        field_id = item["id"]
        if field_id in names:
            continue
        if field_id in limits and not sources.rules.strip():
            dropped += 1  # punkty tylko według zasad oceny z Plików rekrutacji
            continue
        value = _short(item.get("value"))
        source, quote = _grounded(item.get("quote"), sources)
        checked = (
            _checked_value(
                labels[field_id],
                value,
                quote,
                limits.get(field_id),
                context=contexts[field_id],
            )
            if value and quote is not None
            else None
        )
        if checked is None:
            dropped += 1
            continue
        fields[field_id] = {"value": checked, "source": source, "quote": quote}

    # Bez odpowiedzi modelu nie ma stanowisk — siatki lat też nie ma.
    years, years_dropped = (
        _years(data, structure, sources, today or business_today()) if data else ({}, 0)
    )
    dropped += years_dropped
    for field_id, entry in years.items():
        if field_id in names:
            continue
        model_value = fields.get(field_id)
        if entry["value"] is None and model_value:
            # Kod nie policzył stażu z ról, a model ma wartość z cytatem
            # (np. „0” z notatki „nie pracował w służbie zdrowia”) — zostaje
            # wartość modelu, siatka obok.
            fields[field_id] = {**model_value, "years": entry["years"]}
        else:
            fields[field_id] = entry

    tables = {table["table"]: table for table in extendable_tables(structure)}
    extra_rows: list[dict[str, Any]] = []
    for row in (data.get("extra_rows") or [])[:ROWS_PARSED_MAX]:
        if not isinstance(row, dict) or row.get("table") not in tables:
            dropped += 1
            continue
        table = tables[row["table"]]
        cells: dict[str, dict[str, Any]] = {}
        for column, cell in (row.get("cells") or {}).items():
            if column not in table["columns"] or not isinstance(cell, dict):
                dropped += 1
                continue
            label = table["columns"][column]
            value = _short(cell.get("value"))
            source, quote = _grounded(cell.get("quote"), sources)
            checked = (
                _checked_value(label, value, quote, context=table.get("title") or "")
                if value and quote is not None
                else None
            )
            if checked is None:
                dropped += 1
                continue
            cells[column] = {"value": checked, "source": source, "quote": quote}
        if cells:
            extra_rows.append({"table": table["table"], "cells": cells})
    # Najpierw puste wiersze wzoru, dopiero reszta ponad wzór — z limitem.
    kept: list[dict[str, Any]] = []
    per_table: dict[int, int] = {}
    for row in _into_free_rows(structure, fields, extra_rows):
        if per_table.get(row["table"], 0) >= EXTRA_ROWS_MAX:
            dropped += 1
            continue
        per_table[row["table"]] = per_table.get(row["table"], 0) + 1
        kept.append(row)
    return {"fields": fields, "extra_rows": kept, "dropped": dropped}


def _years(
    data: dict[str, Any], structure: dict[str, Any], sources: Sources, today: date
) -> tuple[dict[str, dict[str, Any]], int]:
    """Pola lat ze stanowisk zacytowanych przez model (``client_form_years``)."""
    from app.services import client_form_years  # noqa: PLC0415

    labels = " \n ".join(
        f"{item.get('row_label') or ''} {item.get('label') or ''}"
        for item in structure.get("fields") or []
    )

    def grounded(quote: Any) -> tuple[Optional[str], Optional[str]]:
        return _grounded(quote, sources)

    def grounded_rules(quote: Any) -> tuple[Optional[str], Optional[str]]:
        # Próg punktów albo minimum stażu: z zasad oceny albo z wymagań wzoru.
        for text in (sources.rules, labels):
            found = _quote_in_text(quote, text)
            if found is not None:
                return "rules", found
        return None, None

    return client_form_years.build(
        data,
        structure=structure,
        grounded=grounded,
        grounded_rules=grounded_rules,
        date_in_quote=_date_in_quote,
        ongoing=_ONGOING,
        today=today,
    )


def _into_free_rows(
    structure: dict[str, Any],
    fields: dict[str, dict[str, Any]],
    extra_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Dopisane wiersze najpierw w puste wiersze wzoru tej tabeli.

    Model bywa, że pierwsze stanowisko wpisze do wiersza 1, a kolejne od razu
    do „extra_rows” — w dokumencie zostałyby puste wiersze 2–3 nad nimi.
    """
    free: dict[int, list[dict[str, str]]] = {}
    for item in structure.get("fields") or []:
        if item.get("kind") != "cell" or not (item.get("row_label") or "").startswith(
            "Wiersz "
        ):
            continue
        t_part, r_part, c_part = item["id"].split(".")
        table, row = int(t_part[1:]), int(r_part[1:])
        rows = free.setdefault(table, [])
        if not rows or rows[-1]["_row"] != str(row):
            rows.append({"_row": str(row)})
        rows[-1][c_part] = item["id"]
    left: list[dict[str, Any]] = []
    for extra in extra_rows:
        slots = [
            slot
            for slot in free.get(extra["table"], [])
            if not any(
                (fields.get(field_id) or {}).get("value")
                for key, field_id in slot.items()
                if key != "_row"
            )
        ]
        if not slots:
            left.append(extra)
            continue
        slot = slots[0]
        for column, cell in extra["cells"].items():
            if column in slot:
                fields[slot[column]] = cell
    return left


def missing_ids(structure: dict[str, Any], fields: dict[str, Any]) -> list[str]:
    """Pola do uzupełnienia — bez wolnych wierszy wzoru (``spare_ids``)."""
    return client_form_structure.missing_ids(structure, fields)


def _years_prompt_fields(structure: dict[str, Any]) -> list[dict[str, str]]:
    """Pola lat z nazwą wiersza — model bez tej listy pomijał „Kompetencje
    dodatkowe” (staging 20.11.2026: dokumentacja, NFZ, rejestry bez wpisu)."""
    from app.services.client_form_years import years_fields  # noqa: PLC0415

    ids = years_fields(structure)
    return [
        {"id": item["id"], "row": item.get("row_label") or item.get("label") or ""}
        for item in structure.get("fields") or []
        if item["id"] in ids
    ]


def build_prompt(structure: dict[str, Any], sources: Sources) -> str:
    fields = [
        {
            key: item.get(key)
            for key in ("id", "label", "row_label", "section", "table", "max_points")
            if item.get(key)
        }
        for item in client_form_structure.with_table_titles(structure)
        if not (
            item.get("kind") == "line"
            and (
                NAME_LABEL.search(item.get("label") or "")
                or VENDOR_LABEL.search(item.get("label") or "")
            )
        )
        and (item.get("max_points") is None or sources.rules.strip())
    ]
    return CLIENT_FORM_FILL.render(
        fields=json_for_prompt(fields),
        tables=json_for_prompt(extendable_tables(structure)),
        years_fields=json_for_prompt(_years_prompt_fields(structure)),
        cv=fence("cv", sources.cv[:CV_MAX]),
        notes=fence("screening_notes", sources.notes[:NOTES_MAX]),
        rules=fence("scoring_rules", sources.rules[:RULES_MAX]),
    )


def _call_model(system: str, prompt: str, chain: tuple[str, ...]) -> str:
    from app.services.claude_client import call_claude, text_of  # noqa: PLC0415

    message = call_claude(
        model=chain[0],
        fallback_models=list(chain[1:]) or None,
        max_tokens=12000,
        thinking={"type": "disabled"},
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    return text_of(message)


async def fill(
    db: AsyncSession,
    *,
    structure: dict[str, Any],
    sources: Sources,
    candidate_name: str,
    user_id: int,
    candidate_city: str = "",
) -> dict[str, Any]:
    """Wartości pól formularza. Nigdy nie rzuca — model to podpowiedź."""
    chain = tuple(model_chain_for(FEATURE))
    fallback = check_parse(
        "",
        structure=structure,
        sources=sources,
        candidate_name=candidate_name,
        candidate_city=candidate_city,
    )
    if not api_key_configured(chain[0]):
        return {
            **fallback,
            "status": "unavailable",
            "message": MSG_UNAVAILABLE,
            "model": None,
        }
    try:
        system = CLIENT_FORM_FILL.system_prompt or ""
        async with ai_feature(db, FEATURE, user_id=user_id):
            # Licznik AI zapisuje wiersz w tej sesji — commit PRZED modelem.
            await db.commit()
            raw = await run_in_threadpool(
                _call_model, system, build_prompt(structure, sources), chain
            )
        result = check_parse(
            raw,
            structure=structure,
            sources=sources,
            candidate_name=candidate_name,
            candidate_city=candidate_city,
        )
    except Exception as exc:  # noqa: BLE001 — AI to podpowiedź, nigdy bramka
        logger.warning("client_form_fill: model niedostępny (%s)", type(exc).__name__)
        return {
            **fallback,
            "status": "unavailable",
            "message": MSG_UNAVAILABLE,
            "model": None,
        }
    logger.info(
        "client_form_fill: %d pól, %d wierszy dopisanych, %d odrzuconych",
        len(result["fields"]),
        len(result["extra_rows"]),
        result["dropped"],
    )
    return {**result, "status": "ok", "message": None, "model": chain[0]}
