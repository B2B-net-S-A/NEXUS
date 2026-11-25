"""Osoba w „CV wysłane” na Poligonie (lekcja „Terminy przy ruchu”, 25.11.2026).

Lekcja `lekcja-terminy-przy-ruchu` (PR #3786) każe Delivery Leadowi przesunąć
kandydata z „CV wysłane” na „Rozmowa u klienta” i w oknie ruchu wysłać
rekruterowi terminy od klienta. Kolumna „CV wysłane” rekrutacji ćwiczebnej była
pusta od nagrania Poligonu (Kamil Dębowski stoi już na „Rozmowie u klienta”,
bo ćwiczy wybór terminu), więc zadania nie dało się zrobić tak, jak je opisano:
ruch z „QC CV” prosto na „Rozmowę u klienta” zaliczał lekcję, ale okno nie
miało części „Klient podał terminy” (test na stagingu 25.11.2026).

Tu dokładamy jedną osobę do „CV wysłane”: kopię karty Weroniki Cisowskiej
z „QC CV” (CV po przeglądzie, ze stawką do klienta) bez plakietki
przedwstępnej. Panel osoby bierze treść z osoby-szablonu (`store.ts`,
`toTemplate`), więc wystarczy karta i wpis w `meta.people`.
"""

from __future__ import annotations

import copy

POLIGON_JOB = 990001
KANBAN_KEY = f"GET /api/pipeline/kanban/{POLIGON_JOB}"

SOURCE_STAGE = "interview"  # „QC CV”
TARGET_STAGE = "cv_sent"

#: Weronika Cisowska (`PEOPLE[8]`): karta z „QC CV”, przedwstępna podpisana.
SOURCE_CANDIDATE = 990109

#: Osoba spoza nagrania, za Ewą Jesionowską (990116) w `EXTRA_PEOPLE`.
PERSON = {
    "candidate_id": 990117,
    "entry_id": 990317,
    "name": "Marta",
    "lastname": "Jarzębska",
}


def with_terms_card(kanban: dict) -> dict:
    """Tablica z osobą w „CV wysłane”; drugie wywołanie niczego nie dokłada."""
    out = copy.deepcopy(kanban)
    columns = out["columns"]
    target = next((c for c in columns if c.get("stage") == TARGET_STAGE), None)
    source = next(
        (
            item
            for c in columns
            if c.get("stage") == SOURCE_STAGE
            for item in c.get("items", [])
            if item.get("candidate_id") == SOURCE_CANDIDATE
        ),
        None,
    )
    if target is None or source is None:
        raise SystemExit(f"{KANBAN_KEY}: brak kolumny „CV wysłane” albo karty 990109")
    items = [
        i
        for i in target.get("items", [])
        if i.get("candidate_id") != PERSON["candidate_id"]
    ]
    card = {
        **copy.deepcopy(source),
        "id": PERSON["entry_id"],
        "candidate_id": PERSON["candidate_id"],
        "name": PERSON["name"],
        "lastname": PERSON["lastname"],
        "stage": TARGET_STAGE,
        "stage_def_id": target["stage_def_id"],
        "pre_contract": None,
        "interview_badge": None,
        "followup": None,
    }
    target["items"] = [*items, card]
    target["count"] = len(target["items"])
    return out


def terms_practice(dataset: dict, people: list[dict]) -> tuple[dict, list[dict]]:
    """Odczyty do nałożenia na zestaw i lista osób z dopisaną osobą w „CV wysłane”."""
    others = [p for p in people if p["candidate_id"] != PERSON["candidate_id"]]
    return {KANBAN_KEY: with_terms_card(dataset[KANBAN_KEY])}, [*others, dict(PERSON)]
