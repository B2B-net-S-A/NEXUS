"""Godzinowa ponowna weryfikacja wstrzymanych zamówień z maila (0316).

Dwie warstwy, celowo rozdzielone:

* reguła („czy to czeka na podpis umowy?", „czy już czas na kartę?") jest
  czysta i testowana tablicowo — bez bazy i bez zegara systemowego;
* orkiestracja (licznik prób, karta dla DL, historia biegu, retencja) na
  prawdziwej bazie, z odczytem PDF-a podmienionym na stub.

Baza testowa jest wspólna dla całego przebiegu i nie jest czyszczona, a bieg
przegląda KAŻDY wstrzymany wpis — dlatego wszystkie asercje idą po WŁASNYM
dokumencie testu, nigdy po globalnych licznikach biegu.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus, RateUnit
from app.models.order_mail import OrderMailDocument, OrderMailRecheckRun
from app.services import order_mail_ingest as ingest
from app.services import order_mail_recheck as recheck
from app.services.order_document_text import OrderDocumentText
from app.services.order_mail_gate import (
    CODE_AUTOAPPLY_DISABLED,
    CODE_AUTOAPPLY_EXCLUDED_CLIENT,
    CODE_CLIENT_NOT_CONFIRMED,
    CODE_PERSON_DECISION_NEW,
    CODE_PERSON_KNOWN_ELSEWHERE_IDLE,
    CODE_PERSON_KNOWN_ELSEWHERE_OPEN,
    CODE_PERSON_NAMESAKES,
    CODE_RATE_OUT_OF_BAND,
)
from app.services.order_mail_recheck_reasons import (
    CATEGORY_AWAITING_CONTRACT,
    CATEGORY_CONFIG,
    CATEGORY_OTHER,
    CATEGORY_UNRECOGNIZED,
    advance_attempts,
    classify_hold,
    should_alert,
)

NOW = datetime(2033, 5, 10, 9, 0, tzinfo=timezone.utc)


def _notify_spy(monkeypatch):
    """Podsłuch kart DL zapisujący ID dokumentów.

    Baza testowa jest wspólna i nie jest czyszczona, a bieg przegląda KAŻDY
    wstrzymany wpis — globalny licznik wywołań mierzyłby cudze dokumenty.
    """
    seen: list[int] = []

    async def notify(db, row, **_kwargs):
        seen.append(row.id)
        return 1

    monkeypatch.setattr(ingest, "notify_review", notify)
    return seen


def _unique_nip() -> str:
    """Poprawny NIP (suma kontrolna) unikalny dla tego przebiegu testu."""
    weights = (6, 5, 7, 2, 3, 4, 5, 6, 7)
    while True:
        base = f"{int(uuid.uuid4().int % 10**9):09d}"
        check = sum(int(d) * w for d, w in zip(base, weights)) % 11
        if check != 10:
            return base + str(check)


# ── Reguła: co znaczy „czeka na podpis umowy" ───────────────────────────────


@pytest.mark.parametrize(
    "codes, expected",
    [
        # Zamówienie MD/kosztowe z osobą nieznaną u klienta i bez żywej umowy.
        ([CODE_PERSON_DECISION_NEW], CATEGORY_AWAITING_CONTRACT),
        # Kandydat jest w bazie, ale nigdzie nie pracuje — umowa w podpisie.
        ([CODE_PERSON_KNOWN_ELSEWHERE_IDLE], CATEGORY_AWAITING_CONTRACT),
        (
            [CODE_PERSON_DECISION_NEW, CODE_PERSON_KNOWN_ELSEWHERE_IDLE],
            CATEGORY_AWAITING_CONTRACT,
        ),
        # Osoba z TRWAJĄCĄ współpracą u innego klienta to pytanie o zdublowany
        # rekord klienta, nie o podpis — decyduje człowiek.
        ([CODE_PERSON_KNOWN_ELSEWHERE_OPEN], CATEGORY_OTHER),
        ([CODE_PERSON_NAMESAKES], CATEGORY_OTHER),
        # Jeden dodatkowy powód przesuwa CAŁY dokument do „inny powód".
        (
            [CODE_PERSON_KNOWN_ELSEWHERE_IDLE, CODE_RATE_OUT_OF_BAND],
            CATEGORY_OTHER,
        ),
        # Wyłącznik automatu to stan konfiguracji, nie problem zamówienia.
        ([CODE_AUTOAPPLY_DISABLED], CATEGORY_CONFIG),
        ([CODE_AUTOAPPLY_EXCLUDED_CLIENT], CATEGORY_CONFIG),
        ([CODE_CLIENT_NOT_CONFIRMED], CATEGORY_OTHER),
        # Wpis sprzed wdrożenia kodów: nie wiemy, więc nie wyciszamy.
        ([], CATEGORY_OTHER),
        (None, CATEGORY_OTHER),
    ],
)
def test_classification_of_hold_reasons(codes, expected):
    assert classify_hold(codes) == expected


def test_document_without_a_client_is_its_own_category():
    """Nie rozpoznano klienta = nie ma komu wystawić karty (odbiorcą jest DL klienta)."""
    assert (
        classify_hold([CODE_CLIENT_NOT_CONFIRMED], client_known=False)
        == CATEGORY_UNRECOGNIZED
    )


# ── Licznik prób ────────────────────────────────────────────────────────────


def test_awaiting_contract_never_counts_an_attempt():
    meta = {"attempts": 2, "category": CATEGORY_OTHER}
    after = advance_attempts(meta, category=CATEGORY_AWAITING_CONTRACT, now=NOW)
    assert after["attempts"] == 0 and after["category"] == CATEGORY_AWAITING_CONTRACT


def test_attempts_grow_only_while_the_category_stays_the_same():
    meta = None
    for expected in (1, 2, 3, 4):
        meta = advance_attempts(meta, category=CATEGORY_OTHER, now=NOW)
        assert meta["attempts"] == expected
    # „Trzy próby Z RZĘDU": inny problem zaczyna liczenie od nowa.
    meta = advance_attempts(meta, category=CATEGORY_CONFIG, now=NOW)
    meta = advance_attempts(meta, category=CATEGORY_OTHER, now=NOW)
    assert meta["attempts"] == 1


# ── Kiedy Delivery Lead dostaje kartę ───────────────────────────────────────


def _alert(meta, *, waiting_hours=0.0):
    return should_alert(
        meta,
        waiting_since=NOW - timedelta(hours=waiting_hours),
        now=NOW,
        after_attempts=3,
        after_hours=6,
    )


def test_card_waits_for_the_third_consecutive_failure():
    assert not _alert({"category": CATEGORY_OTHER, "attempts": 1})
    assert not _alert({"category": CATEGORY_OTHER, "attempts": 2})
    assert _alert({"category": CATEGORY_OTHER, "attempts": 3})


def test_a_document_waiting_for_a_signature_never_alerts():
    assert not _alert({"category": CATEGORY_AWAITING_CONTRACT, "attempts": 0})
    assert not _alert(
        {"category": CATEGORY_AWAITING_CONTRACT, "attempts": 0}, waiting_hours=999
    )
    assert not _alert(
        {"category": CATEGORY_UNRECOGNIZED, "attempts": 0}, waiting_hours=999
    )


def test_turning_the_automation_off_does_not_silence_the_queue():
    """Wyłącznik gasi TYLKO zapis automatyczny — ręczne „Zastosuj" go nie czyta.

    Dokument, który stoi wyłącznie z tego powodu, zapisze więc WYŁĄCZNIE
    człowiek. Gdyby ta kategoria była cicha, przestawienie wyłącznika kasowałoby
    alarmowanie całej kolejki — i zamykało karty już wystawione.
    """
    assert not _alert({"category": CATEGORY_CONFIG, "attempts": 2})
    assert _alert({"category": CATEGORY_CONFIG, "attempts": 3})


def test_a_document_the_loop_never_saw_still_alerts_after_the_grace_hours():
    """Bezpiecznik: wyłączona albo zatrzymana pętla nie może uciszyć wszystkiego."""
    assert not _alert(None, waiting_hours=1)
    assert _alert(None, waiting_hours=7)
    assert not _alert(None, waiting_hours=0)


def test_a_loop_that_stopped_looking_still_lets_the_card_out():
    """Pętla, która ZOBACZYŁA wpis raz i zamilkła, zamrażała go na zawsze.

    ``attempts`` stało na 1, więc próg nigdy nie padał, a dobowy skaner — nie
    widząc dokumentu w ``live`` — zamykał nawet kartę wystawioną wcześniej.
    """
    fresh = {
        "category": CATEGORY_OTHER,
        "attempts": 1,
        "last_at": (NOW - timedelta(minutes=30)).isoformat(),
    }
    stale = {
        "category": CATEGORY_OTHER,
        "attempts": 1,
        "last_at": (NOW - timedelta(hours=20)).isoformat(),
    }
    assert not _alert(fresh, waiting_hours=48)
    assert _alert(stale, waiting_hours=48)
    # „Czeka na podpis" milczy nawet wtedy — to decyzja z ticketu.
    assert not _alert({**stale, "category": CATEGORY_AWAITING_CONTRACT}, waiting_hours=48)


# ── Orkiestracja na bazie ───────────────────────────────────────────────────

_STUB_POLICY = SimpleNamespace(
    key="stub",
    display_name="Stub",
    rule_version="v1",
    extract_rows=None,
    table_authoritative=False,
    reapply_on_refresh=False,
    open_ended_period=False,
    closes_on_md_exhaustion=False,
)


def _extraction(name: str, *, rate: str = "140.00") -> dict:
    return {
        "title": f"ZAM/{uuid.uuid4().hex[:6]}",
        "start_date": "2033-09-01",
        "end_date": "2033-11-30",
        "source": "claude",
        "uncertain": False,
        "confidence": {"title": 1.0},
        "consultant_rows": [
            {
                "consultant_name": name,
                "rate_client": rate,
                "rate_unit": "hour",
                "uncertain": False,
            }
        ],
    }


def _use_real_gate(monkeypatch, *, deterministic: bool = True):
    """Przeliczenie planu bez PDF-a, ale z PRAWDZIWYM resolverem, planerem i bramką.

    Dokładnie te trzy warstwy rozstrzygają, czy podpisanie umowy odblokowuje
    zamówienie — stub ma zdjąć z testu odczyt pliku, nie samą decyzję.
    """
    from app.services.order_pdf_parser import ConsultantOrderRow

    async def fake_refresh(db, row):
        extraction = ingest.restore_extraction(row.extraction)
        policy = SimpleNamespace(**vars(_STUB_POLICY))
        if deterministic:
            policy.extract_rows = lambda _text: [
                ConsultantOrderRow(
                    consultant_name=r.consultant_name,
                    rate_client=r.rate_client,
                    rate_unit=r.rate_unit,
                    uncertain=False,
                )
                for r in extraction.consultant_rows
            ]
        doc = OrderDocumentText("stub", 1, False, False, None, 0.0)
        await ingest._plan_and_gate(
            db,
            row,
            extraction,
            doc,
            [policy],
            row.client_id,
            row.identification_method,
        )
        row.error = None

    monkeypatch.setattr(ingest, "refresh_review_plan", fake_refresh)
    monkeypatch.setattr(ingest, "_replannable", lambda row: True)


async def _held_document(db, *, client, name, **fields):
    doc = OrderMailDocument(
        internet_message_id=f"<{uuid.uuid4()}@recheck.test>",
        attachment_name="zamowienie.pdf",
        storage_path=fields.pop("storage_path", "zamowienie.pdf"),
        client_id=client.id,
        identification_method=fields.pop("identification_method", "registry_id"),
        outcome="needs_review",
        gate_verdict="review",
        received_at=datetime.now(timezone.utc),
        extraction=_extraction(name),
        **fields,
    )

    db.add(doc)
    await db.commit()
    return doc


@pytest.mark.asyncio
async def test_signing_the_contract_unblocks_the_order_without_a_human(monkeypatch):
    """Sedno ticketu: wpis czeka na podpis, a po podpisaniu zapisuje się sam.

    Kandydat jest w bazie (rekrutacja w NEXUSIE), ale nie ma jeszcze umowy —
    bramka wstrzymuje wtedy zapis i prosi o potwierdzenie tożsamości. To jest
    kategoria „czeka na podpis": zero kart dla Delivery Leada, licznik prób
    stoi na zerze, a wpis wraca w każdym biegu.
    """
    _use_real_gate(monkeypatch)
    alerted = _notify_spy(monkeypatch)
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Recheck sign {uuid.uuid4().hex[:8]}")
        first, last = "Roman", "Podpisywany" + uuid.uuid4().hex[:6]
        candidate = Candidate(name=first, lastname=last)
        db.add_all([client, candidate])
        await db.flush()
        doc = await _held_document(db, client=client, name=f"{first} {last}")
        doc_id = doc.id

        for _ in range(4):
            await recheck.run_recheck(db)
        await db.refresh(doc)
        assert doc.outcome == "needs_review"
        meta = doc.document_meta["recheck"]
        assert meta["category"] == CATEGORY_AWAITING_CONTRACT
        assert meta["attempts"] == 0
        assert doc_id not in alerted

        # Umowa podpisana — kontrakt wchodzi na roster klienta.
        db.add(
            Contract(
                client_id=client.id,
                candidate_id=candidate.id,
                status=ContractStatus.active,
                start_date=date(2033, 8, 1),
                rate_candidate=Decimal("100"),
                rate_client=Decimal("140"),
                rate_unit=RateUnit.hourly,
            )
        )
        await db.commit()

        result = await recheck.run_recheck(db)
        entry = next(e for e in result.details if e["document_id"] == doc_id)
        assert entry["outcome"] == "applied", entry
        await db.refresh(doc)
        assert doc.outcome == "auto_applied"
        # Udany zapis kasuje ślad prób — kolejne wstrzymanie zaczyna od zera.
        assert "recheck" not in (doc.document_meta or {})
        assert doc_id not in alerted


@pytest.mark.asyncio
async def test_other_reason_alerts_the_delivery_lead_on_the_third_attempt(monkeypatch):
    _use_real_gate(monkeypatch)
    alerted = _notify_spy(monkeypatch)
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Recheck other {uuid.uuid4().hex[:8]}")
        db.add(client)
        await db.flush()
        # Klient niepotwierdzony numerem rejestrowym — powód spoza „czeka na podpis".
        doc = await _held_document(
            db,
            client=client,
            name="Nieznana Osoba" + uuid.uuid4().hex[:6],
            identification_method="marker",
        )
        doc_id = doc.id

        for expected in (1, 2):
            await recheck.run_recheck(db)
            await db.refresh(doc)
            assert doc.document_meta["recheck"]["attempts"] == expected
            assert doc_id not in alerted

        result = await recheck.run_recheck(db)
        await db.refresh(doc)
        assert doc.document_meta["recheck"]["category"] == CATEGORY_OTHER
        assert doc.document_meta["recheck"]["attempts"] == 3
        assert doc_id in alerted
        entry = next(e for e in result.details if e["document_id"] == doc_id)
        assert entry["alerted"] is True and entry["outcome"] == "held"


@pytest.mark.asyncio
async def test_history_row_matches_its_own_entries_and_is_pruned(monkeypatch):
    _use_real_gate(monkeypatch)
    monkeypatch.setattr(ingest, "notify_review", AsyncMock(return_value=0))
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Recheck history {uuid.uuid4().hex[:8]}")
        db.add(client)
        await db.flush()
        doc = await _held_document(
            db, client=client, name="Historia Testowa" + uuid.uuid4().hex[:6]
        )
        doc_id = doc.id
        stale = OrderMailRecheckRun(
            started_at=datetime.now(timezone.utc) - timedelta(days=400),
            finished_at=datetime.now(timezone.utc) - timedelta(days=400),
            trigger="scheduled",
        )
        db.add(stale)
        await db.commit()
        stale_id = stale.id

        result = await recheck.run_recheck(db, trigger="manual")
        assert result.checked == len(result.details)
        assert result.applied + result.held == result.checked

        run = (
            await db.execute(
                select(OrderMailRecheckRun)
                .order_by(OrderMailRecheckRun.id.desc())
                .limit(1)
            )
        ).scalar_one()
        assert run.trigger == "manual"
        assert run.checked == len(run.details)
        entry = next(e for e in run.details if e["document_id"] == doc_id)
        assert entry["client_id"] == client.id
        assert entry["client_name"] == client.name
        assert entry["outcome"] in ("applied", "held")
        # Retencja: bieg sprzed roku znika przy najbliższym biegu.
        assert await db.get(OrderMailRecheckRun, stale_id) is None


@pytest.mark.asyncio
async def test_unrecognized_client_is_retried_without_paying_for_the_model(
    monkeypatch, tmp_path
):
    """Wpis bez klienta ponawia SAMO rozpoznanie — model nie jest wołany.

    Odblokowuje się sam, gdy ktoś uzupełni NIP u klienta. ``process_pdf_bytes``
    czyta modelem PRZED sprawdzeniem klienta, więc ponowne wołanie jej płaciłoby
    za AI w każdym biegu — ta ścieżka istnieje właśnie po to, żeby tego uniknąć.
    """
    monkeypatch.setattr(
        ingest,
        "parse_order_document",
        AsyncMock(side_effect=AssertionError("ponowienie nie woła modelu")),
    )
    nip = _unique_nip()
    text = OrderDocumentText(f"NIP {nip} zamówienie", 1, False, False, None, 0.0)
    monkeypatch.setattr(recheck, "extract_order_text", lambda *a: text)
    monkeypatch.setattr(
        ingest.storage_service, "get_order_mail_attachment_path", lambda p: tmp_path / p
    )
    storage = tmp_path / f"unknown-{uuid.uuid4().hex[:6]}.pdf"
    storage.write_bytes(b"%PDF-1.4 dummy")
    async with AsyncSessionLocal() as db:
        doc = OrderMailDocument(
            internet_message_id=f"<{uuid.uuid4()}@recheck.test>",
            attachment_name=storage.name,
            storage_path=storage.name,
            outcome="unrecognized_client",
            received_at=datetime.now(timezone.utc),
            extraction=_extraction("Ktoś Tam"),
        )
        db.add(doc)
        await db.commit()
        doc_id = doc.id

        await recheck.run_recheck(db)
        await db.refresh(doc)
        assert doc.outcome == "unrecognized_client" and doc.client_id is None
        assert doc.document_meta["recheck"]["category"] == CATEGORY_UNRECOGNIZED
        assert doc.document_meta["recheck"]["attempts"] == 0

        # Ktoś uzupełnia NIP u klienta — wpis rozpoznaje się sam.
        client = Client(
            name=f"Recheck NIP {uuid.uuid4().hex[:8]}", nip=nip
        )
        db.add(client)
        await db.commit()
        _use_real_gate(monkeypatch)
        monkeypatch.setattr(ingest, "notify_review", AsyncMock(return_value=0))

        await recheck.run_recheck(db)
        await db.refresh(doc)
        assert doc.client_id == client.id
        assert doc.outcome in ("needs_review", "auto_applied")
        assert doc_id == doc.id


@pytest.mark.asyncio
async def test_a_run_never_looks_at_more_documents_than_its_budget(monkeypatch):
    """Sufit na bieg: każdy recheck to ekstrakcja tekstu, a skan idzie przez OCR."""
    monkeypatch.setattr(recheck.settings, "ORDER_MAIL_RECHECK_MAX_DOCS", 2)
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Recheck budget {uuid.uuid4().hex[:8]}")
        db.add(client)
        await db.flush()
        for _ in range(3):
            await _held_document(
                db, client=client, name="Budżet Testowy" + uuid.uuid4().hex[:6]
            )
        # Wprost o listę kandydatów: `result.checked <= 2` przechodzi też dla
        # zera, a przy wspólnej bazie testowej zero bywa prawdą z innego powodu.
        picked = await recheck._candidate_ids(db, now=datetime.now(timezone.utc))
        assert len(picked) == 2


@pytest.mark.asyncio
async def test_every_document_the_run_touches_leaves_a_timestamp(monkeypatch):
    """Rotacja `last_at NULLS FIRST` działa tylko wtedy, gdy KAŻDY wpis dostaje stempel.

    Wpis, którego nie da się przeliczyć (zniknął plik źródłowy), zjadał
    wcześniej budżet niewidzialnie: bez stempla wracał na czoło sortowania
    w każdym biegu, bez wiersza w historii i bez licznika prób. Sto takich
    wierszy zatrzymywało całą funkcję, a z ekranu nie dało się tego poznać.
    """
    monkeypatch.setattr(ingest, "notify_review", AsyncMock(return_value=0))
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Recheck no file {uuid.uuid4().hex[:8]}")
        db.add(client)
        await db.flush()
        doc = await _held_document(
            db,
            client=client,
            name="Bez Pliku" + uuid.uuid4().hex[:6],
            storage_path="order_mail/nie/ma/takiego/pliku.pdf",
        )
        doc_id = doc.id

        result = await recheck.run_recheck(db)
        entry = next(e for e in result.details if e["document_id"] == doc_id)
        assert entry["outcome"] == "held" and entry["reasons"]
        await db.refresh(doc)
        assert doc.document_meta["recheck"]["last_at"]
        assert doc.document_meta["recheck"]["attempts"] == 1

        # …i po trzech biegach Delivery Lead jednak się dowiaduje.
        await recheck.run_recheck(db)
        alerted = _notify_spy(monkeypatch)
        await recheck.run_recheck(db)
        await db.refresh(doc)
        assert doc.document_meta["recheck"]["attempts"] == 3
        assert doc_id in alerted


@pytest.mark.asyncio
async def test_the_switch_turns_the_whole_recheck_off(monkeypatch):
    monkeypatch.setattr(recheck.settings, "ORDER_MAIL_RECHECK_ENABLED", False)
    async with AsyncSessionLocal() as db:
        result = await recheck.run_recheck(db)
        assert (result.checked, result.details) == (0, [])


@pytest.mark.asyncio
async def test_a_failing_alert_does_not_undo_the_recheck(monkeypatch):
    """Padnięte powiadomienie gubi tylko powiadomienie.

    Bez savepointu i bez wcześniejszego ``flush`` błąd SQL w karcie dla
    Delivery Leada wycofałby CAŁE przeliczenie razem z licznikiem prób — wpis
    wracałby co godzinę na tę samą próbę i karta nie wyszłaby nigdy.
    """
    from sqlalchemy import text as sql_text

    _use_real_gate(monkeypatch)
    monkeypatch.setattr(recheck.settings, "ORDER_MAIL_RECHECK_ALERT_AFTER_ATTEMPTS", 1)

    async def failing_notify(db, row, **_kwargs):
        await db.execute(sql_text("SELECT * FROM order_mail_table_that_does_not_exist"))

    monkeypatch.setattr(ingest, "notify_review", failing_notify)
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Recheck alert fail {uuid.uuid4().hex[:8]}")
        db.add(client)
        await db.flush()
        doc = await _held_document(
            db,
            client=client,
            name="Alert Padnięty" + uuid.uuid4().hex[:6],
            identification_method="marker",
        )
        doc_id = doc.id

        result = await recheck.run_recheck(db)
        entry = next(e for e in result.details if e["document_id"] == doc_id)
        assert entry["outcome"] == "held" and entry["alerted"] is False
        await db.refresh(doc)
        assert doc.document_meta["recheck"]["attempts"] == 1
        assert "alerted_at" not in doc.document_meta["recheck"]
        # Sesja nadaje się do dalszej pracy — inaczej zapis biegu by padł.
        assert (await db.execute(sql_text("SELECT 1"))).scalar() == 1
