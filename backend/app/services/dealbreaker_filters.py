"""Dealbreaker-switche: twarde ukrywanie zamiast punktowania (runda 3).

Punkty degradują, ale nie usuwają — kandydat za 250 PLN/h przy budżecie
120 PLN/h nadal wypływa na listę, tylko niżej. Dla rekrutera to nie jest
„trochę gorszy match", tylko strata czasu. Te filtry są TWARDĄ, świadomie
włączaną wersją tych samych porównań, które scoring robi miękko.

Trzy żelazne zasady, każda okupiona zmierzonym wypadkiem:

1. **Nieznany PRZECHODZI.** Wycinamy wyłącznie na POZYTYWNEJ wiedzy
   (stawka znana i ponad budżet; `remote_only is True`). Filtr stażu przy
   pokryciu 1,2% zredukował kiedyś lejek 11 091 → 45 — brak danych nie jest
   dowodem niedopasowania. WYJĄTEK (decyzja Artura 27.09.2026): must-have.
   Technologia, której nie ma w profilu, CV ani notatkach, ukrywa; kandydat
   bez żadnych danych też (powód ``no_data``) — wcześniej to on wypełniał
   nocne propozycje zamiast ludzi z danymi.
2. **Twardy sufit BEZ marginesu i BEZ osobnego uzbrajania (decyzja
   produktowa Artura, 19.08).** Wpisana/znana stawka budżetu ukrywa każdą
   ZNANĄ stawkę kandydata powyżej niej (strict ``>``; równa przechodzi),
   a sama obecność budżetu aktywuje filtr — zero dodatkowych przełączników.
   Pomiar z 18.08 zostaje tu jako świadomie zaakceptowany koszt: na zbiorach
   A+B (2 212 par z historii decyzji) sufit bez marginesu ukrywa 44% realnie
   dowiezionych kandydatów, bo stawki są rutynowo negocjowane w dół.
   Właściciel produktu wybrał przewidywalność („budżet znaczy budżet") nad
   recall — NIE przywracaj marginesu bez jego decyzji.
3. **Ukrywanie nigdy nie jest ciche.** Konsument dostaje liczniki per powód
   i renderuje „ukryto N" — pustka bez wyjaśnienia czyta się jak utrata
   danych (reguła „awaria ≠ pustka").

Granica finansowa: budżet PLN/h to stawka KANDYDACKA (operacyjna — rekruter
rozmawia o niej z kandydatem codziennie; stawka Championa jest widoczna na
karcie oferty). Cennik klienta pozostaje za VIEW_FINANCE i ten moduł go nie
dotyka. Jedyna porównywalna para jednostek to PLN/h ↔ PLN/h — legacy
``Job.salary_min/max`` (PLN/mies.) jest tu ignorowane z tych samych powodów,
dla których odmawia go warstwa salary (brak polityki konwersji).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Optional, Sequence

from app.core.config import settings


def resolve_job_budget_hourly(job) -> Optional[float]:
    """Budżet PLN/h dla kandydata: jawne pole oferty, fallback Champion.

    ``rate_budget_hourly`` ustawia rekruter na formularzu oferty; gdy puste,
    używamy stawki z profilu Championa (`rate_value` — z definicji dokumentu
    stawka DLA KANDYDATA w PLN/h). Import przez scoring_service, żeby nie
    dublować parsowania profilu i respektować flagę sygnałów Championa.
    """
    explicit = getattr(job, "rate_budget_hourly", None)
    if explicit is not None:
        try:
            value = float(explicit)
        except (TypeError, ValueError):
            value = 0.0
        if value > 0:
            return value
    from app.services.scoring_service import get_champion_hourly_rate

    return get_champion_hourly_rate(job)


def _candidate_rate_pln_hourly(candidate) -> Optional[float]:
    """Stawka kandydata w PLN/h albo None (nieznana / niekanoniczna waluta)."""
    # „Stawka od” (0414) — przed przeliczeniem kandydata stawka profilu.
    from app.services.candidate_rate_from import effective_rate

    rate, currency = effective_rate(candidate)
    if rate is None:
        return None
    # Historical acceptance of an unlabeled profile amount is not evidence
    # that it can be compared with this request's PLN budget.
    if str(currency or "").strip().upper() != "PLN":
        return None
    try:
        value = float(rate)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def budget_excludes(candidate, budget_hourly: float) -> bool:
    """True wyłącznie, gdy ZNANA stawka jest ŚCIŚLE powyżej budżetu.

    Równość przechodzi — kandydat „dokładnie w budżecie" mieści się w nim.
    """
    cand = _candidate_rate_pln_hourly(candidate)
    if cand is None:
        return False
    return cand > budget_hourly


def candidate_consents_below_min_rate(candidate) -> bool:
    """Zgoda z rozmowy telefonicznej na oferty poniżej minimalnej stawki.

    Praktykant wpisuje MINIMUM kandydata w ``expected_rate_hourly``, więc sufit
    budżetu znaczy „budżet poniżej minimum". Jawne „dzwońcie mimo to" (tylko
    ``True``, nie brak odpowiedzi) zostawia takiego kandydata na liście.
    """
    return getattr(candidate, "accepts_below_min_rate", None) is True


def candidate_consents_more_office_days(candidate) -> bool:
    """Zgoda z rozmowy na więcej dni w biurze niż zadeklarowane maksimum."""
    return getattr(candidate, "accepts_more_office_days", None) is True


def employment_only_refuses_b2b(candidate) -> bool:
    """True tylko przy POZYTYWNYM „tylko umowa o pracę" z rozmowy telefonicznej.

    Pracujemy wyłącznie na B2B, więc taka osoba nie jest kandydatem do żadnej
    rekrutacji. Brak odpowiedzi przechodzi — „nieznany przechodzi".
    """
    return getattr(candidate, "b2b_willingness", None) == "employment_only"


def work_time_mismatch(candidate, job_work_mode: Optional[str]) -> bool:
    """True tylko przy ZNANYM wymiarze po obu stronach, który się wyklucza.

    „Tylko part-time" nie pasuje do etatu pełnego, „tylko full-time" — do
    części etatu. ``also_part_time`` pasuje do obu, a ``contract`` (projekt)
    nie mówi o wymiarze, więc nie bramkuje.
    """
    preference = getattr(candidate, "work_time_preference", None)
    if job_work_mode == "fulltime":
        return preference == "part_time_only"
    if job_work_mode == "parttime":
        return preference == "full_time_only"
    return False


def work_time_fit_status(candidate, inputs: "DealbreakerInputs") -> str:
    """Plakietka wymiaru pracy na wierszu dopasowania (decyzja Artura 24.09.2026).

    Sprzeczny wymiar NIE ukrywa kandydata — rekruter widzi ostrzeżenie i sam
    decyduje. ``"part_time_only"`` = kandydat szuka wyłącznie części etatu przy
    rekrutacji na pełny etat, ``"full_time_only"`` = odwrotnie; ``"ok"`` = znany
    i zgodny, ``"unknown"`` = kandydat nie podał, ``"not_applicable"`` =
    rekrutacja bez wymiaru (projekt, Talent Radar).
    """
    mode = inputs.job_work_mode
    if mode not in ("fulltime", "parttime"):
        return "not_applicable"
    preference = getattr(candidate, "work_time_preference", None)
    if preference not in ("full_time_only", "also_part_time", "part_time_only"):
        return "unknown"
    if work_time_mismatch(candidate, mode):
        return preference
    return "ok"


def remote_only_refuses_office(candidate) -> bool:
    """True tylko przy POZYTYWNYM „wyłącznie zdalnie" z notatek.

    Źródło: ``_notes_insights.preferences.remote_only`` — pole strukturalne
    ekstrakcji rozmów (True u 1 382 kandydatów, False u 5 893; reszta to
    nieznane i PRZECHODZI). Świadomie nie zgadujemy z wolnego tekstu.

    Runda 9 (R9-N8-6): notatka jest słabszym źródłem niż profil. Profil,
    który jej przeczy — tryb hybrydowy/stacjonarny, limit dni w biurze większy
    od zera albo zgoda na więcej dni — wygrywa; o biurze decyduje wtedy bramka
    dni (``office_days_exceeded``). Profil „tylko zdalnie” (zwykle uzupełniony
    z tej samej notatki) niczego nie zmienia.
    """
    from app.services.location_utils import _notes_insights_dict

    if candidate_consents_more_office_days(candidate):
        return False
    days = getattr(candidate, "max_onsite_days_per_week", None)
    if isinstance(days, int) and not isinstance(days, bool) and days > 0:
        return False
    profile_prefs = getattr(candidate, "preferences", None)
    modes = (
        profile_prefs.get("remote_modes") if isinstance(profile_prefs, dict) else None
    )
    if isinstance(modes, list) and {"hybrid", "onsite"} & set(modes):
        return False
    ins = _notes_insights_dict(candidate)
    if ins is None:
        return False
    prefs = ins.get("preferences")
    if not isinstance(prefs, dict):
        return False
    return prefs.get("remote_only") is True


# Od tylu dni w biurze inne miasto kandydata ukrywa (niżej — plakietka).
OFFICE_CITY_HARD_MIN_DAYS = 4


@dataclass(frozen=True)
class DealbreakerInputs:
    """Rubryki JEDNEGO wyszukiwania, już rozwiązane. Czyste dane: bez ORM, bez `Job`.

    Konstruowane RAZ na wyszukiwanie (`dealbreaker_inputs_for_job` dla ofert,
    `dealbreaker_inputs_for_radar` dla Talent Radaru) i przekazywane do
    `apply_dealbreakers` — dzięki temu bramka nigdy nie musi wiedzieć, skąd
    wzięły się liczby ani czy chodzi o prawdziwą ofertę, czy o efemeryczne
    zapytanie radaru.
    """

    budget_hourly: Optional[float] = None
    must_skills: tuple[
        str, ...
    ] = ()  # kanoniczne, TYLKO jawne (patrz job_explicit_must_skills)
    # Wpisy `must_skills`, których bramka NIE użyła, bo są punktem wymagań,
    # a nie nazwą technologii. Wystawiane w odpowiedzi `/ai-matches`, żeby
    # niedziałająca bramka nie była cicha — to ta sama zasada co liczniki
    # ukrycia, tylko w drugą stronę.
    must_skills_ignored: tuple[str, ...] = ()
    onsite_days_per_week: Optional[int] = None
    office_tokens: frozenset[str] = frozenset()  # location_tokens(miasto biura)
    wants_office: bool = False  # onsite/hybrid ALBO dni w biurze > 0
    exclude_unknown_skill_evidence: bool = False
    # `Job.work_mode` jako napis (fulltime | parttime | contract). Talent Radar
    # nie zna wymiaru pracy — None wyłącza bramkę wymiaru.
    job_work_mode: Optional[str] = None
    verification_job_id: Optional[int] = None
    verification_fingerprint: Optional[str] = None
    # Tryb pracy rekrutacji (onsite | hybrid | remote) — decyduje, czy inne
    # miasto ukrywa, czy tylko ostrzega (`office_city_is_hard`).
    remote_policy: Optional[str] = None
    # 30.09.2026: skąd są krytyczne (`dl` | `suggested` | `none`; `None` =
    # tryb `all` albo radar) i technologie must+nice, dla których dowód z CV
    # i notatek dołącza się RAZ na paczkę (bramka, plakietki, ocena).
    critical_source: Optional[str] = None
    evidence_labels: tuple[str, ...] = ()
    # „Tylko zdalnie” z notatek UKRYWA wyłącznie przy pracy (prawie)
    # stacjonarnej albo przy jawnym „wyklucz tylko zdalnych”; przy hybrydzie
    # 1–3 dni to plakietka `remote_fit` (decyzja Artura 07.10.2026 — 76% osób
    # z tą flagą, które zespół zweryfikował do biura, wysłano do klienta).
    # Domyślnie True: wołający bez `inputs` zachowuje się jak dotąd.
    remote_only_hides: bool = True
    # Słowa wierszy krytycznych z wyboru Delivery Leada (09.10.2026): etykieta
    # → słowa, których bramka szuka w profilu, CV i notatkach. Dzięki nim
    # krytyczna może być dowolna fraza, nie tylko nazwa technologii
    # (`critical_skills.critical_gate_options`). Krotka par — dataclass
    # pozostaje haszowalna.
    critical_options: tuple[tuple[str, tuple[str, ...]], ...] = ()

    @property
    def gate_options(self) -> dict[str, tuple[str, ...]]:
        """``critical_options`` jako słownik dla funkcji dowodu."""
        return dict(self.critical_options)

    @property
    def gate_evidence_labels(self) -> tuple[str, ...]:
        """Etykiety do ``attach_gate_evidence`` — nadzbiór ``must_skills``."""
        labels = list(self.evidence_labels)
        for label in self.must_skills:
            if label not in labels:
                labels.append(label)
        return tuple(labels)

    @property
    def requires_office_days(self) -> bool:
        return (self.onsite_days_per_week or 0) > 0

    @property
    def office_city_is_hard(self) -> bool:
        """Inne miasto UKRYWA tylko przy pracy (prawie) stacjonarnej.

        Decyzja Artura 27.09.2026 (wariant C): hybryda 1–3 dni w biurze —
        kandydat z innego miasta zostaje z plakietką „inne miasto” (dojazd,
        relokacja); 4–5 dni albo tryb stacjonarny — ukrywa jak dotąd. Zespół
        dodawał do hybryd w Warszawie ludzi z Krakowa czy Łodzi (70 ze 150
        w rekrutacjach z 25.09), a bramka ich chowała.
        """
        return (self.onsite_days_per_week or 0) >= OFFICE_CITY_HARD_MIN_DAYS or (
            self.remote_policy == "onsite"
        )


def missing_must_skills(
    candidate,
    must: Sequence[str],
    *,
    include_unknown: bool = False,
    verification_job_id=None,
    verification_fingerprint=None,
    options: Optional[Mapping[str, Sequence[str]]] = None,
) -> list[str]:
    """Must-have, których kandydat NIE MA nigdzie: profil, CV, notatki.

    Decyzja Artura 27.09.2026: must jest spełniony, gdy technologia stoi na
    liście umiejętności (``skill_present`` — ta sama tolerancja co chipy ✓/✗),
    w tekście profilu, w CV albo w notatkach rekruterów (dowód z
    ``must_text_evidence.attach_gate_evidence``; bez niego — sam profil i CV).
    Wymaganie z kilkoma opcjami („A lub B”, przykłady klienta) spełnia
    dowolna. Weryfikacja rekrutera (``reviewed_gate_status``) ma pierwszeństwo.

    Kandydat bez żadnych danych NIE przechodzi już automatycznie — ma
    wszystkie must „brakujące”, a ``apply_dealbreakers`` liczy go jako
    ``no_data``. ``include_unknown`` dotyczy tylko weryfikacji „nieznane”.
    """
    if not must:
        return []
    from app.services.must_gate_terms import requirement_with_options
    from app.services.must_text_evidence import evidence_for, text_met_labels
    from app.services.requirement_verification import reviewed_gate_status
    from app.services.scoring_service import candidate_skill_names, skill_present

    cand_skills = candidate_skill_names(candidate)
    evidence = evidence_for(candidate, must)
    text_met: Optional[frozenset[str]] = evidence.met if evidence else None
    missing = []
    for label in must:
        review = reviewed_gate_status(
            candidate,
            label,
            job_id=verification_job_id,
            fingerprint=verification_fingerprint,
        )
        if review == "met":
            continue
        if review == "not_met" or (review == "unknown" and include_unknown):
            missing.append(label)
            continue
        requirement = requirement_with_options(label, options)
        names = requirement.options if requirement else (label,)
        if skill_present(label, cand_skills) or any(
            skill_present(name, cand_skills) for name in names
        ):
            continue
        if text_met is None:
            # Bez dołączonego dowodu (testy, ścieżki bez bazy) — profil i CV.
            text_met = text_met_labels(candidate, must, options=options)
        if label in text_met:
            continue
        missing.append(label)
    return missing


def office_days_exceeded(candidate, required_days: Optional[int]) -> bool:
    """True TYLKO gdy wymagane dni > 0 i znana deklaracja kandydata jest niższa.

    Kandydat bez zapisanej deklaracji (`max_onsite_days_per_week is None`)
    przechodzi — „nieznany przechodzi" tak samo jak przy budżecie.
    """
    if not required_days or required_days <= 0:
        return False
    cand_days = getattr(candidate, "max_onsite_days_per_week", None)
    if not isinstance(cand_days, int) or isinstance(cand_days, bool):
        return False
    return cand_days < required_days


def office_city_mismatch(
    candidate, office_tokens: frozenset[str], *, required_days: Optional[int]
) -> bool:
    """True TYLKO gdy oferta wymaga dni w biurze, ma zadeklarowane miasto,
    kandydat ma ZNANE tokeny biura (`candidate_office_tokens`) i żaden nie
    pokrywa się z miastem oferty.

    Brak wymaganych dni, brak miasta oferty lub brak znanej lokalizacji
    kandydata — w każdym z tych przypadków „nie wiemy", więc przechodzi.
    """
    if not required_days or required_days <= 0:
        return False
    if not office_tokens:
        return False
    from app.services.location_utils import candidate_office_tokens, tokens_overlap

    cand_tokens = candidate_office_tokens(candidate)
    if not cand_tokens:
        return False
    return not tokens_overlap(set(office_tokens), cand_tokens)


def resolve_effective_remote_policy(job) -> Optional[str]:
    """Tryb pracy dla rubryk: kolumna oferty, a w jej braku — profil Championa.

    `job.remote_policy` wygrywa zawsze, gdy ustawiona — tak jak
    `resolve_job_budget_hourly` traktuje kolumnę stawki. Fallback do Championa
    działa TYLKO za `CHAMPION_MATCH_SIGNALS_ENABLED` (ta sama flaga, pod którą
    warstwa scoringu — `scoring_service._score_location` — już stosuje ten
    sygnał): bez niej silnik i tak by go nie użył, więc bramka nie miałaby
    czego egzekwować.
    """
    explicit = getattr(job, "remote_policy", None)
    value = getattr(explicit, "value", explicit)
    if value:
        return value
    if not bool(getattr(settings, "CHAMPION_MATCH_SIGNALS_ENABLED", False)):
        return None
    from app.services import champion_view
    from app.services.champion_job_sync import champion_work_mode_to_remote

    return champion_work_mode_to_remote(champion_view.basics(job).get("work_mode"))


# Znaki i słowa, które zdradzają, że wpis `must_skills` jest PUNKTEM WYMAGAŃ,
# a nie nazwą technologii. Myślnik/przecinek/nawias rozdzielają kwalifikator od
# nazwy („apache kafka – minimum 4 lata"), a spójniki i rzeczowniki wymagań
# („i", „lub", „doświadczenie", „znajomość") występują wyłącznie w zdaniach.
# Ukośnik jest tu ŚWIADOMIE, mimo że bywa częścią prawdziwej nazwy (`CI/CD`,
# `TDD/BDD`, `UI/UX`). Zmierzone na produkcji: 24 oferty mają w zestawie
# bramkującym wpis z ukośnikiem, a przytłaczająca większość to ALTERNATYWY
# („Docker/Kubernetes", „Pytest/Jest/Cypress", „Flask/FastAPI", „KYC / AML"),
# których nikt nie ma dosłownie jako umiejętności — czyli ta sama awaria co
# proza, tylko węższa. Wykluczenie ukośnika kosztuje 3 oferty ze 193, które
# tracą bramkę must-have i wracają do stanu sprzed 0278 (bramka słabsza, nikt
# błędnie ukryty). Osiem do jednego na korzyść wykluczenia, a kierunek błędu
# jest ten właściwy: „nieznane przechodzi". `CI/CD` i spółka zostają sygnałem
# dla warstwy punktowej — nie znikają, po prostu nie bramkują.
_PROSE_SEPARATORS = ("–", "—", ",", ";", ":", "(", ")", "|", "&", "/")
_PROSE_WORDS = frozenset(
    {
        "i",
        "oraz",
        "lub",
        "albo",
        "w",
        "z",
        "na",
        "do",
        "przy",
        "od",
        "minimum",
        "min",
        "mile",
        "widziane",
        "co",
        "najmniej",
        "doświadczenie",
        "doswiadczenie",
        "doświadczenia",
        "doswiadczenia",
        "znajomość",
        "znajomosc",
        "znajomości",
        "znajomosci",
        "umiejętność",
        "umiejetnosc",
        "umiejętności",
        "umiejetnosci",
        "gotowość",
        "gotowosc",
        "praktyczna",
        "praktyczne",
        "praktyczny",
        "rok",
        "roku",
        "lat",
        "lata",
        "poziom",
        "poziomie",
        "stanowisku",
        "experience",
        "years",
        "knowledge",
        "ability",
        "minimum.",
        "and",
        "or",
        "with",
        "in",
        "of",
        "the",
    }
)

# Nazwa technologii bywa trzywyrazowa („Amazon Web Services", „Microsoft SQL
# Server"), ale nigdy nie jest zdaniem. Sufit trzymamy przy trzech słowach
# i 40 znakach — powyżej tego w produkcji leżą wyłącznie punkty wymagań.
# Frazy CZYNNOŚCIOWE: „tworzenie dokumentacji technicznej", „pisanie zapytań
# sql", „zarządzanie ryzykiem", „budowa aplikacji webowych", „wykształcenie
# wyższe". Przechodzą testy wyżej (krótkie, bez separatorów, bez słów z
# `_PROSE_WORDS`), ale opisują CZYNNOŚĆ albo wymóg formalny, nie technologię —
# nikt nie ma ich w profilu jako umiejętności, więc bramkowanie nimi opróżnia
# listę tak samo jak proza. Zmierzone po pierwszej naprawie: 20 ofert i 25
# unikalnych wpisów wciąż tak bramkowało.
#
# Rozpoznajemy je po GŁOWIE frazy: polski rzeczownik odczasownikowy kończy się
# na -anie/-enie/-cie, plus krótka lista rzeczowników czynności, które tej
# końcówki nie mają. Wymóg ≥2 słów jest celowy — jednowyrazowe
# „Programowanie" zostawiamy, bo bywa realną deklaracją kandydata.
_ACTIVITY_HEADS = frozenset(
    {
        "budowa",
        "rozwój",
        "rozwoj",
        "wsparcie",
        "analiza",
        "współpraca",
        "wspolpraca",
        "zasady",
        "obsługa",
        "obsluga",
        "utrzymanie",
        "wykształcenie",
        "wyksztalcenie",
    }
)
_ACTIVITY_SUFFIXES = ("anie", "enie", "cie")

_GATE_MAX_WORDS = 3
_GATE_MAX_CHARS = 40


def is_gate_eligible_must(name: str) -> bool:
    """Czy ten wpis `must_skills` bramkuje (27.09.2026: tylko technologie).

    Reguła żyje w `must_gate_terms.gate_requirement`: wersje odcięte („Java 8+”
    → Java), przykłady klienta jako jedno wymaganie („CI/CD tools like
    Bitbucket, Jenkins” → CI/CD lub Bitbucket lub Jenkins), języki, branże,
    metodyki, role i umiejętności miękkie nie bramkują.
    """
    from app.services.must_gate_terms import gate_requirement

    return gate_requirement(name) is not None


def is_syntactic_technology_name(name: str) -> bool:
    """Czy pojedyncza NAZWA wygląda na technologię, a nie na punkt wymagań.

    Bramka porównuje wpis z umiejętnościami kandydata jako CAŁY STRING, więc
    działa wyłącznie dla wpisów będących NAZWĄ technologii. W produkcji 70%
    ofert ma w tej kolumnie punkty wymagań przepisane z ogłoszenia („apache
    kafka – minimum 4 lata komercyjnego doświadczenia", „gotowość do pracy
    hybrydowej w warszawie"), których żaden kandydat nigdy nie ma w profilu
    jako umiejętności — więc bramka ukrywała KAŻDEGO, kto ma jakiekolwiek
    umiejętności, i zostawiała listę pustą.
    """
    text = (name or "").strip()
    if not text or len(text) > _GATE_MAX_CHARS:
        return False
    if any(sep in text for sep in _PROSE_SEPARATORS):
        return False
    words = text.lower().split()
    if not words or len(words) > _GATE_MAX_WORDS:
        return False
    if any(w in _PROSE_WORDS for w in words):
        return False
    if len(words) >= 2:
        head = words[0]
        if head in _ACTIVITY_HEADS or head.endswith(_ACTIVITY_SUFFIXES):
            return False
    return True


def gate_eligible_must_skills(must: Sequence[str]) -> list[str]:
    """Podzbiór `must` nadający się na bramkę — patrz `is_gate_eligible_must`.

    Świadomie NIE zawężamy tego w `job_explicit_must_skills`: bramka gotowości
    handoffu ma nadal widzieć, że Delivery Lead wymagania PODAŁ (podał je, tylko
    prozą), a warstwa punktowa scoringu ma je nadal czytać jako sygnał. Zawęża
    się wyłącznie UKRYWANIE, bo tylko ono krzywdzi przy fałszywym trafieniu.
    """
    return [m for m in must if is_gate_eligible_must(m)]


def _has_any_data(candidate) -> bool:
    from app.services.must_text_evidence import evidence_for, has_any_data

    return has_any_data(candidate, evidence_for(candidate, ()))


def dealbreaker_inputs_for_job(job) -> DealbreakerInputs:
    """Rozwiąż rubryki JEDNEJ oferty raz, dla wszystkich pięciu powierzchni.

    Kolumny oferty (0278: `rate_budget_hourly`, `must_skills`,
    `onsite_days_per_week`, `location`) wygrywają zawsze, gdy ustawione. Profil
    Championa wypełnia braki TYLKO za `CHAMPION_MATCH_SIGNALS_ENABLED` — silnik
    scoringu stosuje ten sam sygnał pod tą samą flagą (poza must-have: Tier 0
    Championa jest bezwarunkowy, patrz `job_explicit_must_skills`), więc bramka
    i punktacja patrzą na to samo. Każdy odczyt idzie przez `getattr`: obiekt
    bez nowych atrybutów (stary stub testowy, oferta efemeryczna sprzed tej
    flagi) daje `None`/puste, nigdy `AttributeError`.
    """
    from app.services.location_utils import location_tokens
    from app.services.scoring_service import job_explicit_must_skills

    budget = resolve_job_budget_hourly(job)
    # Na bramkę idą WYŁĄCZNIE wpisy będące nazwą technologii. Punkty wymagań
    # przepisane z ogłoszenia zostają w scoringu i w bramce gotowości, ale nie
    # ukrywają nikogo — patrz `gate_eligible_must_skills`.
    declared_must = tuple(job_explicit_must_skills(job))
    eligible_must = tuple(gate_eligible_must_skills(declared_must))
    critical_source: Optional[str] = None
    critical_options: dict[str, tuple[str, ...]] = {}
    from app.services.critical_skills import (
        critical_gate_options,
        effective_critical,
        gate_mode,
    )

    if gate_mode() == "critical":
        # 30.09.2026: ukrywają tylko umiejętności krytyczne (decyzja DL albo
        # podpowiedź z historii); reszta must daje punkty (audyt B1/B2).
        resolution = effective_critical(job)
        chosen = set(resolution.labels)
        if resolution.source == "dl":
            # 09.10.2026: o tym, co jest krytyczne, decyduje Delivery Lead —
            # także fraza spoza technologii. Szukamy wtedy słów jej wiersza.
            must = tuple(m for m in declared_must if m in chosen)
            critical_options = critical_gate_options(job)
        else:
            must = tuple(m for m in eligible_must if m in chosen)
        critical_source = resolution.source
    else:
        must = eligible_must
    must_ignored = tuple(m for m in declared_must if m not in set(must))
    evidence_labels = _evidence_labels(job, eligible_must)

    days = getattr(job, "onsite_days_per_week", None)
    office_location = getattr(job, "office_location", None) or getattr(
        job, "location", None
    )

    if bool(getattr(settings, "CHAMPION_MATCH_SIGNALS_ENABLED", False)):
        from app.services import champion_view

        champion = getattr(job, "champion_profile", None)
        champion = champion if isinstance(champion, dict) else {}
        if days is None:
            champ_days = champion_view.basics(job).get("onsite_days_per_week")
            if isinstance(champ_days, int) and not isinstance(champ_days, bool):
                days = champ_days
        if not office_location:
            basics_raw = champion.get("basics")
            basics_raw = basics_raw if isinstance(basics_raw, dict) else {}
            office_location = basics_raw.get("candidate_location_pref") or champion.get(
                "location"
            )

    office_tokens = frozenset(location_tokens(office_location))
    policy = resolve_effective_remote_policy(job)
    explicit_remote_exclusion = bool(getattr(job, "exclude_remote_only", False))
    wants_office = (
        bool(days and days > 0)
        or policy in ("onsite", "hybrid")
        or explicit_remote_exclusion
    )
    remote_only_hides = (
        bool(days and days >= OFFICE_CITY_HARD_MIN_DAYS)
        or policy == "onsite"
        or explicit_remote_exclusion
    )

    work_mode = getattr(job, "work_mode", None)
    work_mode = getattr(work_mode, "value", work_mode)

    return DealbreakerInputs(
        budget_hourly=budget,
        must_skills=must,
        must_skills_ignored=must_ignored,
        onsite_days_per_week=days,
        office_tokens=office_tokens,
        wants_office=wants_office,
        job_work_mode=work_mode if isinstance(work_mode, str) else None,
        remote_policy=policy,
        critical_source=critical_source,
        evidence_labels=evidence_labels,
        remote_only_hides=remote_only_hides,
        critical_options=tuple(critical_options.items()),
    )


def _evidence_labels(job, eligible_must: Sequence[str]) -> tuple[str, ...]:
    """Technologie must i nice oferty, które da się sprawdzić w CV i notatkach.

    Obejmuje też must, które ocena wyciąga z opisu (``job_skill_requirements``
    sięga dalej niż wymagania podane wprost) — inaczej ``_score_skills`` nie
    widziałoby dowodu z CV dla tych pozycji (pomiar 30.09.2026 na produkcji).
    """
    from app.services.scoring_service import job_skill_requirements

    try:
        reqs = job_skill_requirements(job)
        scored = list(reqs.get("must") or []) + list(reqs.get("nice") or [])
    except Exception:  # noqa: BLE001 — obiekt bez pól oferty (radar, atrapa)
        scored = []
    out = list(eligible_must)
    for label in gate_eligible_must_skills(scored):
        if label not in out:
            out.append(label)
    return tuple(out)


def rate_fit_status(candidate, inputs: DealbreakerInputs) -> str:
    """`"ok" | "over_budget" | "below_min_consented" | "unknown"` — status stawki.

    ``below_min_consented``: budżet jest poniżej minimum kandydata, ale kandydat
    zgodził się w rozmowie na telefon z taką ofertą — bramka go nie ukrywa.
    """
    if inputs.budget_hourly is None:
        return "unknown"
    cand_rate = _candidate_rate_pln_hourly(candidate)
    if cand_rate is None:
        return "unknown"
    if cand_rate <= inputs.budget_hourly:
        return "ok"
    if candidate_consents_below_min_rate(candidate):
        return "below_min_consented"
    return "over_budget"


def office_fit_status(candidate, inputs: DealbreakerInputs) -> str:
    """`"ok" | "days_exceeded" | "over_consented" | "city_mismatch" | "unknown" |
    "not_required"`.

    `"not_required"` gdy oferta w ogóle nie wymaga jawnej liczby dni w biurze —
    odróżnia „biuro nas nie dotyczy" od „nie wiemy, ile dni". `"over_consented"`:
    oferta chce więcej dni niż deklaracja kandydata, ale kandydat zgodził się
    w rozmowie na telefon z taką ofertą.
    """
    if not inputs.requires_office_days:
        return "not_required"
    if office_days_exceeded(candidate, inputs.onsite_days_per_week):
        if candidate_consents_more_office_days(candidate):
            return "over_consented"
        return "days_exceeded"
    if office_city_mismatch(
        candidate, inputs.office_tokens, required_days=inputs.onsite_days_per_week
    ):
        return "city_mismatch"
    cand_days = getattr(candidate, "max_onsite_days_per_week", None)
    if not isinstance(cand_days, int) or isinstance(cand_days, bool):
        return "unknown"
    return "ok"


def remote_fit_status(candidate, inputs: DealbreakerInputs) -> str:
    """`"prefers_remote" | "ok" | "not_required"` — plakietka „tylko zdalnie”.

    `"prefers_remote"`: rekrutacja chce biura, ale tylko w trybie hybrydowym
    (nie ukrywamy — rekruter widzi ostrzeżenie), a z notatek wiadomo, że
    kandydat chce pracować wyłącznie zdalnie. Gdy rekrutacja jest stacjonarna,
    taki kandydat jest ukryty i plakietki nie zobaczy nikt.
    """
    if not inputs.wants_office:
        return "not_required"
    if not inputs.remote_only_hides and remote_only_refuses_office(candidate):
        return "prefers_remote"
    return "ok"


@dataclass
class DealbreakerResult:
    kept: list = field(default_factory=list)
    hidden_employment_only: int = 0
    hidden_over_budget: int = 0
    # 27.09.2026: brak must I brak jakichkolwiek danych (CV, umiejętności,
    # notatki) — „nic o nim nie wiemy”, osobno od „nie ma Kafki”.
    hidden_no_data: int = 0
    hidden_missing_must: int = 0
    hidden_office_days_exceeded: int = 0
    hidden_office_city_mismatch: int = 0
    hidden_remote_only: int = 0
    # Od 24.09.2026 wymiar pracy tylko ostrzega (`work_time_fit_status`), więc
    # licznik jest zawsze 0 — zostaje dla kształtu `meta.hidden` i starych
    # przeglądów, które ten powód jeszcze niosą.
    hidden_work_time_mismatch: int = 0
    exclusion_reasons: dict[int, str] = field(default_factory=dict)

    def hidden_meta(self) -> dict:
        # Kolejność kluczy = kolejność powodów w pętli `apply_dealbreakers`
        # (tylko etat → budżet → brak danych → must-have → dni w biurze → miasto →
        # tylko-zdalnie); `work_time_mismatch` zawsze 0 od 24.09.2026.
        return {
            "employment_only": self.hidden_employment_only,
            "over_budget": self.hidden_over_budget,
            "no_data": self.hidden_no_data,
            "missing_must": self.hidden_missing_must,
            "office_days_exceeded": self.hidden_office_days_exceeded,
            "office_city_mismatch": self.hidden_office_city_mismatch,
            "remote_only": self.hidden_remote_only,
            "work_time_mismatch": self.hidden_work_time_mismatch,
        }


def apply_dealbreakers(
    candidates: list,
    *,
    inputs: Optional[DealbreakerInputs] = None,
    exclude_over_budget: bool = True,
    budget_hourly: Optional[float] = None,
    exclude_remote_only: Optional[bool] = None,
    exclude_missing_must: bool = True,
    exclude_office_days_exceeded: bool = True,
    exclude_office_city_mismatch: bool = True,
) -> DealbreakerResult:
    """Przefiltruj listę kandydatów switchami; policz ukrytych per powód.

    ``exclude_over_budget`` ma default ``True`` z decyzji produktowej 19.08:
    znany budżet działa Z AUTOMATU jako dealbreaker (konsument może go jawnie
    wyłączyć, żeby pokazać też przekraczających). Bez znanego budżetu filtr
    jest no-opem — brak budżetu po stronie oferty to także „nie wiemy",
    nie powód do ukrywania.

    Trzy nowe rubryki (0278) mają domyślnie WŁĄCZONE ukrywanie
    (``exclude_missing_must`` / ``exclude_office_days_exceeded`` /
    ``exclude_office_city_mismatch``), ale każda jest no-opem bez danych do
    porównania: pusta ``inputs.must_skills`` nie ukrywa nikogo, a dni/miasto
    działają WYŁĄCZNIE gdy ``inputs.requires_office_days`` (dni > 0).

    ``exclude_remote_only`` domyślnie ``None`` = AUTO: gdy nie podane jawnie,
    rozwiązuje się z ``inputs.wants_office`` — oferta, która chce biura
    (kolumna/Champion/dni > 0), automatycznie ukrywa zadeklarowane „wyłącznie
    zdalnie". Jawne ``True``/``False`` zawsze wygrywa (istniejący kontrakt
    sprzed rubryk — C2 na ``/ai-matches`` liczy to jawnie).

    ``budget_hourly`` (legacy) nadpisuje ``inputs.budget_hourly``, gdy podane —
    zgodność wsteczna z wywołaniami sprzed 0278, które nie znają ``inputs``.

    Kolejność powodów jest deterministyczna i STAŁA: tylko etat → budżet →
    must-have (``no_data``, gdy o kandydacie nic nie wiadomo) → dni w biurze →
    miasto biura (tylko 4+ dni albo stacjonarnie) → tylko-zdalnie.
    Pierwszy pasujący powód wygrywa — kandydat łapiący kilka naraz nie migruje
    między licznikami.

    Fakty z rozmowy praktykanta (0374): „tylko umowa o pracę" ukrywa zawsze
    (jak budżet — to nie rubryka, więc wyłącznik rubryk go nie dotyczy), zgoda
    na ofertę poniżej minimum albo na więcej dni w biurze zostawia kandydata
    widocznym. Znany wymiar pracy sprzeczny z `Job.work_mode` NIE ukrywa
    (decyzja Artura 24.09.2026) — wiersz niesie plakietkę `work_time_fit`.

    Kill-switch ``settings.RUBRIC_DEALBREAKERS_ENABLED`` (default ``True``):
    przy ``False`` trzy nowe predykaty są no-opem, a AUTO ``exclude_remote_only``
    (czyli ``None`` → ``wants_office``) rozwiązuje się do ``False`` — dokładnie
    przedwczesne zachowanie. Jawnie przekazane ``exclude_remote_only`` NIE jest
    dotykane: reguła C2 na ``/ai-matches`` przeżywa wyłącznik.
    """
    rubrics_enabled = bool(getattr(settings, "RUBRIC_DEALBREAKERS_ENABLED", True))
    if not rubrics_enabled:
        exclude_missing_must = False
        exclude_office_days_exceeded = False
        exclude_office_city_mismatch = False
        if exclude_remote_only is None:
            exclude_remote_only = False

    effective_inputs = inputs if inputs is not None else DealbreakerInputs()
    effective_budget = (
        budget_hourly if budget_hourly is not None else effective_inputs.budget_hourly
    )
    if exclude_remote_only is None:
        exclude_remote_only = bool(effective_inputs.wants_office)

    from app.services.critical_skills import gate_mode

    # 30.09.2026 (decyzje Artura): budżet i dni w biurze tylko plakietka
    # (`rate_fit_status`, `office_fit_status`) — ukrywały 32% i 8% osób,
    # które zespół potem wysyłał; kandydat bez żadnych danych ukryty zawsze.
    # `MUST_GATE_MODE=all` przywraca zachowanie v8 w całości.
    critical_mode = gate_mode() == "critical"
    result = DealbreakerResult()
    budget_active = (
        exclude_over_budget and effective_budget is not None and not critical_mode
    )
    must_active = exclude_missing_must and bool(effective_inputs.must_skills)
    days_active = (
        exclude_office_days_exceeded
        and effective_inputs.requires_office_days
        and not critical_mode
    )
    no_data_always = critical_mode and rubrics_enabled
    city_active = (
        exclude_office_city_mismatch
        and effective_inputs.requires_office_days
        and effective_inputs.office_city_is_hard
        and bool(effective_inputs.office_tokens)
    )

    for candidate in candidates:
        if employment_only_refuses_b2b(candidate):
            result.hidden_employment_only += 1
            if (candidate_id := getattr(candidate, "id", None)) is not None:
                result.exclusion_reasons[candidate_id] = "employment_only"
            continue
        if (
            budget_active
            and budget_excludes(candidate, effective_budget)
            and not candidate_consents_below_min_rate(candidate)
        ):
            result.hidden_over_budget += 1
            if (candidate_id := getattr(candidate, "id", None)) is not None:
                result.exclusion_reasons[candidate_id] = "over_budget"
            continue
        if no_data_always and not _has_any_data(candidate):
            result.hidden_no_data += 1
            if (candidate_id := getattr(candidate, "id", None)) is not None:
                result.exclusion_reasons[candidate_id] = "no_data"
            continue
        if must_active and missing_must_skills(
            candidate,
            effective_inputs.must_skills,
            include_unknown=effective_inputs.exclude_unknown_skill_evidence,
            verification_job_id=effective_inputs.verification_job_id,
            verification_fingerprint=effective_inputs.verification_fingerprint,
            options=effective_inputs.gate_options,
        ):
            from app.services.must_text_evidence import evidence_for, has_any_data

            if not has_any_data(
                candidate, evidence_for(candidate, effective_inputs.must_skills)
            ):
                result.hidden_no_data += 1
                reason = "no_data"
            else:
                result.hidden_missing_must += 1
                reason = "missing_must"
            if (candidate_id := getattr(candidate, "id", None)) is not None:
                result.exclusion_reasons[candidate_id] = reason
            continue
        if (
            days_active
            and office_days_exceeded(candidate, effective_inputs.onsite_days_per_week)
            and not candidate_consents_more_office_days(candidate)
        ):
            result.hidden_office_days_exceeded += 1
            if (candidate_id := getattr(candidate, "id", None)) is not None:
                result.exclusion_reasons[candidate_id] = "office_days_exceeded"
            continue
        if city_active and office_city_mismatch(
            candidate,
            effective_inputs.office_tokens,
            required_days=effective_inputs.onsite_days_per_week,
        ):
            result.hidden_office_city_mismatch += 1
            if (candidate_id := getattr(candidate, "id", None)) is not None:
                result.exclusion_reasons[candidate_id] = "office_city_mismatch"
            continue
        if (
            exclude_remote_only
            and effective_inputs.remote_only_hides
            and remote_only_refuses_office(candidate)
        ):
            result.hidden_remote_only += 1
            if (candidate_id := getattr(candidate, "id", None)) is not None:
                result.exclusion_reasons[candidate_id] = "remote_only"
            continue
        result.kept.append(candidate)
    return result
