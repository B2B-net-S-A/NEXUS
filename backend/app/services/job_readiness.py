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
MSG_SEARCH_REQUIREMENTS = (
    "Dodaj co najmniej jedno wymaganie do wyszukiwania w bazie "
    "(sekcja „Co wpisać” w Profilu Championa)."
)

# Kod walidacji Championa → zdanie bramki briefu/rubryki, które opisuje TEN SAM
# brak. Issue Championa znika z listy handoffu WYŁĄCZNIE wtedy, gdy to zdanie
# faktycznie jest na liście — inaczej DL widziałby ten sam brak dwa razy,
# raz słowami bramki, raz słowami Championa. Gdy bramki się rozjeżdżają (np.
# hybryda z zerem dni: rubryka uznaje zero za znaną wartość, walidacja nie),
# issue ZOSTAJE: pusta lista braków przy przycisku, który po kliknięciu
# i tak dostałby 422 z ``enforce_operation``, byłaby kłamstwem.
# Każdy inny kod (``column_conflict``, ``skill_column_conflict``,
# ``unresolved_value``, ``ineligible_must``, ``conflicting_office_days``,
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

    return blockers


def job_search_blockers(job: Job) -> list[str]:
    """Wymagania do wyszukiwania w bazie (sekcja 2 Championa, 25.09.2026).

    Decyzja Artura: rekrutacja trafia do searchu z co najmniej jednym wierszem
    wymagań — to od nich rekruter zaczyna „Szukaj ręcznie”. Tylko przy
    handoffie (jak rubryki): automatyczna alokacja tego nie czyta.
    """
    if champion_view.search_requirements(job.champion_profile):
        return []
    return [MSG_SEARCH_REQUIREMENTS]


def job_handoff_blockers(job: Job) -> list[str]:
    """Pełna bramka „Przekaż do searchu": brief + trzy rubryki + wymagania do
    wyszukiwania, w tej kolejności.

    Kolejność jest częścią kontraktu — ``JobHandoffButton`` renderuje listę
    dosłownie, a braki briefu są bardziej podstawowe niż braki rubryk.

    Czwarty składnik dokłada braki widoczne WYŁĄCZNIE w Profilu Championa
    (``column_conflict``, ``skill_column_conflict``, ``unresolved_value``,
    ...) — ale pomija issue, którego brak (``_MIRRORED_VALIDATION_CODES``)
    lista wyżej JUŻ nazywa swoim zdaniem. Rozjazd bramek zostaje widoczny.
    """
    from app.services.champion_intake import validation

    issues = validation(job.champion_profile, job)["issues"]
    gate = (
        job_readiness_blockers(job)
        + job_rubric_blockers(job)
        + job_search_blockers(job)
    )
    listed = set(gate)
    return gate + [
        issue["message"]
        for issue in issues
        if "handoff" in issue["blocked_operations"]
        and _MIRRORED_VALIDATION_CODES.get(issue["code"]) not in listed
    ]
