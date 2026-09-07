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
        blockers.append("Uzupełnij tytuł rekrutacji.")
    if job.client_id is None:
        blockers.append("Przypisz klienta do rekrutacji.")

    cp = job.champion_profile if isinstance(job.champion_profile, dict) else {}
    pc = champion_view.project(cp)
    has_context = bool((pc.get("about") or "").strip()) or bool(
        pc.get("responsibilities")
    )
    if not has_context:
        blockers.append(
            "Uzupełnij kontekst projektu (o projekcie / obowiązki) w Profilu Championa."
        )

    questions = cp.get("screening_questions")
    questions = questions if isinstance(questions, list) else []
    valid_questions = [
        q
        for q in questions
        if isinstance(q, dict) and (q.get("question") or "").strip()
    ]
    if len(valid_questions) < 2:
        blockers.append("Dodaj co najmniej 2 pytania screeningowe w Profilu Championa.")

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

    if not inputs.must_skills:
        blockers.append(
            "Dodaj co najmniej jedną technologię must-have (pole oferty lub "
            "sekcja „Stack technologiczny” w Profilu Championa)."
        )
    if inputs.budget_hourly is None:
        blockers.append(
            "Uzupełnij budżet stawki kandydata w PLN/h (pole oferty lub "
            "stawka w Profilu Championa)."
        )
    if policy is None:
        blockers.append("Określ tryb pracy: zdalnie, hybrydowo albo stacjonarnie.")
    elif policy in ("onsite", "hybrid"):
        if inputs.onsite_days_per_week is None:
            blockers.append(
                "Podaj liczbę dni w biurze w tygodniu (tryb hybrydowy/stacjonarny)."
            )
        if not inputs.office_tokens:
            blockers.append(
                "Podaj miasto biura w lokalizacji oferty (tryb hybrydowy/stacjonarny)."
            )

    return blockers


def job_handoff_blockers(job: Job) -> list[str]:
    """Pełna bramka „Przekaż do searchu": brief + trzy rubryki, w tej kolejności.

    Kolejność jest częścią kontraktu — ``JobHandoffButton`` renderuje listę
    dosłownie, a braki briefu są bardziej podstawowe niż braki rubryk.
    """
    return job_readiness_blockers(job) + job_rubric_blockers(job)
