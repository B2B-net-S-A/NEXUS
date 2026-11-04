"""„Tyle mogę zrobić za Ciebie” — pusty panel Jarvisa (27.10.2026).

Ludzie nie wiedzieli, że Jarvis przygotuje notatkę, ruch na tablicy albo
debrief, i pisali „siema” albo pytali o przepis. Lista mówi to w ich
słowach i powstaje z TYCH SAMYCH narzędzi, które ta rola dostaje do modelu
(``tools_for_user``) — Finanse widzą co innego niż rekruter. Pozycja trafia
na listę, gdy rola ma którekolwiek z jej narzędzi.
"""

from __future__ import annotations

from typing import Collection

# (opis dla człowieka, narzędzia — wystarczy jedno)
READ: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Twoje zadania na dziś", ("my_board_tasks", "my_interview_cycle")),
    ("kandydaci i ich historia", ("get_candidate",)),
    ("szukanie w bazie kandydatów", ("search_candidates", "talent_radar_search")),
    ("tablice rekrutacji", ("get_job_board",)),
    ("dopasowanie osoby do rekrutacji", ("explain_match",)),
    ("„Moi ludzie” do przepięcia", ("my_people_for_job", "my_people")),
    ("klienci, kontrakty i zamówienia", ("get_client_profile", "list_contracts")),
    ("zapisy w umowach ramowych", ("search_framework_contracts",)),
    ("liczby: placementy, CV, kontrakty", ("evaluate_metric",)),
    ("urlopy i sprzęt", ("my_leave_balance", "my_equipment")),
)
WRITE: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("notatka", ("create_note",)),
    ("dodanie do rekrutacji", ("add_candidates_to_job",)),
    ("przesunięcie na tablicy", ("move_candidate_stage",)),
    ("debrief po rozmowie", ("save_interview_debrief",)),
    ("spotkanie w kalendarzu", ("create_calendar_event",)),
    ("werdykt klienta", ("record_hm_feedback",)),
)
# Operacje, których Jarvis nie wykonuje nigdy (``link``) — stałe dla każdej roli.
NEVER: tuple[str, ...] = (
    "wysyłka maila",
    "CV i umowa B2B",
    "zmiana stawki",
    "usuwanie",
)


def capabilities_for(tool_names: Collection[str]) -> dict[str, list[str]]:
    names = frozenset(tool_names)

    def pick(rows: tuple[tuple[str, tuple[str, ...]], ...]) -> list[str]:
        return [label for label, tools in rows if names.intersection(tools)]

    return {"read": pick(READ), "write": pick(WRITE), "never": list(NEVER)}
