"""Szablon Championa 09.2026 — siedem sekcji, zero utraty danych.

Testy pilnują trzech rzeczy, z których każda już raz zawiodła po cichu:

1. **Zapis z UI nie kasuje pól sparsowanego dokumentu.** Do 09.2026
   ``ChampionProfile`` nie deklarowało kluczy zapisywanych przez parser, a
   Pydantic z domyślnym ``extra="ignore"`` wyrzucał je przy pierwszym zapisie —
   razem z ``rate_value`` (twardy sufit stawki) i ``seniority_min_years`` (kara
   seniority). Nic tego nie sygnalizowało: profil dalej się otwierał, tylko dwa
   filtry przestawały działać.

2. **Oba kształty profilu czytają się identycznie.** Migracja jest leniwa, więc
   przez długi czas w bazie będą leżeć obok siebie profile sprzed i po
   przebudowie. Konsument widzący tylko jeden kształt zwraca pustkę, a pustka
   w tych miejscach czyta się jak „nie ma takich danych".

3. **Tekst idący do WEKTORA oferty nie drgnął dla starych profili.** Gdyby
   drgnął, przebudowa formularza wmieszałaby się w pomiar jakości retrievalu i
   nie dałoby się rozstrzygnąć, co zmieniło wynik.
"""

from __future__ import annotations

import pytest

from app.schemas.champion import ChampionProfile
from app.services import champion_view


def _generator():
    """Moduł generatora wzoru — mieszka w `scripts/`, więc poza pakietem app."""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import generate_champion_template  # noqa: PLC0415

    return generate_champion_template


def _template_text(doc) -> str:
    """Cały widoczny tekst dokumentu — akapity ORAZ komórki tabel.

    Sam `doc.paragraphs` nie wystarcza: wzór jest tabelkowy, więc wszystkie
    etykiety pól siedzą w komórkach i test czytający tylko akapity przechodziłby
    niezależnie od tego, co w tych polach naprawdę jest.

    Idziemy po CIELE dokumentu w kolejności, a nie `doc.paragraphs` + `doc.tables`
    osobno: tamto zwraca najpierw wszystkie akapity, potem wszystkie tabele, więc
    pozycje w wyniku nie mają nic wspólnego z układem strony — a asercja
    o kolejności („standardy nad sekcją 1") byłaby wtedy pusta.
    """
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    parts: list[str] = []
    for block in doc.element.body:
        tag = block.tag.split("}")[-1]
        if tag == "p":
            parts.append(Paragraph(block, doc).text)
        elif tag == "tbl":
            for row in Table(block, doc).rows:
                seen: set[str] = set()
                for cell in row.cells:
                    if cell.text not in seen:
                        seen.add(cell.text)
                        parts.append(cell.text)
    return "\n".join(parts)


# Kształt 1:1 z tym, co ``build_champion_dict`` zapisywał w imporcie 08.2026
# (1095 plików, parser v3). To jest stan 949 wierszy na produkcji.
LEGACY_PROFILE: dict = {
    "basics": {
        "onsite_days_per_week": 2,
        "candidate_location_pref": "Warszawa",
        "language": "PL",
    },
    "project_context": {
        "about": "Rozbudowa platformy płatności.",
        "responsibilities": "Rozwój API, code review",
        "selling_points": "Nowy zespół, greenfield",
    },
    "screening_questions": [
        {
            "id": "q1",
            "question": "Doświadczenie z Kafką?",
            "ideal_answer": "min. 2 lata produkcyjnie",
            "deal_breaker": "tylko z tutoriali",
        }
    ],
    "sourcing": {
        "keywords": "java, kafka, spring",
        "target_companies": "Asseco, Comarch",
        "notes": "nie zawężamy do bankowości",
        "sources": ["linkedin"],
    },
    "role_name": "Senior Java Developer",
    "seniority_min_years": 10,
    "rate_value": 122.50,
    "rate_raw": "122,50 PLN/h",
    "work_mode": "hybrydowo",
    "start_date": "2026-10-01",
    "contract_length": "3-5 miesięcy",
    "sectors": ["banking"],
    "disqualifiers": ["brak polskiego"],
    "client_standards": {
        "priority_rules": "bankowość w pierwszej kolejności",
        "offlimit": True,
        "contract_type": "B2B",
        "cv_language": "en",
    },
    "internal_consultant_insight": "Zespół rozproszony, dużo spotkań",
    "historical_client_questions": "Pytali o Kafkę i o Kubernetes",
    "_source": "traffit_recruitment_file:123",
    "_parser": "champion_parse:v3:haiku-4.5",
}


