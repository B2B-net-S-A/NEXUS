"""Dwie bramki gotowości rekrutacji — brief i rubryki — i dlaczego są DWIE.

``job_readiness_blockers`` odpowiada na pytanie „czy brief jest na tyle
kompletny, żeby ktokolwiek mógł zacząć szukać": tytuł, klient, kontekst
projektu i dwa pytania screeningowe. Czyta ją nie tylko ręczny handoff, ale też
**automatyczna alokacja rekrutacji** (``recruitment_allocation``), która przy
niepustej liście parkuje żądanie jako ``brief_not_ready``.

``job_handoff_blockers`` dokłada do tego trzy rubryki rekrutacji (0278):
must-have, budżet PLN/h i obecność w biurze. Ta bramka obowiązuje WYŁĄCZNIE
przy „Przekaż do searchu" i na ekranie gotowości, który ten przycisk opisuje.

**Rozdzielenie jest celowe i nie wolno go zwijać z powrotem w jedną funkcję.**
Rubryki dorzucone do wspólnej bramki zatrzymałyby automatyczną alokację dla
każdej rekrutacji, która ich nie ma — czyli po cichu wyłączyłyby świeżo wdrożoną
funkcję, której ta zmiana wcale nie dotyczy. Objaw byłby niewidoczny: żądania
parkowałyby się z powodem „brief_not_ready", a nikt nie szukałby przyczyny
w bramce handoffu. Złapały to dopiero
``tests/test_recruitment_allocation_database.py`` (alokacja przestawała
przypisywać rekruterów), nie testy handoffu.
"""

from app.models.job import Job
from app.services import champion_view
from app.services.dealbreaker_filters import (
    dealbreaker_inputs_for_job,
    resolve_effective_remote_policy,
)

# Komunikaty bramek — jedna definicja, bo ten sam tekst jest kontraktem
# ``JobHandoffButton`` i testów ORAZ kluczem odduplikowania niżej.
MSG_TITLE = "Uzupełnij tytuł rekrutacji."
MSG_CLIENT = "Przypisz klienta do rekrutacji."
MSG_CONTEXT = (
    "Uzupełnij kontekst projektu (o projekcie / obowiązki) w Profilu Championa."
)
MSG_QUESTIONS = "Dodaj co najmniej 2 pytania screeningowe w Profilu Championa."
MSG_MUST = (
    "Dodaj co najmniej jedną technologię must-have (pole oferty lub "
    "sekcja „Stack technologiczny” w Profilu Championa)."
)
MSG_BUDGET = (
    "Uzupełnij budżet stawki kandydata w PLN/h (pole oferty lub "
    "stawka w Profilu Championa)."
)
MSG_WORK_MODE = "Określ tryb pracy: zdalnie, hybrydowo albo stacjonarnie."
MSG_OFFICE_DAYS = "Podaj liczbę dni w biurze w tygodniu (tryb hybrydowy/stacjonarny)."
MSG_OFFICE_CITY = (
    "Podaj miasto biura w lokalizacji oferty (tryb hybrydowy/stacjonarny)."
)
MSG_CRITICAL = (
    "Potwierdź umiejętności krytyczne w Profilu Championa (albo wybierz "
    "„Brak krytycznych”)."
)
MSG_SEARCH_REQUIREMENTS = (
    "Dodaj co najmniej jedno wymaganie do wyszukiwania w bazie "
    "(sekcja „Co wpisać” w Profilu Championa)."
)
MSG_DEAL_BREAKER = (
    "Przy każdym pytaniu screeningowym wpisz odpowiedź, która dyskwalifikuje "
    "kandydata (Profil Championa)."
)
# Rekrutacja bez szkiców (04.10.2026): decyzje, których wymaga przekazanie.
MSG_HIRING_MANAGER = "Wskaż hiring managera albo zaznacz „Klient nie podał”."
MSG_DEADLINE = "Ustaw termin albo zaznacz „Klient nie podał”."
MSG_CATEGORY = "Wybierz kategorię kompetencji."
MSG_HEADCOUNT = "Podaj liczbę osób do zatrudnienia (co najmniej 1)."

