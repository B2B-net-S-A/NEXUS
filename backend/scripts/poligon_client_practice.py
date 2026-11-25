"""Klient ćwiczebny Poligonu: karta klienta, kontrakty, zamówienia i Finanse.

Decyzja Artura z 22.11.2026 („klient ćwiczebny”): wpisy Nowości z ekranów
klienta, kontraktów i Finansów nie miały na Poligonie drogi do elementu, bo
zestaw obejmował tylko rekrutację 990001. Ten moduł dokłada do zestawu
(`frontend/src/lib/poligon/dataset.json`) odczyty wokół klienta „Bank Północny”:

- lista klientów i karta klienta (Przegląd z „Wymaga uwagi”, rozliczenie
  poprzedniego miesiąca krokami, Konsultanci);
- dwa kontrakty B2B: trwający (linia zamówienia MD, stawka z aneksu do
  wprowadzenia, zamówienie kończy się za 40 dni) i zakończony, po którym klient
  zamówił jeszcze okres („Zamówione po końcu”);
- opieka, start, dokumenty i aneksy trwającego kontraktu;
- kolejka „Zamówienia z maila” z jednym wpisem do sprawdzenia;
- Finanse: rozjazd stawki i zamówienie do korekty po zmianie stawki Partnera.

Nic tu nie pochodzi z nagrania: wszystkie teksty, osoby, numery i kwoty są
wymyślone (repo jest publiczne). Kwoty stoją w odpowiedziach w całości, a tryb
Poligonu zdejmuje je osobie bez „Stawki i kwoty: podgląd” tak jak serwer
(`lib/poligon/amounts.ts`). Klucze odpowiedzi trafiają do
`meta.fiction_responses`, więc strażnik zestawu sprawdza je jak tekst
wymyślony, nie jak nagranie.
"""

from __future__ import annotations

from urllib.parse import urlencode

POLIGON_JOB = 990001
POLIGON_CLIENT = 990501
CLIENT_NAME = "Bank Północny"
CLIENT_LEGAL_NAME = "Bank Północny S.A. (firma ćwiczebna)"
JOB_TITLE = "Senior Project Manager (bankowość)"
DL = (990901, "Anna Poligonowa")
REC = (990902, "Jakub Szkoleniowy")

# Konsultanci u klienta: osoby ćwiczebne z „Moich ludzi” (indeksy 11 i 12 z
# `PEOPLE` w `build_poligon_dataset.py`, identyfikatory 990112 i 990113).
ACTIVE = {"candidate_id": 990112, "name": "Filip Bukowiec", "contract_id": 990521}
ENDED = {"candidate_id": 990113, "name": "Maja Wierzbicka", "contract_id": 990522}
# Osoba po stronie klienta (nie kandydat) — dopisana do `meta.client_people`.
CLIENT_CONTACT = (990531, "Ewelina Klonowska", "Kierowniczka programu płatności")
CLIENT_PEOPLE = [CLIENT_CONTACT[1]]

ORDER_ACTIVE = 990541
ORDER_AFTER_END = 990542
ORDER_ENDED = 990543  # zamówienie Mai zakończone razem z umową
ORDER_MAIL_DOC = 990561
FRAMEWORK_ID = 990571
INVOICE_ID = 990551
DOCUMENT_ID = 990595
ANNEX_DOCUMENT_ID = 990596
AMENDMENT_ID = 990598
RATE_READ_ID = 990599
CARE_PLAN_ID = 990581
CARE_CASE_ID = 990585

ORDER_NUMBER = "ĆW/ZAM/2026/07"
ORDER_AFTER_END_NUMBER = "ĆW/ZAM/2026/11"
CONTRACT_NUMBER = "ĆW-B2B-0521"

# Kwoty ćwiczebne (zł/h, miesiąc = 168 h). Zgodne z rekrutacją ćwiczebną:
# kandydat 105 zł/h, do klienta 122 zł/h. Aneks 1 (w mocy od 60 dni) podniósł
# stawkę Partnera ze 100 do 105 zł/h, a aneks 2 z dokumentu podnosi ją do
# 110 zł/h za 9 dni — tej zmiany nie ma jeszcze w harmonogramie.
HOURS = 168
RATE_CANDIDATE = 105.0
RATE_CLIENT = 122.0
RATE_FROM_ANNEX = 110.0
RATE_BEFORE_ANNEX = 100.0  # stawka Partnera przed aneksem 1; tak zostało w zamówieniu
MD_RATE_CLIENT = 976.0  # 122 zł/h × 8 h
MD_BUDGET = 120  # MD w linii zamówienia


def _money(v: float) -> str:
    return f"{v:.2f}"


def _monthly(v: float) -> float:
    return round(v * HOURS, 2)


def contracts_key(params: list[tuple[str, str]]) -> str:
    """Klucz zestawu dla `/api/contracts` tak, jak liczy go `store.ts`."""
    return "GET /api/contracts?" + urlencode(sorted(params))


# --- kontrakty --------------------------------------------------------------


