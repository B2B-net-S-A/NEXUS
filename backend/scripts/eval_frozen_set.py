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


# Holdout B (runda 2, 18.08.2026) — drugi zamrożony zbiór do POTWIERDZANIA
# flipów. Po kilkunastu eksperymentach na zbiorze A rośnie ryzyko cichego
# dopasowania decyzji do jego szumu; werdykt GO przyszłego flipu powinien
# odtwarzać się na B, którego żaden dotychczasowy strojony wybór nie widział.
# Proweniencja: prod 18.08 — oferty z champion_profile, >=3 kandydatami GT
# (etapy pozytywne jak w harnessie), bez seedów (external_source='manual'),
# z WYKLUCZENIEM zbioru A ORAZ 50 ofert treningowych LTR (na nich strojono
# wagi 60/10/15/5/0, więc pomiar na nich nie jest out-of-sample).
FROZEN_JOB_IDS_2026_08_B: tuple[int, ...] = (
    3242,
    3253,
    3631,
    3834,
    3843,
    3921,
    3937,
    3938,
    3939,
    3956,
    3987,
    3991,
    3992,
    3993,
    3994,
    4026,
    4033,
    4034,
    4038,
    4084,
    4086,
    4099,
    4101,
    4136,
    4139,
    4143,
    4144,
    4148,
    4149,
    4156,
    4161,
    4162,
    4164,
    4167,
    4168,
    4170,
    4172,
    4182,
    4190,
    4191,
    4193,
    4197,
    4198,
    4204,
    4205,
    4209,
    4210,
    4212,
    4215,
    4218,
)


def frozen_ids_csv_b() -> str:
    return ",".join(str(i) for i in FROZEN_JOB_IDS_2026_08_B)