def test_ui_save_preserves_every_parsed_field() -> None:
    """Walidacja + dump nie może zgubić ŻADNEGO pola sparsowanego dokumentu.

    To jest regresja, nie hipoteza: przed przebudową ten sam przebieg kasował
    12 z 16 kluczy. Test celowo sprawdza WARTOŚCI, nie samą obecność sekcji —
    pole przeniesione do właściwej sekcji, ale z wyzerowaną zawartością, byłoby
    tą samą awarią pod inną nazwą.
    """
    profile = ChampionProfile.model_validate(LEGACY_PROFILE)

    assert profile.basics.rate_value == 122.50
    assert profile.basics.seniority_min_years == 10
    assert profile.basics.role_name == "Senior Java Developer"
    assert profile.basics.rate_raw == "122,50 PLN/h"
    assert profile.basics.work_mode == "hybrydowo"
    assert profile.basics.start_date == "2026-10-01"
    assert profile.basics.contract_length == "3-5 miesięcy"
    assert profile.search.disqualifiers == ["brak polskiego"]
    assert profile.client.sectors == ["banking"]
    assert profile.client.priority_rules == "bankowość w pierwszej kolejności"
    assert profile.client.offlimit is True
    assert profile.client.contract_type == "B2B"
    assert profile.client.cv_language == "en"
    assert profile.client.consultant_insight == "Zespół rozproszony, dużo spotkań"
    assert profile.client.historical_questions == "Pytali o Kafkę i o Kubernetes"
    assert profile.client.selling_points == "Nowy zespół, greenfield"

    dumped = profile.model_dump()
    # Proweniencja przeżywa zapis — bez niej nie da się odróżnić profilu
    # napisanego ręcznie od jednego z 1095 sparsowanych w sierpniu.
    assert dumped["_source"] == "traffit_recruitment_file:123"
    assert dumped["_parser"] == "champion_parse:v3:haiku-4.5"


def test_migration_is_idempotent() -> None:
    """Druga walidacja nie może niczego zmienić.

    Zapis profilu to walidacja → dump → zapis, a odczyt znowu walidacja. Gdyby
    przebieg nie był stały, profil dryfowałby przy każdym otwarciu strony.
    """
    once = ChampionProfile.model_validate(LEGACY_PROFILE).model_dump()
    twice = ChampionProfile.model_validate(once).model_dump()
    assert once == twice


def test_new_shape_wins_over_legacy_keys() -> None:
    """Payload niosący oba kształty zachowuje NOWY.

    Zdarza się realnie: edytor otwarty przed wdrożeniem, zapisany po nim.
    Wygrana starego klucza cofnęłaby właśnie wpisaną zmianę.
    """
    mixed = dict(LEGACY_PROFILE)
    mixed["project"] = {"about": "NOWA TREŚĆ", "responsibilities": ""}
    profile = ChampionProfile.model_validate(mixed)
    assert profile.project.about == "NOWA TREŚĆ"