def _contract_base(person: dict, status: str) -> dict:
    return {
        "id": person["contract_id"],
        "missing_fields": [],
        "draft_order_id": None,
        "candidate_id": person["candidate_id"],
        "client_id": POLIGON_CLIENT,
        "job_id": POLIGON_JOB,
        "contract_type": "b2b",
        "status": status,
        "documents": [],
        "candidate_name": person["name"],
        "client_name": CLIENT_NAME,
        "job_title": JOB_TITLE,
        "rate_candidate": RATE_CANDIDATE,
        "rate_client": RATE_CLIENT,
        "framework_rate": None,
        "target_rate_min": None,
        "target_rate_max": None,
        "currency": "PLN",
        "rate_client_currency": "PLN",
        "rate_candidate_currency": "PLN",
        "rate_unit": "hourly",
        "billing_hours_per_month": HOURS,
        "margin": round(RATE_CLIENT - RATE_CANDIDATE, 2),
        "candidate_rate_schedule": [],
        "client_rate_schedule": [],
        "framework_rate_schedule": [],
        "client_pm_name": None,
        "client_pm_email": None,
        "client_pm_contact_id": CLIENT_CONTACT[0],
        "client_pm_contact_name": CLIENT_CONTACT[1],
        "client_pm_contact_position": CLIENT_CONTACT[2],
        "line_manager": None,
        "work_mode": "hybrid",
        "office_location": None,
        "team_name": None,
        "project_name": "Program płatności (ćwiczenie)",
        "handover_notes": None,
        "termination_reason": None,
        "termination_lessons": None,
        "terminated_at": None,
        "returned_from_contract_id": None,
        "agreement_termination_mode": None,
        "agreement_termination_party": None,
        "agreement_termination_signed_on": None,
        "agreement_last_day": None,
        "notice_period_months": 1,
        "project_code": None,
        "prolongation_status": "unknown",
        "engagement_model": "time_based",
        "hours_pool_total": None,
        "hours_pool_consumed": 0,
        "order_consumption": None,
        "order_consumption_unit": None,
        "hours_pool_remaining": None,
        "hours_pool_usage_pct": None,
        "draft_template_id": None,
        "draft_updated_at": None,
        "draft_updated_by": None,
        "created_at": "@rel:-200",
        "updated_at": "@rel:-3",
        "group_members": [],
        "rate_document_change": None,
        "order_after_end": None,
    }


def active_contract_row() -> dict:
    """Trwający kontrakt: zamówienie MD kończy się za 40 dni, stawka z aneksu czeka."""
    return {
        **_contract_base(ACTIVE, "active"),
        "start_date": "@reld:-200",
        "end_date": None,
        "client_order_start_date": "@reld:-200",
        "client_order_end_date": "@reld:40",
        "latest_order_end_date": "@reld:40",
        "rate_document_change": {
            "from": "@reld:9",
            "rate": RATE_FROM_ANNEX,
            "kind": "annex",
            "category": "review",
            "count": 1,
        },
    }


def ended_contract_row() -> dict:
    """Zakończony kontrakt, po którym klient zamówił jeszcze okres."""
    return {
        **_contract_base(ENDED, "ended"),
        "start_date": "@reld:-320",
        "end_date": "@reld:-12",
        "client_order_start_date": "@reld:-320",
        "client_order_end_date": "@reld:-12",
        "latest_order_end_date": "@reld:48",
        "terminated_at": "@rel:-12",
        "termination_reason": "project_ended",
        "agreement_termination_mode": "notice",
        "agreement_termination_party": "contractor",
        "agreement_last_day": "@reld:-12",
        "order_after_end": {
            "contract_id": ENDED["contract_id"],
            "order_id": ORDER_AFTER_END,
            "status": "draft",
            "start_date": "@reld:-11",
            "end_date": "@reld:48",
            "count": 1,
        },
    }


def contract_list(items: list[dict], *, page_size: int = 20) -> dict:
    return {
        "items": items,
        "total": len(items),
        "contractors_total": len(items),
        "contracts_total": len(items),
        "future_start_total": 0,
        "page": 1,
        "page_size": page_size,
    }


def contract_detail(row: dict) -> dict:
    monthly_client = _monthly(row["rate_client"])
    monthly_candidate = _monthly(row["rate_candidate"])
    order_after_end = row.get("order_after_end")
    return {
        **{k: v for k, v in row.items() if k != "order_after_end"},
        "candidate_email": None,
        "candidate_phone": None,
        "candidate_email_effective": None,
        "candidate_phone_effective": None,
        "candidate_email_source": None,
        "candidate_phone_source": None,
        "client_pm_contact_hint": None,
        "monthly_rate_candidate": monthly_candidate,
        "monthly_rate_client": monthly_client,
        "monthly_margin": round(monthly_client - monthly_candidate, 2),
        "eur_pln_rate": None,
        "related_contracts": [],
        "can_reverse_termination": row["status"] == "ended",
        "can_return_after_break": False,
        "termination_reversed_at": None,
        "termination_reversed_by_name": None,
        "return_contract_id": None,
        "order_after_end": (
            [
                {
                    "order_id": order_after_end["order_id"],
                    "client_id": POLIGON_CLIENT,
                    "order_group_id": None,
                    "order_number": ORDER_AFTER_END_NUMBER,
                    "status": order_after_end["status"],
                    "start_date": order_after_end["start_date"],
                    "end_date": order_after_end["end_date"],
                    "held_by_termination": False,
                }
            ]
            if order_after_end
            else []
        ),
    }


def contract_activities(contract_id: int) -> list:
    return [
        {
            "id": 990591 + (contract_id - ACTIVE["contract_id"]) * 2,
            "action": "created",
            "details": None,
            "user_id": DL[0],
            "user_name": DL[1],
            "created_at": "@rel:-200",
        }
    ]


def contract_documents(contract_id: int) -> list:
    return [
        {
            "id": DOCUMENT_ID if contract_id == ACTIVE["contract_id"] else 990695,
            "contract_id": contract_id,
            "filename": "umowa-b2b-cwiczebna.pdf",
            "doc_type": "contract",
            "content_type": "application/pdf",
            "size_bytes": 182_000,
            "expiry_date": None,
            "uploaded_by": DL[0],
            "uploaded_by_email": None,
            "created_at": "@rel:-201",
            "source": "upload",
            "sharepoint_item_id": None,
            "sharepoint_push_status": None,
            "sharepoint_push_error": None,
            "folder_id": None,
        },
        {
            "id": ANNEX_DOCUMENT_ID if contract_id == ACTIVE["contract_id"] else 990696,
            "contract_id": contract_id,
            "filename": "aneks-2-zmiana-stawki-cwiczebny.pdf",
            "doc_type": "annex",
            "content_type": "application/pdf",
            "size_bytes": 64_000,
            "expiry_date": None,
            "uploaded_by": DL[0],
            "uploaded_by_email": None,
            "created_at": "@rel:-2",
            "source": "upload",
            "sharepoint_item_id": None,
            "sharepoint_push_status": None,
            "sharepoint_push_error": None,
            "folder_id": None,
        },
    ]


