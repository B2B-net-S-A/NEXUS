"""Migracja 0306: PFRON 507–509 — rozdzielenie zamówienia nadpisanego „reaktywacją”.

Blok SQL jest WYKONYWANY na bazie testowej (literówka w nazwie kolumny wyszłaby
dopiero na produkcji, a entrypoint połknąłby ją przez ``|| echo skipped``).
Test buduje dokładnie scenariusz z nocy 9/10.09.2026 — zamówienie przepisane
w miejscu nowym okresem, Activity ``order_mail_reactivate`` z ``before``,
dokument z maila, wiersze potomne sprzed i po nadpisaniu — na własnych id
i własnym markerze (``build_renewal_split_sql``), więc nie koliduje z id
produkcyjnymi ani z markerem, który zakłada ``alembic upgrade heads``.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select, text

from app.core.database import AsyncSessionLocal
from app.services.pfron_renewal_split_repair import (
    HANDLED_FOREIGN_KEYS,
    INCIDENT_WINDOW,
    NEW_PERIOD_END,
    NEW_PERIOD_START,
    PFRON_RENEWAL_SPLIT_MARKER,
    PFRON_RENEWAL_SPLIT_SQL,
    PREVIOUS_PERIOD_END,
    SplitTarget,
    build_renewal_split_sql,
)

BACKEND = Path(__file__).resolve().parents[1]
MIGRATION = BACKEND / "alembic/versions/0306_pfron_renewal_split_repair.py"
ENTRYPOINT = BACKEND / "entrypoint.sh"

T0 = datetime(2026, 9, 9, 22, 7, 13, tzinfo=timezone.utc)
MESSAGE = "Powrót po 1 dniach od zakończenia poprzedniego zamówienia"


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
    ):
        assert value in sql, value


def test_block_has_no_accidental_bind_parameters():
    """``text()`` czyta ``:słowo`` jako parametr — blok musi go nie mieć.

    Godzina w literale („22:07”) albo klucz „order:507” poza apostrofami
    zamieniłyby wykonanie migracji w „A value is required for bind parameter”.
    """
    assert text(PFRON_RENEWAL_SPLIT_SQL).compile().params == {}


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
        "document_not_applied_to_order",
        "document_plan_mismatch",
        "another_order_covers_new_period",
        "another_order_covers_previous_period",
        "rate_unit_change_suspected",
        "rate_unit_unverifiable",
        "unknown_foreign_key_reference",
    ):
        assert f"'{reason}'" in sql, reason


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
    assert {(t, c) for t, c in rows} == set(HANDLED_FOREIGN_KEYS)


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
            # sprzed nadpisania.
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
            # PDF zmieniony w aplikacji po nadpisaniu — stary plik mógł zniknąć.
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
                plan_total="25000.00",
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
        }
        seeded = {
            key: await _seed_target(
                db, tag=tag, client=client, dl_user=dl_user, spec=spec
            )
            for key, spec in specs.items()
        }
        a = seeded["a"]
        after = datetime(2026, 9, 10, 8, 0, tzinfo=timezone.utc)
        before = datetime(2026, 8, 10, 8, 0, tzinfo=timezone.utc)
        stale_message_id = f"<{uuid.uuid4()}@pfron.test>"
        db.add_all(
            [
                DlAlert(
                    alert_type="missing_revenue_rate",
                    user_id=dl_user.id,
                    client_id=client.id,
                    order_id=a["order_id"],
                    title="stary okres",
                    message="stary okres",
                    dedupe_key=f"missing_revenue_rate:order:{a['order_id']}:{dl_user.id}:0",
                    created_at=before,
                ),
                DlAlert(
                    alert_type="missing_revenue_rate",
                    user_id=dl_user.id,
                    client_id=client.id,
                    order_id=a["order_id"],
                    title="nowy okres",
                    message="nowy okres",
                    dedupe_key=f"missing_revenue_rate:order:{a['order_id']}:{dl_user.id}:1",
                    created_at=after,
                ),
                Notification(
                    user_id=dl_user.id,
                    title="Zamówienie kończy się za 30 dni",
                    message="kończy się 2026-08-31.",
                    notification_type=NotificationType.client_order_ending_30d,
                    related_entity_type="client_order",
                    related_entity_id=a["order_id"],
                    created_at=datetime(2026, 8, 1, 8, 0, tzinfo=timezone.utc),
                ),
                Notification(
                    user_id=dl_user.id,
                    title="Zamówienie kończy się za 7 dni",
                    message="kończy się 2026-11-30.",
                    notification_type=NotificationType.client_order_ending_7d,
                    related_entity_type="client_order",
                    related_entity_id=a["order_id"],
                    created_at=after,
                ),
                Activity(
                    entity_type="client_order",
                    entity_id=a["order_id"],
                    action="created",
                    details={},
                    created_at=datetime(2026, 5, 20, 9, 0, tzinfo=timezone.utc),
                ),
                Activity(
                    entity_type="client_order",
                    entity_id=a["order_id"],
                    action="order_note",
                    details={"note": "po nadpisaniu"},
                    created_at=after,
                ),
                Activity(
                    entity_type="client",
                    entity_id=client.id,
                    action="order_viewed",
                    details={"order_id": a["order_id"]},
                    created_at=after,
                ),
                # F: nowy PDF wgrany w aplikacji po nadpisaniu.
                Activity(
                    entity_type="client",
                    entity_id=client.id,
                    action="order_file_uploaded",
                    details={
                        "order_id": seeded["f"]["order_id"],
                        "filename": "poprawiony.pdf",
                        "replaced": True,
                    },
                    created_at=after,
                ),
                # E: stary okres odtworzony ręcznie po nadpisaniu.
                ClientOrder(
                    client_id=client.id,
                    contract_id=seeded["e"]["contract_id"],
                    title="PFRON/2026/STARE-E (ręcznie)",
                    status=ClientOrderStatus.completed,
                    start_date=date(2026, 6, 1),
                    end_date=PREVIOUS_PERIOD_END,
                    created_at=after,
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
                ContractClientRate(
                    contract_id=a["contract_id"],
                    rate=Decimal("81.370"),
                    effective_from=NEW_PERIOD_START,
                    source_order_id=a["order_id"],
                    created_at=after,
                ),
                ClientOrderMdConsumption(
                    order_id=a["order_id"],
                    period_month="2026-09",
                    md_reported=Decimal("3"),
                    source="manual",
                    created_at=after,
                ),
                ClientOrderMdConsumption(
                    order_id=a["order_id"],
                    period_month="2026-08",
                    md_reported=Decimal("5"),
                    source="manual",
                    created_at=after,
                ),
            ]
        )
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
        "g": "rate_unit_unverifiable",
        "h": "document_plan_mismatch",
    }
    try:
        async with AsyncSessionLocal() as db:
            untouched_before = {
                key: dict(await _order_row(db, seeded[key]["order_id"]))
                for key in skipped
            }
            await db.execute(text(sql))
            await db.commit()

        async with AsyncSessionLocal() as db:
            receipt = json.loads(
                await db.scalar(
                    text("SELECT value::text FROM app_settings WHERE key = :k"),
                    {"k": marker},
                )
            )
            assert (receipt["split"], receipt["skipped"]) == (3, 5)
            by_order = {r["order_id"]: r for r in receipt["orders"]}
            for key, reason in skipped.items():
                assert by_order[seeded[key]["order_id"]]["reason"] == reason, key
            assert {
                (fk["table"], fk["column"])
                for fk in receipt["foreign_keys_to_client_orders"]
            } == set(HANDLED_FOREIGN_KEYS)

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
            entry_a = by_order[a["order_id"]]
            assert entry_a["moved_to_new_order"]["dl_alerts"] == 1
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
            assert entry_a["contract_revenue_resync"] == "pending_next_order_write"
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
            assert (
                by_order[b["order_id"]]["restored_order"]["file_mode"]
                == "previous_order_had_no_file"
            )

            # ── F: PDF zmieniony w aplikacji po T0 — ścieżki nie podpinamy ────
            f = seeded["f"]
            new_f = by_order[f["order_id"]]["new_order_id"]
            original_f = await _order_row(db, f["order_id"])
            assert original_f["status"] == "completed"
            assert original_f["file_path"] is None and original_f["filename"] is None
            entry_f = by_order[f["order_id"]]
            assert entry_f["restored_order"]["file_mode"] == (
                "previous_file_uncertain_after_file_change"
            )
            assert (
                entry_f["restored_order"]["file_path_before_overwrite"]
                == (f["before_file"])
            )
            renewal_f = await _order_row(db, new_f)
            assert renewal_f["file_path"] == (
                f"client_orders/{f['order_id']}/abcd1234-nowe.pdf"
            )
            # Wartość z planu dokumentu, nie stara kolumna poprzedniego okresu.
            assert renewal_f["total_value"] == Decimal("25000.000")
            assert original_f["total_value"] == Decimal("12345.000")

            # ── C, D, E, G, H: pominięte i nietknięte ─────────────────────────
            for key in skipped:
                assert (
                    dict(await _order_row(db, seeded[key]["order_id"]))
                    == (untouched_before[key])
                ), key
            # 8 zamówień + ręcznie odtworzony stary okres E + 3 wydzielone.
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(ClientOrder)
                    .where(ClientOrder.contract_id.in_(contract_ids))
                )
                == 12
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
            for key in ("a", "b", "f"):
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