# Kod braku → zdanie. Kody są kluczami lustra frontu
# (`frontend/src/lib/__fixtures__/job-readiness-blockers.json`) — formularz
# `/jobs/new` mapuje po nich brak na sekcję, a ochrona przed nowym brakiem
# (`assert_no_new_handoff_blockers`) porównuje KODY, nie zdania: zdania braków
# Championa niosą wartości, więc porównanie zdań odrzucałoby niewinne edycje.
BLOCKER_CODES: dict[str, str] = {
    "title": MSG_TITLE,
    "client": MSG_CLIENT,
    "context": MSG_CONTEXT,
    "questions": MSG_QUESTIONS,
    "must": MSG_MUST,
    "budget": MSG_BUDGET,
    "work_mode": MSG_WORK_MODE,
    "office_days": MSG_OFFICE_DAYS,
    "office_city": MSG_OFFICE_CITY,
    "critical": MSG_CRITICAL,
    "search": MSG_SEARCH_REQUIREMENTS,
    "deal_breaker": MSG_DEAL_BREAKER,
    "hiring_manager": MSG_HIRING_MANAGER,
    "deadline": MSG_DEADLINE,
    "category": MSG_CATEGORY,
    "headcount": MSG_HEADCOUNT,
}
_CODE_BY_MESSAGE: dict[str, str] = {msg: code for code, msg in BLOCKER_CODES.items()}

# Kod walidacji Championa → zdanie bramki briefu/rubryki, które opisuje TEN SAM
# brak. Issue Championa znika z listy handoffu WYŁĄCZNIE wtedy, gdy to zdanie
# faktycznie jest na liście — inaczej DL widziałby ten sam brak dwa razy,
# raz słowami bramki, raz słowami Championa. Gdy bramki się rozjeżdżają (np.
# hybryda z zerem dni: rubryka uznaje zero za znaną wartość, walidacja nie),
# issue ZOSTAJE: pusta lista braków przy przycisku, który po kliknięciu
# i tak dostałby 422 z ``enforce_operation``, byłaby kłamstwem.
# Każdy inny kod (``column_conflict``, ``skill_column_conflict``,
# ``unresolved_value``, ``critical_not_in_must``, ``conflicting_office_days``,
# ``ambiguous_office``, ...) jest realnym dodatkiem i zostaje zawsze.
_MIRRORED_VALIDATION_CODES: dict[str, str] = {
    "missing_role": MSG_TITLE,
    "missing_client": MSG_CLIENT,
    "missing_context": MSG_CONTEXT,
    "missing_questions": MSG_QUESTIONS,
    "missing_requirements": MSG_MUST,
    "missing_must": MSG_MUST,
    "missing_budget": MSG_BUDGET,
    "missing_work_mode": MSG_WORK_MODE,
    "missing_office_days": MSG_OFFICE_DAYS,
    "missing_office_city": MSG_OFFICE_CITY,
}


def job_readiness_blockers(job: Job) -> list[str]:
    """Czy brief w ogóle nadaje się do szukania (P0-A).

    Champion jest wymagany: to specyfikacja idealnego kandydata od Delivery
    Leada i najmocniejszy sygnał matchingu, więc handoff bez niego dawałby
    słaby ranking wyłącznie z treści ogłoszenia — dokładnie problem „ranking
    przed Championem", któremu handoff ma zapobiegać. Stąd kontekst projektu
    plus co najmniej dwa pytania screeningowe, obok podstaw (tytuł, klient),
    które kotwiczą wyszukiwanie.

    Rubryk rekrutacji TU NIE MA — patrz docstring modułu i
    :func:`job_handoff_blockers`.
    """
    blockers: list[str] = []
    if not (job.title or "").strip():
        blockers.append(MSG_TITLE)
    if job.client_id is None:
        blockers.append(MSG_CLIENT)

    cp = job.champion_profile if isinstance(job.champion_profile, dict) else {}
    pc = champion_view.project(cp)
    has_context = bool((pc.get("about") or "").strip()) or bool(
        pc.get("responsibilities")
    )
    if not has_context:
        blockers.append(MSG_CONTEXT)

    questions = cp.get("screening_questions")
    questions = questions if isinstance(questions, list) else []
    valid_questions = [
        q
        for q in questions
        if isinstance(q, dict) and (q.get("question") or "").strip()
    ]
    if len(valid_questions) < 2:
        blockers.append(MSG_QUESTIONS)

    return blockers


