"""Runda 10 audytu (27.09.2026) — poczta zamówień, testy bez bazy.

Każdy test odtwarza jedno znalezisko R10-N3-* / R10-N12-6 i padał przed
poprawką.
"""

from __future__ import annotations

import time
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.api import order_mail_queue as queue
from app.services import order_mail_ingest as ingest
from app.services import order_mail_recheck as recheck
from app.services.order_client_identity import ClientIdentification, ClientRegistry
from app.services.order_document_text import OrderDocumentText
from app.services.order_mail_apply import _split_person_name
from app.services.order_mail_planner import (
    ACTION_GROUP,
    ExistingOrder,
    plan_document,
)
from app.models.order_mail import OUTCOME_FAILED
from tests.test_order_mail_gate_and_planner import (
    TODAY,
    _extraction,
    _resolved,
    _row,
)


# ── R10-N3-2: linia MD nie kończy się datą ────────────────────────────────────


def test_live_md_group_line_sends_the_next_order_to_a_human():
    """Osoba na aktywnej linii MD do 31.03, PDF od 01.04: dawniej ``future``
    i zapis automatem samodzielnego zamówienia obok linii (ręcznie: 409)."""
    p = plan_document(
        client_id=1,
        extraction=_extraction([_row("A A")]),
        resolved=[_resolved(0, "A A", contract_id=10)],
        existing_orders_by_contract={
            10: [
                ExistingOrder(
                    80,
                    "active",
                    "445",
                    date(2031, 1, 1),
                    date(2031, 3, 31),
                    order_group_id=77,
                )
            ]
        },
        is_group_client=True,
        today=TODAY,
    )
    assert p.rows[0].action == ACTION_GROUP
    assert p.auto_eligible_actions is False
    assert any("#80" in r for r in p.rows[0].reasons)


# ── R10-N3-10: „KOWALSKI Jan” ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("tokens", "expected"),
    [
        (["KOWALSKI", "Jan"], ("Jan", "Kowalski")),
        (["Jan", "KOWALSKI"], ("Jan", "Kowalski")),
        (["NOWAK-KOWALSKA", "Anna", "Maria"], ("Anna Maria", "Nowak-Kowalska")),
        (["Anna", "Maria", "Nowak"], ("Anna Maria", "Nowak")),
        (["JAN", "KOWALSKI"], ("Jan", "Kowalski")),
    ],
)
def test_new_person_name_takes_the_capitalised_word_as_surname(tokens, expected):
    assert _split_person_name(tokens) == expected


# ── R10-N3-3: pusty tekst Nordei to nie „nie-zamówienie” ─────────────────────


@pytest.mark.asyncio
async def test_unreadable_nordea_pdf_is_failed_not_dismissed(monkeypatch):
    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", "77")
    empty = OrderDocumentText("", 3, True, False, None, 0.0)
    monkeypatch.setattr(ingest, "extract_order_text", lambda *args: empty)
    monkeypatch.setattr(
        ingest,
        "identify_client",
        lambda *a, **k: ClientIdentification(client_key="77", method="registry_id"),
    )
    monkeypatch.setattr(ingest, "_deleted_client_ids", AsyncMock(return_value=set()))
    parser = AsyncMock()
    monkeypatch.setattr(ingest, "parse_order_document", parser)
    row = SimpleNamespace(attachment_name="order.pdf", sender_email="a@nordea.com")
    await ingest.process_pdf_bytes(
        AsyncMock(), row, b"%PDF-dummy", registry=ClientRegistry({})
    )
    assert row.outcome == OUTCOME_FAILED
    assert row.error == ingest.UNREADABLE_TEXT_ERROR
    parser.assert_not_awaited()


# ── R10-N3-4: odczyt ``none`` jest ponawiany ─────────────────────────────────


def test_empty_read_is_retried_like_a_fallback_read(monkeypatch):
    monkeypatch.setattr(ingest, "_replannable", lambda row: True)
    row = SimpleNamespace(
        outcome="needs_review",
        client_id=5,
        extraction={"source": "none"},
        document_meta={},
    )
    assert ingest._needs_ai_retry(row) is True
    row.extraction = {"source": "claude"}
    assert ingest._needs_ai_retry(row) is False


# ── R10-N3-5: NUL w polach maila ──────────────────────────────────────────────


def test_nul_is_stripped_from_journal_fields():
    msg = {
        "id": "graph-\x00x",
        "internetMessageId": "<a\x00b@example>",
        "subject": "Zam\x00ówienie",
        "from": {"emailAddress": {"address": "Orders\x00@Bank.example"}},
        "receivedDateTime": "2031-03-03T08:00:00Z",
    }
    row = ingest._base_row(None, msg)
    assert "\x00" not in (row.subject + row.internet_message_id + row.sender_email)
    assert row.subject == "Zamówienie"
    assert row.sender_email == "orders@bank.example"
    assert ingest._attachment_name({"name": "zam\x00.pdf"}) == "zam.pdf"


