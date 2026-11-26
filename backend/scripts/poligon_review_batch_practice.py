"""Porcja dnia na Poligonie (lekcje „Porcja…”, 26.11.2026).

Pięć lekcji porannej porcji ma zadanie na `/porcja`: profil „Kogo szukamy”
nad kartą (`review-batch.role-profile`), „Wybierz rekrutację na dziś”
(`review-batch.focus`), „Nie pasuje…” (`review-batch.reject`), wymagania
„Musi mieć” (`review-batch.requirements`) i „Oddaj … do Nowych” przy
rekrutacji spoza P0 (`review-batch.return-group`). Na Poligonie
`/api/review-batch/*` szło do prawdziwego API — z porcją osoby, która ćwiczy.
Pusta porcja, karta bez profilu albo brak rekrutacji niżej niż P0 = brak
elementu z zadania. 26.11.2026 do 10:00 „Oddaj do Nowych” zaliczyły trzy
osoby, wszystkie furtką „Coś nie działa”, a „Porcja: karta” od 23.11.2026
miała 22 powroty do pokazu u 13 osób.

Odpowiedzi są wymyślone: karty to osoby z „Nowych” rekrutacji ćwiczebnej
(P1), „Do domknięcia” to osoby ze „Screeningu” tej samej rekrutacji, a P0
osoby, która ćwiczy, to druga rekrutacja ćwiczebna bez nowych osób. Dzięki
temu rekrutacja ćwiczebna „nie jest teraz Twoim P0” i stoi przy niej
„Oddaj … do Nowych”. Front bierze odczyty z zestawu (`OWNED_PATHS`
w `frontend/src/lib/poligon/store.ts`); zapisy (wybór rekrutacji, profil,
„Dodaj kolejnych”) Poligon blokuje jak każdy inny.
"""

from __future__ import annotations

POLIGON_JOB = 990001
JOB_TITLE = "Senior Project Manager (bankowość)"
#: Druga rekrutacja ćwiczebna: P0 osoby, która ćwiczy, bez nowych osób.
P0_JOB = 990002
P0_TITLE = "Analityk ryzyka kredytowego (bankowość)"
BUDGET_HOURLY = 105

KANBAN_KEY = f"GET /api/pipeline/kanban/{POLIGON_JOB}"
STATUS_KEY = "GET /api/review-batch/me"
QUEUE_KEY = "GET /api/review-batch/me/queue?limit=20"
FOCUS_KEY = "GET /api/review-batch/me/focus"

#: Karta po karcie: stanowisko, miasto, lata, stawka i dowód wymagań z CV.
#: Stany to „experience” (✓), „mention” (~) i „none” (✗), jak w porcji.
CARDS = (
    {
        "position": "Project Manager",
        "city": "Gdańsk",
        "years": 9,
        "rate": 110,
        "score": 82,
        "states": (
            "experience",
            "experience",
            "mention",
            "experience",
            "experience",
            "mention",
            "none",
            "experience",
        ),
        # „Wysłany wczoraj do tego klienta” (porcja-wyslany-do-tego-klienta).
        "client_recent": {"days": 1, "job_id": P0_JOB, "job_title": P0_TITLE},
    },
    {
        "position": "Delivery Manager",
        "city": "Warszawa",
        "years": 12,
        "rate": 120,
        "score": 76,
        "states": (
            "experience",
            "mention",
            "experience",
            "experience",
            "none",
            "experience",
            "experience",
            "none",
        ),
        "client_recent": None,
    },
    {
        "position": "IT Project Manager",
        "city": "Poznań",
        "years": 6,
        "rate": 95,
        "score": 71,
        "states": (
            "experience",
            "experience",
            "none",
            "mention",
            "experience",
            "none",
            "mention",
            "none",
        ),
        "client_recent": None,
    },
    {
        "position": "Scrum Master",
        "city": "Wrocław",
        "years": 5,
        "rate": 90,
        "score": 64,
        "states": (
            "mention",
            "experience",
            "none",
            "experience",
            "none",
            "none",
            "mention",
            "none",
        ),
        "client_recent": None,
    },
)

#: Ile pierwszych „Musi mieć” Championa idzie do „Kluczowe w tej rekrutacji”.
CRITICAL_COUNT = 3


def _must_labels(dataset: dict) -> list[str]:
    stack = dataset[f"GET /api/jobs/{POLIGON_JOB}"]["champion_profile"]["stack"]
    labels = [row["name"] for row in stack["must"]]
    if len(labels) < CRITICAL_COUNT + 2:
        raise SystemExit(
            f"GET /api/jobs/{POLIGON_JOB}: za mało „Musi mieć” do kart porcji"
        )
    return labels


def _column(kanban: dict, stage: str) -> list[dict]:
    for column in kanban["columns"]:
        if column.get("stage") == stage and column.get("items"):
            return column["items"]
    raise SystemExit(f"{KANBAN_KEY}: brak osób w etapie „{stage}” do porcji")