def job_rubric_blockers(job: Job) -> list[str]:
    """Trzy rubryki rekrutacji: must-have, stawka, obecność w biurze (0278).

    ``inputs``/``policy`` liczone RAZ i tym samym resolverem co dealbreakery na
    pięciu powierzchniach rankingu — bramka pyta dokładnie o to, co później
    faktycznie egzekwuje ranking, więc Delivery Lead nie może wypełnić bramki
    czymś, czego silnik i tak nie przeczyta.

    Budżet jest ZAWSZE wymagany (decyzja produktowa 07.09), niezależnie od trybu
    pracy. Dni w biurze i miasto biura wymagane są TYLKO przy ``onsite``/
    ``hybrid`` — oferta w pełni zdalna nie ma czego pytać o biuro.
    ``onsite_days_per_week == 0`` przy hybrydzie/stacjonarnie jest ZNANĄ
    wartością (np. „hybrydowo, ale bez ustalonej liczby dni" zapisane jako
    zero) i nie blokuje: dealbreakery dni/miasta są wtedy i tak no-opem
    (``DealbreakerInputs.requires_office_days`` jest ``False`` dla zera).
    """
    blockers: list[str] = []
    inputs = dealbreaker_inputs_for_job(job)
    policy = resolve_effective_remote_policy(job)

    # Must-have PODANE prozą (`must_skills_ignored`) też są podane: nie
    # bramkują rankingu, ale Delivery Lead wypełnił rubrykę — handoff nie może
    # odsyłać go po „technologię”, którą już wpisał zdaniem (patrz
    # `gate_eligible_must_skills`).
    if not (inputs.must_skills or inputs.must_skills_ignored):
        blockers.append(MSG_MUST)
    if inputs.budget_hourly is None:
        blockers.append(MSG_BUDGET)
    if policy is None:
        blockers.append(MSG_WORK_MODE)
    elif policy in ("onsite", "hybrid"):
        if inputs.onsite_days_per_week is None:
            blockers.append(MSG_OFFICE_DAYS)
        if not inputs.office_tokens:
            blockers.append(MSG_OFFICE_CITY)
    if critical_decision_missing(job):
        blockers.append(MSG_CRITICAL)

    return blockers


def critical_decision_missing(job: Job) -> bool:
    """Decyzja DL o umiejętnościach krytycznych (30.09.2026).

    Wymagana, gdy MUST ma co najmniej jedną technologię ze słownika, a pole
    ``stack.critical`` jest puste (``None``). „Brak krytycznych” (``[]``) to
    decyzja. W trybie ``MUST_GATE_MODE=all`` bramka nie czyta krytycznych.
    """
    from app.services.critical_skills import gate_mode, stored_critical
    from app.services.must_gate_terms import critical_eligible
    from app.services.scoring_service import job_explicit_must_skills

    if gate_mode() != "critical" or stored_critical(job) is not None:
        return False
    return any(critical_eligible(label) for label in job_explicit_must_skills(job))


def job_search_blockers(job: Job) -> list[str]:
    """Wymagania do wyszukiwania w bazie (sekcja 2 Championa, 25.09.2026).

    Decyzja Artura: rekrutacja trafia do searchu z co najmniej jednym wierszem
    wymagań — to od nich rekruter zaczyna „Szukaj ręcznie”. Tylko przy
    handoffie (jak rubryki): automatyczna alokacja tego nie czyta.
    """
    if champion_view.search_requirements(job.champion_profile):
        return []
    return [MSG_SEARCH_REQUIREMENTS]


def job_question_blockers(job: Job, *, include_open: bool = False) -> list[str]:
    """Odpowiedź dyskwalifikująca przy każdym pytaniu (decyzja Artura 02.10.2026).

    Rekruter ma wiedzieć nie tylko, co jest dobrą odpowiedzią, ale i co
    kandydata skreśla. Tylko przy PIERWSZYM przekazaniu do searchu: rekrutacja
    już przekazana (`is_open`) nie jest blokowana — 96 z 99 pytań sprzed tej
    daty nie miało tego pola. Automatyczna alokacja tej bramki nie czyta.

    ``include_open=True`` liczy pytania także przy ``is_open`` — ponowne
    otwarcie rekrutacji i ochrona przed nowym brakiem w trakcie pracy
    (rekrutacja bez szkiców, 04.10.2026).
    """
    if getattr(job, "is_open", False) and not include_open:
        return []
    questions = (job.champion_profile or {}).get("screening_questions")
    for question in questions if isinstance(questions, list) else []:
        if not isinstance(question, dict):
            continue
        if not str(question.get("question") or "").strip():
            continue
        if not str(question.get("deal_breaker") or "").strip():
            return [MSG_DEAL_BREAKER]
    return []


