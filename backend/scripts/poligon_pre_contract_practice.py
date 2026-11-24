"""Stop do podpisu przedwstępnej na Poligonie (lekcje Nowości, 23.11.2026).

Funkcja z PR-a #3796 (`docs/claude/rekrutacja-tablica/stop-do-podpisu-przedwstepnej.md`)
ma dwie lekcje: Delivery Lead i Head of Recruitment ustawiają przedwstępną
dla rekrutacji i robią wyjątek dla osoby, a rekruter rozpoznaje kartę, która
stoi do podpisu. Nagranie Poligonu jest sprzed funkcji, więc stan jest
wymyślony tutaj:

- rekrutacja ćwiczebna: „każda osoba podpisuje przed wysłaniem CV”, karta
  stoi do podpisu (ustawiła Anna Poligonowa, DL poligonu);
- Szymon Grabowiec w „QC CV”: prośba wysłana, czeka na podpis — strzałka
  z kłódką i plakietka „Stop ·” (ustawienie rekrutacji);
- Weronika Cisowska w „QC CV”: przedwstępna podpisana, więc przegląd DL-a
  i wysyłka do klienta (ćwiczenie `dl-wysylka`) idą jak dotąd;
- reszta osób (szablon panelu) widzi tylko ustawienie rekrutacji.

`can_set_stop` w odpowiedziach pary zależy od roli oglądającego — ustawia go
`store.ts` (`forViewer`), tak jak serwer (`pre_contract_stop.can_set_stop`).
Odpowiedzi pary Szymona i Weroniki są w całości wymyślone
(`meta.fiction_responses`); kanban, rekrutacja i para osoby-szablonu to
nagrane odczyty z dopisanymi polami.
"""

from __future__ import annotations

import copy

POLIGON_JOB = 990001
TEMPLATE_CANDIDATE = 990105
TRAINER_DL = (990901, "Anna Poligonowa")
TRAINER_REC = (990902, "Jakub Szkoleniowy")

# Osoby z „QC CV” nagranej rekrutacji (indeksy 8 i 9 z `PEOPLE`).
STOPPED = {"candidate_id": 990110, "entry_id": 990310, "name": "Szymon Grabowiec"}
SIGNED = {"candidate_id": 990109, "entry_id": 990309, "name": "Weronika Cisowska"}

JOB_TITLE = "Senior Project Manager (bankowość)"
CLIENT_ID = 990501
CLIENT_NAME = "Bank Północny"

JOB_KEY = f"GET /api/jobs/{POLIGON_JOB}"
KANBAN_KEY = f"GET /api/pipeline/kanban/{POLIGON_JOB}"


def pair_key(candidate_id: int) -> str:
    return (
        f"GET /api/pre-contracts/pair?candidate_id={candidate_id}&job_id={POLIGON_JOB}"
    )


RULE_SET_AT = "@rel:-3.2"

#: `jobs.pre_contract_rule` (`pre_contract_stop.rule_record`).
JOB_RULE_RECORD = {
    "needed_before": "cv_sent",
    "stop": True,
    "set_by": TRAINER_DL[0],
    "set_by_name": TRAINER_DL[1],
    "set_at": RULE_SET_AT,
}

#: `job_rule` w odpowiedzi pary (`pre_contract_stop.rule_payload`).
JOB_RULE = {
    "needed_before": "cv_sent",
    "needed_before_label": "przed wysłaniem CV",
    "stop": True,
    "set_by_name": TRAINER_DL[1],
    "set_at": RULE_SET_AT,
}

#: Blokada Szymona (`pre_contract_stop.stop_payload`).
STOP = {
    "column": "cv_sent",
    "needed_before": "cv_sent",
    "origin": "job",
    "set_by_name": TRAINER_DL[1],
    "set_at": RULE_SET_AT,
}

STOPPED_BADGE = {
    "state": "sent",
    "label": "Przedwstępna wysłana · czeka 2 dni",
    "tone": "wait",
    "detail": "Wysłana kandydatowi",
}
SIGNED_BADGE = {
    "state": "signed",
    "label": "Przedwstępna podpisana",
    "tone": "ok",
    "detail": "Podpisana obustronnie.",
}

STOPPED_REQUEST_ID = 990811
SIGNED_REQUEST_ID = 990812


def _person(user: tuple[int, str]) -> dict:
    return {"id": user[0], "name": user[1]}