def contract_amendments(person: dict, effective: int) -> list:
    """Aneks 1 (w mocy): stawka Partnera 100 → 105 zł/h. U Filipa aneks 2 z dokumentu czeka (`rate_documents`)."""
    return [
        {
            "id": AMENDMENT_ID if person is ACTIVE else AMENDMENT_ID - 1,
            "contract_id": person["contract_id"],
            "amendment_type": "rate_change",
            "old_values": {"rate_candidate": RATE_BEFORE_ANNEX},
            "new_values": {"rate_candidate": RATE_CANDIDATE},
            "effective_date": f"@reld:{effective}",
            "reason": "Aneks 1: podwyżka po pół roku współpracy.",
            "document_id": None,
            "created_by": DL[0],
            "created_by_email": None,
            "created_at": f"@rel:{effective - 2}",
            "created_by_name": DL[1],
            "source": "manual",
            "b2b_document_id": None,
            "state": "in_force",
            "document": None,
            "withdrawn": False,
            "withdrawable": False,
        }
    ]


def rate_documents() -> dict:
    """Karta „Stawka z dokumentu”: aneks podaje 110 zł/h, harmonogram ma 105 zł/h."""
    return {
        "items": [
            {
                "id": RATE_READ_ID,
                "document_id": ANNEX_DOCUMENT_ID,
                "filename": "aneks-2-zmiana-stawki-cwiczebny.pdf",
                "kind": "annex",
                "document_date": "@reld:-2",
                "category": "review",
                "reasons": ["Stawka w aneksie różni się od harmonogramu kontraktu."],
                "decision": None,
                "decided_at": None,
                "undo_until": None,
                "read_at": "@rel:-1.5",
                "steps": [
                    {
                        "from": "@reld:9",
                        "to": None,
                        "rate": RATE_FROM_ANNEX,
                        "nexus_rate": RATE_CANDIDATE,
                        "condition": None,
                    }
                ],
                "quote": "Od dnia wejścia w życie aneksu stawka Partnera wynosi 110,00 zł netto za godzinę.",
            }
        ],
        "amounts_visible": True,
        "can_apply": True,
    }


# --- opieka i start ----------------------------------------------------------


def _care_contract(person: dict) -> dict:
    return {
        "id": person["contract_id"],
        "candidate_id": person["candidate_id"],
        "candidate_name": person["name"],
        "client_id": POLIGON_CLIENT,
        "client_name": CLIENT_NAME,
        "job_id": POLIGON_JOB,
        "job_title": JOB_TITLE,
        "status": "active",
        "is_live": True,
        "start_date": "@reld:-200",
        "end_date": None,
    }


def care_card() -> dict:
    return {
        "contract_id": ACTIVE["contract_id"],
        "candidate_id": ACTIVE["candidate_id"],
        "candidate_name": ACTIVE["name"],
        "client_id": POLIGON_CLIENT,
        "client_name": CLIENT_NAME,
        "role": JOB_TITLE,
        "form": "b2b",
        "start_on": "@reld:-200",
        "end_on": None,
        "owner": {"user_id": DL[0], "name": DL[1], "source": "delivery_lead"},
        "cadence": {"level": "monthly", "label": "Raz w miesiącu", "until_on": None},
        "health": {
            "level": "watch",
            "label": "Do obserwacji",
            "reasons": [
                "Zamówienie kończy się za 40 dni, a nie ma decyzji o przedłużeniu."
            ],
        },
        "kpis": {
            "last_contact": {"on": "@reld:-24", "days_ago": 24},
            "satisfaction": None,
            "manager_feedback": None,
            "order_end": {"on": "@reld:40", "days": 40},
        },
        "next_step": {
            "kind": "contact",
            "label": "Rozmowa z konsultantem",
            "detail": "Zapytaj o plany po końcu zamówienia.",
        },
        "known_project": {
            "source": None,
            "area": "Płatności",
            "manager": {
                "contact_id": CLIENT_CONTACT[0],
                "name": CLIENT_CONTACT[1],
                "position": CLIENT_CONTACT[2],
            },
            "team_size": 8,
            "team_externals": 2,
            "technologies": [],
            "vendors": [],
            "hiring": None,
            "project_end_month": None,
            "quote": None,
        },
        "cases": [],
        "plan": [
            {
                "id": CARE_PLAN_ID,
                "kind": "monthly",
                "label": "Rozmowa miesięczna",
                "due_on": "@reld:6",
                "status": "open",
                "skip_reason": None,
            }
        ],
        "can_edit": True,
        "can_change_owner": True,
        "can_see_feedback": True,
    }


def care_contract() -> dict:
    return {
        "contract": {
            **_care_contract(ACTIVE),
            "label": f"{ACTIVE['name']} · {CLIENT_NAME}",
            "day_of_cooperation": 200,
        },
        "owner": {
            "user": {"id": DL[0], "name": DL[1]},
            "source": "delivery_lead",
            "explicit": False,
        },
        "client_default_owner": None,
        "cadence": {
            "level": "monthly",
            "source": "program",
            "starts_on": "@reld:-110",
            "until_on": None,
            "returns_to": None,
            "reason": None,
            "note": None,
            "author": None,
            "can_edit": True,
        },
        "plan": [
            {
                "id": CARE_PLAN_ID,
                "kind": "monthly",
                "label": "Rozmowa miesięczna",
                "due_on": "@reld:6",
                "status": "open",
                "overdue": False,
                "done_conversation_id": None,
                "resolved_at": None,
                "skip_reason": None,
                "skip_note": None,
            }
        ],
        "next_contact": {
            "due_on": "@reld:6",
            "label": "Rozmowa miesięczna",
            "plan_item_id": CARE_PLAN_ID,
            "overdue": False,
        },
        "last_satisfaction": None,
        "conversations": [],
        "tech_cards": [],
        "redeploy": [],
        "project_end": None,
        "can_edit": True,
    }


