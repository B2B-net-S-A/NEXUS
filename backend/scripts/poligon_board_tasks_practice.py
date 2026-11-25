"""„Czeka na Ciebie” na Poligonie (lekcja „Pracuj po kolei”, 25.11.2026).

Lekcja `lekcja-pracuj-po-kolei` (rekruter, TCM, Delivery Lead) każe na pulpicie
otworzyć „Pracuj po kolei” w panelu „Czeka na Ciebie”. Przycisk stoi tylko
wtedy, gdy kolejka ma osoby (`BoardTasksPanel.tsx`, `buildPersonQueue`), a na
Poligonie `GET /api/board-tasks` szedł do prawdziwego API — z kolejką osoby,
która ćwiczy. Kto nie miał swoich kart (Delivery Lead, TCM), nie widział
przycisku ani w pokazie, ani w zadaniu, i kończył furtką po 45 s; 24.11.2026
jedna osoba oblała tę lekcję 7 razy.

Odpowiedź jest wymyślona: osoby ćwiczebne z „Screeningu” (bez arkusza)
i „Zweryfikowanego” (bez stawki) rekrutacji ćwiczebnej. Reszta sekcji jest
pusta, bo na Poligonie nie ma czego z nich ćwiczyć. Front bierze ją z zestawu
(`OWNED_PATHS` w `frontend/src/lib/poligon/store.ts`).
"""

from __future__ import annotations

POLIGON_JOB = 990001
JOB_TITLE = "Senior Project Manager (bankowość)"
CLIENT_NAME = "Bank Północny"

KEY = "GET /api/board-tasks"
KANBAN_KEY = f"GET /api/pipeline/kanban/{POLIGON_JOB}"

#: Etap na Tablicy → lista „Czeka na Ciebie” i czego brakuje osobie.
FLOW_LISTS = {"screening": ("screening", ["sheet"]), "verified": ("verified", ["rate"])}


def _row(item: dict, index: int, missing: list[str]) -> dict:
    """Wiersz w kształcie `FlowPairRow` (`frontend/src/lib/api/boardTasks.ts`)."""
    return {
        "candidate_id": item["candidate_id"],
        "candidate_name": f"{item['name']} {item['lastname']}",
        "job_id": POLIGON_JOB,
        "job_title": JOB_TITLE,
        "job_working_title": None,
        "client_name": CLIENT_NAME,
        # Najdłużej czekający pierwsi: kolejne osoby o pół dnia młodsze.
        "since": f"@rel:-{3 - index * 0.5:.1f}",
        "claimed_until": None,
        "missing": missing,
        "call_at": None,
        "qc_status": None,
    }


def board_tasks(kanban: dict) -> dict:
    """`BoardTasksResponse` z osobami ćwiczebnymi w „Screeningu” i „Zweryfikowanym”."""
    flow: dict[str, list[dict]] = {"screening": [], "verified": []}
    for column in kanban["columns"]:
        target = FLOW_LISTS.get(column.get("stage"))
        if target is None:
            continue
        name, missing = target
        flow[name] = [_row(item, i, missing) for i, item in enumerate(column.get("items", []))]
    if not flow["screening"]:
        raise SystemExit(f"{KANBAN_KEY}: brak osób w „Screeningu” do „Czeka na Ciebie”")
    return {
        "cpro_to_send": [],
        "cpro_sent": [],
        "dl_review": [],
        "window_days": 30,
        "dl_review_window_days": 30,
        "can_send_to_client": False,
        "prep_attention": [],
        "booked_calls": [],
        "followups": [],
        "followups_by_others": [],
        "can_set_cpro_sender": False,
        "allocation_proposals": [],
        "can_decide_proposals": False,
        "allocation_leave_known": False,
        "new_job_leads": [],
        "new_people": [],
        "cv_in_transit": None,
        "pending_jobs": None,
        "unfinished_forms": [],
        "requirement_fixes": [],
        "agreements": {"to_confirm": [], "to_close": [], "waiting_on_others": []},
        "flow": {
            "applies": True,
            "new_requests": [],
            "new_request_days": 3,
            "postings": [],
            "postings_total": 0,
            "claimed": [],
            "screening": flow["screening"],
            "verified": flow["verified"],
            "waiting_client": [],
            "waiting_client_days": 7,
            "unsigned_contracts": [],
            "order_mail_review": 0,
            "top_proposals": [],
            "top_proposals_per_job": 3,
            "autofill_decisions": [],
            "autofill_decisions_total": 0,
        },
        "finance": None,
        "rate_changes": [],
        "rate_changes_by_others": [],
    }


def board_tasks_practice(dataset: dict) -> tuple[dict, list[str]]:
    """Odczyt do nałożenia na zestaw i klucze w całości wymyślone."""
    return {KEY: board_tasks(dataset[KANBAN_KEY])}, [KEY]
