"""Dealbreaker-switche: twarde ukrywanie zamiast punktowania (runda 3).

Punkty degradują, ale nie usuwają — kandydat za 250 PLN/h przy budżecie
120 PLN/h nadal wypływa na listę, tylko niżej. Dla rekrutera to nie jest
„trochę gorszy match", tylko strata czasu. Te filtry są TWARDĄ, świadomie
włączaną wersją tych samych porównań, które scoring robi miękko.

Trzy żelazne zasady, każda okupiona zmierzonym wypadkiem:

1. **Nieznany PRZECHODZI.** Wycinamy wyłącznie na POZYTYWNEJ wiedzy
   (stawka znana i ponad budżet; `remote_only is True`). Filtr stażu przy
   pokryciu 1,2% zredukował kiedyś lejek 11 091 → 45 — brak danych nie jest
   dowodem niedopasowania.
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
from typing import Optional, Sequence

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
    rate = getattr(candidate, "expected_rate_hourly", None)
    if rate is None:
        return None
    currency = getattr(candidate, "expected_rate_currency", None)
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


def remote_only_refuses_office(candidate) -> bool:
    """True tylko przy POZYTYWNYM „wyłącznie zdalnie" z notatek.

    Źródło: ``_notes_insights.preferences.remote_only`` — pole strukturalne
    ekstrakcji rozmów (True u 1 382 kandydatów, False u 5 893; reszta to
    nieznane i PRZECHODZI). Świadomie nie zgadujemy z wolnego tekstu.
    """
    from app.services.location_utils import _notes_insights_dict

    ins = _notes_insights_dict(candidate)
    if ins is None:
        return False
    prefs = ins.get("preferences")
    if not isinstance(prefs, dict):
        return False
    return prefs.get("remote_only") is True


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
    verification_job_id: Optional[int] = None
    verification_fingerprint: Optional[str] = None

    @property
    def requires_office_days(self) -> bool:
        return (self.onsite_days_per_week or 0) > 0


def missing_must_skills(
    candidate,
    must: Sequence[str],
    *,
    include_unknown: bool = False,
    verification_job_id=None,
    verification_fingerprint=None,
) -> list[str]:
    """Must-have, których kandydatowi BRAKUJE — „nieznany przechodzi".

    Pusta `must` → `[]` (nie ma czego wymagać). Kandydat bez ŻADNEGO sygnału
    umiejętności (`candidate_skill_names` puste — ani `skills`, ani
    `verified_tech`, ani CV, ani tagi) → `[]` też: brak danych nie jest dowodem
    niedopasowania, tylko brakiem wiedzy. Porównanie idzie przez `skill_present`
    (tolerancja `postgresql`/`postgres`, `node.js`/`nodejs`) — TĘ SAMĄ funkcję,
    której używają chipy ✓/✗ na `/ai-matches`.

    `include_unknown=True` implements an explicitly selected missing-proof
    exclusion policy; it does not turn missing evidence into proven inability.
    """
    if not must:
        return []
    from app.services.scoring_service import candidate_skill_names, skill_present

    from app.services.requirement_verification import reviewed_gate_status

    cand_skills = candidate_skill_names(candidate)
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
        elif (
            review is None
            and (cand_skills or include_unknown)
            and not skill_present(label, cand_skills)
        ):
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
    """Czy ten wpis `must_skills` nadaje się na TWARDĄ bramkę.

    Bramka porównuje wpis z umiejętnościami kandydata jako CAŁY STRING, więc
    działa wyłącznie dla wpisów będących NAZWĄ technologii. W produkcji 70%
    ofert ma w tej kolumnie punkty wymagań przepisane z ogłoszenia („apache
    kafka – minimum 4 lata komercyjnego doświadczenia", „gotowość do pracy
    hybrydowej w warszawie"), których żaden kandydat nigdy nie ma w profilu
    jako umiejętności — więc bramka ukrywała KAŻDEGO, kto ma jakiekolwiek
    umiejętności, i zostawiała listę pustą.
    """
    from app.services.requirement_contract import alternatives

    options = alternatives(name or "")
    if len(options) > 1:
        return all(is_gate_eligible_must(option) for option in options)
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
    must = tuple(gate_eligible_must_skills(declared_must))
    must_ignored = tuple(m for m in declared_must if m not in set(must))

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
    wants_office = (
        bool(days and days > 0)
        or policy in ("onsite", "hybrid")
        or bool(getattr(job, "exclude_remote_only", False))
    )

    return DealbreakerInputs(
        budget_hourly=budget,
        must_skills=must,
        must_skills_ignored=must_ignored,
        onsite_days_per_week=days,
        office_tokens=office_tokens,
        wants_office=wants_office,
    )


def rate_fit_status(candidate, inputs: DealbreakerInputs) -> str:
    """`"ok" | "over_budget" | "unknown"` — status stawki dla etykiety wiersza."""
    if inputs.budget_hourly is None:
        return "unknown"
    cand_rate = _candidate_rate_pln_hourly(candidate)
    if cand_rate is None:
        return "unknown"
    return "over_budget" if cand_rate > inputs.budget_hourly else "ok"


def office_fit_status(candidate, inputs: DealbreakerInputs) -> str:
    """`"ok" | "days_exceeded" | "city_mismatch" | "unknown" | "not_required"`.

    `"not_required"` gdy oferta w ogóle nie wymaga jawnej liczby dni w biurze —
    odróżnia „biuro nas nie dotyczy" od „nie wiemy, ile dni".
    """
    if not inputs.requires_office_days:
        return "not_required"
    if office_days_exceeded(candidate, inputs.onsite_days_per_week):
        return "days_exceeded"
    if office_city_mismatch(
        candidate, inputs.office_tokens, required_days=inputs.onsite_days_per_week
    ):
        return "city_mismatch"
    cand_days = getattr(candidate, "max_onsite_days_per_week", None)
    if not isinstance(cand_days, int) or isinstance(cand_days, bool):
        return "unknown"
    return "ok"


@dataclass
class DealbreakerResult:
    kept: list = field(default_factory=list)
    hidden_over_budget: int = 0
    hidden_missing_must: int = 0
    hidden_office_days_exceeded: int = 0
    hidden_office_city_mismatch: int = 0
    hidden_remote_only: int = 0

    def hidden_meta(self) -> dict:
        # Kolejność kluczy = kolejność powodów w pętli `apply_dealbreakers`
        # (budżet → must-have → dni w biurze → miasto → tylko-zdalnie).
        return {
            "over_budget": self.hidden_over_budget,
            "missing_must": self.hidden_missing_must,
            "office_days_exceeded": self.hidden_office_days_exceeded,
            "office_city_mismatch": self.hidden_office_city_mismatch,
            "remote_only": self.hidden_remote_only,
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

    Kolejność powodów jest deterministyczna i STAŁA: budżet → must-have →
    dni w biurze → miasto biura → tylko-zdalnie. Pierwszy pasujący powód
    wygrywa — kandydat łapiący kilka naraz nie migruje między licznikami.

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

    result = DealbreakerResult()
    budget_active = exclude_over_budget and effective_budget is not None
    must_active = exclude_missing_must and bool(effective_inputs.must_skills)
    days_active = exclude_office_days_exceeded and effective_inputs.requires_office_days
    city_active = (
        exclude_office_city_mismatch
        and effective_inputs.requires_office_days
        and bool(effective_inputs.office_tokens)
    )

    for candidate in candidates:
        if budget_active and budget_excludes(candidate, effective_budget):
            result.hidden_over_budget += 1
            continue
        if must_active and missing_must_skills(
            candidate,
            effective_inputs.must_skills,
            include_unknown=effective_inputs.exclude_unknown_skill_evidence,
            verification_job_id=effective_inputs.verification_job_id,
            verification_fingerprint=effective_inputs.verification_fingerprint,
        ):
            result.hidden_missing_must += 1
            continue
        if days_active and office_days_exceeded(
            candidate, effective_inputs.onsite_days_per_week
        ):
            result.hidden_office_days_exceeded += 1
            continue
        if city_active and office_city_mismatch(
            candidate,
            effective_inputs.office_tokens,
            required_days=effective_inputs.onsite_days_per_week,
        ):
            result.hidden_office_city_mismatch += 1
            continue
        if exclude_remote_only and remote_only_refuses_office(candidate):
            result.hidden_remote_only += 1
            continue
        result.kept.append(candidate)
    return result