def care_timeline() -> dict:
    return {
        "contract": _care_contract(ACTIVE),
        "owner": {"id": DL[0], "name": DL[1]},
        "manager": {
            "id": CLIENT_CONTACT[0],
            "name": CLIENT_CONTACT[1],
            "position": CLIENT_CONTACT[2],
            "area": None,
        },
        "signals": [],
        "front_office_reasons": [],
        "events": [
            {
                "kind": "start",
                "on": "@reld:-200",
                "title": "Start u klienta",
                "detail": "Pierwszy dzień w programie płatności.",
                "link": None,
                "future": False,
            },
            {
                "kind": "care",
                "on": "@reld:-24",
                "title": "Rozmowa miesięczna",
                "detail": "Zadowolony z projektu, pyta o przedłużenie.",
                "link": None,
                "future": False,
            },
        ],
        "feedback_visible": True,
        "can_edit": True,
    }


def contract_notes() -> list:
    """Strumień opieki: notatki i rozmowy kontraktu (`ContractTimelineItem`)."""
    return [
        {
            "id": 990594,
            "kind": "note",
            "at": "@rel:-24",
            "summary": None,
            "content": "Rozmowa miesięczna: zadowolony z projektu, chce zostać po końcu zamówienia.",
            "sub_type": "call",
            "status": None,
            "author_id": DL[0],
            "author_name": DL[1],
            "duration_seconds": None,
        }
    ]


def onboarding() -> list:
    return [
        {
            "id": 990661 + i,
            "contract_id": ACTIVE["contract_id"],
            "label": label,
            "status": "done",
            "assigned_to": DL[0],
            "due_date": None,
            "notes": None,
            "order": i,
            "created_at": "@rel:-205",
            "updated_at": "@rel:-200",
        }
        for i, label in enumerate(
            ("Umowa B2B podpisana", "Dostęp do systemów klienta", "Sprzęt od klienta")
        )
    ]


# --- klient -----------------------------------------------------------------


def client_detail() -> dict:
    return {
        "id": POLIGON_CLIENT,
        "name": CLIENT_NAME,
        "display_name": CLIENT_NAME,
        "industry": "Bankowość",
        "website": None,
        "address": None,
        "status": "active",
        "nda_signed": True,
        "contract_type": None,
        "cv_interactive_enabled": True,
        "cv_content_mode_cap": None,
        "created_at": "@rel:-400",
        "updated_at": "@rel:-3",
        "notes": None,
        "legal_name": CLIENT_LEGAL_NAME,
        "nip": None,
        "regon": None,
        "multi_consultant_orders_enabled": False,
        "cost_orders_enabled": False,
        "periodic_orders_enabled": True,
        "legacy_null_order_type": "periodic",
        "cyfrowy_polsat_order_types_enabled": False,
        "lotte_wedel_order_types_enabled": False,
    }


def client_team() -> dict:
    return {
        "tacs": [],
        "delivery_leads": [
            {
                "id": 990611,
                "user_id": DL[0],
                "name": DL[1],
                "email": None,
                "role": "delivery_lead",
                "is_head": True,
                "created_at": "@rel:-400",
            }
        ],
    }


def directory() -> dict:
    """Lista klientów: jeden klient, „Współpracujemy”, w „Wymaga uwagi” koniec zamówienia."""
    return {
        "items": [
            {
                "client_id": POLIGON_CLIENT,
                "display_name": CLIENT_NAME,
                "legal_name": CLIENT_LEGAL_NAME,
                "industry": "Bankowość",
                "state": "working",
                "active_consultants": 1,
                "planned_consultants": 0,
                "open_jobs": 1,
                "monthly_margin": _monthly(RATE_CLIENT - RATE_CANDIDATE),
                "monthly_margin_unpriced": 0,
                "delivery_leads": [{"name": DL[1], "is_head": True}],
                "framework_effective_date": "@reld:-640",
                "framework_expiry_date": "@reld:60",
                "has_framework_period": True,
                "framework_count": 1,
                "consultant_attention": {
                    "total": 1,
                    "order_ending": 1,
                    "order_ending_first": "@reld:40",
                    "no_current_order": 0,
                    "notice": 0,
                },
                "manually_placed": False,
            }
        ],
        "total": 1,
        "page": 1,
        "page_size": 50,
        "state_counts": {"working": 1, "idle": 0, "archive": 0},
        "amounts_visible": True,
        "manually_placed_count": 0,
        "as_of": "@rel:0",
    }


def _profile_consultant(person: dict, row: dict) -> dict:
    monthly_client = _monthly(RATE_CLIENT)
    monthly_candidate = _monthly(RATE_CANDIDATE)
    return {
        "contract_id": person["contract_id"],
        "candidate": {
            "id": person["candidate_id"],
            "name": person["name"],
            "avatar_url": None,
            "competence_category": "project_management",
            "linkedin": None,
        },
        "job_id": POLIGON_JOB,
        "job_title": JOB_TITLE,
        "job_from_order": False,
        "start_date": row["start_date"],
        "end_date": row["end_date"],
        "monthly_rate_client": monthly_client,
        "monthly_rate_candidate": monthly_candidate,
        "monthly_margin": round(monthly_client - monthly_candidate, 2),
        "hourly_rate_client": RATE_CLIENT,
        "hourly_rate_candidate": RATE_CANDIDATE,
        "currency": "PLN",
        "project_code": None,
        "project_name": "Program płatności (ćwiczenie)",
    }


