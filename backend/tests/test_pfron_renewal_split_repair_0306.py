"""Migracja 0306: PFRON 507–509 — rozdzielenie zamówienia nadpisanego „reaktywacją”.

Blok SQL jest WYKONYWANY na bazie testowej (literówka w nazwie kolumny wyszłaby
dopiero na produkcji, a entrypoint połknąłby ją przez ``|| echo skipped``).
Test buduje dokładnie scenariusz z nocy 9/10.09.2026 — zamówienie przepisane
w miejscu nowym okresem, Activity ``order_mail_reactivate`` z ``before``,
dokument z maila, wiersze potomne sprzed i po nadpisaniu — na własnych id
i własnym markerze (``build_renewal_split_sql``), więc nie koliduje z id
produkcyjnymi ani z markerem, który zakłada ``alembic upgrade heads``.

Druga połowa pliku to przypadki z przeglądu adwersarialnego (10.09.2026):
każdy opisuje stan produkcji, w którym korekta NIE może nic zapisać.
Wszystkie osoby i kwoty są zmyślone.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from app.core.database import AsyncSessionLocal
from app.services.pfron_renewal_split_repair import (
    DEFAULT_LOCK_TIMEOUT,
    HANDLED_FOREIGN_KEYS,
    HUMAN_EDIT_ACTIONS_ON_CLIENT,
    HUMAN_EDIT_ACTIONS_ON_ORDER,
    INCIDENT_WINDOW,
    NEW_PERIOD_END,
    NEW_PERIOD_START,
    PFRON_RENEWAL_SPLIT_MARKER,
    PFRON_RENEWAL_SPLIT_SQL,
    PREVIOUS_PERIOD_END,
    REVENUE_RESYNC_NOT_APPLICABLE,
    REVENUE_RESYNC_PENDING,
    SplitTarget,
    build_renewal_split_sql,
    summarize_receipt_for_log,
)
from app.services.startup_locks import is_lock_timeout

BACKEND = Path(__file__).resolve().parents[1]
MIGRATION = BACKEND / "alembic/versions/0306_pfron_renewal_split_repair.py"
ENTRYPOINT = BACKEND / "entrypoint.sh"
ORDER_API = BACKEND / "app/api/client_orders.py"

T0 = datetime(2026, 9, 9, 22, 7, 13, tzinfo=timezone.utc)
AFTER = datetime(2026, 9, 10, 8, 0, tzinfo=timezone.utc)
MESSAGE = "Powrót po 1 dniach od zakończenia poprzedniego zamówienia"


def _heredoc_opening(tolerated_echo: str) -> str:
    return f"python - <<'PY' || echo \"{tolerated_echo}\"\n"


def _entrypoint_python_block(source: str, tolerated_echo: str) -> str:
    """Treść heredoca ``python - <<'PY' || echo "<tolerated_echo>"``."""
    opening = _heredoc_opening(tolerated_echo)
    assert opening in source, tolerated_echo
    return source.split(opening, 1)[1].split("\nPY\n", 1)[0]


def test_0306_chains_after_0305_and_uses_the_single_sql_source():
    source = MIGRATION.read_text(encoding="utf-8")
    assert 'revision = "0306_pfron_renewal_split_repair"' in source
    assert 'down_revision = "0305_candidate_search_retention_indexes"' in source
    assert "PFRON_RENEWAL_SPLIT_SQL" in source
    entrypoint = ENTRYPOINT.read_text(encoding="utf-8")
    assert "from app.services.pfron_renewal_split_repair import" in entrypoint
    assert 'echo "pfron renewal split repair skipped; continuing"' in entrypoint


def test_production_block_pins_full_business_identity():
    sql = PFRON_RENEWAL_SPLIT_SQL
    for value in (
        "(507, 399, 20), (508, 398, 19), (509, 397, 18)",
        "v_client_id CONSTANT INTEGER := 122",
        "DATE '2026-09-01'",
        "DATE '2026-11-30'",
        "DATE '2026-08-31'",
        "action = 'order_mail_reactivate'",
        "v_order.status::text <> 'active'",
        "pg_advisory_xact_lock(hashtext(v_marker))",
        f"'{PFRON_RENEWAL_SPLIT_MARKER}'",
        "FOR UPDATE",
        # Czekanie na blokady ograniczone i ustawione PRZED pierwszą blokadą.
        f"set_config('lock_timeout', '{DEFAULT_LOCK_TIMEOUT}', true)",
        # Ta sama blokada, od której zaczyna writer maila.
        "PERFORM 1 FROM clients WHERE id = v_client_id FOR UPDATE",
    ):
        assert value in sql, value
    assert DEFAULT_LOCK_TIMEOUT == "15s"
    assert sql.index("set_config('lock_timeout'") < sql.index("pg_advisory_xact_lock")
    assert sql.index("pg_advisory_xact_lock") < sql.index(
        "PERFORM 1 FROM clients WHERE id = v_client_id FOR UPDATE"
    )


def test_block_has_no_accidental_bind_parameters():
    """``text()`` czyta ``:słowo`` jako parametr — blok musi go nie mieć.

    Godzina w literale („22:07”) albo klucz „order:507” poza apostrofami
    zamieniłyby wykonanie migracji w „A value is required for bind parameter”.
    """
    assert text(PFRON_RENEWAL_SPLIT_SQL).compile().params == {}


def test_lock_timeout_is_validated_because_it_lands_in_a_sql_literal():
    kwargs = dict(
        marker="m",
        client_id=1,
        targets=[SplitTarget(1, 1, 1)],
        new_start=NEW_PERIOD_START,
        new_end=NEW_PERIOD_END,
        previous_end=PREVIOUS_PERIOD_END,
        incident_window=INCIDENT_WINDOW,
    )
    assert "'250ms'" in build_renewal_split_sql(**kwargs, lock_timeout="250ms")
    for bad in ("", "0s", "15", "15 s", "15s'; DROP TABLE x; --", "1min"):
        with pytest.raises(ValueError):
            build_renewal_split_sql(**kwargs, lock_timeout=bad)


def test_every_order_that_can_be_skipped_is_left_untouched_by_construction():
    """Każde odrzucenie kończy się ``CONTINUE`` przed pierwszym zapisem."""
    sql = PFRON_RENEWAL_SPLIT_SQL
    first_write = sql.index("INSERT INTO client_orders")
    skip = sql.index("CONTINUE;")
    assert skip < first_write
    # Wszystkie powody odrzucenia są zapisywane w paragonie, nie w logu.
    for reason in (
        "order_missing",
        "state_changed",
        "reactivate_activity_mismatch",
        "edited_after_incident",
        "document_not_applied_to_order",
        "document_plan_mismatch",
        "title_differs_from_mail_plan",
        "rate_unit_differs_from_mail_plan",
        "another_order_covers_new_period",
        "another_order_covers_previous_period",
        "rate_unit_change_suspected",
        "rate_unit_unverifiable",
        "unknown_foreign_key_reference",
    ):
        assert f"'{reason}'" in sql, reason


def test_human_edit_actions_are_the_ones_the_order_api_writes():
    """Przemianowanie akcji w API po cichu wyłączyłoby blokadę ręcznych edycji."""
    source = ORDER_API.read_text(encoding="utf-8")
    for action in HUMAN_EDIT_ACTIONS_ON_CLIENT + HUMAN_EDIT_ACTIONS_ON_ORDER:
        assert f'action="{action}"' in source, action
    # PATCH, PDF i anulowanie piszą Activity KLIENTA z ``details.order_id``,
    # zakończenie — Activity zamówienia; blok szuka ich dokładnie tam.
    for action in HUMAN_EDIT_ACTIONS_ON_CLIENT:
        block = source.split(f'action="{action}"', 1)[0].rsplit("Activity(", 1)[1]
        assert 'entity_type="client"' in block, action
    for action in HUMAN_EDIT_ACTIONS_ON_ORDER:
        block = source.split(f'action="{action}"', 1)[0].rsplit("Activity(", 1)[1]
        assert 'entity_type="client_order"' in block, action


def test_entrypoint_logs_only_counts_and_reasons_then_runs_the_revenue_step():
    """Log kontenera idzie do Grafany — paragon (tytuły, stawki, ścieżki) nie."""
    source = ENTRYPOINT.read_text(encoding="utf-8")
    split_block = _entrypoint_python_block(
        source, "pfron renewal split repair skipped; continuing"
    )
    resync_block = _entrypoint_python_block(
        source, "pfron revenue resync skipped; continuing"
    )
    compile(split_block, "pfron-split-entrypoint", "exec")
    compile(resync_block, "pfron-resync-entrypoint", "exec")
    assert "summarize_receipt_for_log(" in split_block
    assert "{receipt}" not in split_block
    assert "run_pfron_revenue_resync(db)" in resync_block
    assert "summarize_for_log(summary)" in resync_block
    assert "await db.commit()" in resync_block
    for block in (split_block, resync_block):
        # Błąd bez treści (DETAIL potrafi zacytować wiersz), start idzie dalej.
        assert "except Exception as exc" in block
        assert "{exc" not in block
        assert "sys.exit(1)" in block
    # Krok przychodu jest NASTĘPNYM blokiem Pythona po korekcie.
    between = source.split(split_block, 1)[1].split(
        _heredoc_opening("pfron revenue resync skipped; continuing"), 1
    )[0]
    assert "python" not in between


def test_receipt_log_line_carries_counts_and_reasons_only():
    receipt = {
        "split": 1,
        "skipped": 2,
        "orders": [
            {
                "status": "split",
                "order_id": 7,
                "restored_order": {
                    "title": "ZMYSLONE/2026/1",
                    "rate_client": 85.0,
                    "file_path": "client_orders/7/abcd-stare.pdf",
                },
            },
            {"status": "skipped", "reason": "edited_after_incident"},
            {"status": "skipped", "reason": "edited_after_incident"},
        ],
    }
    assert summarize_receipt_for_log(receipt) == (
        "split=1 skipped=2 skip_reasons=edited_after_incident:2"
    )
    assert summarize_receipt_for_log({"split": 3, "skipped": 0, "orders": []}) == (
        "split=3 skipped=0"
    )
    assert summarize_receipt_for_log(None) == "no receipt"


@pytest.mark.asyncio
async def test_handled_foreign_keys_match_the_live_catalog():
    """Nowy klucz obcy do ``client_orders`` wymaga decyzji w tej korekcie.

    Blok i tak zatrzymuje zamówienie wskazywane przez nieznany klucz, ale
    ciche zatrzymanie trzech zamówień PFRON na produkcji byłoby gorsze niż
    czerwony test tutaj.
    """
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                text(
                    "SELECT c.conrelid::regclass::text, a.attname "
                    "FROM pg_constraint c JOIN pg_attribute a "
                    "ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1] "
                    "WHERE c.contype = 'f' "
                    "AND c.confrelid = 'client_orders'::regclass"
                )
            )
        ).all()
    live = {(t, c) for t, c in rows}
    assert live == set(HANDLED_FOREIGN_KEYS), (
        "Klucze obce do client_orders rozjechały się z HANDLED_FOREIGN_KEYS w "
        "app/services/pfron_renewal_split_repair.py: "
        f"nowe={sorted(live - set(HANDLED_FOREIGN_KEYS))}, "
        f"zniknęły={sorted(set(HANDLED_FOREIGN_KEYS) - live)}. "
        "Jeśli korekta 0306 JESZCZE NIE przeszła na produkcji "
        "(brak app_settings['0306_pfron_renewal_split_repair']): zdecyduj, co "
        "blok ma zrobić z wierszami nowego klucza — przenieść je za nowym "
        "okresem (osobny UPDATE jak dla dl_alerts) albo tylko zatrzymać "
        "zamówienie — i dopisz klucz do HANDLED_FOREIGN_KEYS. Jeśli paragon "
        "na produkcji potwierdza, że korekta już przeszła: nowy klucz jest dla "
        "niej bez znaczenia — dopisz go do HANDLED_FOREIGN_KEYS albo usuń ten "
        "test razem z blokiem."
    )


# ── Scenariusz wykonany na bazie ─────────────────────────────────────────────


async def _seed_target(db, *, tag, client, dl_user, spec):
    """Kontrakt + zamówienie w stanie PO nadpisaniu + Activity + dokument z maila."""
    from app.models.activity import Activity
    from app.models.candidate import Candidate
    from app.models.client_order import ClientOrder, ClientOrderStatus
    from app.models.contract import Contract, ContractStatus, ContractType, RateUnit
    from app.models.contract_candidate_rate import ContractCandidateRate
    from app.models.order_mail import OrderMailDocument

    candidate = Candidate(
        name="Anna",
        lastname=f"Pfron{spec['key']}{tag}",
        email=f"{spec['key']}-{tag}@t.test",
    )
    db.add(candidate)
    await db.flush()
    contract = Contract(
        candidate_id=candidate.id,
        client_id=client.id,
        contract_type=ContractType.b2b,
        status=ContractStatus.active,
        start_date=date(2025, 1, 1),
        rate_candidate=Decimal("60"),
        rate_unit=RateUnit.hourly,
        billing_hours_per_month=160,
    )
    db.add(contract)
    await db.flush()
    db.add_all(
        [
            ContractCandidateRate(
                contract_id=contract.id,
                rate=Decimal("55.000"),
                effective_from=date(2026, 1, 1),
            ),
            ContractCandidateRate(
                contract_id=contract.id,
                rate=Decimal("60.000"),
                effective_from=date(2026, 9, 1),
            ),
        ]
    )
    order = ClientOrder(
        client_id=client.id,
        contract_id=contract.id,
        title=spec["new_title"],
        status=ClientOrderStatus.active,
        order_type="periodic",
        start_date=spec.get("start", NEW_PERIOD_START),
        end_date=spec.get("end", NEW_PERIOD_END),
        rate_client=spec["rate_client"],
        rate_candidate=Decimal("60.000"),
        rate_unit=RateUnit.hourly,
        billing_hours_per_month=168,
        rate_client_currency="PLN",
        rate_candidate_currency="PLN",
        total_value=Decimal("12345.000"),
        description="Opis tej samej współpracy",
        notes=spec["notes"],
        filled_at=spec["filled_at"],
        filename="nowe.pdf",
        file_path=None,
        content_type="application/pdf",
        size_bytes=1000,
        file_uploaded_at=T0 + timedelta(seconds=2),
        created_at=datetime(2026, 5, 20, 9, 0, tzinfo=timezone.utc),
    )
    db.add(order)
    await db.flush()
    order.file_path = f"client_orders/{order.id}/abcd1234-nowe.pdf"
    before_file = spec["before_file"](order.id)
    reactivate = Activity(
        entity_type="client_order",
        entity_id=order.id,
        action="order_mail_reactivate",
        user_id=None,
        details={
            "document_id": None,  # uzupełnione po zapisie dokumentu
            "before": {
                "title": spec["old_title"],
                "start_date": spec["before_start"],
                "end_date": str(PREVIOUS_PERIOD_END),
                "rate_client": spec["before_rate"],
                "file_path": before_file,
                **spec.get("before_extra", {}),
            },
            "message": MESSAGE,
        },
        created_at=T0,
    )
    db.add(reactivate)
    doc = OrderMailDocument(
        internet_message_id=f"<{uuid.uuid4()}@pfron.test>",
        client_id=client.id,
        outcome="auto_applied",
        gate_verdict="auto",
        applied_order_id=order.id,
        applied_at=T0 + timedelta(seconds=5),
        created_at=datetime(2026, 9, 5, 8, 0, tzinfo=timezone.utc),
        proposal={
            "rows": [
                {
                    "row_index": 0,
                    "action": spec.get("plan_action", "reactivate"),
                    "target_order_id": order.id,
                    "title": spec["new_title"],
                    "start_date": str(NEW_PERIOD_START),
                    "end_date": str(NEW_PERIOD_END),
                    "total_value": spec.get("plan_total"),
                }
            ],
            "apply_result": {
                "error": None,
                "rows": [
                    {
                        "row_index": 0,
                        "action": "reactivate",
                        "order_id": order.id,
                        "activated": True,
                        "contract_revived": False,
                        "error": None,
                    }
                ],
            },
        },
    )
    db.add(doc)
    await db.flush()
    reactivate.details = {**reactivate.details, "document_id": doc.id}
    await db.flush()
    return {
        "candidate_id": candidate.id,
        "contract_id": contract.id,
        "order_id": order.id,
        "document_id": doc.id,
        "reactivate_id": reactivate.id,
        "before_file": before_file,
    }


async def _order_row(db, order_id):
    return (
        (
            await db.execute(
                text("SELECT * FROM client_orders WHERE id = :i"), {"i": order_id}
            )
        )
        .mappings()
        .one()
    )


@pytest.mark.asyncio
async def test_repair_splits_overwritten_orders_and_is_idempotent():
    from app.core.security import hash_password
    from app.models.activity import Activity
    from app.models.client import Client
    from app.models.client_order import ClientOrder, ClientOrderStatus
    from app.models.contract_client_rate import ContractClientRate
    from app.models.dl_alert import DlAlert
    from app.models.md_consumption import ClientOrderMdConsumption
    from app.models.notification import Notification, NotificationType
    from app.models.order_mail import OrderMailDocument
    from app.models.user import User, UserRole

    tag = uuid.uuid4().hex[:8]
    marker = f"test_0306_{tag}"
    async with AsyncSessionLocal() as db:
        client = Client(name=f"PFRON test {tag}")
        dl_user = User(
            email=f"pfron-dl-{tag}@example.test",
            password_hash=hash_password("x"),
            name=f"DL {tag}",
            role=UserRole.delivery_lead,
            is_active=True,
        )
        db.add_all([client, dl_user])
        await db.flush()
        specs = {
            # Pełny przypadek: stare notatki, stary PDF, start i stawka w `before`,
            # pierwsza aktywacja wystemplowana przez nadpisanie.
            "a": dict(
                key="a",
                new_title="PFRON/2026/NOWE-A",
                old_title="PFRON/2026/STARE-A",
                rate_client=Decimal("81.370"),
                before_rate="85.000",
                before_start="2026-06-01",
                notes="Notatka starej umowy\n" + MESSAGE,
                filled_at=T0 + timedelta(seconds=3),
                before_file=lambda oid: (
                    f"client_orders/{oid}/deadbeef-stare_zamowienie.pdf"
                ),
            ),
            # Brak startu i PDF-u w `before`, notatki = sam dopisek, aktywacja
            # sprzed nadpisania, wartość nowego okresu w planie dokumentu.
            "b": dict(
                key="b",
                new_title="PFRON/2026/NOWE-B",
                old_title="PFRON/2026/STARE-B",
                rate_client=Decimal("160.000"),
                before_rate="150.000",
                before_start="None",
                notes=MESSAGE,
                filled_at=datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc),
                before_file=lambda oid: None,
                plan_total="25000.00",
            ),
            # Ktoś już poprawił okres — blok nie może zgadywać.
            "c": dict(
                key="c",
                new_title="PFRON/2026/NOWE-C",
                old_title="PFRON/2026/STARE-C",
                rate_client=Decimal("81.370"),
                before_rate="85.000",
                before_start="2026-06-01",
                notes=MESSAGE,
                filled_at=T0 + timedelta(seconds=3),
                before_file=lambda oid: None,
                end=date(2026, 12, 31),
            ),
            # Stawka sprzed nadpisania to kwota miesięczna — jednostka się zmieniła.
            "d": dict(
                key="d",
                new_title="PFRON/2026/NOWE-D",
                old_title="PFRON/2026/STARE-D",
                rate_client=Decimal("81.370"),
                before_rate="13600.000",
                before_start="2026-06-01",
                notes=MESSAGE,
                filled_at=T0 + timedelta(seconds=3),
                before_file=lambda oid: None,
            ),
            # Stary okres ktoś już odtworzył ręcznie po nadpisaniu.
            "e": dict(
                key="e",
                new_title="PFRON/2026/NOWE-E",
                old_title="PFRON/2026/STARE-E",
                rate_client=Decimal("81.370"),
                before_rate="85.000",
                before_start="2026-06-01",
                notes=MESSAGE,
                filled_at=T0 + timedelta(seconds=3),
                before_file=lambda oid: None,
            ),
            # PDF podmieniony w aplikacji po nadpisaniu — ręczna edycja po T0.
            "f": dict(
                key="f",
                new_title="PFRON/2026/NOWE-F",
                old_title="PFRON/2026/STARE-F",
                rate_client=Decimal("81.370"),
                before_rate="85.000",
                before_start="2026-06-01",
                notes=MESSAGE,
                filled_at=T0 + timedelta(seconds=3),
                before_file=lambda oid: f"client_orders/{oid}/cafebabe-stare.pdf",
            ),
            # Bez bieżącej stawki nie ma czym sprawdzić jednostki.
            "g": dict(
                key="g",
                new_title="PFRON/2026/NOWE-G",
                old_title="PFRON/2026/STARE-G",
                rate_client=None,
                before_rate="85.000",
                before_start="2026-06-01",
                notes=MESSAGE,
                filled_at=T0 + timedelta(seconds=3),
                before_file=lambda oid: None,
            ),
            # Plan dokumentu nie jest powrotem po przerwie z tego zamówienia.
            "h": dict(
                key="h",
                new_title="PFRON/2026/NOWE-H",
                old_title="PFRON/2026/STARE-H",
                rate_client=Decimal("81.370"),
                before_rate="85.000",
                before_start="2026-06-01",
                notes=MESSAGE,
                filled_at=T0 + timedelta(seconds=3),
                before_file=lambda oid: None,
                plan_action="new",
            ),
            # `before` niesie też metadane pliku — wracają razem ze ścieżką.
            "i": dict(
                key="i",
                new_title="PFRON/2026/NOWE-I",
                old_title="PFRON/2026/STARE-I",
                rate_client=Decimal("81.370"),
                before_rate="85.000",
                before_start="2026-06-01",
                notes=MESSAGE,
                filled_at=T0 + timedelta(seconds=3),
                before_file=lambda oid: f"client_orders/{oid}/0badf00d-stare_i.pdf",
                before_extra={
                    "filename": "Zamowienie czerwiec.pdf",
                    "content_type": "application/pdf",
                    "size_bytes": 2048,
                    "file_uploaded_by": dl_user.id,
                    "file_uploaded_at": "2026-06-02 09:30:00+00:00",
                },
            ),
        }
        seeded = {
            key: await _seed_target(
                db, tag=tag, client=client, dl_user=dl_user, spec=spec
            )
            for key, spec in specs.items()
        }
        a = seeded["a"]
        before = datetime(2026, 8, 10, 8, 0, tzinfo=timezone.utc)
        stale_message_id = f"<{uuid.uuid4()}@pfron.test>"
        # A: poprzednik z linii MD (zamiana kontraktora) — nie przedłużenie.
        predecessor = ClientOrder(
            client_id=client.id,
            contract_id=a["contract_id"],
            title="PFRON/2025/POPRZEDNIE-A",
            status=ClientOrderStatus.completed,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31),
            created_at=datetime(2025, 1, 1, 8, 0, tzinfo=timezone.utc),
        )
        db.add(predecessor)
        await db.flush()
        await db.execute(
            text("UPDATE client_orders SET predecessor_order_id = :p WHERE id = :o"),
            {"p": predecessor.id, "o": a["order_id"]},
        )
        alert_old = DlAlert(
            alert_type="missing_revenue_rate",
            user_id=dl_user.id,
            client_id=client.id,
            order_id=a["order_id"],
            title="stary okres",
            message="stary okres",
            dedupe_key=f"missing_revenue_rate:order:{a['order_id']}:{dl_user.id}:0",
            created_at=before,
        )
        alert_new = DlAlert(
            alert_type="missing_revenue_rate",
            user_id=dl_user.id,
            client_id=client.id,
            order_id=a["order_id"],
            title="nowy okres",
            message="nowy okres",
            dedupe_key=f"missing_revenue_rate:order:{a['order_id']}:{dl_user.id}:1",
            created_at=AFTER,
        )
        notification_new = Notification(
            user_id=dl_user.id,
            title="Zamówienie kończy się za 7 dni",
            message="kończy się 2026-11-30.",
            notification_type=NotificationType.client_order_ending_7d,
            related_entity_type="client_order",
            related_entity_id=a["order_id"],
            created_at=AFTER,
        )
        note_after = Activity(
            entity_type="client_order",
            entity_id=a["order_id"],
            action="order_note",
            details={"note": "po nadpisaniu"},
            created_at=AFTER,
        )
        viewed_after = Activity(
            entity_type="client",
            entity_id=client.id,
            action="order_viewed",
            details={"order_id": a["order_id"]},
            created_at=AFTER,
        )
        step_after = ContractClientRate(
            contract_id=a["contract_id"],
            rate=Decimal("81.370"),
            effective_from=NEW_PERIOD_START,
            source_order_id=a["order_id"],
            created_at=AFTER,
        )
        september = ClientOrderMdConsumption(
            order_id=a["order_id"],
            period_month="2026-09",
            md_reported=Decimal("3"),
            source="manual",
            created_at=AFTER,
        )
        db.add_all(
            [
                alert_old,
                alert_new,
                Notification(
                    user_id=dl_user.id,
                    title="Zamówienie kończy się za 30 dni",
                    message="kończy się 2026-08-31.",
                    notification_type=NotificationType.client_order_ending_30d,
                    related_entity_type="client_order",
                    related_entity_id=a["order_id"],
                    created_at=datetime(2026, 8, 1, 8, 0, tzinfo=timezone.utc),
                ),
                notification_new,
                Activity(
                    entity_type="client_order",
                    entity_id=a["order_id"],
                    action="created",
                    details={},
                    created_at=datetime(2026, 5, 20, 9, 0, tzinfo=timezone.utc),
                ),
                note_after,
                viewed_after,
                # F: nowy PDF wgrany w aplikacji po nadpisaniu.
                Activity(
                    entity_type="client",
                    entity_id=client.id,
                    action="order_file_uploaded",
                    user_id=dl_user.id,
                    details={
                        "order_id": seeded["f"]["order_id"],
                        "filename": "poprawiony.pdf",
                        "replaced": True,
                    },
                    created_at=AFTER,
                ),
                # E: stary okres odtworzony ręcznie po nadpisaniu.
                ClientOrder(
                    client_id=client.id,
                    contract_id=seeded["e"]["contract_id"],
                    title="PFRON/2026/STARE-E (ręcznie)",
                    status=ClientOrderStatus.completed,
                    start_date=date(2026, 6, 1),
                    end_date=PREVIOUS_PERIOD_END,
                    created_at=AFTER,
                ),
                # A: inny dokument z tego samego biegu, który zapisał zamówienie
                # jeszcze w STARYM stanie („bez zmian”) — nie wolno go przepiąć.
                OrderMailDocument(
                    internet_message_id=stale_message_id,
                    client_id=client.id,
                    outcome="auto_applied",
                    gate_verdict="auto",
                    applied_order_id=a["order_id"],
                    applied_at=T0 + timedelta(seconds=1),
                    created_at=datetime(2026, 8, 20, 8, 0, tzinfo=timezone.utc),
                    proposal={
                        "rows": [
                            {
                                "row_index": 0,
                                "action": "unchanged",
                                "target_order_id": a["order_id"],
                                "start_date": "2026-06-01",
                            }
                        ],
                        "apply_result": {
                            "error": None,
                            "rows": [
                                {
                                    "row_index": 0,
                                    "action": "unchanged",
                                    "order_id": a["order_id"],
                                }
                            ],
                        },
                    },
                ),
                step_after,
                september,
                ClientOrderMdConsumption(
                    order_id=a["order_id"],
                    period_month="2026-08",
                    md_reported=Decimal("5"),
                    source="manual",
                    created_at=AFTER,
                ),
            ]
        )
        await db.flush()
        moved_ids_expected = {
            "order_mail_documents": [a["document_id"]],
            "activities_client_order": [note_after.id],
            "activities_client_details": [viewed_after.id],
            "notifications": [notification_new.id],
            "dl_alerts": [alert_new.id],
            "contract_client_rates": [step_after.id],
            "client_order_md_consumptions": [september.id],
            "client_order_invoice_consumptions": [],
            "md_consumption_import_rows": [],
            "client_order_offboarding_cases": [],
            "client_order_offboarding_targets": [],
            "client_order_group_events": [],
            "client_orders_predecessor": [],
        }
        predecessor_id = predecessor.id
        await db.commit()
        client_id, dl_id = client.id, dl_user.id

    contract_ids = [s["contract_id"] for s in seeded.values()]
    targets = [
        SplitTarget(s["order_id"], s["contract_id"], s["document_id"])
        for s in seeded.values()
    ]
    sql = build_renewal_split_sql(
        marker=marker,
        client_id=client_id,
        targets=targets,
        new_start=NEW_PERIOD_START,
        new_end=NEW_PERIOD_END,
        previous_end=PREVIOUS_PERIOD_END,
        incident_window=INCIDENT_WINDOW,
    )
    skipped = {
        "c": "state_changed",
        "d": "rate_unit_change_suspected",
        "e": "another_order_covers_previous_period",
        "f": "edited_after_incident",
        "g": "rate_unit_unverifiable",
        "h": "document_plan_mismatch",
    }
    try:
        async with AsyncSessionLocal() as db:
            untouched_before = {
                key: dict(await _order_row(db, seeded[key]["order_id"]))
                for key in skipped
            }
            original_a_before = dict(await _order_row(db, a["order_id"]))
            await db.execute(text(sql))
            await db.commit()

        async with AsyncSessionLocal() as db:
            receipt = json.loads(
                await db.scalar(
                    text("SELECT value::text FROM app_settings WHERE key = :k"),
                    {"k": marker},
                )
            )
            assert (receipt["split"], receipt["skipped"]) == (3, 6)
            by_order = {r["order_id"]: r for r in receipt["orders"]}
            for key, reason in skipped.items():
                assert by_order[seeded[key]["order_id"]]["reason"] == reason, key
            assert {
                (fk["table"], fk["column"])
                for fk in receipt["foreign_keys_to_client_orders"]
            } == set(HANDLED_FOREIGN_KEYS)
            assert summarize_receipt_for_log(receipt) == (
                "split=3 skipped=6 skip_reasons="
                "another_order_covers_previous_period:1,document_plan_mismatch:1,"
                "edited_after_incident:1,rate_unit_change_suspected:1,"
                "rate_unit_unverifiable:1,state_changed:1"
            )

            # ── F: ręczna edycja po T0 w paragonie, z tym, co zmieniono ──────
            edits = by_order[seeded["f"]["order_id"]]["detail"]
            assert [(e["action"], e["user_id"]) for e in edits] == [
                ("order_file_uploaded", dl_id)
            ]
            assert edits[0]["changed"] is None
            assert datetime.fromisoformat(edits[0]["created_at"]) == AFTER

            # ── A: oryginał przywrócony, nowy okres w nowym wierszu ──────────
            new_a = by_order[a["order_id"]]["new_order_id"]
            original = await _order_row(db, a["order_id"])
            assert original["status"] == "completed"
            assert original["title"] == "PFRON/2026/STARE-A"
            assert (original["start_date"], original["end_date"]) == (
                date(2026, 6, 1),
                PREVIOUS_PERIOD_END,
            )
            assert original["rate_client"] == Decimal("85.000")
            # Koszt z harmonogramu umowy na 31.08 (krok 55 od 01.01, nie 60 od 01.09).
            assert original["rate_candidate"] == Decimal("55.000")
            assert original["notes"] == "Notatka starej umowy"
            assert original["filled_at"] is None
            assert original["file_path"] == a["before_file"]
            assert original["filename"] == "stare_zamowienie.pdf"
            assert original["content_type"] == "application/pdf"
            assert original["size_bytes"] is None
            assert original["file_uploaded_at"] is None
            # Wartość całkowita zostaje przy zamówieniu, którego dotyczyła.
            assert original["total_value"] == Decimal("12345.000")
            assert original["predecessor_order_id"] == predecessor_id

            renewal = await _order_row(db, new_a)
            assert renewal["status"] == "active"
            assert renewal["contract_id"] == a["contract_id"]
            assert renewal["client_id"] == client_id
            assert renewal["title"] == "PFRON/2026/NOWE-A"
            assert (renewal["start_date"], renewal["end_date"]) == (
                NEW_PERIOD_START,
                NEW_PERIOD_END,
            )
            assert renewal["rate_client"] == Decimal("81.370")
            assert renewal["rate_candidate"] == Decimal("60.000")
            assert renewal["rate_unit"] == "hourly"
            assert renewal["billing_hours_per_month"] == 168
            assert renewal["description"] == "Opis tej samej współpracy"
            assert renewal["order_type"] == "periodic"
            assert (
                renewal["notes"] == f"Zamówienie z maila (dokument #{a['document_id']})"
            )
            assert renewal["total_value"] is None  # plan dokumentu nie miał wartości
            assert (
                renewal["file_path"]
                == f"client_orders/{a['order_id']}/abcd1234-nowe.pdf"
            )
            assert renewal["filename"] == "nowe.pdf"
            assert renewal["created_at"] == T0
            assert renewal["created_by_user_id"] is None
            assert renewal["filled_at"] == T0 + timedelta(seconds=3)
            # Przedłużenie, nie zamiana kontraktora: bez poprzednika z kopii.
            assert renewal["predecessor_order_id"] is None

            doc = await db.get(OrderMailDocument, a["document_id"])
            assert doc.applied_order_id == new_a
            assert doc.proposal["apply_result"]["rows"][0]["order_id"] == new_a
            # Plan nadal wskazuje poprzednika jako cel „powrotu po przerwie”.
            assert doc.proposal["rows"][0]["target_order_id"] == a["order_id"]
            # Dokument z tego samego biegu, który zapisał STARY stan, zostaje
            # przy oryginale i trafia do przeglądu — nie zgadujemy okresu.
            stale_doc = await db.scalar(
                select(OrderMailDocument).where(
                    OrderMailDocument.internet_message_id == stale_message_id
                )
            )
            assert stale_doc.applied_order_id == a["order_id"]
            assert (
                stale_doc.proposal["apply_result"]["rows"][0]["order_id"]
                == (a["order_id"])
            )

            alerts = {
                row.title: row
                for row in (
                    await db.scalars(
                        select(DlAlert).where(DlAlert.client_id == client_id)
                    )
                ).all()
            }
            assert alerts["stary okres"].order_id == a["order_id"]
            assert alerts["nowy okres"].order_id == new_a
            assert alerts["nowy okres"].dedupe_key == (
                f"missing_revenue_rate:order:{new_a}:{dl_id}:1"
            )
            notifications = {
                n.notification_type: n.related_entity_id
                for n in (
                    await db.scalars(
                        select(Notification).where(Notification.user_id == dl_id)
                    )
                ).all()
            }
            assert (
                notifications[NotificationType.client_order_ending_30d] == a["order_id"]
            )
            assert notifications[NotificationType.client_order_ending_7d] == new_a

            actions_original = set(
                (
                    await db.scalars(
                        select(Activity.action).where(
                            Activity.entity_type == "client_order",
                            Activity.entity_id == a["order_id"],
                        )
                    )
                ).all()
            )
            assert actions_original == {
                "created",
                "order_mail_reactivate",
                "order_mail_overwrite_reverted",
            }
            renewal_activity = await db.scalar(
                select(Activity).where(
                    Activity.entity_type == "client_order",
                    Activity.entity_id == new_a,
                    Activity.action == "order_mail_renewal",
                )
            )
            assert renewal_activity.details["source"] == marker
            assert renewal_activity.details["renewal_of_order_id"] == a["order_id"]
            assert renewal_activity.details["gap_days"] == 1
            assert renewal_activity.details["document_id"] == a["document_id"]
            moved_note = await db.scalar(
                select(Activity.entity_id).where(
                    Activity.entity_type == "client_order",
                    Activity.action == "order_note",
                    Activity.entity_id.in_([a["order_id"], new_a]),
                )
            )
            assert moved_note == new_a
            viewed = await db.scalar(
                select(Activity).where(
                    Activity.entity_type == "client",
                    Activity.entity_id == client_id,
                    Activity.action == "order_viewed",
                )
            )
            assert viewed.details["order_id"] == new_a
            step = await db.scalar(
                select(ContractClientRate).where(
                    ContractClientRate.contract_id == a["contract_id"],
                    ContractClientRate.effective_from == NEW_PERIOD_START,
                )
            )
            assert step.source_order_id == new_a
            consumptions = {
                c.period_month: c.order_id
                for c in (
                    await db.scalars(
                        select(ClientOrderMdConsumption).where(
                            ClientOrderMdConsumption.order_id.in_(
                                [a["order_id"], new_a]
                            )
                        )
                    )
                ).all()
            }
            assert consumptions == {"2026-09": new_a, "2026-08": a["order_id"]}

            # ── Paragon A: pozwala cofnąć korektę ręcznie ────────────────────
            entry_a = by_order[a["order_id"]]
            assert entry_a["moved_to_new_order"]["dl_alerts"] == 1
            assert entry_a["moved_row_ids"] == moved_ids_expected
            assert {
                table: len(ids) for table, ids in entry_a["moved_row_ids"].items()
            } == entry_a["moved_to_new_order"]
            snapshot_a = entry_a["order_before_repair"]
            assert snapshot_a["id"] == a["order_id"]
            for column in (
                "status",
                "title",
                "notes",
                "file_path",
                "rate_unit",
                "predecessor_order_id",
            ):
                assert snapshot_a[column] == original_a_before[column], column
            for column in ("start_date", "end_date"):
                assert snapshot_a[column] == original_a_before[column].isoformat()
            for column in ("rate_client", "rate_candidate", "total_value"):
                assert Decimal(str(snapshot_a[column])) == original_a_before[column]
            assert entry_a["restored_order"]["notes"] == "Notatka starej umowy"
            assert (
                entry_a["kept_on_previous_order_after_incident"][
                    "md_consumptions_before_new_period"
                ]
                == 1
            )
            assert entry_a["restored_order"]["rate_candidate_source"] == (
                "contract_schedule_on_previous_last_day"
            )
            assert entry_a["documents_left_for_review"] == [stale_doc.id]
            assert entry_a["contract_revenue_resync"] == REVENUE_RESYNC_PENDING
            assert entry_a["new_order"]["total_value_source"] == (
                "plan_without_total_value"
            )

            # ── B: bez startu i PDF-u w `before`, aktywacja sprzed nadpisania ─
            b = seeded["b"]
            new_b = by_order[b["order_id"]]["new_order_id"]
            original_b = await _order_row(db, b["order_id"])
            assert original_b["status"] == "completed"
            assert original_b["start_date"] is None
            assert original_b["end_date"] == PREVIOUS_PERIOD_END
            assert original_b["rate_client"] == Decimal("150.000")
            # Koszt NIGDY nie jest kosztem nowego okresu (60) — dzień 31.08.
            assert original_b["rate_candidate"] == Decimal("55.000")
            assert original_b["notes"] is None
            assert original_b["filled_at"] == datetime(
                2026, 6, 1, 10, 0, tzinfo=timezone.utc
            )
            assert original_b["file_path"] is None and original_b["filename"] is None
            renewal_b = await _order_row(db, new_b)
            assert renewal_b["filled_at"] == T0
            assert (
                renewal_b["notes"]
                == f"Zamówienie z maila (dokument #{b['document_id']})"
            )
            assert (
                renewal_b["file_path"]
                == f"client_orders/{b['order_id']}/abcd1234-nowe.pdf"
            )
            # Wartość z planu dokumentu, nie stara kolumna poprzedniego okresu.
            assert renewal_b["total_value"] == Decimal("25000.000")
            assert original_b["total_value"] == Decimal("12345.000")
            entry_b = by_order[b["order_id"]]
            assert entry_b["restored_order"]["file_mode"] == (
                "previous_order_had_no_file"
            )
            assert entry_b["restored_order"]["notes"] is None
            # Bez daty startu przywrócony okres nie tworzy kroku przychodu.
            assert entry_b["contract_revenue_resync"] == REVENUE_RESYNC_NOT_APPLICABLE

            # ── I: metadane pliku z `before` wracają do oryginału ─────────────
            i = seeded["i"]
            original_i = await _order_row(db, i["order_id"])
            assert original_i["file_path"] == i["before_file"]
            assert original_i["filename"] == "Zamowienie czerwiec.pdf"
            assert original_i["content_type"] == "application/pdf"
            assert original_i["size_bytes"] == 2048
            assert original_i["file_uploaded_by"] == dl_id
            assert original_i["file_uploaded_at"] == datetime(
                2026, 6, 2, 9, 30, tzinfo=timezone.utc
            )
            renewal_i = await _order_row(db, by_order[i["order_id"]]["new_order_id"])
            assert renewal_i["file_path"] == (
                f"client_orders/{i['order_id']}/abcd1234-nowe.pdf"
            )
            assert renewal_i["size_bytes"] == 1000
            assert by_order[i["order_id"]]["restored_order"]["file_mode"] == (
                "previous_file_restored"
            )

            # ── C, D, E, F, G, H: pominięte i nietknięte ──────────────────────
            for key in skipped:
                assert (
                    dict(await _order_row(db, seeded[key]["order_id"]))
                    == (untouched_before[key])
                ), key
            # 9 zamówień + poprzednik A + ręcznie odtworzony stary okres E
            # + 3 wydzielone.
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(ClientOrder)
                    .where(ClientOrder.contract_id.in_(contract_ids))
                )
                == 14
            )

            snapshot = (
                await db.execute(
                    text(
                        "SELECT id, status::text, title, start_date, end_date, updated_at "
                        "FROM client_orders WHERE contract_id = ANY(:c) ORDER BY id"
                    ),
                    {"c": contract_ids},
                )
            ).all()
            activities_count = await db.scalar(
                select(func.count())
                .select_from(Activity)
                .where(Activity.details["source"].astext == marker)
            )
            assert activities_count == 6

        # Drugi bieg: marker zatrzymuje blok — nic się nie zmienia.
        async with AsyncSessionLocal() as db:
            await db.execute(text(sql))
            await db.commit()
        # Trzeci bieg BEZ markera: tożsamość sama chroni przed drugim podziałem
        # (oryginały są już zakończone ze starym okresem → „state_changed”).
        async with AsyncSessionLocal() as db:
            await db.execute(
                text("DELETE FROM app_settings WHERE key = :k"), {"k": marker}
            )
            await db.execute(text(sql))
            await db.commit()
        async with AsyncSessionLocal() as db:
            again = (
                await db.execute(
                    text(
                        "SELECT id, status::text, title, start_date, end_date, updated_at "
                        "FROM client_orders WHERE contract_id = ANY(:c) ORDER BY id"
                    ),
                    {"c": contract_ids},
                )
            ).all()
            assert again == snapshot
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(Activity)
                    .where(Activity.details["source"].astext == marker)
                )
                == 6
            )
            third = json.loads(
                await db.scalar(
                    text("SELECT value::text FROM app_settings WHERE key = :k"),
                    {"k": marker},
                )
            )
            assert third["split"] == 0
            third_reasons = {r["order_id"]: r["reason"] for r in third["orders"]}
            for key in ("a", "b", "i"):
                assert third_reasons[seeded[key]["order_id"]] == "state_changed"
            for key, reason in skipped.items():
                assert third_reasons[seeded[key]["order_id"]] == reason
    finally:
        async with AsyncSessionLocal() as db:
            order_ids = [
                row[0]
                for row in (
                    await db.execute(
                        text(
                            "SELECT id FROM client_orders WHERE contract_id = ANY(:c)"
                        ),
                        {"c": contract_ids},
                    )
                ).all()
            ]
            await db.execute(
                text("DELETE FROM notifications WHERE user_id = :u"), {"u": dl_id}
            )
            await db.execute(
                text("DELETE FROM dl_alerts WHERE client_id = :c"), {"c": client_id}
            )
            await db.execute(
                text(
                    "DELETE FROM activities WHERE (entity_type = 'client_order' "
                    "AND entity_id = ANY(:o)) OR (entity_type = 'client' AND entity_id = :c)"
                ),
                {"o": order_ids, "c": client_id},
            )
            await db.execute(
                text("DELETE FROM order_mail_documents WHERE client_id = :c"),
                {"c": client_id},
            )
            await db.execute(
                text("DELETE FROM client_orders WHERE contract_id = ANY(:c)"),
                {"c": contract_ids},
            )
            await db.execute(
                text("DELETE FROM contracts WHERE id = ANY(:c)"), {"c": contract_ids}
            )
            await db.execute(
                text("DELETE FROM candidates WHERE id = ANY(:c)"),
                {"c": [s["candidate_id"] for s in seeded.values()]},
            )
            await db.execute(
                text("DELETE FROM clients WHERE id = :c"), {"c": client_id}
            )
            await db.execute(text("DELETE FROM users WHERE id = :u"), {"u": dl_id})
            await db.execute(
                text("DELETE FROM app_settings WHERE key = :k"), {"k": marker}
            )
            await db.commit()


# ── Przegląd adwersarialny: stany, w których korekta nie może nic zapisać ───


def _spec(key: str, **over):
    base = dict(
        key=key,
        new_title=f"PFRON/2026/NOWE-{key}",
        old_title=f"PFRON/2026/STARE-{key}",
        rate_client=Decimal("81.370"),
        before_rate="85.000",
        before_start="2026-06-01",
        notes=MESSAGE,
        filled_at=T0 + timedelta(seconds=3),
        before_file=lambda oid: None,
    )
    base.update(over)
    return base


async def _setup(db, tag):
    from app.core.security import hash_password
    from app.models.client import Client
    from app.models.user import User, UserRole

    client = Client(name=f"PFRON guard {tag}")
    dl_user = User(
        email=f"pfron-guard-{tag}@example.test",
        password_hash=hash_password("x"),
        name=f"DL {tag}",
        role=UserRole.delivery_lead,
        is_active=True,
    )
    db.add_all([client, dl_user])
    await db.flush()
    return client, dl_user


def _sql(marker, client_id, seeded, **kwargs):
    return build_renewal_split_sql(
        marker=marker,
        client_id=client_id,
        targets=[
            SplitTarget(s["order_id"], s["contract_id"], s["document_id"])
            for s in seeded
        ],
        new_start=NEW_PERIOD_START,
        new_end=NEW_PERIOD_END,
        previous_end=PREVIOUS_PERIOD_END,
        incident_window=INCIDENT_WINDOW,
        **kwargs,
    )


async def _receipt(db, marker):
    raw = await db.scalar(
        text("SELECT value::text FROM app_settings WHERE key = :k"), {"k": marker}
    )
    return None if raw is None else json.loads(raw)


async def _orders_of_client(db, client_id):
    return (
        await db.execute(
            text(
                "SELECT id, status::text, start_date, end_date, contract_id "
                "FROM client_orders WHERE client_id = :c ORDER BY id"
            ),
            {"c": client_id},
        )
    ).all()


async def _cleanup(client_id, dl_id, marker):
    async with AsyncSessionLocal() as db:
        contract_ids = [
            r[0]
            for r in (
                await db.execute(
                    text("SELECT id FROM contracts WHERE client_id = :c"),
                    {"c": client_id},
                )
            ).all()
        ]
        order_ids = [
            r[0]
            for r in (
                await db.execute(
                    text("SELECT id FROM client_orders WHERE client_id = :c"),
                    {"c": client_id},
                )
            ).all()
        ]
        candidate_ids = [
            r[0]
            for r in (
                await db.execute(
                    text("SELECT candidate_id FROM contracts WHERE id = ANY(:c)"),
                    {"c": contract_ids},
                )
            ).all()
        ]
        await db.execute(
            text("DELETE FROM notifications WHERE user_id = :u"), {"u": dl_id}
        )
        await db.execute(
            text("DELETE FROM dl_alerts WHERE client_id = :c"), {"c": client_id}
        )
        await db.execute(
            text(
                "DELETE FROM activities WHERE (entity_type = 'client_order' "
                "AND entity_id = ANY(:o)) OR (entity_type = 'client' AND entity_id = :c) "
                "OR (entity_type = 'contract' AND entity_id = ANY(:k))"
            ),
            {"o": order_ids, "c": client_id, "k": contract_ids},
        )
        await db.execute(
            text("DELETE FROM client_order_md_consumptions WHERE order_id = ANY(:o)"),
            {"o": order_ids},
        )
        await db.execute(
            text("DELETE FROM order_mail_documents WHERE client_id = :c"),
            {"c": client_id},
        )
        await db.execute(
            text("DELETE FROM client_orders WHERE client_id = :c"), {"c": client_id}
        )
        await db.execute(
            text("DELETE FROM contracts WHERE id = ANY(:c)"), {"c": contract_ids}
        )
        await db.execute(
            text("DELETE FROM candidates WHERE id = ANY(:c)"), {"c": candidate_ids}
        )
        await db.execute(text("DELETE FROM clients WHERE id = :c"), {"c": client_id})
        await db.execute(text("DELETE FROM users WHERE id = :u"), {"u": dl_id})
        await db.execute(text("DELETE FROM app_settings WHERE key = :k"), {"k": marker})
        await db.commit()


async def _assert_skipped_and_untouched(marker, client_id, seeded, before, reason):
    """Paragon z powodem, wiersz bajt w bajt ten sam, żadnego nowego zamówienia."""
    async with AsyncSessionLocal() as db:
        receipt = await _receipt(db, marker)
        entry = receipt["orders"][0]
        assert (entry["status"], entry["reason"]) == ("skipped", reason)
        assert (receipt["split"], receipt["skipped"]) == (0, 1)
        assert dict(await _order_row(db, seeded["order_id"])) == before["row"]
        assert await _orders_of_client(db, client_id) == before["orders"]
        return entry


async def _state_before(client_id, seeded):
    async with AsyncSessionLocal() as db:
        return {
            "row": dict(await _order_row(db, seeded["order_id"])),
            "orders": await _orders_of_client(db, client_id),
        }


@pytest.mark.asyncio
async def test_total_value_typed_into_the_renewal_after_incident_skips_the_order():
    """Przegląd, przypadek I: DL wpisał wartość NOWEGO okresu w nadpisany wiersz.

    Blok zostawia bieżące ``total_value`` oryginałowi — bez tej blokady wartość
    nowego okresu siedziałaby w obu wierszach (podwójny przychód).
    """
    from app.models.activity import Activity

    tag = uuid.uuid4().hex[:8]
    marker = f"t0306i_{tag}"
    async with AsyncSessionLocal() as db:
        client, dl = await _setup(db, tag)
        s = await _seed_target(
            db, tag=tag, client=client, dl_user=dl, spec=_spec("t", plan_total="30000")
        )
        await db.commit()
        client_id, dl_id = client.id, dl.id
    try:
        async with AsyncSessionLocal() as db:
            # Ślad, który zostawia PATCH /api/clients/{c}/orders/{o}.
            await db.execute(
                text("UPDATE client_orders SET total_value = 30000 WHERE id = :i"),
                {"i": s["order_id"]},
            )
            db.add(
                Activity(
                    entity_type="client",
                    entity_id=client_id,
                    action="order_updated",
                    user_id=dl_id,
                    details={
                        "order_id": s["order_id"],
                        "changed": ["total_value"],
                        "auto_activated": False,
                        "contract_revived": False,
                    },
                    created_at=AFTER,
                )
            )
            await db.commit()
        before = await _state_before(client_id, s)
        async with AsyncSessionLocal() as db:
            await db.execute(text(_sql(marker, client_id, [s])))
            await db.commit()
        entry = await _assert_skipped_and_untouched(
            marker, client_id, s, before, "edited_after_incident"
        )
        assert [(e["action"], e["changed"], e["user_id"]) for e in entry["detail"]] == [
            ("order_updated", ["total_value"], dl_id)
        ]
    finally:
        await _cleanup(client_id, dl_id, marker)


@pytest.mark.asyncio
async def test_unit_changed_after_incident_without_history_skips_the_order():
    """Przegląd, przypadek B: jednostka zmieniona po T0 (bez śladu w historii).

    Stawka przywrócona pod cudzą jednostką to cichy błąd 8×; ``before`` jej
    nie niesie, więc jedyną miarą jest to, co writer zapisał z planu.
    """
    tag = uuid.uuid4().hex[:8]
    marker = f"t0306b_{tag}"
    async with AsyncSessionLocal() as db:
        client, dl = await _setup(db, tag)
        s = await _seed_target(db, tag=tag, client=client, dl_user=dl, spec=_spec("u"))
        await db.commit()
        client_id, dl_id = client.id, dl.id
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(
                text("UPDATE client_orders SET rate_unit = 'daily' WHERE id = :i"),
                {"i": s["order_id"]},
            )
            await db.commit()
        before = await _state_before(client_id, s)
        async with AsyncSessionLocal() as db:
            await db.execute(text(_sql(marker, client_id, [s])))
            await db.commit()
        entry = await _assert_skipped_and_untouched(
            marker, client_id, s, before, "rate_unit_differs_from_mail_plan"
        )
        # Plan bez jednostki → writer wziął jednostkę umowy (godzinową).
        assert entry["detail"]["expected_rate_unit"] == "hourly"
        assert entry["detail"]["current_rate_unit"] == "daily"
    finally:
        await _cleanup(client_id, dl_id, marker)


@pytest.mark.asyncio
async def test_plan_unit_is_read_like_the_writer_reads_it():
    """Plan „hour” → godzinowa: zgodny wiersz przechodzi, dzienny — nie."""
    tag = uuid.uuid4().hex[:8]
    marker = f"t0306p_{tag}"
    async with AsyncSessionLocal() as db:
        client, dl = await _setup(db, tag)
        ok = await _seed_target(
            db, tag=tag, client=client, dl_user=dl, spec=_spec("ph")
        )
        other = await _seed_target(
            db, tag=tag, client=client, dl_user=dl, spec=_spec("pd")
        )
        for seeded, unit in ((ok, "hour"), (other, "day")):
            await db.execute(
                text(
                    "UPDATE order_mail_documents SET proposal = jsonb_set("
                    "proposal, '{rows,0,rate_unit}', to_jsonb(CAST(:u AS text))) "
                    "WHERE id = :d"
                ),
                {"u": unit, "d": seeded["document_id"]},
            )
        await db.commit()
        client_id, dl_id = client.id, dl.id
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(text(_sql(marker, client_id, [ok, other])))
            await db.commit()
        async with AsyncSessionLocal() as db:
            receipt = await _receipt(db, marker)
            by_order = {e["order_id"]: e for e in receipt["orders"]}
            assert by_order[ok["order_id"]]["status"] == "split"
            assert by_order[other["order_id"]]["reason"] == (
                "rate_unit_differs_from_mail_plan"
            )
            assert by_order[other["order_id"]]["detail"]["expected_rate_unit"] == (
                "daily"
            )
    finally:
        await _cleanup(client_id, dl_id, marker)


@pytest.mark.asyncio
async def test_title_changed_after_incident_without_history_skips_the_order():
    tag = uuid.uuid4().hex[:8]
    marker = f"t0306n_{tag}"
    async with AsyncSessionLocal() as db:
        client, dl = await _setup(db, tag)
        s = await _seed_target(db, tag=tag, client=client, dl_user=dl, spec=_spec("n"))
        await db.commit()
        client_id, dl_id = client.id, dl.id
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(
                text("UPDATE client_orders SET title = 'ZMYSLONY/99' WHERE id = :i"),
                {"i": s["order_id"]},
            )
            await db.commit()
        before = await _state_before(client_id, s)
        async with AsyncSessionLocal() as db:
            await db.execute(text(_sql(marker, client_id, [s])))
            await db.commit()
        entry = await _assert_skipped_and_untouched(
            marker, client_id, s, before, "title_differs_from_mail_plan"
        )
        assert entry["detail"] == {
            "current_title": "ZMYSLONY/99",
            "expected_title": "PFRON/2026/NOWE-n",
        }
    finally:
        await _cleanup(client_id, dl_id, marker)


@pytest.mark.asyncio
async def test_renewal_reentered_on_another_contract_of_the_same_person_skips():
    """Przegląd, przypadek A: przedłużenie wpisane ręcznie przez „Nowy kontraktor
    / zamówienie” — ten przepływ zawsze zakłada NOWY kontrakt tej osoby.

    Bez sprawdzenia wszystkich kontraktów osoby korekta dołożyłaby drugie
    żywe zamówienie na ten sam okres.
    """
    from app.models.client_order import ClientOrder, ClientOrderStatus
    from app.models.contract import Contract, ContractStatus, ContractType, RateUnit

    tag = uuid.uuid4().hex[:8]
    marker = f"t0306a_{tag}"
    async with AsyncSessionLocal() as db:
        client, dl = await _setup(db, tag)
        s = await _seed_target(db, tag=tag, client=client, dl_user=dl, spec=_spec("x"))
        second = Contract(
            candidate_id=s["candidate_id"],
            client_id=client.id,
            contract_type=ContractType.b2b,
            status=ContractStatus.active,
            start_date=NEW_PERIOD_START,
            rate_candidate=Decimal("60"),
            rate_unit=RateUnit.hourly,
            billing_hours_per_month=160,
        )
        db.add(second)
        await db.flush()
        manual = ClientOrder(
            client_id=client.id,
            contract_id=second.id,
            title="PFRON/2026/NOWE-x (ręcznie)",
            status=ClientOrderStatus.active,
            order_type="periodic",
            start_date=NEW_PERIOD_START,
            end_date=NEW_PERIOD_END,
            rate_client=Decimal("81.370"),
            rate_unit=RateUnit.hourly,
            created_at=AFTER,
        )
        db.add(manual)
        await db.flush()
        manual_id, second_id = manual.id, second.id
        await db.commit()
        client_id, dl_id = client.id, dl.id
    try:
        before = await _state_before(client_id, s)
        async with AsyncSessionLocal() as db:
            await db.execute(text(_sql(marker, client_id, [s])))
            await db.commit()
        entry = await _assert_skipped_and_untouched(
            marker, client_id, s, before, "another_order_covers_new_period"
        )
        assert [(c["order_id"], c["contract_id"]) for c in entry["detail"]] == [
            (manual_id, second_id)
        ]
    finally:
        await _cleanup(client_id, dl_id, marker)


@pytest.mark.asyncio
async def test_same_contract_extension_and_leftover_draft_shell_skip_the_orders():
    """Przegląd, przypadek K: przedłużenie na TYM SAMYM kontrakcie i stary
    szkic bez dat — oba zajmują nowy okres, oba zatrzymują korektę."""
    from app.models.client_order import ClientOrder, ClientOrderStatus
    from app.models.contract import RateUnit

    tag = uuid.uuid4().hex[:8]
    marker = f"t0306k_{tag}"
    async with AsyncSessionLocal() as db:
        client, dl = await _setup(db, tag)
        s1 = await _seed_target(
            db, tag=tag, client=client, dl_user=dl, spec=_spec("n1")
        )
        s2 = await _seed_target(
            db, tag=tag, client=client, dl_user=dl, spec=_spec("n2")
        )
        db.add_all(
            [
                ClientOrder(
                    client_id=client.id,
                    contract_id=s1["contract_id"],
                    title="PFRON/2026/NOWE-n1 (przedłużenie)",
                    status=ClientOrderStatus.active,
                    start_date=NEW_PERIOD_START,
                    end_date=NEW_PERIOD_END,
                    rate_client=Decimal("81.370"),
                    rate_unit=RateUnit.hourly,
                    created_at=AFTER,
                ),
                ClientOrder(
                    client_id=client.id,
                    contract_id=s2["contract_id"],
                    title="(bez numeru)",
                    status=ClientOrderStatus.draft,
                    start_date=None,
                    end_date=None,
                    created_at=datetime(2026, 5, 2, 8, 0, tzinfo=timezone.utc),
                ),
            ]
        )
        await db.commit()
        client_id, dl_id = client.id, dl.id
    try:
        async with AsyncSessionLocal() as db:
            orders_before = await _orders_of_client(db, client_id)
            await db.execute(text(_sql(marker, client_id, [s1, s2])))
            await db.commit()
        async with AsyncSessionLocal() as db:
            receipt = await _receipt(db, marker)
            reasons = {
                e["order_id"]: (e["status"], e["reason"]) for e in receipt["orders"]
            }
            assert reasons == {
                s1["order_id"]: ("skipped", "another_order_covers_new_period"),
                s2["order_id"]: ("skipped", "another_order_covers_new_period"),
            }
            assert await _orders_of_client(db, client_id) == orders_before
    finally:
        await _cleanup(client_id, dl_id, marker)


@pytest.mark.asyncio
async def test_unknown_foreign_key_row_skips_the_order():
    """Przegląd, przypadek C: nieznany klucz obcy zatrzymuje zamówienie."""
    tag = uuid.uuid4().hex[:8]
    marker = f"t0306c_{tag}"
    table = f"zz_t0306_{tag}"
    async with AsyncSessionLocal() as db:
        client, dl = await _setup(db, tag)
        s = await _seed_target(db, tag=tag, client=client, dl_user=dl, spec=_spec("k"))
        await db.commit()
        client_id, dl_id = client.id, dl.id
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(
                text(
                    f"CREATE TABLE {table} (id serial PRIMARY KEY, "
                    "order_ref integer REFERENCES client_orders(id) ON DELETE CASCADE)"
                )
            )
            await db.execute(
                text(f"INSERT INTO {table} (order_ref) VALUES (:o)"),
                {"o": s["order_id"]},
            )
            await db.commit()
        before = await _state_before(client_id, s)
        async with AsyncSessionLocal() as db:
            await db.execute(text(_sql(marker, client_id, [s])))
            await db.commit()
        entry = await _assert_skipped_and_untouched(
            marker, client_id, s, before, "unknown_foreign_key_reference"
        )
        assert entry["detail"] == [{"table": table, "column": "order_ref", "rows": 1}]
        async with AsyncSessionLocal() as db:
            inventory = (await _receipt(db, marker))["foreign_keys_to_client_orders"]
        assert [fk["handled"] for fk in inventory if fk["table"] == table] == [False]
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(text(f"DROP TABLE IF EXISTS {table}"))
            await db.commit()
        await _cleanup(client_id, dl_id, marker)


@pytest.mark.asyncio
async def test_two_concurrent_runs_split_once():
    """Przegląd, przypadek D: rolling deploy — dwa biegi, jeden podział."""
    tag = uuid.uuid4().hex[:8]
    marker = f"t0306d_{tag}"
    async with AsyncSessionLocal() as db:
        client, dl = await _setup(db, tag)
        s = await _seed_target(db, tag=tag, client=client, dl_user=dl, spec=_spec("p"))
        await db.commit()
        client_id, dl_id = client.id, dl.id
    sql = _sql(marker, client_id, [s])
    try:
        first = AsyncSessionLocal()
        second = AsyncSessionLocal()
        try:
            await first.execute(text(sql))  # trzyma advisory lock, bez commitu

            async def run_second():
                await second.execute(text(sql))
                await second.commit()

            task = asyncio.create_task(run_second())
            await asyncio.sleep(1.0)
            assert not task.done(), "drugi bieg ma czekać na advisory lock"
            await first.commit()
            await asyncio.wait_for(task, timeout=30)
        finally:
            await first.close()
            await second.close()
        async with AsyncSessionLocal() as db:
            count = await db.scalar(
                text("SELECT count(*) FROM client_orders WHERE contract_id = :c"),
                {"c": s["contract_id"]},
            )
            receipt = await _receipt(db, marker)
            assert (count, receipt["split"], receipt["skipped"]) == (2, 1, 0)
    finally:
        await _cleanup(client_id, dl_id, marker)


@pytest.mark.asyncio
async def test_failure_in_a_later_target_rolls_back_everything():
    """Przegląd, przypadek E: błąd przy drugim zamówieniu cofa pierwsze; bez markera."""
    tag = uuid.uuid4().hex[:8]
    marker = f"t0306e_{tag}"
    async with AsyncSessionLocal() as db:
        client, dl = await _setup(db, tag)
        s1 = await _seed_target(
            db, tag=tag, client=client, dl_user=dl, spec=_spec("e1")
        )
        s2 = await _seed_target(
            db,
            tag=tag,
            client=client,
            dl_user=dl,
            # Przechodzi wzorzec daty, pada dopiero na rzutowaniu.
            spec=_spec("e2", before_start="2026-02-30"),
        )
        await db.commit()
        client_id, dl_id = client.id, dl.id
    try:
        before = await _state_before(client_id, s1)
        with pytest.raises(DBAPIError):
            async with AsyncSessionLocal() as db:
                await db.execute(text(_sql(marker, client_id, [s1, s2])))
                await db.commit()
        async with AsyncSessionLocal() as db:
            assert await _receipt(db, marker) is None
            assert dict(await _order_row(db, s1["order_id"])) == before["row"]
            assert await _orders_of_client(db, client_id) == before["orders"]
    finally:
        await _cleanup(client_id, dl_id, marker)


@pytest.mark.asyncio
async def test_mail_writer_client_lock_times_out_the_block_without_writing():
    """Stary kontener w trakcie zapisu z maila trzyma wiersz klienta.

    Blok czeka najwyżej ``lock_timeout`` i pada w całości: nic nie zapisuje,
    marker nie powstaje — następny start (tu: drugi bieg) robi korektę.
    """
    from app.models.client import Client

    tag = uuid.uuid4().hex[:8]
    marker = f"t0306l_{tag}"
    async with AsyncSessionLocal() as db:
        client, dl = await _setup(db, tag)
        s = await _seed_target(db, tag=tag, client=client, dl_user=dl, spec=_spec("l"))
        await db.commit()
        client_id, dl_id = client.id, dl.id
    try:
        before = await _state_before(client_id, s)
        writer = AsyncSessionLocal()
        try:
            # Dokładnie to, od czego zaczyna ``order_mail_apply.apply_document``.
            await writer.scalar(
                select(Client.id).where(Client.id == client_id).with_for_update()
            )
            with pytest.raises(DBAPIError) as error:
                async with AsyncSessionLocal() as db:
                    await db.execute(
                        text(_sql(marker, client_id, [s], lock_timeout="300ms"))
                    )
                    await db.commit()
            assert is_lock_timeout(error.value)
        finally:
            await writer.rollback()
            await writer.close()
        async with AsyncSessionLocal() as db:
            assert await _receipt(db, marker) is None
            assert dict(await _order_row(db, s["order_id"])) == before["row"]
            assert await _orders_of_client(db, client_id) == before["orders"]
        # Blokada zwolniona → kolejny start przeprowadza korektę.
        async with AsyncSessionLocal() as db:
            await db.execute(text(_sql(marker, client_id, [s])))
            await db.commit()
        async with AsyncSessionLocal() as db:
            assert (await _receipt(db, marker))["split"] == 1
    finally:
        await _cleanup(client_id, dl_id, marker)


@pytest.mark.asyncio
async def test_block_restores_the_callers_lock_timeout():
    """Alembic wykonuje kolejne migracje w TEJ SAMEJ transakcji — 15 s nie
    może z bloku wyciec ani na ścieżce z markerem, ani po pełnym biegu."""
    marker = f"t0306r_{uuid.uuid4().hex[:8]}"
    sql = build_renewal_split_sql(
        marker=marker,
        client_id=0,
        targets=[SplitTarget(0, 0, 0)],
        new_start=NEW_PERIOD_START,
        new_end=NEW_PERIOD_END,
        previous_end=PREVIOUS_PERIOD_END,
        incident_window=INCIDENT_WINDOW,
    )
    async with AsyncSessionLocal() as db:
        try:
            await db.execute(text("SET LOCAL lock_timeout = '7s'"))
            await db.execute(text(sql))  # pełny bieg: zamówienie nie istnieje
            assert await db.scalar(text("SHOW lock_timeout")) == "7s"
            receipt = await _receipt(db, marker)
            assert receipt["orders"][0]["reason"] == "order_missing"
            await db.execute(text(sql))  # ścieżka z markerem
            assert await db.scalar(text("SHOW lock_timeout")) == "7s"
        finally:
            await db.rollback()