def test_clearing_a_field_sticks_after_normalisation() -> None:
    """Wyczyszczone pole zostaje puste, gdy stare klucze już nie istnieją.

    Migracja uzupełnia PUSTE pole nowej sekcji wartością ze starego klucza — to
    jest jej sens. Dlatego handler `PUT` normalizuje zapisany profil PRZED
    nałożeniem payloadu; ten test opisuje właśnie tamtą kolejność. Gdyby scalać
    wprost na surowym profilu, skasowanie frazy w edytorze nigdy by się nie
    zapisało, bo migracja wpisywałaby ją z powrotem z `sourcing.keywords`.
    """
    normalized = ChampionProfile.model_validate(LEGACY_PROFILE).model_dump()
    assert normalized["search"]["keywords"] == "java, kafka, spring"
    assert "sourcing" not in normalized

    normalized["search"] = {**normalized["search"], "keywords": ""}
    reread = ChampionProfile.model_validate(normalized)
    assert reread.search.keywords == ""


@pytest.mark.parametrize(
    "accessor",
    [
        champion_view.basics,
        champion_view.search,
        champion_view.project,
        champion_view.client,
        champion_view.screening_questions,
        champion_view.narrative_parts,
        champion_view.embedding_parts,
        champion_view.hourly_rate,
        champion_view.seniority_min_years,
        champion_view.disqualifiers,
    ],
)
def test_both_shapes_read_identically(accessor) -> None:
    """Każdy akcesor daje ten sam wynik dla profilu starego i zmigrowanego.

    Porównanie pomija wartości puste, bo brak klucza i pusty napis to dla
    konsumenta ta sama informacja — wszyscy czytają przez `.get()` i sprawdzają
    prawdziwość. Zmigrowany profil niesie domyślne `""` z modelu, stary po
    prostu nie ma tego klucza; wymaganie identycznych SŁOWNIKÓW testowałoby
    kształt dumpa Pydantica, a nie to, co widzi scoring.
    """

    def meaningful(value):
        if isinstance(value, dict):
            return {k: v for k, v in value.items() if v not in (None, "", [], {})}
        return value

    migrated = ChampionProfile.model_validate(LEGACY_PROFILE).model_dump()
    assert meaningful(accessor(LEGACY_PROFILE)) == meaningful(accessor(migrated))


def test_embedding_text_for_legacy_profile_is_unchanged() -> None:
    """Wektor 949 istniejących ofert nie może drgnąć przez przebudowę formularza.

    Zakres jest DOKŁADNIE ten sprzed zmiany: `about`, `responsibilities`,
    `selling_points` — nic więcej. Rozszerzenie go (np. o pytania screeningowe
    albo słowa kluczowe) jest osobną zmianą jakości wyszukiwania i wymaga
    własnego A/B; ten test istnieje po to, żeby nie dało się jej przemycić.
    """
    assert champion_view.embedding_parts(LEGACY_PROFILE) == [
        "Rozbudowa platformy płatności.",
        "Rozwój API, code review",
        "Nowy zespół, greenfield",
    ]


def test_structured_stack_reaches_the_embedding_but_only_when_present() -> None:
    """Stack dochodzi do wektora tylko wtedy, gdy ktoś go faktycznie wypełnił."""
    with_stack = ChampionProfile.model_validate(
        {
            **LEGACY_PROFILE,
            "stack": {"must": [{"name": "Java"}], "nice": [], "notes": ""},
        }
    ).model_dump()
    parts = champion_view.embedding_parts(with_stack)
    assert parts[0] == "Java"
    assert parts[1:] == champion_view.embedding_parts(LEGACY_PROFILE)


def test_hourly_rate_survives_the_round_trip() -> None:
    """Sufit stawki działa po zapisie z UI — dokładnie to psuło się wcześniej."""
    saved = ChampionProfile.model_validate(LEGACY_PROFILE).model_dump()
    assert champion_view.hourly_rate(saved) == 122.50
    assert champion_view.seniority_min_years(saved) == 10


def test_empty_profile_is_not_an_error() -> None:
    """Brak Championa to stan ~95% ofert — każdy akcesor musi go znieść."""
    for source in (None, {}, "nonsense", 42):
        assert champion_view.basics(source) == {}
        assert champion_view.narrative_parts(source) == []
        assert champion_view.hourly_rate(source) is None