def test_order_document_text_has_no_nul(monkeypatch, tmp_path):
    from app.services import order_document_text as odt

    monkeypatch.setattr(odt, "extract_text", lambda *a: "Call\x00 Off")
    monkeypatch.setattr(odt, "_pdf_page_count", lambda path: 1)
    monkeypatch.setattr(odt, "_extract_pdf_native", lambda path: "x" * 500)
    doc = odt.extract_order_text(str(tmp_path / "a.pdf"), "a.pdf")
    assert doc.text == "Call Off"


# ── R10-N3-8: kwoty w powodach dla roli bez finansów ─────────────────────────


def test_amounts_are_hidden_in_money_reasons_only():
    hide = queue._hide_amounts
    assert (
        hide("„Jan Kowalski”: stawka 1400 odbiega o 45% od obowiązującej 965,50")
        == "„Jan Kowalski”: stawka … odbiega o …% od obowiązującej …"
    )
    assert hide("„A”: stawka 1 250,00 zł poza pasmem 800–1200") == (
        "„A”: stawka … … zł poza pasmem …–…"
    )
    # Daty, numery rekordów i zamówień zostają, gdy powód nie mówi o pieniądzach.
    reason = "Okres nachodzi na otwarte zamówienie #611 (7/2031, do 2031-06-30)"
    assert hide(reason) == reason
    # W powodzie o stawce data i numer zamówienia też zostają.
    assert hide("stawka 900 na zamówieniu #611 od 30.09.2026") == (
        "stawka … na zamówieniu #611 od 30.09.2026"
    )
    assert hide(None) is None


@pytest.mark.parametrize(
    "hostile",
    [
        "stawka " + "1 " * 8000 + "x",
        "stawka " + "111 " * 4000 + "-",
        "stawka " + "1" * 16000 + "-",
        "stawka " + "1.1" * 5000 + "/",
    ],
)
def test_amount_mask_is_linear_on_hostile_text(hostile):
    started = time.perf_counter()
    queue._hide_amounts(hostile)
    assert time.perf_counter() - started < 0.05


def test_gate_reasons_are_masked_in_proposal_for_non_finance_role():
    proposal = {
        "rows": [{"reasons": ["stawka 1400 poza pasmem"], "rate_client": "1400"}],
        "blocking": ["kwota 50000 zł"],
        "resolved": [{"reason": "stawka 900"}],
    }
    out = queue._redact_proposal(proposal, show_finance=False)
    assert out["rows"][0]["reasons"] == ["stawka … poza pasmem"]
    assert out["rows"][0]["rate_client"] is None
    assert out["blocking"] == ["kwota … zł"]
    assert out["resolved"][0]["reason"] == "stawka …"