def job_decision_blockers(job: Job) -> list[str]:
    """Decyzje wymagane przy przekazaniu (rekrutacja bez szkiców, 04.10.2026).

    Hiring manager i termin: wartość albo jawne „Klient nie podał”. Kategoria
    kompetencji (uczestnicy rekrutacji i automat przydziału czytają ją
    wprost) i liczba osób co najmniej 1. Tylko w bramce przekazania — bramka
    briefu automatu przydziału (`job_readiness_blockers`) jej nie czyta.
    """
    blockers: list[str] = []
    if getattr(job, "hiring_manager_contact_id", None) is None and not getattr(
        job, "hiring_manager_not_provided", False
    ):
        blockers.append(MSG_HIRING_MANAGER)
    if getattr(job, "deadline", None) is None and not getattr(
        job, "deadline_not_provided", False
    ):
        blockers.append(MSG_DEADLINE)
    if getattr(job, "competence_category_id", None) is None:
        blockers.append(MSG_CATEGORY)
    if (getattr(job, "headcount", None) or 0) < 1:
        blockers.append(MSG_HEADCOUNT)
    return blockers


def job_handoff_blocker_items(
    job: Job, *, include_open: bool = False
) -> list[dict[str, str]]:
    """Pełna bramka przekazania jako ``[{code, message}]`` — kolejność jak
    w :func:`job_handoff_blockers`.

    Kody: klucze ``BLOCKER_CODES`` (lustro frontu), a dla braków widocznych
    wyłącznie w Profilu Championa — ``champion:<kod walidacji>``.
    ``include_open`` — patrz :func:`job_question_blockers`.
    """
    from app.services.champion_intake import validation

    issues = validation(job.champion_profile, job)["issues"]
    gate = (
        job_readiness_blockers(job)
        + job_rubric_blockers(job)
        + job_search_blockers(job)
        + job_question_blockers(job, include_open=include_open)
        + job_decision_blockers(job)
    )
    listed = set(gate)
    items = [
        {"code": _CODE_BY_MESSAGE[message], "message": message} for message in gate
    ]
    items += [
        {"code": f"champion:{issue['code']}", "message": issue["message"]}
        for issue in issues
        if "handoff" in issue["blocked_operations"]
        and _MIRRORED_VALIDATION_CODES.get(issue["code"]) not in listed
    ]
    return items


def handoff_blocker_codes(job: Job) -> set[str]:
    """Kody braków rekrutacji w pracy — wejście ochrony przed nowym brakiem."""
    return {item["code"] for item in job_handoff_blocker_items(job, include_open=True)}


# Brak, który wychodzi dopiero po uzupełnieniu „rodzica” (pytania bez odpowiedzi
# dyskwalifikującej, tryb pracy bez dni i miasta biura, must-have bez decyzji
# o krytycznych), nie jest NOWYM brakiem — zapis naprawił rodzica, a nie
# zepsuł rekrutację. Inaczej stara rekrutacja bez pytań nie dałaby się
# uzupełniać po kawałku.
_REVEALED_BY: dict[str, str] = {
    "deal_breaker": "questions",
    "office_days": "work_mode",
    "office_city": "work_mode",
    "critical": "must",
}


def new_handoff_blockers(before: set[str], job: Job) -> list[dict[str, str]]:
    """Braki, których nie było przed zapisem (porównanie po KODACH)."""
    return [
        item
        for item in job_handoff_blocker_items(job, include_open=True)
        if item["code"] not in before and _REVEALED_BY.get(item["code"]) not in before
    ]


def job_handoff_blockers(job: Job) -> list[str]:
    """Pełna bramka „Przekaż do searchu": brief + trzy rubryki + wymagania do
    wyszukiwania + odpowiedzi dyskwalifikujące + decyzje (hiring manager,
    termin, kategoria, liczba osób — 04.10.2026), w tej kolejności.

    Kolejność jest częścią kontraktu — ``JobHandoffButton`` renderuje listę
    dosłownie, a braki briefu są bardziej podstawowe niż braki rubryk.

    Czwarty składnik dokłada braki widoczne WYŁĄCZNIE w Profilu Championa
    (``column_conflict``, ``skill_column_conflict``, ``unresolved_value``,
    ...) — ale pomija issue, którego brak (``_MIRRORED_VALIDATION_CODES``)
    lista wyżej JUŻ nazywa swoim zdaniem. Rozjazd bramek zostaje widoczny.
    """
    return [item["message"] for item in job_handoff_blocker_items(job)]