# ── kontrakt wzoru Word z parserem dokumentu ────────────────────────────────
#
# Wgrany „Profil Championa" jest rozbijany na sekcje regexami po NAZWACH
# nagłówków. Numeracja jest opcjonalna (`_NUM`), więc przenumerowanie sekcji jest
# bezpieczne — przemianowanie NIE. Przy przebudowie 09.2026 przemianowane zostały
# dwie sekcje treściowe („Pytania od Delivery Leada" → „Pytania screeningowe") i
# dwie graniczne, a trzy nagłówki są zupełnie nowe.
#
# Ten test czyta tytuły WPROST z generatora wzoru, więc wzór i parser nie mogą
# się rozjechać przez literówkę w Wordzie.


def _fold(text: str) -> str:
    """Lustro `champion_builder._fold_for_match` — parser dopasowuje bez diakrytyków."""
    from app.services.cv_generator_b2b.champion_builder import _fold_for_match

    return _fold_for_match(text)


def test_every_template_heading_is_recognised_by_the_cv_parser() -> None:
    import re
    import sys
    from pathlib import Path

    from app.services.cv_generator_b2b.champion_builder import _HEADINGS

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from generate_champion_template import SECTION_TITLES  # noqa: PLC0415

    unmatched = []
    for index, title in enumerate(SECTION_TITLES, start=1):
        # Tak, jak nagłówek wygląda w dokumencie: z numerem sekcji.
        line = _fold(f"{index}. {title}")
        if not any(re.match(pattern, line, re.IGNORECASE) for pattern, _ in _HEADINGS):
            unmatched.append(title)

    assert not unmatched, (
        "Parser CV nie rozpozna tych nagłówków wzoru: "
        f"{unmatched}. Dodaj wzorzec w `champion_builder._HEADINGS` — bez niego "
        "sekcja poprzedzająca połknie tę i całą jej treść."
    )


def test_every_content_field_label_is_recognised_by_the_cv_parser() -> None:
    """Etykiety pól TREŚCIOWYCH też muszą pasować do wzorców parsera.

    Osobny test od tego wyżej, bo tamten sprawdza wyłącznie NAGŁÓWKI SEKCJI —
    i właśnie dlatego przepuścił lukę: „Insight od naszego konsultanta u klienta"
    nie pasował do wzorca `INSIGHT OD KONSULTANTA`, więc pole z nowego wzoru
    cicho nie trafiało do promptu generatora CV. Wyszło to dopiero po puszczeniu
    wygenerowanego pliku przez prawdziwy parser, nie przez replikę wyrażenia.
    """
    import re
    import sys
    from pathlib import Path

    from app.services.cv_generator_b2b.champion_builder import _HEADINGS

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from generate_champion_template import CONTENT_FIELD_LABELS  # noqa: PLC0415

    # Wyłącznie wzorce TREŚCIOWE: graniczne (`None`) tylko ucinają sekcję, więc
    # dopasowanie etykiety do jednego z nich nie znaczy, że treść gdziekolwiek trafi.
    content_patterns = [p for p, field in _HEADINGS if field is not None]

    unmatched = [
        label
        for label in CONTENT_FIELD_LABELS
        if not any(
            re.match(pattern, _fold(f"{label}:"), re.IGNORECASE)
            for pattern in content_patterns
        )
    ]
    assert not unmatched, (
        "Parser CV nie zbierze treści spod tych etykiet wzoru: "
        f"{unmatched}. Albo popraw etykietę we wzorze, albo poszerz wzorzec "
        "w `champion_builder._HEADINGS`."
    )