def client_profile() -> dict:
    active = active_contract_row()
    ended = ended_contract_row()
    monthly_margin = _monthly(RATE_CLIENT - RATE_CANDIDATE)
    return {
        "summary": {
            "open_jobs": 1,
            "active_consultants": 1,
            "active_contracts": 1,
            "total_placements": 2,
            # Serwer: suma miesięcznych marż w pełnych złotych (`api/clients.py`).
            "active_mrr": int(monthly_margin),
            "active_mrr_unpriced_contracts": 0,
            "active_mrr_fx_missing_contracts": 0,
            "ltv": int(monthly_margin * 17),
            "avg_time_to_fill_days": 21.0,
            "avg_time_to_fill_source": "opened_at",
            "avg_time_to_fill_not_assessable": 0,
        },
        "open_jobs": [
            {
                "id": POLIGON_JOB,
                "title": JOB_TITLE,
                "seniority": "senior",
                "priority": "high",
                "days_open": 9,
                "candidate_count": 16,
                "salary_min": 95.0,
                "salary_max": 115.0,
                "recruiter": {
                    "id": REC[0],
                    "name": REC[1],
                    "email": None,
                    "avatar_url": None,
                },
                "created_at": "@rel:-9",
            }
        ],
        "active_consultants": [
            {
                **_profile_consultant(ACTIVE, active),
                "days_to_end": None,
                "contract_status": "active",
                "project_part": None,
                "executive_contract": None,
                "order_start_date": "@reld:-200",
                "order_end_date": "@reld:40",
                "order_status": "active",
                "order_ending_on": "@reld:40",
                "attention": ["order_ending"],
                "prolongation_status": "unknown",
                "hours_pool_total": None,
                "hours_pool_consumed": 0.0,
            }
        ],
        "planned_consultants": [],
        "pending_consultants": [],
        "historical": {
            "placements": [
                {
                    **_profile_consultant(ENDED, ended),
                    "terminated_at": "@rel:-12",
                    "termination_reason": "project_ended",
                    "duration_months": 10,
                    "total_revenue": round(_monthly(RATE_CLIENT) * 10, 2),
                }
            ],
            "placements_total": 1,
            "lost_jobs": [],
        },
    }


def framework_contracts() -> dict:
    return {
        "items": [
            {
                "id": FRAMEWORK_ID,
                "client_id": POLIGON_CLIENT,
                "name": "Umowa ramowa (ćwiczebna)",
                "status": "active",
                "effective_date": "@reld:-640",
                "expiry_date": "@reld:60",
                "signed_via": "upload",
                "currency": "PLN",
                "parent_contract_id": None,
                "contract_terms_id": None,
                "filename": None,
                "has_file": False,
                "content_type": None,
                "size_bytes": None,
                "uploaded_by": None,
                "uploaded_at": None,
                "notes": None,
                "source_system": None,
                "source_key": None,
                "import_run_id": None,
                "created_at": "@rel:-640",
                "updated_at": "@rel:-640",
                "amendments_count": 0,
                "days_to_expiry": 60,
            }
        ],
        "total": 1,
    }


def client_contacts() -> list:
    return [
        {
            "id": CLIENT_CONTACT[0],
            "client_id": POLIGON_CLIENT,
            "name": CLIENT_CONTACT[1],
            "email": None,
            "phone": None,
            "position": CLIENT_CONTACT[2],
            "department": None,
            "is_decision_maker": True,
            "notes": None,
            "last_contacted_at": "@rel:-45",
            "created_at": "@rel:-400",
            "is_key_relationship": True,
            "relationship_strength": None,
            "key_relationship_owner_id": DL[0],
            "last_personal_touchpoint_at": "@rel:-45",
            "relationship_notes": None,
        }
    ]


def invoicing() -> dict:
    """Poprzedni miesiąc: RCP przyjęte, faktura w KSeF, zapłata bez wyciągów."""
    net = _money(RATE_CLIENT * HOURS)
    return {
        "period": "@relm:-1",
        "rows": [
            {
                "key": f"o{ORDER_ACTIVE}",
                "kind": "periodic",
                "kind_label": "okresowe",
                "group_id": None,
                "order_id": ORDER_ACTIVE,
                "client_id": POLIGON_CLIENT,
                "order_number": ORDER_NUMBER,
                "currency": "PLN",
                "expected_net": net,
                "missing": 0,
                "sheet_invoiced": None,
                "budget": None,
                "lines": [
                    {
                        "order_id": ORDER_ACTIVE,
                        "consultant": ACTIVE["name"],
                        "basis": "hours",
                        "unit": "h",
                        "quantity": str(HOURS),
                        "unit_price": _money(RATE_CLIENT),
                        "net": net,
                        "currency": "PLN",
                        "note": "RCP przyjęte",
                        "sheet_invoiced": None,
                    }
                ],
                "invoice_ids": [INVOICE_ID],
                "status": "accepted",
                "status_label": "Zgodne",
                "invoiced_net": net,
                "difference": "0.00",
                "client_name": CLIENT_NAME,
            }
        ],
        "invoices": [
            {
                "id": INVOICE_ID,
                "invoice_number": "ĆW/FV/2026/101",
                "ksef_number": "ĆW-KSEF-0001",
                "invoice_kind": "original",
                "issue_date": "@reld:-19",
                "due_date": "@reld:2",
                "period": "@relm:-1",
                "period_source": "invoice",
                "currency": "PLN",
                "net": net,
                "gross": _money(RATE_CLIENT * HOURS * 1.23),
                "client_id": POLIGON_CLIENT,
                "client_name": CLIENT_NAME,
                "buyer_name": CLIENT_LEGAL_NAME,
                "buyer_nip": None,
                "buyer_foreign_id": None,
                "buyer_number_kind": "nip",
                "corrections": [],
                "match_status": "matched",
                "match_method": "order_number",
                "match_reason": None,
                "match_reason_text": None,
                "ignore_reason": None,
                "targets": [
                    {"group_id": None, "order_id": ORDER_ACTIVE, "label": ORDER_NUMBER}
                ],
                "check": "accepted",
                "check_basis": "amount",
                "expected": net,
                "difference": "0.00",
                "difference_accepted": None,
                "payment_status": "unpaid",
                "paid": "0.00",
                "to_pay": _money(RATE_CLIENT * HOURS * 1.23),
                "paid_on": None,
                "overdue_days": 0,
                "payment_unknown": True,
                "payment_unknown_reason": "statements",
                "payment_account": None,
                "statements_until": None,
            }
        ],
        "summary": {
            "rows": 1,
            "not_invoiced": 0,
            "invoiced": 1,
            "differences": 0,
            "unknown": 0,
            "cost": 0,
            "unmatched_invoices": 0,
            "expected": [{"currency": "PLN", "amount": net}],
            "invoiced_net": [{"currency": "PLN", "amount": net}],
            "overdue": 0,
            "payment_unknown": 1,
            "payment_unknown_reasons": [
                {
                    "reason": "statements",
                    "label": "Brak wyciągów rachunku",
                    "account": None,
                    "count": 1,
                }
            ],
        },
        "overdue": [],
        "module_enabled": True,
        "can_manage": False,
    }


