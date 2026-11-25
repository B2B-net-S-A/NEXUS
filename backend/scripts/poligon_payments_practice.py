"""Plan przelewów na Poligonie (lekcja „Zajęcia i spory”, 25.11.2026).

Lekcja `lekcja-zajecia-i-spory` (PR #3816) każe w Przelewach przy fakturze
kontraktora zacząć wpisywać zajęcie wierzytelności. Plan przelewów czyta się
przez `POST /api/finance/payments/plan` (serwer sprawdza rachunki w wykazie
VAT), a Poligon traktował każdy POST jak zapis i odpowiadał 409: ekran
pokazywał „Nie udało się pobrać danych”, przycisku „Zajęcie” nie było i lekcja
kończyła się furtką po 45 s (test na stagingu 25.11.2026).

Front czyta teraz ten POST z zestawu (`READ_POSTS` w `store.ts`), a tu jest
odpowiedź: jedna faktura kontraktora ćwiczebnego (Filip Bukowiec, kontrakt
990521 klienta ćwiczebnego), bez rachunku, więc nic nie da się zaznaczyć do
paczki. Przycisk „Zajęcie” stoi przy fakturze z `contract_id`.
"""

from __future__ import annotations

try:
    from scripts.poligon_client_practice import ACTIVE, HOURS, RATE_CANDIDATE
except ModuleNotFoundError:  # wywołanie z `backend/`
    from poligon_client_practice import ACTIVE, HOURS, RATE_CANDIDATE

KEY = "POST /api/finance/payments/plan"

ENTRY_ID = 990611
SETTLEMENT_ID = 990612
INVOICE_NUMBER = "FV/ĆW/2026/10"
VAT_RATE = 0.23


def _money(value: float) -> str:
    return f"{value:.2f}"


def payment_plan() -> dict:
    """`PaymentPlan` (`frontend/src/lib/api/finance-payments.ts`) z fakturą kontraktora ćwiczebnego."""
    net = RATE_CANDIDATE * HOURS
    vat = round(net * VAT_RATE, 2)
    gross = net + vat
    item = {
        "entry_id": ENTRY_ID,
        "invoice_number": INVOICE_NUMBER,
        "ksef_number": None,
        "seller_name": ACTIVE["name"],
        "seller_nip": None,
        "category": "contractor",
        "due_date": "@reld:2",
        "currency": "PLN",
        "gross_amount": _money(gross),
        "vat_amount": _money(vat),
        "to_pay": _money(gross),
        "amount_note": None,
        "account_note": None,
        "mode": None,
        "mode_label": None,
        "mode_suggested": False,
        "account": None,
        "account_source": None,
        "account_source_label": None,
        "title": INVOICE_NUMBER,
        "white_list": {
            "state": "off",
            "label": "Na Poligonie wykazu VAT nie sprawdzamy",
        },
        "selectable": False,
        "block": "poligon",
        "block_label": "Na Poligonie przelewów się nie wysyła.",
        "acks": [],
        "hints": [],
        "batch_id": None,
        "preselect": False,
        "contract_id": ACTIVE["contract_id"],
        "period_month": "@relm:-1",
        "settlement_id": SETTLEMENT_ID,
        "hold": None,
        "contractor_amount": None,
        "garnishments": [],
    }
    return {
        "until": "@reld:7",
        "items": [item],
        "count": 1,
        "selectable": 0,
        "blocked": 1,
        "totals": {"PLN": _money(gross)},
    }


def payments_practice() -> tuple[dict, list[str]]:
    """Odczyt do nałożenia na zestaw i klucze w całości wymyślone."""
    return {KEY: payment_plan()}, [KEY]