@pytest.mark.asyncio
async def test_queue_item_hides_amounts_in_reasons_for_role_without_finance(
    monkeypatch,
):
    """Hybryda DL+TCM albo DL spoza portfela: kwoty w ``extraction`` były
    zredagowane, a ``gate_reasons`` i ``error`` cytowały stawki."""
    from app.models.user import User, UserRole

    monkeypatch.setattr(queue, "_attachment_exists", lambda doc: True)
    reason = "„Jan Kowalski”: stawka 1400 odbiega o 45% od obowiązującej 965"
    doc = SimpleNamespace(
        id=1,
        received_at=None,
        created_at=None,
        sender_email="a@b.example",
        subject="Zamówienie",
        attachment_name="z.pdf",
        outcome="needs_review",
        client_id=5,
        identification_method="registry_id",
        identification_reason="NIP",
        client_policy=None,
        gate_verdict="review",
        gate_reasons=[reason],
        document_meta={},
        extraction=None,
        proposal=None,
        applied_order_id=None,
        applied_at=None,
        reviewed_at=None,
        error="Nie udało się zapisać zamówienia: stawka 1400",
        storage_path=None,
    )
    db = AsyncMock()
    db.scalar = AsyncMock(return_value="Bank")

    # Konto z rolą Delivery Leada widzi kwoty („Stawki i kwoty: podgląd”), ale
    # nie u TEGO klienta: treść zostaje, kwoty są maskowane, a przycisków
    # pliku i zapisu nie ma.
    lead = User(
        id=7,
        email="dl-outside@example.com",
        role=UserRole.delivery_lead,
        roles=["delivery_lead", "talent_community_manager"],
    )
    outside = queue._FinanceBoundary(frozenset({99}))
    body = await queue._serialize(db, doc, lead, boundary=outside)
    assert body["gate_reasons"] == [
        "„Jan Kowalski”: stawka … odbiega o …% od obowiązującej …"
    ]
    assert "1400" not in body["error"]
    assert body["identification_reason"] == "NIP"
    assert body["has_file"] is False
    assert body["can_apply"] is False and body["can_dismiss"] is False

    # Ten sam DL u klienta z przypisania: pełna treść, plik i zapis.
    assigned = queue._FinanceBoundary(frozenset({5}))
    body = await queue._serialize(db, doc, lead, boundary=assigned)
    assert body["gate_reasons"] == [reason]
    assert "1400" in body["error"]
    assert body["has_file"] is True
    assert body["can_apply"] is True and body["can_dismiss"] is True

    # Konto bez podglądu kwot (domyślnie TCM): bezpieczna projekcja — zdania
    # ogólne zamiast treści, która cytuje nazwiska i stawki.
    tcm = User(
        id=8,
        email="tcm@example.com",
        role=UserRole.talent_community_manager,
        roles=["talent_community_manager"],
    )
    body = await queue._serialize(db, doc, tcm, boundary=queue._FinanceBoundary(None))
    assert body["gate_reasons"] == ["Sprawdź odczytane dane przed zapisem."]
    assert body["identification_reason"] == "Klient rozpoznany automatycznie."
    assert body["error"] == "Przetwarzanie dokumentu zakończyło się błędem."
    assert body["has_file"] is False
    assert body["can_apply"] is False and body["can_dismiss"] is False

    # Finanse prowadzą zamówienia u wszystkich klientów (decyzja 02.10.2026).
    finance = User(
        id=9, email="fin@example.com", role=UserRole.finance, roles=["finance"]
    )
    body = await queue._serialize(
        db, doc, finance, boundary=queue._FinanceBoundary(None)
    )
    assert body["gate_reasons"] == [reason]
    assert body["has_file"] is True
    assert body["can_apply"] is True and body["can_dismiss"] is True


# ── R10-N3-9: odmowa writera bez nazwisk w logu ──────────────────────────────


def test_refusal_log_line_carries_no_names():
    import inspect

    from app.services import order_mail_apply

    source = inspect.getsource(order_mail_apply._write_document)
    start = source.index('"order_mail apply refused')
    call = source[start : source.index(")", start)]
    assert "exc" not in call


# ── R10-N3-11: bez recheku nie ma ponowień ───────────────────────────────────


def test_no_retry_promise_when_recheck_is_off(monkeypatch):
    now = datetime(2031, 3, 3, 12, 0, tzinfo=timezone.utc)
    row = SimpleNamespace(
        outcome=OUTCOME_FAILED,
        storage_path="om/x.pdf",
        document_meta={},
        received_at=now - timedelta(hours=1),
        created_at=None,
    )
    monkeypatch.setattr(recheck.settings, "ORDER_MAIL_RECHECK_ENABLED", True)
    assert recheck.failed_retry_pending(row, now=now, has_file=True) is True
    monkeypatch.setattr(recheck.settings, "ORDER_MAIL_RECHECK_ENABLED", False)
    assert recheck.failed_retry_pending(row, now=now, has_file=True) is False


# ── R10-N12-6: padający co bieg recheck degraduje sondę ──────────────────────


def test_repeated_recheck_failures_degrade_the_probe(monkeypatch):
    monkeypatch.setattr(ingest.settings, "ORDER_MAIL_POLL_INTERVAL_MINUTES", 60)
    now = datetime(2031, 3, 3, 12, 0, tzinfo=timezone.utc)
    fresh = now - timedelta(minutes=30)
    verdict = ingest.order_mail_health_verdict
    common = dict(
        finished_at=fresh, last_status="partial", unprocessed_messages=0, now=now
    )
    assert verdict(**common) == "healthy"
    assert verdict(**common, recheck_failures_in_row=2) == "healthy"
    assert (
        verdict(**common, recheck_failures_in_row=ingest.RECHECK_FAILURES_DEGRADED)
        == "degraded"
    )


def test_recheck_result_knows_whether_it_ran():
    assert recheck.RecheckRunResult().ran is False


@pytest.mark.asyncio
async def test_recheck_outside_the_window_does_not_count_as_a_run(monkeypatch):
    monkeypatch.setattr(recheck.settings, "ORDER_MAIL_RECHECK_ENABLED", False)
    result = await recheck.run_recheck(AsyncMock(), trigger="scheduled")
    assert result.ran is False