def settlements() -> dict:
    return {
        "client_id": POLIGON_CLIENT,
        "client_name": CLIENT_NAME,
        "month": "@relm:-1",
        "can_see_amounts": True,
        "signature_hold": None,
        "rows": [
            {
                "contract_id": ACTIVE["contract_id"],
                "person": ACTIVE["name"],
                "order_number": ORDER_NUMBER,
                "kind": "periodic",
                "currency": "PLN",
                "state": "invoiced",
                "positions": [],
                "net": _money(RATE_CLIENT * HOURS),
                "cost": _money(RATE_CANDIDATE * HOURS),
                "integration_cost": None,
                "margin": _money((RATE_CLIENT - RATE_CANDIDATE) * HOURS),
                "margin_pct": round(
                    (RATE_CLIENT - RATE_CANDIDATE) / RATE_CLIENT * 100, 1
                ),
                "template": False,
                "ksef_number": "ĆW-KSEF-0001",
                "invoice_number": "ĆW/FV/2026/101",
            }
        ],
        "integration": {"enabled": False, "limit": None, "year": None, "items": []},
        "can_decide": False,
    }


# --- zamówienia z maila -----------------------------------------------------


def order_mail_item() -> dict:
    return {
        "id": ORDER_MAIL_DOC,
        "received_at": "@rel:-0.4",
        "sender_email": None,
        "subject": f"Zamówienie {ORDER_AFTER_END_NUMBER} — przedłużenie (ćwiczenie)",
        "attachment_name": "zamowienie-cwiczebne.pdf",
        "outcome": "needs_review",
        "client_id": POLIGON_CLIENT,
        "client_name": CLIENT_NAME,
        "identification_method": "registry_id",
        "identification_reason": "Numer rejestrowy klienta z nagłówka PDF.",
        "client_policy": "Zamówienia okresowe na godziny.",
        "gate_verdict": "review",
        "gate_reasons": [
            f"Umowa z osobą {ENDED['name']} jest zakończona — sprawdź, czy zamówienie ma trafić do innej osoby.",
        ],
        "document_meta": None,
        "extraction": {
            "title": ORDER_AFTER_END_NUMBER,
            "source": "poligon",
            "currency": "PLN",
            "start_date": "@reld:-11",
            "end_date": "@reld:48",
            "md_total": None,
            "rate_unit": "hour",
            "rate_client": _money(RATE_CLIENT),
            "rate_client_gross": None,
            "rate_client_md": None,
            "total_value": None,
            "consultant_ref": None,
            "uncertain": False,
            "ai_failure": None,
            "confidence": None,
            "model_rows": [],
            "consultant_rows": [
                {
                    "consultant_name": ENDED["name"],
                    "start_date": "@reld:-11",
                    "end_date": "@reld:48",
                    "rate_client": _money(RATE_CLIENT),
                    "rate_client_gross": None,
                    "rate_unit": "hour",
                    "md_total": None,
                    "client_category": None,
                    "uncertain": False,
                    "uncertain_reason": None,
                }
            ],
            "uncertain_reasons": [],
            "document_truncated": False,
            "title_needs_review": False,
            "consultant_md_matched": False,
            "consultant_rate_matched": True,
        },
        "proposal": {
            "rows": [
                {
                    "title": ORDER_AFTER_END_NUMBER,
                    "action": "new_draft",
                    "reasons": ["Nowa osoba bez umowy"],
                    "currency": "PLN",
                    "start_date": "@reld:-11",
                    "end_date": "@reld:48",
                    "md_total": None,
                    "row_name": ENDED["name"],
                    "rate_unit": "hour",
                    "row_index": 0,
                    "order_type": "periodic",
                    "contract_id": ENDED["contract_id"],
                    "rate_client": _money(RATE_CLIENT),
                    "total_value": None,
                    "candidate_id": ENDED["candidate_id"],
                    "decision_kind": None,
                    "overlap_options": [],
                    "target_order_id": None,
                    "overlap_trim_end": None,
                    "previous_end_date": None,
                    "previous_order_id": None,
                    "previous_rate_unit": None,
                    "existing_person_ids": [],
                    "overlap_start_after": None,
                    "previous_start_date": None,
                    "previous_order_title": None,
                    "previous_rate_client": None,
                    "previous_rate_currency": None,
                }
            ],
            "blocking": [],
            "resolved": [],
            "client_id": POLIGON_CLIENT,
            "order_number": ORDER_AFTER_END_NUMBER,
            "is_group_client": False,
        },
        "applied_order_id": None,
        "applied_at": None,
        "reviewed_at": None,
        "error": None,
        "can_apply": True,
        "can_dismiss": True,
        "has_file": False,
        "failed_retry_pending": False,
    }


def order_mail_sync_status() -> dict:
    return {
        "enabled": False,
        "interval_minutes": 15,
        "autoapply_enabled": True,
        "running": False,
        "started_at": None,
        "interrupted": False,
        "last_completed": None,
        "can_trigger": False,
    }


# --- Finanse ----------------------------------------------------------------


def rate_divergences() -> dict:
    """Linia zamówienia ma koszt sprzed aneksu 1 (100 zł/h), kontrakt 105 zł/h."""
    return {
        "rows": [
            {
                "md": None,
                "leg": "cost",
                "leg_label": "koszt",
                "link": f"/contracts/{ACTIVE['contract_id']}",
                "month": "@relm:-1",
                "effect": "Koszt w zamówieniu niższy niż w kontrakcie.",
                "person": ACTIVE["name"],
                "currency": "PLN",
                "rounding": False,
                "difference": _money(RATE_CANDIDATE - RATE_BEFORE_ANNEX),
                "order_rate": _money(RATE_BEFORE_ANNEX),
                "client_name": CLIENT_NAME,
                "order_number": ORDER_NUMBER,
                "contract_rate": _money(RATE_CANDIDATE),
            }
        ],
        "month": "@relm:-1",
        "skipped": {"other_currency": 0, "no_contract_rate": 0},
        "generated_at": "@rel:-0.3",
        "checked_lines": 1,
    }


