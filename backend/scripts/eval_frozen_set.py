"""Zamrożony zbiór ewaluacyjny — 50 ofert z Championami (08.2026).

Proweniencja: selekcja z 17.08.2026 — oferty z champion_profile i >=3
kandydatami ground-truth w historii decyzji, pula 1000. Na TYM zbiorze
mierzone były wszystkie flipy programu (sygnały v1, kara seniority,
rozszerzone aliasy, wagi 45/25/10/8/2) — porównywalność między pomiarami
wymaga, żeby lista NIE dryfowała. Zmiana zbioru = nowa era pomiarowa
(nowa stała obok, nie edycja tej).

Konsumenci: cotygodniowy straznik (app/tasks/weekly_eval.py) i reczne biegi
harnessu (frozen_ids_csv() jako wartosc --job-ids).
"""

FROZEN_JOB_IDS_2026_08: tuple[int, ...] = (
    1394,
    1404,
    1412,
    1426,
    4002,
    4008,
    4202,
    4228,
    4235,
    4263,
    4264,
    4312,
    4313,
    4344,
    4348,
    4418,
    4425,
    4469,
    4478,
    4487,
    4522,
    4527,
    4533,
    4537,
    4556,
    4581,
    4594,
    4610,
    4615,
    4628,
    4678,
    4704,
    4792,
    4833,
    4851,
    4852,
    4873,
    4943,
    4945,
    4972,
    4987,
    4989,
    4990,
    5021,
    5031,
    5044,
    5046,
    5075,
    5092,
    5106,
)


def frozen_ids_csv() -> str:
    return ",".join(str(i) for i in FROZEN_JOB_IDS_2026_08)
