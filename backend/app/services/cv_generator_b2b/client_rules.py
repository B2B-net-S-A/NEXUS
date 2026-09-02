"""Stosowanie reguł CV klienta: nazwa pliku, wymuszony język, opis polityki.

Wejście to zatwierdzony wiersz ``client_cv_rules``. Reguła niezatwierdzona
(``confirmed_at IS NULL``) jest **niewidoczna dla runtime'u** — zasiane
propozycje czekają na człowieka, więc błędne dopasowanie szablonu do klienta
nie może wejść w życie po cichu.

Cztery tokeny i jedna flaga pokrywają wszystkie 14 wzorów nazw wyciągniętych
z szablonów Championa:

    {STANOWISKO}      nazwa roli — z ``Job.title`` (tryb "new") albo z pola
                      formularza (tryb "upload", gdzie joba nie ma)
    {IMIE_NAZWISKO}   kandydat
    {PROJEKT}         numer/nazwa projektu — TYLKO tryb "new"
    {DATA}            data generacji (YYYY-MM-DD), wymaga jej Credit Agricole

Flaga ``spaces_to_underscores`` decyduje, czy spacje wewnątrz PODSTAWIONEJ
wartości zamieniają się na ``_``. Dzięki niej „Jan Kowalski" → „Jan_Kowalski"
daje ``Imię_Nazwisko`` bez osobnych tokenów na imię i nazwisko.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client
from app.models.client_cv_rule import ClientCvRule

# Tokeny rozpoznawane we wzorze nazwy pliku. Nieznany token zostaje w nazwie
# dosłownie — lepiej, żeby rekruter zobaczył „{FOO}" w pliku i poprawił wzór,
# niż żeby literówka cicho zniknęła razem z fragmentem nazwy.
TOKEN_POSITION = "{STANOWISKO}"
TOKEN_FULL_NAME = "{IMIE_NAZWISKO}"
TOKEN_PROJECT = "{PROJEKT}"
TOKEN_DATE = "{DATA}"

KNOWN_TOKENS: tuple[str, ...] = (
    TOKEN_POSITION,
    TOKEN_FULL_NAME,
    TOKEN_PROJECT,
    TOKEN_DATE,
)

# Etykiety PL do komunikatów o brakujących wartościach.
_TOKEN_LABELS: dict[str, str] = {
    TOKEN_POSITION: "stanowisko",
    TOKEN_FULL_NAME: "imię i nazwisko",
    TOKEN_PROJECT: "numer projektu",
    TOKEN_DATE: "data",
}

# Separatory, które wolno zwinąć po wypadnięciu pustego tokenu. Kropka NIE jest
# separatorem — „B2B.NET" to część nazwy firmy w wzorze Credit Agricole.
_SEPARATORS = "_-"


@dataclass(frozen=True)
class CvRuleSnapshot:
    """Niezmienna kopia reguły, bezpieczna poza sesją bazy.

    Pipeline generacji jest synchroniczny i leci w ``run_in_threadpool``.
    Wiersz ORM przekazany tam potrafi przy dostępie do atrybutu spróbować
    doczytać coś z bazy — w async SQLAlchemy kończy się to ``MissingGreenlet``,
    czyli 500 bez CORS-a, widocznym w UI jako „Network Error". Snapshot nie ma
    jak tego zrobić.
    """

    filename_pattern: str | None
    spaces_to_underscores: bool
    cv_language: str | None
    requires_en_copy: bool
    requires_rodo_consent_block: bool
    # Pola trafiające do promptu (migracje 0266/0267). Domyślnie puste, żeby
    # istniejące wywołania konstruktora (testy, harnessy) nie musiały ich znać.
    generator_instructions: str | None = None
    generator_instructions_en: str | None = None
    # Notatka sourcingowa DL — od 02.09.2026 idzie do modelu (decyzja Artura)
    # jako blok <client_notes> pod tą samą granicą: tylko prezentacja faktów.
    notes: str | None = None
    # ── Blokady ─────────────────────────────────────────────────────────
    content_mode: str | None = None
    content_mode_locked: bool = False
    require_screening_notes_min_chars: int | None = None
    require_project_ref: bool = False
    require_position: bool = False
    require_champion: bool = False
    auto_second_language: bool = False
    # ── Polityka prezentacji egzekwowana w kodzie ───────────────────────
    omit_sections: tuple[str, ...] = ()
    max_roles: int | None = None
    max_bullets_per_role: int | None = None
    max_bullet_chars: int | None = None
    why_points_max: int | None = None
    date_format: str | None = None
    glossary: tuple[tuple[str, str], ...] = ()
    # Wersja reguły — stemplowana na wygenerowanym CV.
    version: int | None = None


# Sekcje, które reguła klienta może wyłączyć. `why_points` i `experience`
# celowo poza katalogiem — CV bez doświadczenia i bez „dlaczego ten
# kandydat" nie jest CV, tylko pustym szablonem.
SECTION_KEYS: tuple[str, ...] = ("education", "certifications", "languages", "skills")
SECTION_LABELS: dict[str, dict[str, str]] = {
    "pl": {
        "education": "Wykształcenie",
        "certifications": "Certyfikaty",
        "languages": "Języki",
        "skills": "Umiejętności",
    },
    "en": {
        "education": "Education",
        "certifications": "Certifications",
        "languages": "Languages",
        "skills": "Skills",
    },
}
DATE_FORMATS: tuple[str, ...] = ("MM.YYYY", "MM/YYYY", "YYYY-MM", "YYYY")
CONTENT_MODES: tuple[str, ...] = ("basic", "polished", "tailored")
CONTENT_MODE_LABELS: dict[str, str] = {
    "basic": "Przepisanie",
    "polished": "Redakcja",
    "tailored": "Pod rekrutację",
}


def _clean_glossary(raw: Any) -> tuple[tuple[str, str], ...]:
    out: list[tuple[str, str]] = []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        src = str(item.get("from") or "").strip()
        dst = str(item.get("to") or "").strip()
        if src and dst and src.lower() != dst.lower():
            out.append((src, dst))
    return tuple(out)


def _clean_sections(raw: Any) -> tuple[str, ...]:
    return tuple(
        str(key) for key in (raw or []) if isinstance(key, str) and key in SECTION_KEYS
    )


def _positive(value: Any) -> int | None:
    try:
        number = int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
    return number if number and number > 0 else None


def snapshot_rule(rule: Optional[ClientCvRule]) -> Optional[CvRuleSnapshot]:
    """Zamroź wiersz reguły do postaci przenoszalnej między wątkami."""
    if rule is None:
        return None
    return CvRuleSnapshot(
        filename_pattern=rule.filename_pattern,
        spaces_to_underscores=bool(rule.spaces_to_underscores),
        cv_language=rule.cv_language,
        requires_en_copy=bool(rule.requires_en_copy),
        requires_rodo_consent_block=bool(rule.requires_rodo_consent_block),
        generator_instructions=(rule.generator_instructions or "").strip() or None,
        generator_instructions_en=(
            (getattr(rule, "generator_instructions_en", None) or "").strip() or None
        ),
        notes=(rule.notes or "").strip() or None,
        content_mode=(
            rule.content_mode if rule.content_mode in CONTENT_MODES else None
        ),
        content_mode_locked=bool(getattr(rule, "content_mode_locked", False)),
        require_screening_notes_min_chars=_positive(
            getattr(rule, "require_screening_notes_min_chars", None)
        ),
        require_project_ref=bool(getattr(rule, "require_project_ref", False)),
        require_position=bool(getattr(rule, "require_position", False)),
        require_champion=bool(getattr(rule, "require_champion", False)),
        auto_second_language=bool(getattr(rule, "auto_second_language", False)),
        omit_sections=_clean_sections(getattr(rule, "omit_sections", None)),
        max_roles=_positive(getattr(rule, "max_roles", None)),
        max_bullets_per_role=_positive(getattr(rule, "max_bullets_per_role", None)),
        max_bullet_chars=_positive(getattr(rule, "max_bullet_chars", None)),
        why_points_max=_positive(getattr(rule, "why_points_max", None)),
        date_format=(
            rule.date_format
            if getattr(rule, "date_format", None) in DATE_FORMATS
            else None
        ),
        glossary=_clean_glossary(getattr(rule, "glossary", None)),
        version=getattr(rule, "version", None),
    )


def has_presentation_policy(rule: Optional[CvRuleSnapshot]) -> bool:
    """Czy reguła niesie choć jeden klocek egzekwowany w kodzie."""
    if rule is None:
        return False
    return bool(
        rule.omit_sections
        or rule.max_roles
        or rule.max_bullets_per_role
        or rule.max_bullet_chars
        or rule.why_points_max
        or rule.date_format
        or rule.glossary
    )


def resolve_content_mode(
    rule: Optional[CvRuleSnapshot], requested: str
) -> tuple[str, bool]:
    """Tryb obróbki treści po nałożeniu blokady reguły.

    Zwraca ``(tryb, wymuszony)``. Zablokowany tryb NADPISUJE żądanie — front
    i tak pokazuje kafelki jako wyłączone, ale kontrakt musi trzymać serwer:
    ukryta kontrolka nie jest zabezpieczeniem. Sufit z karty klienta
    (`apply_content_mode_cap`) jest nakładany PO tej funkcji i nadal wygrywa.
    """
    if rule is not None and rule.content_mode and rule.content_mode_locked:
        return rule.content_mode, rule.content_mode != requested
    return requested, False


def required_input_problems(
    rule: Optional[CvRuleSnapshot],
    *,
    mode: str,
    screening_chars: int,
    has_project_ref: bool,
    has_position: bool,
    has_champion: bool,
) -> list[str]:
    """Czego brakuje, żeby generacja u tego klienta w ogóle ruszyła.

    Komunikaty po polsku, jeden na wymóg — lecą jako 422 PRZED naliczeniem
    kwoty, tym samym kanałem co zrzut zgody u PKO BP. ``mode`` to ścieżka
    generacji ("new" z procesu / "upload" z plików): stanowisko ma sens tylko
    w uploadzie (w trybie „new" bierze się z rekrutacji), a wymóg Championa
    inaczej brzmi w każdej z nich.
    """
    if rule is None:
        return []
    problems: list[str] = []
    minimum = rule.require_screening_notes_min_chars or 0
    if minimum > 0 and screening_chars < minimum:
        problems.append(
            f"Ten klient wymaga notatek ze screeningu o długości co najmniej "
            f"{minimum} znaków — jest {screening_chars}."
        )
    if rule.require_project_ref and not has_project_ref:
        problems.append(
            "Ten klient wymaga numeru projektu — uzupełnij pole "
            "„Numer / nazwa projektu”."
        )
    if rule.require_position and mode == "upload" and not has_position:
        problems.append("Ten klient wymaga stanowiska — uzupełnij pole „Stanowisko”.")
    if rule.require_champion and not has_champion:
        problems.append(
            "Ten klient wymaga wymagań z Profilu Championa — wgraj plik "
            "championa albo wpisz wymagania must-have / nice-to-have."
            if mode == "upload"
            else "Ten klient wymaga Profilu Championa — uzupełnij go na karcie "
            "rekrutacji przed generacją."
        )
    return problems


# Sufit długości instrukcji dla generatora. Pole idzie do KAŻDEJ generacji
# u tego klienta, więc nieograniczone rozrastałoby prompt (i rachunek) bez
# żadnego sygnału zwrotnego; 2000 znaków to kilkanaście reguł, nie esej.
GENERATOR_INSTRUCTIONS_MAX_LENGTH = 2000

_PRESENTATION_RULES_TAG = "client_presentation_rules"
_NOTES_TAG = "client_notes"


def _neutralize(text: str) -> str:
    """Znaczniki ``<``/``>`` w treści od DL neutralizowane: nie da się zamknąć
    bloku i „wyjść" do części, w której model widzi wyłącznie polecenia."""
    return text.replace("<", "‹").replace(">", "›")


def _structured_rule_lines(rule: CvRuleSnapshot, language: str) -> list[str]:
    """Klocki polityki prezentacji jako zdania dla modelu (PL albo EN).

    Te same reguły renderer egzekwuje po odpowiedzi — zdania w prompcie są po
    to, żeby model nie pisał treści, którą kod zaraz utnie (ucięty punkt czyta
    się gorzej niż punkt napisany krótko).
    """
    en = language == "en"
    labels = SECTION_LABELS["en" if en else "pl"]
    lines: list[str] = []
    if rule.omit_sections:
        names = ", ".join(labels[key] for key in rule.omit_sections)
        lines.append(
            f"Omit these sections entirely (return empty lists): {names}."
            if en
            else f"Pomiń całkowicie sekcje (zwróć puste listy): {names}."
        )
    if rule.max_roles:
        lines.append(
            f"Include at most the {rule.max_roles} most recent roles in experience."
            if en
            else f"W doświadczeniu uwzględnij maksymalnie {rule.max_roles} "
            "ostatnich stanowisk."
        )
    if rule.max_bullets_per_role:
        lines.append(
            f"At most {rule.max_bullets_per_role} responsibility bullets per role."
            if en
            else f"Maksymalnie {rule.max_bullets_per_role} punktów obowiązków "
            "na stanowisko."
        )
    if rule.max_bullet_chars:
        lines.append(
            f"Each responsibility bullet at most {rule.max_bullet_chars} characters."
            if en
            else f"Każdy punkt obowiązków do {rule.max_bullet_chars} znaków."
        )
    if rule.why_points_max:
        lines.append(
            f'"why_points": at most {rule.why_points_max} items.'
            if en
            else f"Sekcja „dlaczego ten kandydat” (why_points): maksymalnie "
            f"{rule.why_points_max} punktów."
        )
    # Format dat CELOWO nie idzie do promptu: bezpieczniki lat i nakładania
    # się dat parsują daty w kształcie źródłowym (`MM.YYYY`), a model
    # posłuszny prośbie o `MM/YYYY` gubiłby im miesiące. Format nakłada kod
    # na końcu pipeline'u (`apply_date_format`) — deterministycznie.
    if rule.glossary:
        pairs = "; ".join(f"„{src}” → „{dst}”" for src, dst in rule.glossary)
        lines.append(
            f"Client vocabulary (wording only, never facts): {pairs}."
            if en
            else f"Słownictwo klienta (tylko nazewnictwo, nigdy fakty): {pairs}."
        )
    return lines


def build_client_presentation_rules_block(
    rule: Optional[CvRuleSnapshot], language: str = "pl"
) -> str:
    """Blok ``<client_presentation_rules>`` do wiadomości użytkownika.

    Pusty string, gdy klient nie ma ani klocków, ani instrukcji — wtedy
    prompt nie różni się niczym od dotychczasowego. Idzie do wiadomości
    UŻYTKOWNIKA, nie do systemowej: prompt systemowy jest jednym cache'owanym
    blokiem i musi zostać identyczny między generacjami, a reguły różnią się
    per klient.

    Dla CV angielskiego wolny tekst bierze się z wariantu EN, gdy DL go wpisał;
    inaczej z treści podstawowej. Klocki są renderowane w języku dokumentu.
    """
    if rule is None:
        return ""
    lines = _structured_rule_lines(rule, language)
    free_text = ""
    if language == "en" and (rule.generator_instructions_en or "").strip():
        free_text = rule.generator_instructions_en or ""
    else:
        free_text = rule.generator_instructions or ""
    free_text = free_text.strip()[:GENERATOR_INSTRUCTIONS_MAX_LENGTH]
    parts = [*lines]
    if free_text:
        parts.append(free_text)
    if not parts:
        return ""
    body = _neutralize("\n".join(parts))
    return f"<{_PRESENTATION_RULES_TAG}>\n{body}\n</{_PRESENTATION_RULES_TAG}>"


def build_client_notes_block(rule: Optional[CvRuleSnapshot]) -> str:
    """Blok ``<client_notes>`` — notatka sourcingowa Delivery Leada.

    Do 02.09.2026 świadomie NIE trafiała do modelu (reguła szukania w prompcie
    zapraszała do koloryzowania doświadczenia). Decyzja Artura: generator ma ją
    brać pod uwagę. Kompromis: idzie w OSOBNYM bloku, a prompt systemowy każe
    traktować ją jak kontekst o standardach klienta pod tą samą granicą co
    reguły prezentacji — dobór i forma faktów ze źródła, nigdy nowe fakty.
    """
    if rule is None:
        return ""
    text = (rule.notes or "").strip()
    if not text:
        return ""
    return f"<{_NOTES_TAG}>\n{_neutralize(text[:GENERATOR_INSTRUCTIONS_MAX_LENGTH])}\n</{_NOTES_TAG}>"


def build_prompt_blocks(rule: Optional[CvRuleSnapshot], language: str = "pl") -> str:
    """Wszystko, co z reguły klienta trafia do wiadomości użytkownika."""
    parts = [
        block
        for block in (
            build_client_presentation_rules_block(rule, language),
            build_client_notes_block(rule),
        )
        if block
    ]
    return "\n\n".join(parts)


# ── Polityka prezentacji egzekwowana w kodzie ───────────────────────────────


def _shorten(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[: max(limit - 1, 1)]
    space = cut.rfind(" ")
    if space > limit // 2:
        cut = cut[:space]
    return cut.rstrip(" ,;:") + "…"


def _glossary_pattern(src: str) -> re.Pattern[str]:
    # Całe słowa (bez `\b`, który przy polskich znakach nie działa
    # przewidywalnie), bez rozróżniania wielkości liter.
    return re.compile(rf"(?<!\w){re.escape(src)}(?!\w)", re.IGNORECASE)


def _apply_glossary_text(text: str, glossary: tuple[tuple[str, str], ...]) -> str:
    out = text
    for src, dst in glossary:
        # Lambda, nie szablon: `dst` z backslashem albo `\g<0>` wywaliłby
        # `re.error` w threadpoolu — „failed" na każdej generacji u klienta.
        out = _glossary_pattern(src).sub(lambda _m, _dst=dst: _dst, out)
    return out


def apply_presentation_policy(
    candidate_data: dict[str, Any], rule: Optional[CvRuleSnapshot]
) -> list[str]:
    """Domknij klocki reguły PO odpowiedzi modelu, PRZED bezpiecznikami.

    Model dostał te same reguły jako instrukcje, ale prośba nie jest
    gwarancją — „maks. 3 punkty" wypełnione czterema wygląda dla klienta jak
    zignorowane wymaganie. Zwraca listę tego, co trzeba było domknąć (puste,
    gdy model był posłuszny) — rekruter widzi to jako uwagę do sprawdzenia.
    Format dat jest nakładany OSOBNO (`apply_date_format`), na końcu
    pipeline'u, bo bezpieczniki lat i nakładania się dat parsują daty w kształcie
    źródłowym.
    """
    if rule is None:
        return []
    notes: list[str] = []
    for key in rule.omit_sections:
        if candidate_data.get(key):
            candidate_data[key] = []
            notes.append(f"pominięto sekcję „{SECTION_LABELS['pl'][key]}”")
    experience = candidate_data.get("experience") or []
    if rule.max_roles and len(experience) > rule.max_roles:
        candidate_data["experience"] = experience[: rule.max_roles]
        notes.append(f"ucięto doświadczenie do {rule.max_roles} stanowisk")
    if rule.max_bullets_per_role:
        trimmed = 0
        for role in candidate_data.get("experience") or []:
            bullets = role.get("responsibilities") or []
            if len(bullets) > rule.max_bullets_per_role:
                role["responsibilities"] = bullets[: rule.max_bullets_per_role]
                trimmed += 1
        if trimmed:
            notes.append(
                f"ucięto punkty obowiązków do {rule.max_bullets_per_role} "
                f"na stanowisko ({trimmed} stanowisk)"
            )
    if rule.max_bullet_chars:
        shortened = 0
        for role in candidate_data.get("experience") or []:
            bullets = role.get("responsibilities") or []
            new_bullets = []
            for bullet in bullets:
                short = _shorten(str(bullet), rule.max_bullet_chars)
                if short != bullet:
                    shortened += 1
                new_bullets.append(short)
            role["responsibilities"] = new_bullets
        if shortened:
            notes.append(
                f"skrócono {shortened} punktów obowiązków do {rule.max_bullet_chars} znaków"
            )
    why_points = candidate_data.get("why_points") or []
    if rule.why_points_max and len(why_points) > rule.why_points_max:
        candidate_data["why_points"] = why_points[: rule.why_points_max]
        notes.append(f"ucięto „dlaczego ten kandydat” do {rule.why_points_max} punktów")
    if rule.glossary:
        glossary = rule.glossary
        candidate_data["position"] = _apply_glossary_text(
            str(candidate_data.get("position") or ""), glossary
        )
        candidate_data["why_points"] = [
            _apply_glossary_text(str(p), glossary)
            for p in candidate_data.get("why_points") or []
        ]
        for role in candidate_data.get("experience") or []:
            role["position"] = _apply_glossary_text(
                str(role.get("position") or ""), glossary
            )
            role["responsibilities"] = [
                _apply_glossary_text(str(b), glossary)
                for b in role.get("responsibilities") or []
            ]
        for cat in candidate_data.get("skills") or []:
            if isinstance(cat, dict):
                cat["content"] = _apply_glossary_text(
                    str(cat.get("content") or ""), glossary
                )
        candidate_data["certifications"] = [
            _apply_glossary_text(str(c), glossary)
            for c in candidate_data.get("certifications") or []
        ]
    return notes


_DATE_MONTH_YEAR = re.compile(r"(?<!\d)(\d{1,2})[./-](\d{4})(?!\d)")
# Rok poprzedzony separatorem daty to koniec tokenu `MM.YYYY`, nie początek
# `YYYY-MM` — bez tego „03.2019-05.2021" rozpadał się na „03.05/2019.2021".
_DATE_YEAR_MONTH = re.compile(r"(?<![\d./])(\d{4})-(\d{1,2})(?!\d)")


def _render_date(year: str, month: str | None, fmt: str) -> str:
    if fmt == "YYYY" or not month:
        return year
    mm = month.zfill(2)
    if fmt == "MM.YYYY":
        return f"{mm}.{year}"
    if fmt == "MM/YYYY":
        return f"{mm}/{year}"
    if fmt == "YYYY-MM":
        return f"{year}-{mm}"
    return f"{mm}.{year}"


def reformat_dates(text: str, fmt: str) -> str:
    """Przepisz tokeny dat w opisie okresu na wybrany format.

    Rozpoznaje ``MM.YYYY`` / ``MM/YYYY`` / ``MM-YYYY`` oraz ``YYYY-MM``; gołe
    lata i słowa („obecnie”, „present”) zostają. Nieznany kształt nie jest
    ruszany — lepiej zostawić datę taką, jaką napisał model, niż ją zepsuć.
    """
    if fmt not in DATE_FORMATS or not text:
        return text
    # Najpierw `MM.YYYY` (częstszy kształt), potem `YYYY-MM` — w tej kolejności
    # zakres z myślnikiem bez spacji zostaje dwoma datami, nie jedną zlepką.
    out = _DATE_MONTH_YEAR.sub(
        lambda m: _render_date(m.group(2), m.group(1), fmt), text
    )
    out = _DATE_YEAR_MONTH.sub(lambda m: _render_date(m.group(1), m.group(2), fmt), out)
    return out


def apply_date_format(
    candidate_data: dict[str, Any], rule: Optional[CvRuleSnapshot]
) -> int:
    """Nałóż format dat klienta na doświadczenie i wykształcenie. Zwraca
    liczbę zmienionych pól. Wołane NA KOŃCU pipeline'u — po bezpiecznikach,
    które parsują daty w kształcie źródłowym."""
    if rule is None or not rule.date_format:
        return 0
    changed = 0
    for key in ("experience", "education"):
        for entry in candidate_data.get(key) or []:
            if not isinstance(entry, dict):
                continue
            before = str(entry.get("dates") or "")
            after = reformat_dates(before, rule.date_format)
            if after != before:
                entry["dates"] = after
                changed += 1
    return changed


@dataclass(frozen=True)
class FilenameResult:
    """Nazwa pliku plus ostrzeżenia o tokenach, których nie dało się wypełnić."""

    filename: str
    warnings: tuple[str, ...]


def _apply_word_separator(value: str, spaces_to_underscores: bool) -> str:
    collapsed = re.sub(r"\s+", " ", value).strip()
    if spaces_to_underscores:
        return collapsed.replace(" ", "_")
    return collapsed


def _collapse_separators(stem: str) -> str:
    """Zwiń ślady po pustych tokenach: „B2B__Jan" → „B2B_Jan", „ZOB-_X" → „ZOB_X"."""
    collapsed = re.sub(rf"[{_SEPARATORS}]{{2,}}", "_", stem)
    return collapsed.strip(_SEPARATORS + " ")


def build_filename(
    rule: Optional[CvRuleSnapshot],
    *,
    position: str | None,
    candidate_name: str,
    project: str | None = None,
    today: date | None = None,
) -> Optional[FilenameResult]:
    """Złóż nazwę pliku wg wzoru klienta.

    Zwraca ``None``, gdy reguły nie ma albo nie ma ona wzoru — wtedy woła się
    dotychczasowy, globalny ``_build_download_filename`` i **nic się nie zmienia**.

    Brakująca wartość tokenu nie przerywa generacji: token znika razem
    z osieroconym separatorem, a rekruter dostaje ostrzeżenie, żeby uzupełnić
    nazwę ręcznie. Zablokowanie generacji z powodu nieuzupełnionego numeru
    projektu byłoby gorsze niż plik do przemianowania.
    """
    if rule is None or not (rule.filename_pattern or "").strip():
        return None

    pattern = rule.filename_pattern.strip()
    sep = bool(rule.spaces_to_underscores)

    values: dict[str, str] = {
        TOKEN_POSITION: _apply_word_separator(position or "", sep),
        TOKEN_FULL_NAME: _apply_word_separator(candidate_name or "", sep),
        TOKEN_PROJECT: _apply_word_separator(project or "", sep),
        TOKEN_DATE: (today or date.today()).isoformat(),
    }

    warnings: list[str] = []
    stem = pattern
    for token in KNOWN_TOKENS:
        if token not in pattern:
            continue
        value = values[token]
        if not value:
            warnings.append(
                f"WERYFIKUJ: wzór nazwy pliku tego klienta wymaga pola "
                f"„{_TOKEN_LABELS[token]}”, którego nie udało się ustalić — "
                f"uzupełnij nazwę pliku ręcznie po pobraniu."
            )
        stem = stem.replace(token, value)

    stem = _collapse_separators(stem)

    # Ostatnia linia obrony: nazwa musi nieść tożsamość kandydata. Wzór złożony
    # z samych nierozwiązanych tokenów dałby plik „B2B.docx" dla każdego —
    # nie do odróżnienia w folderze „Pobrane" i nie do wysłania klientowi.
    #
    # Pustka sprawdzana OSOBNO i PRZED `in`: `"" in cokolwiek` jest zawsze
    # prawdą, więc warunek oparty wyłącznie na `not in` przepuszczałby dokładnie
    # ten przypadek, przed którym miał chronić — kandydata bez nazwiska.
    name_value = values[TOKEN_FULL_NAME]
    if not stem or not name_value or name_value not in stem:
        return None

    # Znaki zarezerwowane przez systemy plików; polskie znaki i spacje zostają
    # (nagłówek HTTP ma osobną, ASCII-ową ścieżkę przez ``filename*``).
    stem = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "", stem).strip(" .")
    if not stem:
        return None

    return FilenameResult(filename=f"{stem}.docx", warnings=tuple(warnings))


async def resolve_client_rule(
    db: AsyncSession, client_id: int | None
) -> Optional[ClientCvRule]:
    """Zwróć **zatwierdzoną** regułę klienta albo ``None``.

    Propozycje z seeda (``confirmed_at IS NULL``) są tu celowo niewidoczne.
    """
    if not client_id:
        return None
    stmt = select(ClientCvRule).where(
        ClientCvRule.client_id == client_id,
        ClientCvRule.confirmed_at.is_not(None),
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def resolve_client_name(db: AsyncSession, client_id: int | None) -> Optional[str]:
    """Nazwa klienta do UI — ``display_name`` ma pierwszeństwo przed ``name``,
    bo to ta druga jest nadpisywana przez sync Traffita."""
    if not client_id:
        return None
    stmt = select(Client.display_name, Client.name).where(Client.id == client_id)
    row = (await db.execute(stmt)).first()
    if row is None:
        return None
    display_name, name = row
    return (display_name or "").strip() or name


def rule_reminders(rule: Optional[CvRuleSnapshot]) -> tuple[str, ...]:
    """Wymogi klienta, których generator NIE MOŻE spełnić za rekrutera.

    Świadomie nie modyfikujemy dokumentu:

    * PKO BP wymaga wklejenia na dole CV **zrzutu ekranu** maila ze zgodą
      kandydata. Generator nie ma tego obrazu, a wstawienie pustej ramki
      „Zgoda kandydata" wysłałoby do banku dokument wyglądający na
      niedokończony — gorzej niż brak ramki.
    * Czterej klienci wymagają CV w OBU językach. Druga generacja to drugie,
      najdroższe wywołanie modelu w produkcie, więc uruchamia ją człowiek.

    Oba wracają kanałem ostrzeżeń, który rekruter już zna.
    """
    if rule is None:
        return ()
    out: list[str] = []
    if rule.requires_rodo_consent_block:
        # Od 09.2026 zrzut wgrywa rekruter przy generacji i renderer wkleja go
        # sam, więc to ostrzeżenie NIE mówi już „zrób to ręcznie" — mówi „sprawdź,
        # czy się wkleiło". Zostaje, bo wstawienie obrazu jest fail-soft:
        # nieczytelny plik daje CV bez zrzutu zamiast wywalonej generacji.
        out.append(
            "WERYFIKUJ: ten klient wymaga zrzutu ekranu ze zgodą kandydata na "
            "dole CV — sprawdź, czy jest widoczny w pobranym dokumencie."
        )
    if rule.requires_en_copy and not rule.auto_second_language:
        # Przy automacie druga wersja powstaje sama — przypomnienie byłoby
        # fałszywym zadaniem na obu dokumentach.
        out.append(
            "WERYFIKUJ: ten klient oczekuje CV po polsku ORAZ po angielsku — "
            "pamiętaj o wygenerowaniu drugiej wersji językowej."
        )
    if (rule.generator_instructions or "").strip() or (
        rule.generator_instructions_en or ""
    ).strip():
        # Model dostał reguły prezentacji klienta i mógł którąś pominąć jako
        # niedozwoloną (dopisywanie faktów). Rekruter ma wiedzieć, że dokument
        # był kształtowany także tymi regułami — i sprawdzić go pod ich kątem.
        out.append(
            "WERYFIKUJ: zastosowano instrukcje tego klienta dla generatora — "
            "sprawdź dokument pod ich kątem (pominięte instrukcje model zgłasza "
            "osobno w ostrzeżeniach)."
        )
    return tuple(out)


def describe_rule(rule: Optional[CvRuleSnapshot]) -> str:
    """Opis zastosowanej polityki do UI — odpowiednik ``client_policy``
    z odczytu PDF zamówień.

    Pusty string znaczy „klienta wybrano, ale nie ma dla niego zatwierdzonych
    reguł". Ta różnica musi być widoczna: niewłączona reguła jest inaczej
    NIEWIDOCZNA — generacja »działa«, a jedynym objawem jest plik nazwany
    wzorem, którego klient nie akceptuje.
    """
    if rule is None:
        return ""
    parts: list[str] = []
    if (rule.filename_pattern or "").strip():
        parts.append("nazwa pliku")
    if rule.cv_language:
        parts.append(f"język {rule.cv_language.upper()}")
    if rule.requires_rodo_consent_block:
        parts.append("blok zgody RODO")
    if rule.content_mode and rule.content_mode_locked:
        parts.append(
            f"tryb „{CONTENT_MODE_LABELS.get(rule.content_mode, rule.content_mode)}”"
        )
    if has_presentation_policy(rule):
        parts.append("polityka prezentacji")
    if (rule.generator_instructions or "").strip() or (
        rule.generator_instructions_en or ""
    ).strip():
        parts.append("instrukcje dla generatora")
    if (rule.notes or "").strip():
        parts.append("notatka DL")
    return ", ".join(parts)