def test_legacy_headings_are_still_recognised() -> None:
    """Stare nagłówki ZOSTAJĄ obok nowych.

    W firmie krąży kilkaset kopii poprzedniego wzoru i będą wgrywane jeszcze
    długo po tym, jak nowy stanie się obowiązujący. Liczby w komentarzach przy
    wzorcach to wystąpienia w 1095 realnie sparsowanych dokumentach — zdjęcie
    któregokolwiek zamieniłoby te pliki w CV bez sekcji.
    """
    import re

    from app.services.cv_generator_b2b.champion_builder import _HEADINGS

    for legacy in (
        "Pytania od Delivery Leada:",
        "MUST-HAVE:",
        "NICE-TO-HAVE:",
        "Obowiazki na stanowisku:",
        "Historyczne pytania:",
        "Kluczowe slowa do wyszukiwania",
        "Co powiedziec o Kliencie",
    ):
        line = _fold(legacy)
        assert any(
            re.match(pattern, line, re.IGNORECASE) for pattern, _ in _HEADINGS
        ), f"stary nagłówek przestał być rozpoznawany: {legacy}"


# ── sekcja 3 jako źródło wymagań dla scoringu ───────────────────────────────


def test_explicit_stack_does_not_depend_on_the_skill_taxonomy() -> None:
    """Jawnie wpisany stack działa TAKŻE przy pustej mapie aliasów.

    Cała reszta `_extract_skills_from_champion` przepuszcza prozę przez regex
    zbudowany z taksonomii i bez niej nie ma czego dopasować — dlatego funkcja
    otwierała się bramką `if pattern is None: return []`. Tier 0 czyta listę
    wpisaną ręcznie, więc regex nie jest mu do niczego potrzebny; bramka nad nim
    kasowałaby jawnie podane wymagania wszędzie tam, gdzie `ALIAS_MAP` nie
    zdążył się załadować — a objaw byłby milczący: pusta lista must-skilli
    wygląda tak samo jak oferta bez Championa.
    """
    from types import SimpleNamespace

    from app.services import scoring_service

    job = SimpleNamespace(
        champion_profile={
            "stack": {
                "must": [{"name": "Java"}, {"name": "WłasnyFramework"}],
                "nice": [],
                "notes": "",
            }
        },
        must_skills=[],
        nice_skills=[],
        requirements=None,
        description=None,
        title=None,
    )

    original = dict(scoring_service.ALIAS_MAP)
    try:
        scoring_service.ALIAS_MAP.clear()
        scoring_service._CHAMPION_ALIAS_PATTERN = None
        found = [
            item["name"] for item in scoring_service._extract_skills_from_champion(job)
        ]
    finally:
        scoring_service.ALIAS_MAP.update(original)
        scoring_service._CHAMPION_ALIAS_PATTERN = None

    # Nazwa spoza taksonomii przechodzi surowa — Delivery Lead wpisujący
    # technologię, której nie znamy, opisuje realne wymaganie, nie literówkę.
    assert found == ["Java", "WłasnyFramework"]


def test_empty_stack_falls_back_to_narrative_extraction() -> None:
    """Profil bez sekcji 3 wraca do zgadywania z prozy — jak przed przebudową.

    Taksonomia jest tu ZASIANA ręcznie: w gołym teście jednostkowym `ALIAS_MAP`
    jest pusta (wypełnia ją `set_alias_map` przy starcie aplikacji), a ścieżka
    narracyjna bez niej nie ma czego dopasować. Test bez zasiewu przechodziłby
    na pustym zbiorze i nie mówiłby nic o tym, co ma sprawdzać.
    """
    from types import SimpleNamespace

    from app.services import scoring_service

    job = SimpleNamespace(
        champion_profile=LEGACY_PROFILE,
        must_skills=[],
        nice_skills=[],
        requirements=None,
        description=None,
        title=None,
    )

    original = dict(scoring_service.ALIAS_MAP)
    try:
        scoring_service.ALIAS_MAP.update({"java": "Java", "kafka": "Kafka"})
        scoring_service._CHAMPION_ALIAS_PATTERN = None
        found = {
            item["name"] for item in scoring_service._extract_skills_from_champion(job)
        }
    finally:
        scoring_service.ALIAS_MAP.clear()
        scoring_service.ALIAS_MAP.update(original)
        scoring_service._CHAMPION_ALIAS_PATTERN = None

    # Z prozy starego profilu (`sourcing.keywords` = "java, kafka, spring").
    assert found == {"Java", "Kafka"}


