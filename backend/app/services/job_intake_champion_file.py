"""Plik Profilu Championa na /jobs/new — odczyt tabel bez modelu (D4, 10.10.2026).

Do tej daty `POST /api/job-intake/read-file` spłaszczał KAŻDY plik do tekstu
(akapity, potem każda komórka tabeli w osobnej linii — para etykieta / wartość
ginęła), ucinał go na 20 000 znaków i oddawał czytnikowi requestów (AI).
Delivery Lead, który miał już wypełniony wzór Word Profilu Championa,
dostawał więc zgadywanie modelu zamiast własnych wpisów.

Wypełniony wzór czyta teraz ta sama ścieżka co import w istniejącej
rekrutacji (`champion_document.table_profile` + `champion_intake.prepare_profile`,
jak w `champion_intake.preview_document`): z tabel, bez modelu i bez limitu
znaków. Wynik ma kształt odczytu requestu (`job_request_intake.RequestIntake`),
żeby formularz nie rozróżniał źródeł.

Zasady, które łatwo cofnąć „przy okazji”:

* **Wzór rozpoznają etykiety tabel, nigdy nazwa pliku** — pusty wzór też jest
  rozpoznany, dlatego osobno sprawdzamy, czy ktokolwiek coś w nim wpisał.
* **Źródłem pól jest „document”**, nie „request”: to wpis Delivery Leada we
  wzorze, a nie cytat z maila klienta. `evidence` zostaje puste.
* **Niczego nie zgadujemy.** Wartość, której normalizacja nie przyjęła
  (stawka dzienna, „ASAP” w dacie), trafia do uwag, a pole zostaje puste.
* **Sekcje bez pola w formularzu nie giną** — wracają w `champion_extras`
  i formularz dokłada je do zapisu profilu.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Optional

from app.schemas.champion import INSIGHT_TEXT_MAX_CHARS
from app.services import champion_intake
from app.services import job_request_intake as request_intake
from app.services.champion_document import folded, meaningful, table_profile
from app.services.champion_requirement_rows import derive, rows_from_legacy

logger = logging.getLogger(__name__)

READER = "champion_form"
# Źródło pól w `provenance` — chip przy polu mówi „z dokumentu”.
BASIS = "document"
EMPTY_FORM_MESSAGE = (
    "To pusty wzór Profilu Championa — wypełnij go albo wgraj zapytanie klienta."
)
PDF_NOTE = (
    "Wygląda na Profil Championa w PDF — wgraj plik .docx, wtedy odczytamy "
    "tabelę bez AI."
)

# Te same trzy rubryki, po których `table_profile` rozpoznaje wzór.
_FORM_MARKERS = ("must-have", "nice-to-have", "pytania od delivery")
_ADVISORY_VALUE_CHARS = 200
_FIELD_LABELS = {
    "basics.role_name": "Nazwa roli",
    "basics.seniority_min_years": "Minimum lat doświadczenia",
    "basics.work_mode": "Tryb pracy",
    "basics.onsite_days_per_week": "Dni w biurze",
    "basics.candidate_location_pref": "Lokalizacja biura",
    "basics.language": "Język pracy",
    "basics.start_date": "Start",
    "basics.deadline": "Deadline na kandydatów",
    "basics.contract_length": "Długość kontraktu",
    "stack.must": "MUST-HAVE",
    "stack.nice": "NICE-TO-HAVE",
}
_INSIGHT_KEYS = ("id", "source", "topic", "audience", "text", "done", "origin")


class EmptyChampionForm(ValueError):
    """Rozpoznany wzór Profilu Championa, w którym nikt nic nie wpisał."""


def read_champion_form(data: bytes, filename: str) -> Optional[dict[str, Any]]:
    """Profil z wypełnionego wzoru Word albo ``None`` (to nie jest wzór).

    ``None`` znaczy „czytaj jak zwykły plik”: inny format, DOCX bez rubryk
    wzoru albo plik, którego nie da się otworzyć — o nim wypowie się zwykła
    ścieżka swoim komunikatem. Pusty wzór rzuca ``EmptyChampionForm``.
    """
    if not (filename or "").lower().endswith(".docx"):
        return None
    try:
        structured = table_profile(data)
    except Exception as exc:  # noqa: BLE001 — nieczytelny plik ocenia zwykła ścieżka
        logger.warning(
            "job_intake_champion_file: table read failed: %s", type(exc).__name__
        )
        return None
    if not structured:
        return None
    draft = structured["profile"]
    draft["intake"] = {"document_context": structured.get("document_context", {})}
    # Limit notatki sekcji 8 — ten sam, do którego przytnie ją zapis profilu
    # (`champion_insights.merge_insights`). Dłuższa komórka „Od klienta”
    # nie przechodzi walidacji profilu i cały wzór wracałby do odczytu przez AI.
    for note in draft.get("insights") or []:
        note["text"] = note["text"][:INSIGHT_TEXT_MAX_CHARS]
    try:
        profile = champion_intake.prepare_profile(
            draft,
            raw_fields=structured["raw_fields"],
            template_version=structured["template_version"],
        )
    except (ValueError, TypeError) as exc:
        # Wzór rozpoznany, ale z wartością spoza schematu profilu: plik
        # przeczyta zwykła ścieżka zamiast odmowy bez wyjaśnienia.
        logger.warning(
            "job_intake_champion_file: profile rejected: %s", type(exc).__name__
        )
        return None
    if _is_blank(profile):
        raise EmptyChampionForm(EMPTY_FORM_MESSAGE)
    return profile


def _is_blank(profile: dict[str, Any]) -> bool:
    project = profile.get("project") or {}
    stack = profile.get("stack") or {}
    return not (
        (profile.get("basics") or {}).get("role_name")
        or stack.get("must")
        or stack.get("nice")
        or profile.get("screening_questions")
        or project.get("about")
        or project.get("responsibilities")
    )


def _clean(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    return value.strip() or None


def _names(items: Any) -> list[str]:
    return [item["name"] for item in items or [] if item.get("name")]


def _lines(value: Any) -> list[str]:
    return [line.strip() for line in str(value or "").splitlines() if line.strip()]


def _unresolved_notes(unresolved: dict[str, Any]) -> list[str]:
    """Wpisy z pliku, których normalizacja nie przyjęła — pole zostaje puste.

    „brak” i „do ustalenia” to nie treść, tylko brak odpowiedzi: pomijamy.
    """
    notes: list[str] = []
    for path, raw in unresolved.items():
        label = _FIELD_LABELS.get(path)
        kept = [line for line in _lines(raw) if meaningful(line)]
        if not label or not kept:
            continue
        value = " / ".join(kept)
        if len(value) > _ADVISORY_VALUE_CHARS:
            value = value[: _ADVISORY_VALUE_CHARS - 1].rstrip() + "…"
        notes.append(
            f"{label}: w pliku jest „{value}” — nie udało się wpisać tego "
            "w pole. Uzupełnij je ręcznie."
        )
    return notes


def _current_deadline(value: Any, today: date) -> tuple[Optional[str], Optional[str]]:
    """(termin, uwaga): termin z pliku, który już minął, nie trafia do pola.

    Wzór bywa wypełniony tygodnie wcześniej albo użyty drugi raz — nowa
    rekrutacja nie może przez to powstać od razu „po terminie”.
    """
    text = _clean(value)
    if text is None:
        return None, None
    try:
        parsed = date.fromisoformat(text)
    except ValueError:
        return None, None
    if parsed >= today:
        return text, None
    return None, (
        f"Deadline na kandydatów z pliku ({parsed:%d.%m.%Y}) już minął — "
        "wpisz aktualny termin."
    )


def intake_from_champion(
    profile: dict[str, Any], *, today: Optional[date] = None
) -> request_intake.RequestIntake:
    """Profil Championa (po `prepare_profile`) → kształt odczytu requestu.

    ``today`` to dzień według kalendarza firmy (domyślnie `business_today()`).
    """
    from app.core.scheduling import business_today
    from app.services.job_working_title import compose_working_title

    basics = profile.get("basics") or {}
    stack = profile.get("stack") or {}
    search = profile.get("search") or {}
    project = profile.get("project") or {}
    meta = profile.get("intake") or {}
    unresolved = dict(meta.get("unresolved") or {})
    rate_path = champion_intake.RATE_PATH

    # Wymagania: ta sama zamiana co „Uprość do słów kluczowych” — technologia
    # zostaje wierszem, zdanie i wersja idą do opisu wymagań.
    legacy = rows_from_legacy(
        must=_names(stack.get("must")),
        nice=_names(stack.get("nice")),
        requirements=[list(row) for row in search.get("requirements") or []],
    )
    rows = legacy["rows"]
    derived = derive(rows)
    must = [item["name"] for item in derived["must"]]
    nice = [item["name"] for item in derived["nice"]]
    search_requirements = derived["requirements"]
    # „Uwagi / niuanse” wzoru to `stack.notes` — formularz zapisuje tam
    # właśnie zdania opisowe, więc bez tego uwagi z pliku zostałyby nadpisane.
    descriptive: list[str] = []
    for text in (*legacy["descriptive"], *_lines(stack.get("notes"))):
        if text.casefold() not in {d.casefold() for d in descriptive}:
            descriptive.append(text)

    rate_budget = basics.get("rate_value")
    rate_quote = _clean(basics.get("rate_raw"))
    rate_budget_min: Optional[float] = None
    rate_note: Optional[str] = None
    rate_unresolved = _clean(unresolved.pop(rate_path, None))
    if rate_budget is not None:
        bounds = champion_intake.pln_hourly_bounds(rate_quote) if rate_quote else None
        if (
            bounds
            and 0 < bounds[0] < bounds[1]
            and abs(bounds[1] - rate_budget) < 0.005
        ):
            rate_budget_min = bounds[0]
        if rate_path in (meta.get("advisory") or {}):
            rate_note = champion_intake.ADVISORY_ISSUES[rate_path][1]
    elif rate_unresolved:
        rate_note = (
            f"W pliku jest „{rate_unresolved}” — to nie jest stawka w PLN/h "
            "netto. Wpisz budżet ręcznie."
        )

    remote_policy = request_intake._WORK_MODES.get(
        str(basics.get("work_mode") or "").casefold()
    )
    onsite_days = basics.get("onsite_days_per_week")
    onsite_days_month = basics.get("onsite_days_per_month")
    office_cities = request_intake._office_cities(
        {"office_city": basics.get("candidate_location_pref")}
    )
    if remote_policy == "remote":
        onsite_days = onsite_days_month = None
        office_cities = []
    office_city = ", ".join(office_cities)[:255] or None

    questions = [
        request_intake.IntakeQuestion(
            question=q["question"].strip(),
            ideal_answer=str(q.get("ideal_answer") or "").strip(),
            from_request=True,
            deal_breaker=str(q.get("deal_breaker") or "").strip(),
        )
        for q in profile.get("screening_questions") or []
        if _clean(q.get("question"))
    ]
    stored_experience = profile.get("experience") or {}
    experience = {
        key: [
            {
                "name": item["name"],
                "level": item.get("level") or "must",
                "min_years": item.get("min_years"),
            }
            for item in stored_experience.get(key) or []
        ]
        for key in champion_intake.EXPERIENCE_LISTS
    }

    role_name = _clean(basics.get("role_name"))
    seniority = basics.get("seniority_min_years")
    project_about = _clean(project.get("about"))
    responsibilities = _clean(project.get("responsibilities"))
    target_companies = _clean(search.get("target_companies"))
    disqualifiers = [
        text for text in (_clean(d) for d in search.get("disqualifiers") or []) if text
    ]
    selling_points = _clean((profile.get("client") or {}).get("selling_points"))
    deadline, deadline_note = _current_deadline(
        basics.get("deadline"), today or business_today()
    )
    advisories = _unresolved_notes(unresolved)
    if deadline_note:
        advisories.append(deadline_note)

    present = {
        "role": role_name,
        "seniority": seniority is not None,
        "rate": rate_budget is not None,
        "work_mode": remote_policy,
        "about": project_about,
        "responsibilities": responsibilities,
        "experience": any(experience.values()),
        "must": must,
        "nice": nice,
        "search_requirements": search_requirements,
        "target_companies": target_companies,
        "disqualifiers": disqualifiers,
        "selling_points": selling_points,
        "questions": questions,
        "deadline": deadline,
    }

    return request_intake.RequestIntake(
        role_name=role_name,
        must=must,
        nice=nice,
        seniority_min_years=seniority,
        rate_budget_hourly=rate_budget,
        rate_budget_hourly_min=rate_budget_min,
        rate_quote=rate_quote,
        rate_note=rate_note,
        remote_policy=remote_policy,
        onsite_days_per_week=onsite_days,
        onsite_days_per_month=onsite_days_month,
        office_city=office_city,
        office_cities=office_cities,
        start_date=_clean(basics.get("start_date")),
        project_about=project_about,
        responsibilities=responsibilities,
        screening_questions=questions,
        missing=request_intake.missing_fields(
            role_name=role_name,
            must=must,
            rate_budget_hourly=rate_budget,
            remote_policy=remote_policy,
            onsite_days_per_week=onsite_days,
            office_city=office_city,
            project_about=project_about,
            responsibilities=responsibilities,
            questions=questions,
            search_requirements=search_requirements,
        ),
        language=_clean(basics.get("language")),
        contract_length=_clean(basics.get("contract_length")),
        experience=experience,
        target_companies=target_companies,
        disqualifiers=disqualifiers,
        search_requirements=search_requirements,
        requirements=rows,
        descriptive_requirements=descriptive,
        selling_points=selling_points,
        provenance={key: BASIS for key, value in present.items() if value},
        working_title_suggestion=compose_working_title(
            role_name,
            must,
            seniority,
            next(
                (d["name"] for d in experience["domains"] if d["level"] == "must"),
                None,
            ),
        ),
        advisories=advisories,
        deadline=deadline,
    )


def champion_extras(profile: dict[str, Any]) -> dict[str, Any]:
    """Sekcje wzoru, które nie mają pola w formularzu /jobs/new.

    Biała lista: frazy i plan searchu, insight konsultanta, historyczne
    pytania klienta, branże i notatki „Wiedza z rozmów”. Formularz dokłada je
    do zapisu profilu; puste wartości pomijamy, żeby nie kasowały niczego przy
    scalaniu sekcji.
    """
    search = profile.get("search") or {}
    client = profile.get("client") or {}

    def filled(section: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
        return {key: section[key] for key in keys if section.get(key)}

    return {
        "search": filled(search, ("keywords", "notes")),
        "client": filled(
            client, ("consultant_insight", "historical_questions", "sectors")
        ),
        "insights": [
            {key: note.get(key) for key in _INSIGHT_KEYS}
            for note in profile.get("insights") or []
            if note.get("text")
        ],
    }


def looks_like_champion_text(text: str) -> bool:
    """Czy tekst pliku (np. PDF) ma rubryki wzoru Profilu Championa."""
    plain = folded(text or "")
    return all(marker in plain for marker in _FORM_MARKERS)