def order_cost_corrections() -> dict:
    """„Do korekty po zmianie stawki”: zakończone zamówienie Mai ma koszt sprzed aneksu 1."""
    diff = (RATE_CANDIDATE - RATE_BEFORE_ANNEX) * HOURS
    return {
        "rows": [
            {
                "order_id": ORDER_ENDED,
                "client_id": POLIGON_CLIENT,
                "client_name": CLIENT_NAME,
                "contract_id": ENDED["contract_id"],
                "person": ENDED["name"],
                "order_number": "ĆW/ZAM/2026/03",
                "start_date": "@reld:-320",
                "end_date": "@reld:-12",
                "unit": "hourly",
                "currency": "PLN",
                "in_order": [
                    {
                        "from": "@reld:-320",
                        "to": "@reld:-12",
                        "rate": _money(RATE_BEFORE_ANNEX),
                    }
                ],
                "in_contract": [
                    {
                        "from": "@reld:-320",
                        "to": "@reld:-101",
                        "rate": _money(RATE_BEFORE_ANNEX),
                    },
                    {
                        "from": "@reld:-100",
                        "to": "@reld:-12",
                        "rate": _money(RATE_CANDIDATE),
                    },
                ],
                "months": [
                    {
                        "month": f"@relm:{m}",
                        "in_order": _money(RATE_BEFORE_ANNEX * HOURS),
                        "in_contract": _money(RATE_CANDIDATE * HOURS),
                        "diff": _money(diff),
                    }
                    for m in (-3, -2, -1)
                ],
                "estimate": _money(diff * 3),
            }
        ]
    }


def order_changes_summary() -> dict:
    tabs = {
        k: {"total": 0, "todo": 0}
        for k in ("changes", "entries", "exits", "ending", "gaps")
    }
    tabs["exits"] = {"total": 1, "todo": 1}
    return {"period": None, "tabs": tabs, "todo": 1}


# --- zestaw -----------------------------------------------------------------


def contract_list_keys() -> dict[str, object]:
    """Lista kontraktów i liczniki pigułek (każdy wariant parametrów osobno)."""
    active = active_contract_row()
    ended = ended_contract_row()
    live = [active]
    grouped = [("group_by_candidate", "true"), ("page", "1")]
    one = [("group_by_candidate", "true"), ("page", "1"), ("page_size", "1")]
    out: dict[str, object] = {
        contracts_key([("status", "active,ending"), *grouped]): contract_list(live),
        contracts_key(grouped): contract_list([active, ended]),
        contracts_key([("status", "draft,ready_for_signature"), *one]): contract_list(
            [], page_size=1
        ),
        contracts_key([("status", "active,ending"), *one]): contract_list(
            live, page_size=1
        ),
        contracts_key([("bucket", "ending"), *one]): contract_list(
            [ended], page_size=1
        ),
        contracts_key([("bucket", "order_after_end"), *one]): contract_list(
            [ended], page_size=1
        ),
        contracts_key(one): contract_list([active, ended], page_size=1),
        contracts_key([("bucket", "rate_document"), *one]): contract_list(
            [active], page_size=1
        ),
        contracts_key([("bucket", "order_after_end"), *grouped]): contract_list(
            [ended]
        ),
        contracts_key([("bucket", "rate_document"), *grouped]): contract_list([active]),
        contracts_key([("bucket", "ending"), *grouped]): contract_list([ended]),
    }
    # Widok „Kończące się” i „Grupuj: klient” czytają wszystkie wiersze stronami po 100.
    every = [("group_by_candidate", "false"), ("page", "1"), ("page_size", "100")]
    out[contracts_key([("status", "active,ending"), *every])] = contract_list(
        live, page_size=100
    )
    out[contracts_key([("bucket", "ending"), *every])] = contract_list(
        [ended], page_size=100
    )
    out[contracts_key(every)] = contract_list([active, ended], page_size=100)
    return out


def lost_review_empty() -> dict:
    """Zakładka „Przegrane” bez przegranych w okresie (kształt `lost_review.compute`)."""
    side = {"count": 0, "first_cv_days": None, "cvs": None, "interview_share": None}
    return {
        "period": {
            "kind": "month",
            "start": "@relm:0",
            "end": "@relm:1",
            "timezone": "Europe/Warsaw",
        },
        "period_label": "bieżący miesiąc",
        "since": "2026-10-11T22:00:00+00:00",
        "counts": {"won": 0, "lost": 0, "competitor": 0, "idle": 0},
        "hit_ratio": None,
        "known": 0,
        "why_filled": 0,
        "stages": {"no_cv": 0, "cv_only": 0, "interview": 0, "acceptance": 0},
        "compare": {"won": side, "lost": side},
        "trend": [],
        "why_counts": [],
        "source_counts": {"client": 0, "ours": 0, "unknown": 0},
        "client_verdicts": [],
        "clients": [],
        "jobs": [],
        "lessons": [],
        "findings": ["W tym okresie nie ma przegranych rekrutacji."],
    }


