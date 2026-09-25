"""Historia BIZNESOWA zamówienia (ticket 7, 25.09.2026) — reguły widoku.

Czyste funkcje ``app.services.order_history`` na liście zdarzeń w kształcie
dziennika. Przypadek 4500030197 (BIK) odtwarza rzeczywisty układ wpisów
z produkcji (23 wpisy: sześć edycji jednej osoby w 3 minuty, podwójne
„Zakończono zamówienie"); nazwiska są zmyślone.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.services.order_history import (
    CATEGORY_CONSULTANTS,
    CATEGORY_CONSUMPTION,
    CATEGORY_EDITS,
    CATEGORY_ORDER,
    RawEvent,
    build_history,
    dedupe_events,
    technical_changes,
)

T0 = datetime(2026, 9, 24, 12, 22, 18, tzinfo=timezone.utc)
NAMES = {145: "Piotr Przykładowy", 146: "Kamil Testowy"}
_ids = iter(range(1, 10_000))


def ev(
    event_type: str,
    *,
    at: datetime,
    order_id: int | None = None,
    payload: dict | None = None,
    description: str = "opis",
    author_id: int | None = 39,
) -> RawEvent:
    return RawEvent(
        id=next(_ids),
        event_type=event_type,
        description=description,
        order_id=order_id,
        payload=payload,
        created_at=at,
        author_id=author_id,
        author_name="Anna Przykładowa" if author_id else None,
    )


def history(events: list[RawEvent]):
    return build_history(events, person_name=lambda oid: NAMES.get(oid or 0))


def _bik_events() -> list[RawEvent]:
    """Kształt dziennika 4500030197 z produkcji (po odfiltrowaniu technicznych
    wpisów zamówienia — to robi API przed widokiem)."""
    base = datetime(2026, 8, 21, 9, 31, tzinfo=timezone.utc)
    out = [
        ev("utworzenie", at=base, description="Utworzono zamówienie nr 4500030197"),
        ev(
            "dodanie_konsultanta",
            at=base + timedelta(minutes=5),
            order_id=145,
            payload={"consultant": "Piotr Przykładowy", "md_total": "2"},
        ),
        ev(
            "dodanie_konsultanta",
            at=base + timedelta(minutes=21),
            order_id=146,
            payload={"consultant": "Kamil Testowy", "md_total": "9.66"},
        ),
    ]
    imp1 = datetime(2026, 8, 31, 11, 19, 5, tzinfo=timezone.utc)
    for oid, md, rem in ((146, "21.75", "-12.09"), (145, "23", "-21")):
        out.append(
            ev(
                "import_md",
                at=imp1,
                order_id=oid,
                payload={
                    "import_id": 1,
                    "period_month": "2026-07",
                    "md_applied": md,
                    "md_remaining": rem,
                },
                description=f"Za lipiec zużyto {md} MD ({NAMES[oid]})",
            )
        )
    closed = datetime(2026, 9, 23, 11, 40, 3, tzinfo=timezone.utc)
    closing = {
        "lines": 2,
        "reason": "md_exhausted",
        "automatic": True,
        "closure_date": "2026-09-23",
    }
    out.append(ev("zakonczenie", at=closed, payload=closing, author_id=None))
    out.append(
        ev(
            "import_md",
            at=closed,
            order_id=145,
            payload={
                "import_id": 2,
                "period_month": "2026-08",
                "md_applied": "21",
                "md_remaining": "-19",
            },
            description="Za sierpień zużyto 21 MD (Piotr Przykładowy)",
        )
    )
    # Zdublowany zapis systemowy — ta sama minuta, to samo zdarzenie.
    out.append(ev("zakonczenie", at=closed, payload=dict(closing), author_id=None))
    out.append(
        ev(
            "import_md",
            at=closed,
            order_id=146,
            payload={
                "import_id": 2,
                "period_month": "2026-08",
                "md_applied": "4",
                "md_remaining": "-4",
            },
            description="Za sierpień zużyto 4 MD (Kamil Testowy)",
        )
    )
    # Sześć edycji jednej osoby w 3 minuty (24.09.2026).
    series = [
        {"changed": ["ręczna korekta MD"], "md_remaining": "3.7"},
        {"changed": ["ręczna korekta MD"], "md_remaining": "5.963"},
        {
            "changed": ["zejście MD"],
            "period_month": "2026-08",
            "md_reported": "3.7",
            "previous": "4",
            "md_remaining": "6.263",
        },
        {
            "changed": [
                "rate_candidate_currency",
                "rate_client_currency",
                "stawka kosztowa",
                "data zakończenia",
                "budżet MD",
            ],
            "md_remaining": "9.963",
        },
        {
            "changed": ["zejście MD"],
            "period_month": "2026-08",
            "md_reported": "3.7",
            "previous": "3.7",
            "md_remaining": "9.963",
        },
        {"changed": ["ręczna korekta MD"], "md_remaining": "5.963"},
    ]
    offsets = [0, 30, 89, 118, 137, 163]
    for payload, seconds in zip(series, offsets):
        out.append(
            ev(
                "edycja_reczna",
                at=T0 + timedelta(seconds=seconds),
                order_id=146,
                payload=payload,
            )
        )
    return out


def test_bik_history_has_no_single_consumptions_and_no_technical_fields():
    entries = history(_bik_events())
    imports = [e for e in entries if e.event_type == "import_md"]
    # Jeden wpis na import, nie na osobę.
    assert [e.import_id for e in imports] == [2, 1]
    assert imports[0].summary == "Import MD za sierpień 2026 – 2 osoby, 25 MD"
    assert imports[0].category == CATEGORY_CONSUMPTION
    assert set(imports[0].person_names) == set(NAMES.values())
    assert imports[1].summary == "Import MD za lipiec 2026 – 2 osoby, 44,75 MD"
    # Żaden wpis ani zmiana nie nosi surowej nazwy kolumny.
    for entry in entries:
        assert "rate_candidate_currency" not in entry.summary
        assert all("currency" not in c.label for c in entry.changes)
        for detail in entry.details:
            assert "rate_candidate_currency" not in detail.text
            assert "rate_client_currency" not in detail.text


def test_six_edits_of_one_person_are_one_entry_with_net_result():
    entries = history(_bik_events())
    series = [e for e in entries if e.category == CATEGORY_EDITS]
    assert len(series) == 1
    entry = series[0]
    assert entry.person_name == "Kamil Testowy"
    assert len(entry.details) == 6
    # Wynik netto: saldo sprzed serii (import sierpnia) i po niej.
    assert entry.balance_before == Decimal("-4")
    assert entry.balance_after == Decimal("5.963")
    labels = [c.label for c in entry.changes]
    assert "zejście MD" not in labels
    assert "ręczna korekta MD" in labels and "budżet MD" in labels
    assert entry.details[2].text.startswith("Zejście MD za sierpień 2026: 4 → 3,7 MD")


def test_duplicate_system_closure_in_the_same_minute_appears_once():
    entries = history(_bik_events())
    assert [e.event_type for e in entries].count("zakonczenie") == 1


def test_bik_history_shrinks_to_business_entries():
    entries = history(_bik_events())
    assert len(entries) == 7
    categories = {e.category for e in entries}
    assert categories == {
        CATEGORY_ORDER,
        CATEGORY_CONSULTANTS,
        CATEGORY_CONSUMPTION,
        CATEGORY_EDITS,
    }
    # Od najnowszego.
    assert entries == sorted(entries, key=lambda e: (e.created_at, e.key), reverse=True)


def test_edits_more_than_15_minutes_apart_are_separate_entries():
    events = [
        ev(
            "edycja_reczna",
            at=T0,
            order_id=146,
            payload={"diff": {"stawka kosztowa": ["560 zł/MD", "580 zł/MD"]}},
        ),
        ev(
            "edycja_reczna",
            at=T0 + timedelta(minutes=16),
            order_id=146,
            payload={"diff": {"stawka kosztowa": ["580 zł/MD", "600 zł/MD"]}},
        ),
    ]
    assert len([e for e in history(events) if e.category == CATEGORY_EDITS]) == 2


def test_edits_by_another_author_or_of_another_person_are_not_merged():
    events = [
        ev("edycja_reczna", at=T0, order_id=146, payload={"changed": ["budżet MD"]}),
        ev(
            "edycja_reczna",
            at=T0 + timedelta(minutes=1),
            order_id=146,
            payload={"changed": ["budżet MD"]},
            author_id=40,
        ),
        ev(
            "edycja_reczna",
            at=T0 + timedelta(minutes=2),
            order_id=145,
            payload={"changed": ["budżet MD"]},
        ),
    ]
    assert len(history(events)) == 3


def test_net_result_uses_first_before_and_last_after_and_drops_reverted_fields():
    events = [
        ev(
            "edycja_reczna",
            at=T0,
            order_id=146,
            payload={
                "diff": {
                    "stawka kosztowa": ["560 zł/MD", "580 zł/MD"],
                    "budżet MD": ["10 MD", "12 MD"],
                },
                "md_remaining_before": "4",
                "md_remaining": "6",
            },
        ),
        ev(
            "edycja_reczna",
            at=T0 + timedelta(minutes=3),
            order_id=146,
            payload={
                "diff": {
                    "stawka kosztowa": ["580 zł/MD", "600 zł/MD"],
                    "budżet MD": ["12 MD", "10 MD"],
                },
                "md_remaining": "4",
            },
        ),
    ]
    (entry,) = history(events)
    assert [(c.label, c.before, c.after) for c in entry.changes] == [
        ("stawka kosztowa", "560 zł/MD", "600 zł/MD")
    ]
    assert entry.balance_before == Decimal("4")
    assert entry.balance_after == Decimal("4")


def test_a_single_manual_consumption_edit_is_not_in_the_history():
    events = [
        ev(
            "edycja_reczna",
            at=T0,
            order_id=146,
            payload={
                "changed": ["zejście MD"],
                "period_month": "2026-08",
                "md_reported": "3.7",
                "previous": "4",
                "md_remaining": "6",
            },
        )
    ]
    assert history(events) == []


def test_a_technical_only_edit_is_not_in_the_history_but_feeds_the_timeline():
    legacy = ev(
        "edycja_reczna",
        at=T0,
        order_id=146,
        payload={"changed": ["rate_candidate_currency", "rate_client_currency"]},
    )
    new = ev(
        "edycja_reczna",
        at=T0 + timedelta(hours=1),
        order_id=146,
        payload={
            "diff": {},
            "technical": {"waluta stawki kosztowej": ["PLN", "EUR"]},
        },
    )
    assert history([legacy, new]) == []
    # Stary wpis wymieniał waluty przy każdym zapisie formularza — nie dowodzi
    # zmiany, więc nie trafia na Timeline.
    assert technical_changes(legacy) == []
    (change,) = technical_changes(new)
    assert (change.label, change.before, change.after) == (
        "waluta stawki kosztowej",
        "PLN",
        "EUR",
    )


def test_dedupe_keeps_different_events_of_the_same_minute():
    a = ev("import_md", at=T0, order_id=145, description="A", payload={"x": 1})
    b = ev("import_md", at=T0, order_id=146, description="B", payload={"x": 1})
    assert dedupe_events([a, b]) == [a, b]


def test_shared_pool_import_counts_the_pool_not_people():
    events = [
        ev(
            "import_md",
            at=T0,
            payload={"import_id": 7, "period_month": "2026-08", "md_reported": "30"},
        )
    ]
    (entry,) = history(events)
    assert entry.summary == "Import MD za sierpień 2026 – wspólna pula, 30 MD"
    assert entry.import_id == 7