# ── kontrakt API: front dostaje NOWY kształt, zawsze ────────────────────────


def test_api_returns_the_new_shape_for_a_legacy_profile() -> None:
    """`GET /champion-profile` nie może oddać frontowi surowego starego JSONB.

    Edytor buduje stan jako `{...EMPTY_CHAMPION_PROFILE, ...loaded}`, a kształt
    sprzed 09.2026 nie ma ŻADNEGO z siedmiu kluczy sekcji — przeżywa wyłącznie
    `screening_questions`, bo nazwa się nie zmieniła. Delivery Lead widzi więc
    **pusty formularz na wypełnionym profilu**.

    To nie jest usterka kosmetyczna: zapis z takiego formularza nakłada puste
    sekcje na zmigrowany profil i kasuje treść, którą migracja poprawnie
    odczytała. Wykryte NA PRODUKCJI, nie w testach — oferta 408936 miała w bazie
    `role_name`, `rate_value` 122.5, `seniority_min_years` 10 i opis projektu,
    a wszystkie pola w UI były puste. Testy lokalne tego nie widziały, bo
    harness podglądowy zasiewał cache profilem JUŻ zmigrowanym.
    """
    from app.services.champion_view import api_response

    out = api_response(LEGACY_PROFILE)

    # Sekcje wypełnione danymi ze starego kształtu.
    assert out["basics"]["role_name"] == "Senior Java Developer"
    assert out["basics"]["rate_value"] == 122.50
    assert out["basics"]["seniority_min_years"] == 10
    assert out["search"]["keywords"] == "java, kafka, spring"
    assert out["project"]["about"] == "Rozbudowa platformy płatności."
    assert out["client"]["consultant_insight"] == "Zespół rozproszony, dużo spotkań"
    assert len(out["screening_questions"]) == 1

    # Stare klucze NIE wychodzą — front ma dostać jeden kształt, nie dwa naraz.
    for legacy_key in ("project_context", "sourcing", "client_standards"):
        assert legacy_key not in out

    # Brak profilu to pusty słownik, nie wyjątek i nie szkielet z pustymi polami:
    # `{}` odróżnia „oferta nie ma Championa" od „ma, ale pusty".
    assert api_response(None) == {}
    assert api_response({}) == {}


def test_every_champion_exit_to_the_frontend_goes_through_the_normaliser() -> None:
    """Żadne wyjście profilu do frontu nie może omijać `_champion_response`.

    Normalizacja na jednym endpoincie nie wystarcza: profil wraca do frontu
    także z weryfikacji, briefingu, rekomendowanych wyszukiwań i podglądu
    sugestii. Endpoint, który ją ominie, przywraca dokładnie ten defekt —
    i tylko na swojej ścieżce, więc objaw wygląda na losowy.
    """
    import pathlib
    import re

    # `public_share.py` też jest skanowany, mimo że ma WŁASNY normalizator:
    # `_public_champion_projection` celowo zwraca węższy wycinek (bez naszej
    # stawki i firm docelowych), bo odbiorcą tamtego linku jest strona trzecia.
    # Pominięcie tego pliku w strażniku znaczyłoby, że przyszłe wyjście dopisane
    # tam wymyka się kontroli — a to jest akurat najgorsze miejsce na przeciek.
    for name in ("jobs.py", "pipeline.py", "public_share.py"):
        src = (
            pathlib.Path(__file__).resolve().parents[1] / "app" / "api" / name
        ).read_text(encoding="utf-8")
        # Wartość wyciągana i sprawdzana JAWNIE, nie lookaheadem: `\s*` cofa się
        # do zera znaków, więc `(?!...)` sprawdzałby pozycję spacji i przepuszczał
        # dokładnie te wywołania, których szuka.
        # Trzy dozwolone wywołania: alias routera, pełna ścieżka do
        # `champion_view.api_response` oraz węższa projekcja publiczna.
        allowed = (
            "_champion_response",
            "champion_view.api_response",
            "_public_champion_projection",
        )
        raw = [
            value.strip()
            for value in re.findall(r'"champion_profile":\s*([^\n]+)', src)
            if not value.strip().startswith(allowed)
        ]
        assert not raw, (
            f"{name}: profil Championa wychodzi do frontu z pominięciem "
            f"`_champion_response`: {raw}"
        )