def client_practice(template_candidate_id: int) -> dict[str, object]:
    """Odpowiedzi klienta ćwiczebnego: klucz zestawu → odpowiedź."""
    c = POLIGON_CLIENT
    a = ACTIVE["contract_id"]
    e = ENDED["contract_id"]
    active = active_contract_row()
    ended = ended_contract_row()
    out: dict[str, object] = {
        # Lista klientów i to, co dokłada kolumna „Wymaga uwagi”.
        "GET /api/clients/directory/clients?page=1&page_size=50&state=working": directory(),
        "GET /api/client-reports/calendar?mine=false": {
            "month": "@relm:0",
            "today": "@reld:0",
            "items": [],
            "upcoming": [],
            "counts": {},
        },
        "GET /api/my-relationships": [],
        "GET /api/clients-lookup?delivery_scope=true": [{"id": c, "name": CLIENT_NAME}],
        # Karta klienta.
        f"GET /api/clients/{c}": client_detail(),
        f"GET /api/clients/{c}/team": client_team(),
        f"GET /api/clients/{c}/profile": client_profile(),
        f"GET /api/clients/{c}/framework-contracts": framework_contracts(),
        f"GET /api/client-reports/clients/{c}": {
            "client_id": c,
            "can_edit": False,
            "can_confirm": False,
            "definitions": [],
        },
        f"GET /api/clients/{c}/contacts": client_contacts(),
        f"GET /api/clients/{c}/framework-terms": {
            "client_id": c,
            "cards": [],
            "adders": [],
        },
        f"GET /api/clients/{c}/invoicing": invoicing(),
        # Insights → Przegrane (25.11.2026): pasek „Zasady ze spotkań” na stronie
        # rekrutacji klienta i sama zakładka (lekcja nowości) — bez zasad i bez
        # przegranych, więc ekran pokazuje swoje puste stany.
        f"GET /api/insights/lost-review/client-rules/{c}": {"rules": []},
        "GET /api/insights/lost-review?period=month&offset=0": lost_review_empty(),
        f"GET /api/my-clients/{c}/settlements": settlements(),
        f"GET /api/equipment/clients/{c}/provider": {"equipment_provider": "klient"},
        "GET /api/reports/clients?min_closed=0&period=year": {"@status": 403},
        f"GET /api/reports/clients/{c}/trend?months=6": {"@status": 403},
        # Kontrakty: szczegóły, zakładki i panel boczny.
        "GET /api/contractors/stats": {
            "draft": 0,
            "drafts_incomplete": 0,
            "active": 1,
            "active_contracts": 1,
            "ending": 0,
        },
        f"GET /api/contracts/{a}": contract_detail(active),
        f"GET /api/contracts/{e}": contract_detail(ended),
        f"GET /api/contracts/{a}/activities": contract_activities(a),
        f"GET /api/contracts/{e}/activities": contract_activities(e),
        f"GET /api/contracts/{a}/documents": contract_documents(a),
        f"GET /api/contracts/{e}/documents": contract_documents(e)[:1],
        f"GET /api/contracts/{a}/amendments": contract_amendments(ACTIVE, -60),
        f"GET /api/contracts/{e}/amendments": contract_amendments(ENDED, -100),
        f"GET /api/contracts/{a}/annex-documents": [],
        f"GET /api/contracts/{e}/annex-documents": [],
        f"GET /api/contracts/{a}/rate-documents": rate_documents(),
        f"GET /api/contracts/{e}/rate-documents": {
            "items": [],
            "amounts_visible": True,
            "can_apply": False,
        },
        f"GET /api/contracts/{a}/document-folders": {
            "folders": [],
            "orders_folder_name": "Zamówienia",
            "current_contract_number": CONTRACT_NUMBER,
            "suggestions": [],
        },
        f"GET /api/clients/order-documents/by-contract/{a}": {"documents": []},
        f"GET /api/clients/order-documents/by-contract/{e}": {"documents": []},
        f"GET /api/contracts/{a}/benchmark": {"@status": 403},
        f"GET /api/contracts/{e}/benchmark": {"@status": 403},
        f"GET /api/hr/payroll/contracts/{a}/admin-details": {
            "contract_id": a,
            "candidate_id": ACTIVE["candidate_id"],
            "client_id": c,
            "is_replacement": False,
            "replaced_contract_id": None,
            "replaced": None,
            "is_client_referral": False,
        },
        f"GET /api/care/contracts/{a}/card": care_card(),
        f"GET /api/care/contracts/{a}": care_contract(),
        f"GET /api/care/contracts/{a}/timeline": care_timeline(),
        f"GET /api/care/contracts/{a}/feedback": {
            "items": [],
            "client_id": c,
            "can_write": False,
        },
        f"GET /api/contracts/{a}/notes": contract_notes(),
        f"GET /api/hr/lifecycle/contracts/{a}/entry": {"@status": 404},
        f"GET /api/contracts/{a}/onboarding": onboarding(),
        f"GET /api/contracts/{a}/equipment": [],
        f"GET /api/equipment/contracts/{a}": {
            "active": [],
            "history": [],
            "protocols": [],
        },
        f"GET /api/equipment/holders/contract/{a}": {"@status": 403},
        f"GET /api/consultant-panel/contracts/{a}": {"@status": 403},
        f"GET /api/consultant-panel/contracts/{a}/settings": {"@status": 404},
        f"GET /api/start-documents/pair?candidate_id={template_candidate_id}&job_id={POLIGON_JOB}": None,
        f"GET /api/start-documents/clients/{c}": {
            "client_id": c,
            "documents": [],
            "items": [],
        },
        # Zamówienia z maila.
        "GET /api/order-mail/queue?limit=100&outcome=needs_review": {
            "total": 1,
            "items": [order_mail_item()],
        },
        "GET /api/order-mail/queue?limit=1&outcome=needs_review": {
            "total": 1,
            "items": [order_mail_item()],
        },
        f"GET /api/order-mail/queue/{ORDER_MAIL_DOC}": order_mail_item(),
        "GET /api/order-mail/recheck-runs?limit=20": {
            "items": [],
            "scoped": True,
            "last_checked_at": None,
            "last_change_at": None,
            "unchanged_runs": 0,
            "window": {"start_hour": 18, "end_hour": 8, "enabled": False},
        },
        "GET /api/order-mail/sync/status": order_mail_sync_status(),
        # Finanse.
        "GET /api/finance/rate-divergences": rate_divergences(),
        "GET /api/finance/order-cost-corrections": order_cost_corrections(),
        "GET /api/finance/order-changes/summary": order_changes_summary(),
        **contract_list_keys(),
    }
    for outcome in ("auto_applied", "applied", "unrecognized_client", "failed"):
        out[f"GET /api/order-mail/queue?limit=1&outcome={outcome}"] = {
            "total": 0,
            "items": [],
        }
    return out