def _request(person: dict, request_id: int, badge: dict, **fields) -> dict:
    """Prośba w kształcie `PreContractRequestOut`."""
    return {
        "id": request_id,
        "candidate_id": person["candidate_id"],
        "candidate_name": person["name"],
        "job_id": POLIGON_JOB,
        "job_title": JOB_TITLE,
        "client_id": CLIENT_ID,
        "client_name": CLIENT_NAME,
        "state": badge["state"],
        "state_label": badge["detail"] if badge["state"] != "signed" else "Podpisana",
        "badge": badge,
        "is_open": True,
        "needed_before": "cv_sent",
        "needed_before_label": "przed wysłaniem CV",
        "needed_by": None,
        "reason": None,
        # Prośba z ustawienia rekrutacji: proszący = ustawiający, wystawia
        # rekruter prowadzący (`ensure_rule_request`).
        "requested_by": _person(TRAINER_DL),
        "requested_at": "@rel:-3.1",
        "assignee": _person(TRAINER_REC),
        "watchers": [],
        "watching": False,
        "document_id": None,
        "document_type": None,
        "sent_at": None,
        "candidate_signed_at": None,
        "candidate_signature_form": None,
        "candidate_signature_form_label": None,
        "candidate_file_name": None,
        "company_signed_at": None,
        "company_file_name": None,
        "valid_until": None,
        "b2b_deadline": None,
        "closed_at": None,
        "close_reason": None,
        "withdrawal": None,
        "column": "cv_qc",
        "stage_name": "QC CV",
        "can_withdraw": False,
        "can_decide_penalty": False,
        "events": [],
        "blocks_move": None,
        "blocks_set_by": None,
        "blocks_set_at": None,
        **fields,
    }


def stopped_pair() -> dict:
    return {
        "current": _request(
            STOPPED, STOPPED_REQUEST_ID, STOPPED_BADGE, sent_at="@rel:-2.1"
        ),
        "history": [],
        "documents": [],
        "job_rule": JOB_RULE,
        "stop": STOP,
        "can_set_stop": False,
    }


def signed_pair() -> dict:
    return {
        "current": _request(
            SIGNED,
            SIGNED_REQUEST_ID,
            SIGNED_BADGE,
            sent_at="@rel:-3.0",
            candidate_signed_at="@rel:-2.2",
            company_signed_at="@rel:-1.9",
        ),
        "history": [],
        "documents": [],
        "job_rule": JOB_RULE,
        "stop": None,
        "can_set_stop": False,
    }


def _card_meta(request_id: int, badge: dict, stop_column: str | None) -> dict:
    """`KanbanItem.pre_contract` (plakietka karty z kolumną blokady)."""
    return {
        "id": request_id,
        **badge,
        "stop_column": stop_column,
        "stop_origin": "job" if stop_column else None,
    }


def with_card_meta(kanban: dict) -> dict:
    out = copy.deepcopy(kanban)
    metas = {
        STOPPED["candidate_id"]: _card_meta(
            STOPPED_REQUEST_ID, STOPPED_BADGE, "cv_sent"
        ),
        SIGNED["candidate_id"]: _card_meta(SIGNED_REQUEST_ID, SIGNED_BADGE, None),
    }
    found = set()
    for column in out["columns"]:
        for item in column["items"]:
            if item["candidate_id"] in metas:
                item["pre_contract"] = metas[item["candidate_id"]]
                found.add(item["candidate_id"])
    missing = set(metas) - found
    if missing:
        raise SystemExit(f"{KANBAN_KEY}: brak osób {sorted(missing)} na Tablicy")
    return out


def pre_contract_practice(dataset: dict) -> tuple[dict, list[str]]:
    """Odczyty do nałożenia na zestaw i klucze, które są w całości wymyślone."""
    template_pair = {
        **dataset[pair_key(TEMPLATE_CANDIDATE)],
        "job_rule": JOB_RULE,
        "stop": None,
        "can_set_stop": False,
    }
    fiction = {
        pair_key(STOPPED["candidate_id"]): stopped_pair(),
        pair_key(SIGNED["candidate_id"]): signed_pair(),
    }
    out = {
        JOB_KEY: {**dataset[JOB_KEY], "pre_contract_rule": JOB_RULE_RECORD},
        KANBAN_KEY: with_card_meta(dataset[KANBAN_KEY]),
        pair_key(TEMPLATE_CANDIDATE): template_pair,
        **fiction,
    }
    return out, sorted(fiction)
