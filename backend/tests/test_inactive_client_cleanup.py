"""Jednorazowe czyszczenie zakładki „Nieaktywni klienci" — testy na żywej bazie.

Baza testowa jest WSPÓLNA dla przebiegu i nie jest czyszczona, więc każdy
test zawęża ocenę do własnych klientów (``restrict_ids``) i zatwierdza do
usunięcia wyłącznie ich. Raport operacji jest jednorazowy (UNIQUE po
``kind``), dlatego fixture sprząta go przed i po każdym teście, który go
zapisuje.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import delete, select, text

import app.models  # noqa: F401  (rejestracja wszystkich mapperów)
from app.core.database import AsyncSessionLocal
from app.models.activity import Activity
from app.models.client import Client
from app.models.client_cleanup import ClientCleanupRun, PurgedClient
from app.models.client_directory import (
    ClientImportRow,
    ClientImportRun,
    ClientImportRunStatus,
    ClientImportRowStatus,
    ClientPortfolioScope,
    PortfolioCategory,
)
from app.models.contact import Contact
from app.models.job import Job
from app.models.user import User, UserRole
from app.services.inactive_client_cleanup import (
    configured_client_ids,
    evaluate_inactive_clients,
)
from app.services.inactive_client_cleanup_run import (
    CleanupAlreadyExecutedError,
    execute_inactive_client_cleanup,
    load_cleanup_report,
    purged_external_ids,
)

pytestmark = pytest.mark.asyncio


async def _wipe_cleanup_state() -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(delete(PurgedClient))
        await db.execute(delete(ClientCleanupRun))
        await db.commit()


@pytest_asyncio.fixture
async def clean_cleanup_state():
    await _wipe_cleanup_state()
    yield
    await _wipe_cleanup_state()


async def _make_client(
    tag: str,
    *,
    categories: tuple[PortfolioCategory, ...] = (PortfolioCategory.inactive,),
    notes: str | None = None,
    external_id: str | None = None,
) -> int:
    async with AsyncSessionLocal() as db:
        client = Client(
            name=f"Cleanup {tag} {uuid.uuid4().hex[:6]}",
            notes=notes,
            external_source="traffit" if external_id else "manual",
            external_id=external_id,
        )
        db.add(client)
        await db.flush()
        for category in categories:
            db.add(ClientPortfolioScope(client_id=client.id, category=category))
        await db.commit()
        return client.id


async def _make_admin() -> User:
    async with AsyncSessionLocal() as db:
        unique = uuid.uuid4().hex[:8]
        user = User(
            email=f"cleanup-admin-{unique}@example.com",
            password_hash="x",
            name="Cleanup Admin",
            role=UserRole.admin,
            is_active=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


async def _drop_clients(ids: list[int]) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(delete(Contact).where(Contact.client_id.in_(ids)))
        await db.execute(delete(Job).where(Job.client_id.in_(ids)))
        await db.execute(delete(Client).where(Client.id.in_(ids)))
        await db.commit()


def _verdicts(plan) -> dict[int, str]:
    return {
        **{item.client_id: "delete" for item in plan.deletable},
        **{item.client_id: "hold" for item in plan.held},
        **{item.client_id: "keep" for item in plan.kept},
    }


async def test_eight_sources_keep_other_links_hold_and_the_rest_is_deletable():
    empty = await _make_client("pusty")
    with_job = await _make_client("z-rekrutacja")
    with_notes = await _make_client("z-notatka", notes="Rozmowa z CFO 2021")
    with_contact = await _make_client("z-kontaktem")
    also_active = await _make_client(
        "dwie-zakladki",
        categories=(PortfolioCategory.inactive, PortfolioCategory.active),
    )
    only_active = await _make_client(
        "tylko-aktywny", categories=(PortfolioCategory.active,)
    )
    ids = [empty, with_job, with_notes, with_contact, also_active, only_active]
    try:
        async with AsyncSessionLocal() as db:
            db.add(Job(title="Projekt zamknięty", client_id=with_job))
            db.add(Contact(client_id=with_contact, name="Anna Kontakt"))
            await db.commit()

        async with AsyncSessionLocal() as db:
            plan = await evaluate_inactive_clients(db, restrict_ids=ids, environ={})

        verdicts = _verdicts(plan)
        assert verdicts[empty] == "delete"
        assert verdicts[with_job] == "keep"
        assert verdicts[with_notes] == "keep"
        assert verdicts[with_contact] == "hold"
        assert verdicts[also_active] == "hold"
        # Klient bez zakresu „Nieaktywni" w ogóle nie jest oceniany.
        assert only_active not in verdicts

        held = {item.client_id: item for item in plan.held}
        contact_reason = held[with_contact].as_dict()["reasons"][0]
        assert contact_reason["table"] == "contacts"
        assert contact_reason["label"].startswith("Kontakty")
        assert held[also_active].as_dict()["reasons"][0]["code"] == (
            "other_portfolio_tab"
        )
        kept = {item.client_id: item for item in plan.kept}
        assert kept[with_notes].sources["notes"] == 1
        assert kept[with_job].sources["active_projects"] == 1
    finally:
        await _drop_clients(ids)


async def test_administrative_activity_does_not_hold_but_real_activity_does():
    technical = await _make_client("tylko-edycja")
    worked_on = await _make_client("usuniety-onepager")
    ids = [technical, worked_on]
    try:
        async with AsyncSessionLocal() as db:
            db.add(
                Activity(entity_type="client", entity_id=technical, action="updated")
            )
            db.add(
                Activity(
                    entity_type="client",
                    entity_id=technical,
                    action="client_portfolio_excel_imported",
                )
            )
            db.add(
                Activity(
                    entity_type="client",
                    entity_id=worked_on,
                    action="one_pager_deleted",
                )
            )
            await db.commit()

        async with AsyncSessionLocal() as db:
            plan = await evaluate_inactive_clients(db, restrict_ids=ids, environ={})

        verdicts = _verdicts(plan)
        assert verdicts[technical] == "delete"
        assert verdicts[worked_on] == "hold"
        reason = next(item for item in plan.held if item.client_id == worked_on)
        # Czytelna nazwa zamiast kodu — lista B czyta ją człowiek.
        assert reason.as_dict()["reasons"][0]["details"] == ["usunięcie one-pagera"]
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(Activity).where(
                    Activity.entity_type == "client", Activity.entity_id.in_(ids)
                )
            )
            await db.commit()
        await _drop_clients(ids)


async def test_client_named_in_configuration_is_held():
    client_id = await _make_client("w-konfiguracji")
    try:
        async with AsyncSessionLocal() as db:
            plan = await evaluate_inactive_clients(
                db,
                restrict_ids=[client_id],
                environ={"COST_ORDER_CLIENT_IDS": f"15, {client_id}"},
            )
        assert _verdicts(plan)[client_id] == "hold"
        reason = plan.held[0].as_dict()["reasons"][0]
        assert reason["code"] == "configuration"
        assert "COST_ORDER_CLIENT_IDS" in reason["label"]
    finally:
        await _drop_clients([client_id])


async def test_configured_client_ids_reads_only_client_id_lists():
    found = configured_client_ids(
        {
            "COST_ORDER_CLIENT_IDS": "15,22",
            "NORDEA_ORDER_NUMBER_CLIENT_IDS": " 22 ; x ",
            "SOME_OTHER_IDS": "15",
            "EMPTY_CLIENT_IDS": "",
        }
    )
    assert found == {
        15: ["COST_ORDER_CLIENT_IDS"],
        22: ["COST_ORDER_CLIENT_IDS", "NORDEA_ORDER_NUMBER_CLIENT_IDS"],
    }


async def test_execute_deletes_only_confirmed_clients_and_reports_both_lists(
    clean_cleanup_state,
):
    confirmed = await _make_client(
        "zatwierdzony", external_id=f"tomb-{uuid.uuid4().hex[:8]}"
    )
    unconfirmed = await _make_client("po-podgladzie")
    with_contact = await _make_client("wstrzymany")
    with_job = await _make_client("zostaje")
    ids = [confirmed, unconfirmed, with_contact, with_job]
    admin = await _make_admin()
    import_run_id: int | None = None
    try:
        async with AsyncSessionLocal() as db:
            db.add(Contact(client_id=with_contact, name="Jan Kontakt"))
            db.add(Job(title="Rekrutacja", client_id=with_job))
            # Audyt manifestu portfela wskazuje na zatwierdzonego klienta.
            run = ClientImportRun(
                source_system="client_excel",
                source_filename="cleanup-test.xlsx",
                source_sha256=uuid.uuid4().hex * 2,
                status=ClientImportRunStatus.applied,
            )
            db.add(run)
            await db.flush()
            scope_id = await db.scalar(
                select(ClientPortfolioScope.id).where(
                    ClientPortfolioScope.client_id == confirmed
                )
            )
            import_row = ClientImportRow(
                import_run_id=run.id,
                sheet_name="Nieaktywni",
                row_number=1,
                source_name="Zatwierdzony",
                category=PortfolioCategory.inactive,
                status=ClientImportRowStatus.applied,
                matched_client_id=confirmed,
                portfolio_scope_id=scope_id,
            )
            db.add(import_row)
            await db.commit()
            import_run_id, import_row_id = run.id, import_row.id

        async with AsyncSessionLocal() as db:
            await execute_inactive_client_cleanup(
                db,
                actor=admin,
                confirmed_client_ids=[confirmed],
                restrict_ids=ids,
                environ={},
            )
            await db.commit()

        async with AsyncSessionLocal() as db:
            remaining = set(
                (
                    await db.execute(select(Client.id).where(Client.id.in_(ids)))
                ).scalars()
            )
            assert remaining == {unconfirmed, with_contact, with_job}
            assert (
                await db.scalar(
                    select(ClientPortfolioScope.id).where(
                        ClientPortfolioScope.client_id == confirmed
                    )
                )
                is None
            )

            row = await db.get(ClientImportRow, import_row_id)
            assert row is not None
            assert row.purged_at is not None
            assert row.purged_client_id == confirmed
            assert row.matched_client_id is None
            assert row.portfolio_scope_id is None

            report = await load_cleanup_report(db)
            assert report is not None
            assert [item["client_id"] for item in report["deleted"]] == [confirmed]
            held = {item["client_id"]: item for item in report["held"]}
            assert set(held) == {unconfirmed, with_contact}
            assert (
                held[unconfirmed]["reasons"][-1]["code"] == "not_in_confirmed_preview"
            )
            assert held[with_contact]["reasons"][0]["table"] == "contacts"
            assert report["kept_count"] == 1
            assert report["deleted_count"] == 1
            assert report["held_count"] == 2

            audit = await db.scalar(
                select(Activity).where(
                    Activity.entity_type == "client",
                    Activity.entity_id == confirmed,
                    Activity.action == "purged_inactive_cleanup",
                )
            )
            assert audit is not None and audit.user_id == admin.id

            tombstones = await purged_external_ids(db, "traffit")
            purged = await db.scalar(
                select(PurgedClient).where(PurgedClient.client_id == confirmed)
            )
            assert purged is not None and purged.external_id in tombstones
            assert purged.snapshot["portfolio_scopes"][0]["category"] == "inactive"

        # Jednorazowość: drugie wykonanie odmawia, nawet z inną listą.
        async with AsyncSessionLocal() as db:
            with pytest.raises(CleanupAlreadyExecutedError):
                await execute_inactive_client_cleanup(
                    db,
                    actor=admin,
                    confirmed_client_ids=[unconfirmed],
                    restrict_ids=ids,
                    environ={},
                )
            await db.rollback()
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(Activity).where(
                    Activity.entity_type == "client", Activity.entity_id.in_(ids)
                )
            )
            if import_run_id is not None:
                await db.execute(
                    delete(ClientImportRun).where(ClientImportRun.id == import_run_id)
                )
            await db.execute(delete(User).where(User.id == admin.id))
            await db.commit()
        await _drop_clients(ids)


async def test_api_preview_execute_and_report(
    app_client, app_auth_headers, clean_cleanup_state
):
    target = await _make_client("api")
    try:
        preview = await app_client.get(
            "/api/clients/directory/inactive-cleanup/preview",
            headers=app_auth_headers,
        )
        assert preview.status_code == 200, preview.text
        body = preview.json()
        assert target in {item["client_id"] for item in body["to_delete"]}
        assert body["source_labels"]["orders"] == "Zamówienia"

        status_before = await app_client.get(
            "/api/clients/directory/inactive-cleanup", headers=app_auth_headers
        )
        assert status_before.status_code == 200
        assert status_before.json()["report"] is None

        executed = await app_client.post(
            "/api/clients/directory/inactive-cleanup/execute",
            json={"confirmed_client_ids": [target]},
            headers=app_auth_headers,
        )
        assert executed.status_code == 200, executed.text
        report = executed.json()
        assert [item["client_id"] for item in report["deleted"]] == [target]
        assert report["executed_at"]

        again = await app_client.post(
            "/api/clients/directory/inactive-cleanup/execute",
            json={"confirmed_client_ids": []},
            headers=app_auth_headers,
        )
        assert again.status_code == 409
        assert "jednorazowa" in again.json()["detail"]

        preview_after = await app_client.get(
            "/api/clients/directory/inactive-cleanup/preview",
            headers=app_auth_headers,
        )
        assert preview_after.status_code == 409

        status_after = await app_client.get(
            "/api/clients/directory/inactive-cleanup", headers=app_auth_headers
        )
        assert status_after.json()["report"]["deleted_count"] == 1
    finally:
        await _drop_clients([target])


async def test_traffit_sync_does_not_resurrect_a_purged_client(clean_cleanup_state):
    """Faza ``clients`` robi pełny skan co noc — nagrobek musi ją zatrzymać."""

    from app.services.traffit.importer import TraffitImporter

    class _FakePaginator:
        def __init__(self, rows: list[dict]) -> None:
            self._rows = rows

        async def total_count(self, path: str) -> int:  # noqa: ARG002
            return len(self._rows)

        async def get_paginated(self, path, page_size=100, **kwargs):  # noqa: ARG002
            for row in self._rows:
                yield row

    external_id = str(880_000 + int(uuid.uuid4().int % 10_000))
    admin = await _make_admin()
    async with AsyncSessionLocal() as db:
        run = ClientCleanupRun(
            kind=f"test-{uuid.uuid4().hex[:6]}",
            executed_at=datetime.now(timezone.utc),
            executed_by=admin.id,
            candidates_count=1,
            kept_count=0,
            deleted_count=1,
            held_count=0,
        )
        db.add(run)
        await db.flush()
        db.add(
            PurgedClient(
                run_id=run.id,
                client_id=-int(external_id),
                name="Usunięty",
                external_source="traffit",
                external_id=external_id,
            )
        )
        await db.commit()
    try:
        async with AsyncSessionLocal() as db:
            importer = TraffitImporter(
                _FakePaginator([{"id": int(external_id), "name": "Usunięty"}]),
                db,  # type: ignore[arg-type]
            )
            progress = await importer.import_clients()
            resurrected = await db.scalar(
                select(Client.id).where(
                    Client.external_source == "traffit",
                    Client.external_id == external_id,
                )
            )
        assert resurrected is None
        assert progress.skipped == 1
        assert progress.inserted == 0
    finally:
        async with AsyncSessionLocal() as db:
            # Gdyby nagrobek nie zadziałał, test nie może zostawić
            # „wskrzeszonego" klienta we wspólnej bazie.
            await db.execute(
                delete(Client).where(
                    Client.external_source == "traffit",
                    Client.external_id == external_id,
                )
            )
            await db.execute(delete(User).where(User.id == admin.id))
            await db.commit()


# ── Poprawki z przeglądu adwersarialnego ─────────────────────────────────────


async def test_pinned_contract_period_on_scope_counts_as_contract():
    """Daty umowy przypięte do zakresu portfela giną razem z klientem."""

    client_id = await _make_client("przypiete-daty")
    try:
        async with AsyncSessionLocal() as db:
            scope = await db.scalar(
                select(ClientPortfolioScope).where(
                    ClientPortfolioScope.client_id == client_id
                )
            )
            scope.contract_start_override = date(2022, 1, 1)
            scope.contract_end_override = date(2024, 12, 31)
            await db.commit()
        async with AsyncSessionLocal() as db:
            plan = await evaluate_inactive_clients(
                db, restrict_ids=[client_id], environ={}
            )
        assert _verdicts(plan)[client_id] == "keep"
        assert plan.kept[0].sources["contracts"] == 1
    finally:
        await _drop_clients([client_id])


async def test_name_only_references_keep_or_hold_the_client():
    """DynaReporter, B2B bez rekrutacji i sprzedaż wiążą klienta NAZWĄ."""

    tag = uuid.uuid4().hex[:6]
    in_dynareporter = await _make_client(f"dr {tag}")
    in_b2b = await _make_client(f"b2b {tag}")
    in_sales = await _make_client(f"sales {tag}")
    ids = [in_dynareporter, in_b2b, in_sales]
    async with AsyncSessionLocal() as db:
        names = dict(
            (
                await db.execute(
                    select(Client.id, Client.name).where(Client.id.in_(ids))
                )
            ).all()
        )
    admin = await _make_admin()
    seq = 100_000 + int(uuid.uuid4().int % 800_000)
    try:
        async with AsyncSessionLocal() as db:
            # Forma prawna i wielkość liter nie mogą zgubić dopasowania.
            await db.execute(
                text("INSERT INTO dr_clients (name) VALUES (:n)"),
                {"n": names[in_dynareporter].upper() + " SP. Z O.O."},
            )
            await db.execute(
                text(
                    "INSERT INTO b2b_generated_contracts "
                    "(year, seq, contract_number, client_name) "
                    "VALUES (2099, :seq, :num, :n)"
                ),
                {"seq": seq, "num": f"TEST/{seq}/2099", "n": names[in_b2b]},
            )
            await db.execute(
                text(
                    "INSERT INTO dr_sales_leads (user_id, week_start, company_name) "
                    "VALUES (:u, DATE '2099-01-05', :n)"
                ),
                {"u": admin.id, "n": names[in_sales]},
            )
            await db.commit()

        async with AsyncSessionLocal() as db:
            plan = await evaluate_inactive_clients(db, restrict_ids=ids, environ={})

        verdicts = _verdicts(plan)
        assert verdicts[in_dynareporter] == "keep"
        assert verdicts[in_b2b] == "keep"
        assert verdicts[in_sales] == "hold"
        kept = {item.client_id: item for item in plan.kept}
        assert kept[in_dynareporter].sources["cooperation_stats"] == 1
        assert kept[in_b2b].sources["contracts"] == 1
        reason = plan.held[0].as_dict()["reasons"][0]
        assert reason["code"] == "name_reference"
        assert reason["table"] == "dr_sales_leads"
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                text("DELETE FROM dr_clients WHERE name = :n"),
                {"n": names[in_dynareporter].upper() + " SP. Z O.O."},
            )
            await db.execute(
                text(
                    "DELETE FROM b2b_generated_contracts WHERE year = 2099 AND seq = :s"
                ),
                {"s": seq},
            )
            await db.execute(
                text("DELETE FROM dr_sales_leads WHERE user_id = :u"), {"u": admin.id}
            )
            await db.execute(delete(User).where(User.id == admin.id))
            await db.commit()
        await _drop_clients(ids)


async def test_boot_seeded_and_playbook_seed_clients_are_held():
    async with AsyncSessionLocal() as db:
        seeded = Client(name="Ministerstwo Sprawiedliwości", external_source="manual")
        pattern = Client(
            name=f"BNP Cleanup {uuid.uuid4().hex[:6]}", external_source="manual"
        )
        db.add_all([seeded, pattern])
        await db.flush()
        db.add_all(
            [
                ClientPortfolioScope(client_id=seeded.id),
                ClientPortfolioScope(client_id=pattern.id),
            ]
        )
        await db.commit()
        ids = [seeded.id, pattern.id]
    try:
        async with AsyncSessionLocal() as db:
            plan = await evaluate_inactive_clients(db, restrict_ids=ids, environ={})
        held = {item.client_id: item.as_dict()["reasons"] for item in plan.held}
        assert set(held) == set(ids)
        assert "boot_seed" in {reason["code"] for reason in held[ids[0]]}
        assert "playbook_seed" in {reason["code"] for reason in held[ids[1]]}
    finally:
        await _drop_clients(ids)


async def test_code_constant_and_model_foreign_key_signals():
    from app.services.inactive_client_cleanup_signals import (
        code_configured_client_ids,
        matching_playbook_patterns,
        model_client_foreign_keys,
        name_key,
    )

    from app.services import (
        cyfrowy_polsat_orders,
        ezdrowie,
        finance_order_matching,
        lotte_wedel_orders,
    )

    constants = code_configured_client_ids()
    # Żywe wartości, nie literały: conftest przestawia część stałych na ujemne,
    # żeby nie kolidowały z serialem `clients.id` w bazie testowej.
    for client_id in (
        ezdrowie.EZDROWIE_CLIENT_ID,
        finance_order_matching.POLKOMTEL_CLIENT_ID,
        lotte_wedel_orders.LOTTE_WEDEL_CLIENT_ID,
        cyfrowy_polsat_orders.CYFROWY_POLSAT_CLIENT_ID,
        35,  # Orlen — kanoniczne ID polityki odczytu PDF
        122,  # PFRON
    ):
        assert client_id in constants, client_id
    refs = {(table, column) for table, column, _code in model_client_foreign_keys()}
    assert ("contacts", "client_id") in refs
    assert ("client_portfolio_scopes", "client_id") in refs
    assert matching_playbook_patterns("BNP Paribas", ("%bnp%", "%pko%")) == ["%bnp%"]
    assert name_key("ACME SP. Z O.O.") == name_key("Acme") == "acme"


async def test_api_refuses_an_empty_execution(
    app_client, app_auth_headers, clean_cleanup_state
):
    """Pusta lista nie może zużyć jednorazowej operacji."""

    response = await app_client.post(
        "/api/clients/directory/inactive-cleanup/execute",
        json={"confirmed_client_ids": []},
        headers=app_auth_headers,
    )
    assert response.status_code == 422
    async with AsyncSessionLocal() as db:
        assert await db.scalar(select(ClientCleanupRun.id)) is None