# ── Etykiety pól: wzór Word musi mówić to, co robi kod ──────────────────────


def test_location_label_says_office_not_candidate() -> None:
    """Wiersz lokalizacji nazywa się „Lokalizacja biura", nie „kandydata".

    `scoring_service._score_location` porównuje `basics.candidate_location_pref`
    z miastem KANDYDATA — czyli pole od zawsze znaczyło „dokąd trzeba dojechać".
    Stara etykieta mówiła coś dokładnie odwrotnego do zachowania systemu, więc
    Delivery Lead wpisujący tam miasto zamieszkania kandydata psuł dopasowania,
    robiąc dokładnie to, o co prosił formularz.
    """
    text = _template_text(_generator().build())
    assert "Lokalizacja biura" in text
    assert "Lokalizacja kandydata" not in text


def test_two_distinct_language_rows() -> None:
    """Język PRACY i język CV to dwa różne fakty i wzór musi je rozdzielać.

    `basics.language` to wymaganie wobec kandydata i zasila wektor oferty;
    język dokumentu CV stoi w `ClientCvRule.cv_language`, jest per klient i to
    jego słucha generator. Jedna etykieta „Język" kazała zgadywać, a zgadnięcie
    źle znaczyło albo CV w złym języku, albo utracone wymaganie językowe.
    """
    text = _template_text(_generator().build())
    assert "Język pracy" in text
    # Samo „Język" bez doprecyzowania nie może zostać jako osobny wiersz.
    assert "\nJęzyk\n" not in text


def test_deadline_row_is_back() -> None:
    """Termin na kandydatów wrócił — zgubiony przy przebudowie na 7 sekcji.

    Nie da się go wyprowadzić z niczego innego: KPI klienta („5 dni roboczych")
    opisuje TEMPO, a nie datę tej konkretnej rekrutacji.
    """
    assert "Deadline na kandydatów" in _template_text(_generator().build())


def test_template_has_no_client_standards_box_and_points_to_nexus() -> None:
    """Wzór NIE przepisuje standardów klienta — kieruje do karty klienta w NEXUSIE.

    Do 09.2026 ramka „STANDARDY TEGO KLIENTA" pod tytułem i sekcja 7 „Dokumenty"
    niosły treść per KLIENT, kopiowaną do każdej rekrutacji (14 wzorów Word).
    Ta treść ma od teraz jedno miejsce (`client_playbooks`), więc wzór jest
    jeden, sześciosekcyjny, a pod sekcją 6 stoi odsyłacz zamiast kopii.
    """
    gen = _generator()
    text = _template_text(gen.build())
    assert "STANDARDY TEGO KLIENTA" not in text
    assert "7. DOKUMENTY" not in text
    assert "6. O KLIENCIE" in text
    assert "Zasady współpracy" in text
    assert len(gen.SECTION_TITLES) == 6


def test_section_six_carries_only_role_level_client_fields() -> None:
    """Sekcja 6 zostaje z tym, co zależy od TEJ roli, nie od klienta.

    „Co powiedzieć o Kliencie" i „Reguły priorytetu" przeszły na kartę klienta;
    zostały atuty tej oferty, insight konsultanta i historyczne pytania —
    dokładnie te pola, które czytają wektor oferty i prompt generatora CV.
    """
    text = _template_text(_generator().build())
    assert "Co przekona kandydata do tej oferty" in text
    assert "Co powiedzieć o Kliencie" not in text
    assert "Reguły priorytetu" not in text
    section_six_at = text.find("6. O KLIENCIE")
    assert section_six_at != -1
    assert section_six_at < text.find("Insight od naszego konsultanta u klienta")
    assert section_six_at < text.find("Historyczne pytania klienta")