def _item(entry: dict, card: dict, labels: list[str]) -> dict:
    """Karta w kształcie `ReviewBatchItem` (`frontend/src/lib/api/reviewBatch.ts`)."""
    states = dict(zip(labels, card["states"]))
    critical = labels[:CRITICAL_COUNT]
    must = labels[CRITICAL_COUNT:]
    return {
        "process_id": entry["id"],
        "stage_id": entry.get("stage_def_id"),
        "job_id": POLIGON_JOB,
        "job_title": JOB_TITLE,
        "candidate_id": entry["candidate_id"],
        "name": f"{entry['name']} {entry['lastname']}",
        "city": card["city"],
        "years": card["years"],
        "position": card["position"],
        "score": card["score"],
        "matched_must": [label for label in labels if states[label] == "experience"],
        "missing_must": [label for label in labels if states[label] == "none"],
        "rate_from_hourly": card["rate"],
        "rate_currency": "PLN",
        "availability_status": entry.get("availability_status") or "actively_looking",
        "cautions": [],
        "budget_hourly": BUDGET_HOURLY,
        "known": None,
        "order_active": False,
        "order_in_budget": card["rate"] <= BUDGET_HOURLY,
        "sent_before": None,
        "why": {"source": "p1", "via": "owner", "p0_until": None, "chosen": False},
        "client_recent": card["client_recent"],
        "stale": False,
        "opened_on": "@reld:0",
        "key_facts": {
            "critical": [
                {
                    "label": label,
                    "state": states[label],
                    "detail": {
                        "experience": "W stanowiskach z CV",
                        "mention": "Tylko wzmianka w CV",
                        "none": "Brak w CV",
                    }[states[label]],
                }
                for label in critical
            ],
            "polish": {"state": "native", "detail": "Polski ojczysty"},
        },
        "requirements": {
            "critical_missing": sum(states[label] == "none" for label in critical),
            "must_met": sum(states[label] == "experience" for label in must),
            "must_total": len(must),
            "nice_met": 0,
            "nice_total": 0,
            "must": [{"label": label, "state": states[label]} for label in must],
            "nice": [],
        },
    }


def _open_screening(entry: dict) -> dict:
    """„Do domknięcia”: osoba w „Screeningu” bez wyniku (`ReviewBatchOpenScreening`)."""
    return {
        "job_id": POLIGON_JOB,
        "job_title": JOB_TITLE,
        "candidate_id": entry["candidate_id"],
        "name": f"{entry['name']} {entry['lastname']}",
        "overdue": False,
        "parked": False,
        "attempts": 0,
        "last_attempt_at": None,
    }


def review_batch(dataset: dict) -> dict:
    """Odczyty porcji dla `/porcja` na Poligonie."""
    kanban = dataset[KANBAN_KEY]
    labels = _must_labels(dataset)
    new_people = _column(kanban, "new")
    if len(new_people) < 2:
        raise SystemExit(
            f"{KANBAN_KEY}: porcja potrzebuje co najmniej dwóch osób w „Nowych”"
        )
    items = [_item(entry, card, labels) for entry, card in zip(new_people, CARDS)]
    open_today = [_open_screening(entry) for entry in _column(kanban, "screening")]

    p0_job = {
        "job_id": P0_JOB,
        "title": P0_TITLE,
        "pending": 0,
        "p0": True,
        "group": "p0",
        "via": "owner",
        "p0_until": "@reld:5",
    }
    practice_job = {
        "job_id": POLIGON_JOB,
        "title": JOB_TITLE,
        "pending": len(items),
        "p0": False,
        "group": "p1",
        "via": "owner",
        "p0_until": None,
    }
    status = {
        "enabled": True,
        "applies": True,
        "minimum": 10,
        "done_today": 0,
        "pending": len(items),
        "required": len(items),
        "remaining": len(items),
        "met": False,
        "blocks": False,
        "open_screenings": len(open_today),
        "open_today_screenings": open_today,
        "overdue_screenings": 0,
        "jobs": [practice_job],
        "team_jobs": [p0_job, practice_job],
        "more_cards": 20,
        "sources": {
            "p0": 0,
            "rest": len(items),
            "level_next": 20,
            "level_cap": 50,
            "urgent": len(items),
            "other": 0,
            "other_seats": 8,
            "stale": 0,
        },
        "focus": None,
    }
    profile = {
        "job_id": POLIGON_JOB,
        "role": "Project Manager",
        "specialty": "bankowość",
        "technology": None,
        "level": "lider",
        "saved": True,
        "excluded": [{"label": "Business Analyst", "count": 3, "source": "rejections"}],
        "learning": [{"label": "Product Owner", "count": 1, "dismissed": False}],
        "exclude_min": 3,
        "can_edit": True,
    }
    queue = {
        "items": items,
        "job_rules": {},
        "job_profiles": {str(POLIGON_JOB): profile},
        "runs": [{"job_id": POLIGON_JOB, "count": len(items)}],
        "stale": None,
    }

    def option(job: dict, team_size: int) -> dict:
        return {**job, "team_size": team_size, "picked_by": []}

    focus = {
        "items": [option(practice_job, 3), option(p0_job, 2)],
        "focus": None,
        "seats": 10,
    }
    return {
        STATUS_KEY: status,
        QUEUE_KEY: queue,
        FOCUS_KEY: focus,
        f"GET /api/review-batch/me/focus/{POLIGON_JOB}": {
            "job_id": POLIGON_JOB,
            "available": len(items),
            "take": len(items),
            "release": 0,
        },
        f"GET /api/review-batch/me/focus/{P0_JOB}": {
            "job_id": P0_JOB,
            "available": 0,
            "take": 0,
            "release": 0,
        },
    }


def review_batch_practice(dataset: dict) -> tuple[dict, list[str]]:
    """Odczyt do nałożenia na zestaw i klucze w całości wymyślone."""
    responses = review_batch(dataset)
    return responses, sorted(responses)
