"""Poprawki z przeglądu 16.10.2026 (A2, A3, F26–F28) — scalanie i sprzęt.

* A2 — scalenie duplikatu kontraktu zna tabele „Ludzi w NEXUSIE” i ma regułę
  duplikatu dla każdej, która ma unikat albo klucz automatu po kontrakcie,
* A3 — uczestnik Akademii z niezwróconym sprzętem blokuje usunięcie i scalenie
  kandydata (409); zwrócone wydanie traci posiadacza, historia zostaje,
* F26 — sprzęt na kontrakcie usuniętej osoby da się zwrócić,
* F27 — lokalizacja egzemplarza przechodzi przez D10, krótki PIN tylko z etykietą,
* F28 — numer dłuższy niż kolumna: 422 w formularzu, „do wyjaśnienia” w imporcie.

Dane fikcyjne (repo jest publiczne): osoby „Przykładowe”, numery „TEST…”.
"""

from __future__ import annotations

import io
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import openpyxl
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.academy import AcademyApplication
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus, RateUnit
from app.models.equipment import (
    EquipmentAssignment,
    EquipmentImportBatch,
    EquipmentImportRow,
    EquipmentItem,
    EquipmentModel,
)
from app.models.user import User, UserRole
from app.services import equipment_schema
from app.services.contract_merge import (
    ContractMergeManifest,
    _automation_slot,
    _split_slot_duplicates,
    apply_contract_merge_plan,
    approval_fingerprint,
    build_contract_merge_plan,
)
from app.services.equipment import identifiers, importer, registry, sanitize
from tests.test_candidate_merge import _merge, _preview
from tests.test_candidate_merge import _user as _login_user
from tests.test_equipment_api import (
    _headers,
    _item,
    _model,
    _tag,
    make_academy_participant,
    make_people,
    modules_state,
)


@pytest_asyncio.fixture
async def modules_on():
    async with modules_state(True):
        yield


@pytest_asyncio.fixture
async def people():
    return await make_people()


# ── A2: scalenie duplikatu kontraktu ──────────────────────────────────────────


def test_slot_rule_prefers_a_decided_row_then_the_survivor():
    survivor, loser = 10, 11
    rows = [
        {"id": 1, "contract_id": survivor, "status": "open", "slot": "a"},
        {"id": 2, "contract_id": loser, "status": "done", "slot": "a"},
        {"id": 3, "contract_id": loser, "status": "open", "slot": "b"},
        {"id": 4, "contract_id": survivor, "status": "open", "slot": "b"},
        {"id": 5, "contract_id": loser, "status": "open", "slot": "c"},
    ]
    winners, losers = _split_slot_duplicates(
        rows,
        slot_of=lambda row: row["slot"],
        rank={"done": 0, "skipped": 1, "open": 2},
        survivor_id=survivor,
    )
    assert sorted(row["id"] for row in winners) == [2, 4, 5]
    assert sorted(row["id"] for row in losers) == [1, 3]


def test_automation_slot_reads_only_the_rows_own_key():
    assert _automation_slot({"contract_id": 7, "source_key": "contract:7:dl"}) == "dl"
    assert _automation_slot({"contract_id": 7, "source_key": "contract:8:dl"}) is None
    assert (
        _automation_slot({"contract_id": 7, "source_key": "contract:7:dl:merged:3"})
        is None
    )
    assert _automation_slot({"contract_id": 7, "source_key": None}) is None


async def _merge_users(db) -> tuple[User, User]:
    marker = uuid.uuid4().hex[:8]
    owner = User(
        email=f"merge-owner-{marker}@example.com",
        name=f"Opiekunka Przykładowa {marker}",
        role=UserRole.recruiter,
        roles=["recruiter"],
        is_active=True,
    )
    dl = User(
        email=f"merge-dl-{marker}@example.com",
        name=f"Lider Przykładowy {marker}",
        role=UserRole.delivery_lead,
        roles=["delivery_lead"],
        is_active=True,
    )
    db.add_all([owner, dl])
    await db.flush()
    return owner, dl


async def _merge_pair(
    db, *, suffix: str
) -> tuple[Candidate, Client, Contract, Contract]:
    today = business_today()
    candidate = Candidate(
        name="Scalana",
        lastname=f"Przykładowa-{suffix}",
        email=f"hr-merge-{suffix}@example.com",
    )
    client = Client(name=f"Klient Scalenia {suffix}")
    db.add_all([candidate, client])
    await db.flush()
    survivor = Contract(
        candidate_id=candidate.id,
        client_id=client.id,
        status=ContractStatus.active,
        start_date=today - timedelta(days=60),
        rate_candidate=Decimal("100.000"),
        rate_client=Decimal("150.000"),
        margin=Decimal("50.000"),
        rate_unit=RateUnit.hourly,
        billing_hours_per_month=160,
        currency="PLN",
    )
    loser = Contract(
        candidate_id=candidate.id,
        client_id=client.id,
        status=ContractStatus.draft,
        start_date=today - timedelta(days=60),
        rate_unit=RateUnit.hourly,
        billing_hours_per_month=160,
        currency="PLN",
    )
    db.add_all([survivor, loser])
    await db.flush()
    return candidate, client, survivor, loser


async def _insert(db, sql: str, **params) -> int:
    return int((await db.execute(text(sql + " RETURNING id"), params)).scalar_one())


async def _bonus(db, contract_id: int, recipient: int, role: str, status: str) -> int:
    return await _insert(
        db,
        "INSERT INTO hr_bonuses (recipient_user_id, amount, currency, category, "
        "period_year, period_month, status, source, source_key, contract_id, "
        "assigned_at) VALUES (:recipient, 500, 'PLN', :category, 2026, 10, "
        "CAST(:status AS VARCHAR), 'contract_placement', :key, :contract, "
        "CASE WHEN CAST(:assigned AS BOOLEAN) THEN now() END)",
        recipient=recipient,
        category="recruiter" if role == "recruiter" else "delivery_lead",
        status=status,
        assigned=status == "assigned",
        key=f"contract:{contract_id}:{role}",
        contract=contract_id,
    )


async def _cleanup_merge(ids: dict) -> None:
    async with AsyncSessionLocal() as db:
        await db.rollback()
        for table, key in (
            ("hr_bonuses", "bonuses"),
            ("admin_cases", "cases"),
            ("equipment_import_batches", "batches"),
        ):
            if ids.get(key):
                await db.execute(
                    text(f"DELETE FROM {table} WHERE id = ANY(:ids)"),
                    {"ids": ids[key]},
                )
        if ids.get("contracts"):
            await db.execute(
                delete(Activity).where(
                    Activity.external_source == "contract_merge_2026_08",
                    Activity.entity_id.in_(ids["contracts"]),
                )
            )
            await db.execute(
                text("DELETE FROM equipment_protocols WHERE contract_id = ANY(:ids)"),
                {"ids": ids["contracts"]},
            )
            await db.execute(delete(Contract).where(Contract.id.in_(ids["contracts"])))
        if ids.get("items"):
            await db.execute(
                delete(EquipmentItem).where(EquipmentItem.id.in_(ids["items"]))
            )
        if ids.get("candidate"):
            await db.execute(delete(Candidate).where(Candidate.id == ids["candidate"]))
        if ids.get("client"):
            await db.execute(delete(Client).where(Client.id == ids["client"]))
        if ids.get("users"):
            await db.execute(delete(User).where(User.id.in_(ids["users"])))
        await db.commit()


async def test_contract_merge_carries_every_hr_table_with_duplicate_rules():
    """Duplikat z danymi w każdej z dziesięciu nowych tabel i z opiekunem.

    Przed poprawką scalenie odmawiało (``unknown_contract_foreign_keys``), a bez
    reguł duplikatu przepięcie wpadałoby na UNIQUE planu kontaktów i indeks
    aktywnego wpisu „Do przepięcia”, a premie i zadania recepcji dublowałyby się.
    """
    suffix = uuid.uuid4().hex[:10]
    today = business_today()
    now = datetime.now(timezone.utc)
    ids: dict = {}
    try:
        async with AsyncSessionLocal() as db:
            owner, dl = await _merge_users(db)
            owner_id = owner.id
            ids["users"] = [owner_id, dl.id]
            candidate, client, survivor, loser = await _merge_pair(db, suffix=suffix)
            sid, lid = survivor.id, loser.id
            ids.update(contracts=[sid, lid], candidate=candidate.id, client=client.id)
            await db.execute(
                text("UPDATE contracts SET care_owner_user_id = :u WHERE id = :id"),
                {"u": owner.id, "id": lid},
            )
            conversation = await _insert(
                db,
                "INSERT INTO care_conversations (contract_id, author_user_id, "
                "occurred_on) VALUES (:c, :u, :d)",
                c=lid,
                u=owner.id,
                d=today - timedelta(days=50),
            )
            plan = {}
            for key, contract, kind, seq, status in (
                ("s_day7_open", sid, "day_7", 0, "open"),
                ("l_day7_done", lid, "day_7", 0, "done"),
                ("s_day30_done", sid, "day_30", 0, "done"),
                ("l_day30_open", lid, "day_30", 0, "open"),
                ("l_quarter", lid, "quarterly", 1, "open"),
            ):
                plan[key] = await _insert(
                    db,
                    "INSERT INTO contract_care_plan_items (contract_id, kind, seq, "
                    "due_on, status, done_conversation_id, resolved_at) "
                    "VALUES (:c, :k, :seq, :due, :st, :conv, :res)",
                    c=contract,
                    k=kind,
                    seq=seq,
                    due=today - timedelta(days=40),
                    st=status,
                    conv=conversation if key == "l_day7_done" else None,
                    res=now if status == "done" else None,
                )
            redeploy = {}
            for key, contract, reason, status in (
                ("s_change_open", sid, "wants_change", "open"),
                ("l_change_progress", lid, "wants_change", "in_progress"),
                ("l_end_open", lid, "project_end", "open"),
            ):
                redeploy[key] = await _insert(
                    db,
                    "INSERT INTO redeploy_queue_items (contract_id, reason, status) "
                    "VALUES (:c, :r, :st)",
                    c=contract,
                    r=reason,
                    st=status,
                )
            card = await _insert(
                db,
                "INSERT INTO tech_cards (contract_id, client_id, interview_on) "
                "VALUES (:c, :client, :d)",
                c=lid,
                client=client.id,
                d=today - timedelta(days=20),
            )
            case_id = await _insert(
                db,
                "INSERT INTO admin_cases (title, contract_id) VALUES (:t, :c)",
                t=f"Wejście konsultanta {suffix}",
                c=lid,
            )
            ids["cases"] = [case_id]
            model = EquipmentModel(category="laptop", name=f"Laptop Scalenia {suffix}")
            db.add(model)
            await db.flush()
            item = EquipmentItem(
                model_id=model.id, serial_number=f"TESTMERGE{suffix}".upper()
            )
            db.add(item)
            await db.flush()
            ids["items"] = [item.id]
            protocol = await _insert(
                db,
                "INSERT INTO equipment_protocols (kind, year, seq, number, "
                "protocol_date, contract_id, holder_name, issuer_name, "
                "template_version) VALUES ('wydanie', 2099, :seq, :no, :d, :c, "
                "'Scalana Przykładowa', 'Recepcja', 'v1')",
                seq=int(uuid.uuid4().int % 2_000_000_000) + 1,
                no=f"TEST/{suffix}",
                d=today,
                c=lid,
            )
            assignment = await _insert(
                db,
                "INSERT INTO equipment_assignments (item_id, contract_id, "
                "issue_protocol_id) VALUES (:i, :c, :p)",
                i=item.id,
                c=lid,
                p=protocol,
            )
            tasks = {}
            for key, contract, kind, slot, status in (
                ("s_start_open", sid, "wydanie", "start", "otwarte"),
                ("l_start_done", lid, "wydanie", "start", "zrobione"),
                ("l_end_open", lid, "zwrot", "end", "otwarte"),
            ):
                tasks[key] = await _insert(
                    db,
                    "INSERT INTO equipment_tasks (kind, status, title, contract_id, "
                    "source_key) VALUES (:k, :st, 'Zadanie testowe', :c, :key)",
                    k=kind,
                    st=status,
                    c=contract,
                    key=f"contract:{contract}:{slot}",
                )
            batch = await _insert(
                db,
                "INSERT INTO equipment_import_batches (file_name, file_sha256) "
                "VALUES ('test.xlsx', :sha)",
                sha="0" * 64,
            )
            ids["batches"] = [batch]
            import_row = await _insert(
                db,
                "INSERT INTO equipment_import_rows (batch_id, sheet, row_number, "
                "decision, holder_contract_id) VALUES (:b, 'LAPTOPY', 2, "
                "'do_wyjasnienia', :c)",
                b=batch,
                c=lid,
            )
            bonuses = {
                "s_dl_proposed": await _bonus(db, sid, dl.id, "dl", "proposed"),
                "l_dl_assigned": await _bonus(db, lid, dl.id, "dl", "assigned"),
                "l_recruiter": await _bonus(db, lid, owner.id, "recruiter", "proposed"),
            }
            bonuses["l_manual"] = await _insert(
                db,
                "INSERT INTO hr_bonuses (recipient_user_id, amount, currency, "
                "category, period_year, period_month, source, contract_id) "
                "VALUES (:r, 100, 'PLN', 'custom', 2026, 10, 'manual', :c)",
                r=owner.id,
                c=lid,
            )
            ids["bonuses"] = list(bonuses.values())
            await db.commit()

            manifest = ContractMergeManifest(same_client_groups=((sid, lid),))
            audit = await build_contract_merge_plan(db, manifest, today=today)
            assert audit["global_blockers"] == []
            group = audit["groups"][0]
            assert group["survivor_id"] == sid
            assert group["blockers"] == []
            loser_children = group["child_row_ids"][str(lid)]
            assert loser_children["tech_cards"] == [card]
            assert loser_children["equipment_import_rows"] == [import_row]
            await db.rollback()

            applied = await apply_contract_merge_plan(
                db,
                manifest,
                expected_fingerprint=audit["fingerprint"],
                expected_approval_fingerprint=approval_fingerprint(
                    audit["fingerprint"]
                ),
                today=today,
            )
            await db.commit()
            moved = applied["applied"][0]["reparented"]
            assert moved["contract_care_plan_items_duplicates_removed"] == 2
            assert moved["redeploy_queue_items_duplicates_dismissed"] == 1
            assert moved["equipment_tasks_duplicates_closed"] == 1
            assert moved["hr_bonuses_duplicates_cancelled"] == 1

            def rows(sql: str):
                return db.execute(text(sql), {"ids": [sid, lid]})

            assert (
                await db.scalar(
                    text("SELECT count(*) FROM contracts WHERE id = :l"), {"l": lid}
                )
                == 0
            )
            assert (
                await db.scalar(
                    text("SELECT care_owner_user_id FROM contracts WHERE id = :s"),
                    {"s": sid},
                )
                == owner_id
            )
            assert (
                await db.scalar(
                    text("SELECT contract_id FROM care_conversations WHERE id = :id"),
                    {"id": conversation},
                )
                == sid
            )
            # Plan: zrobiony punkt wygrywa z otwartym, bez dwóch punktów na termin.
            plan_rows = {
                (row.kind, row.status): row.id
                for row in await rows(
                    "SELECT id, kind, status FROM contract_care_plan_items "
                    "WHERE contract_id = ANY(:ids)"
                )
            }
            assert plan_rows == {
                ("day_7", "done"): plan["l_day7_done"],
                ("day_30", "done"): plan["s_day30_done"],
                ("quarterly", "open"): plan["l_quarter"],
            }
            assert (
                await db.scalar(
                    text(
                        "SELECT done_conversation_id FROM contract_care_plan_items "
                        "WHERE id = :id"
                    ),
                    {"id": plan["l_day7_done"]},
                )
                == conversation
            )
            # „Do przepięcia”: jeden aktywny na powód, nadmiarowy zostaje jako ślad.
            queue = {
                row.id: (row.contract_id, row.status, row.resolved_at is not None)
                for row in await rows(
                    "SELECT id, contract_id, status, resolved_at "
                    "FROM redeploy_queue_items WHERE contract_id = ANY(:ids)"
                )
            }
            assert queue == {
                redeploy["s_change_open"]: (sid, "dismissed", True),
                redeploy["l_change_progress"]: (sid, "in_progress", False),
                redeploy["l_end_open"]: (sid, "open", False),
            }
            for table, row_id in (
                ("tech_cards", card),
                ("admin_cases", case_id),
                ("equipment_protocols", protocol),
                ("equipment_assignments", assignment),
            ):
                assert (
                    await db.scalar(
                        text(f"SELECT contract_id FROM {table} WHERE id = :id"),
                        {"id": row_id},
                    )
                    == sid
                ), table
            assert (
                await db.scalar(
                    text(
                        "SELECT holder_contract_id FROM equipment_import_rows "
                        "WHERE id = :id"
                    ),
                    {"id": import_row},
                )
                == sid
            )
            # Zadania recepcji: zrobione wygrywa, przejmuje klucz zachowanego.
            task_rows = {
                row.id: (row.contract_id, row.status, row.source_key)
                for row in await rows(
                    "SELECT id, contract_id, status, source_key FROM equipment_tasks "
                    "WHERE contract_id = ANY(:ids)"
                )
            }
            assert task_rows == {
                tasks["l_start_done"]: (sid, "zrobione", f"contract:{sid}:start"),
                tasks["s_start_open"]: (
                    sid,
                    "anulowane",
                    f"contract:{sid}:start:merged:{tasks['s_start_open']}",
                ),
                tasks["l_end_open"]: (sid, "otwarte", f"contract:{sid}:end"),
            }
            # Premie: zatwierdzona zostaje, dublująca propozycja anulowana.
            bonus_rows = {
                row.id: (
                    row.contract_id,
                    row.status,
                    row.source_key,
                    row.cancel_reason,
                )
                for row in await rows(
                    "SELECT id, contract_id, status, source_key, cancel_reason "
                    "FROM hr_bonuses WHERE contract_id = ANY(:ids)"
                )
            }
            assert bonus_rows == {
                bonuses["l_dl_assigned"]: (sid, "assigned", f"contract:{sid}:dl", None),
                bonuses["s_dl_proposed"]: (
                    sid,
                    "cancelled",
                    f"contract:{sid}:dl:merged:{bonuses['s_dl_proposed']}",
                    "contract_merged",
                ),
                bonuses["l_recruiter"]: (
                    sid,
                    "proposed",
                    f"contract:{sid}:recruiter",
                    None,
                ),
                bonuses["l_manual"]: (sid, "proposed", None, None),
            }
            activity = await db.scalar(
                select(Activity).where(
                    Activity.entity_type == "contract",
                    Activity.entity_id == sid,
                    Activity.external_source == "contract_merge_2026_08",
                )
            )
            assert activity is not None
            assert "care_owner_user_id" in activity.details["changed_fields"]
            assert activity.details["reparented_rows"]["tech_cards"] == 1
    finally:
        await _cleanup_merge(ids)


async def _entry_case(db, contract_id: int, *, status: str, key: str | None) -> int:
    return await _insert(
        db,
        "INSERT INTO lifecycle_cases (kind, status, audience, contract_id, "
        "pending_name, start_date, source_key) VALUES ('onboarding', "
        "CAST(:st AS VARCHAR), 'consultant', :c, 'Scalana Przykładowa', :d, :key)",
        st=status,
        c=contract_id,
        d=business_today(),
        key=key,
    )


async def _entry_task(
    db,
    case_id: int,
    *,
    key: str,
    done_at: datetime | None = None,
    done_by: int | None = None,
) -> int:
    return await _insert(
        db,
        "INSERT INTO lifecycle_tasks (case_id, title, category, assignee_kind, "
        "status, done_at, done_by, key, source) VALUES (:case, :title, 'other', "
        "'care_owner', CAST(:st AS VARCHAR), :at, :by, :key, 'client')",
        case=case_id,
        title=f"Zadanie {key}",
        st="done" if done_at else "open",
        at=done_at,
        by=done_by,
        key=key,
    )


@pytest.mark.parametrize("survivor_has_entry", [True, False])
async def test_contract_merge_carries_care_rhythm_mails_and_consultant_entry(
    survivor_has_entry: bool,
):
    """Etap 3: rytm kontaktu, maile powitalne, odbiorcy komunikatów i wejście.

    Bez wpisu w katalogu FK scalenie odmawiało (``unknown_contract_foreign_keys``),
    a wejście konsultanta (bez FK) zostawało przy skasowanym kontrakcie — lista
    zadań znikała z zachowanego, a drugie żywe wejście łamało unikat kontraktu.
    """
    suffix = uuid.uuid4().hex[:10]
    today = business_today()
    ids: dict = {}
    try:
        async with AsyncSessionLocal() as db:
            owner, dl = await _merge_users(db)
            ids["users"] = [owner.id, dl.id]
            candidate, client, survivor, loser = await _merge_pair(db, suffix=suffix)
            sid, lid = survivor.id, loser.id
            ids.update(contracts=[sid, lid], candidate=candidate.id, client=client.id)
            cadence = await _insert(
                db,
                "INSERT INTO care_cadence_periods (contract_id, level, starts_on, "
                "reason, created_by) VALUES (:c, 'monthly', :d, 'new_at_client', :u)",
                c=lid,
                d=today,
                u=owner.id,
            )
            mail = await _insert(
                db,
                "INSERT INTO consultant_welcome_mails (contract_id, "
                "recipient_email, subject, body, delivery) VALUES (:c, "
                "'konsultant@example.com', 'Witaj', 'Treść testowa', 'simulated')",
                c=lid,
            )
            announcement = await _insert(
                db,
                "INSERT INTO care_announcements (code, subject, body) "
                "VALUES (:code, 'Komunikat testowy', 'Treść testowa')",
                code=uuid.uuid4().hex[:8].upper(),
            )
            ids["announcements"] = [announcement]
            recipient = await _insert(
                db,
                "INSERT INTO care_announcement_recipients (announcement_id, "
                "candidate_id, contract_id, email) VALUES (:a, :cand, :c, "
                "'konsultant@example.com')",
                a=announcement,
                cand=candidate.id,
                c=lid,
            )
            entries = {
                "l_live": await _entry_case(
                    db, lid, status="active", key=f"contract:{lid}:entry"
                ),
                "l_done": await _entry_case(db, lid, status="done", key=None),
            }
            if survivor_has_entry:
                entries["s_live"] = await _entry_case(
                    db, sid, status="active", key=f"contract:{sid}:entry"
                )
            # Postęp wejścia duplikatu: zrobione zadanie i sprawa administracja@.
            ticked_at = datetime(2026, 10, 12, 9, 30, tzinfo=timezone.utc)
            tasks = {
                "l_nda": await _entry_task(
                    db,
                    entries["l_live"],
                    key="pack:nda",
                    done_at=ticked_at,
                    done_by=owner.id,
                ),
                "l_mail": await _entry_task(db, entries["l_live"], key="welcome_mail"),
            }
            if survivor_has_entry:
                tasks["s_nda"] = await _entry_task(
                    db, entries["s_live"], key="pack:nda"
                )
                tasks["s_other"] = await _entry_task(
                    db, entries["s_live"], key="pack:vpn"
                )
                tasks["s_mail"] = await _entry_task(
                    db, entries["s_live"], key="welcome_mail"
                )
            admin_case = await _insert(
                db,
                "INSERT INTO admin_cases (title, area, source, source_key, "
                "contract_id, lifecycle_case_id) VALUES ('Wejście konsultanta: "
                "Scalana Przykładowa', 'onboarding', 'contract', :key, :c, :lc)",
                key=f"contract:{lid}:start",
                c=lid,
                lc=entries["l_live"],
            )
            ids["cases"] = [admin_case]
            await db.commit()

            manifest = ContractMergeManifest(same_client_groups=((sid, lid),))
            audit = await build_contract_merge_plan(db, manifest, today=today)
            assert audit["global_blockers"] == []
            assert audit["groups"][0]["blockers"] == []
            await db.rollback()
            applied = await apply_contract_merge_plan(
                db,
                manifest,
                expected_fingerprint=audit["fingerprint"],
                expected_approval_fingerprint=approval_fingerprint(
                    audit["fingerprint"]
                ),
                today=today,
            )
            await db.commit()
            moved = applied["applied"][0]["reparented"]
            assert moved["lifecycle_cases"] == 2
            assert moved["lifecycle_cases_cancelled"] == (
                1 if survivor_has_entry else 0
            )
            for table, row_id in (
                ("care_cadence_periods", cadence),
                ("consultant_welcome_mails", mail),
                ("care_announcement_recipients", recipient),
            ):
                assert (
                    await db.scalar(
                        text(f"SELECT contract_id FROM {table} WHERE id = :id"),
                        {"id": row_id},
                    )
                    == sid
                ), table
            cases = {
                row.id: (row.contract_id, row.status, row.source_key)
                for row in await db.execute(
                    text(
                        "SELECT id, contract_id, status, source_key "
                        "FROM lifecycle_cases WHERE id = ANY(:ids)"
                    ),
                    {"ids": list(entries.values())},
                )
            }
            if survivor_has_entry:
                assert cases == {
                    entries["s_live"]: (sid, "active", f"contract:{sid}:entry"),
                    entries["l_live"]: (sid, "cancelled", f"contract:{lid}:entry"),
                    entries["l_done"]: (sid, "done", None),
                }
            else:
                assert cases == {
                    entries["l_live"]: (sid, "active", f"contract:{sid}:entry"),
                    entries["l_done"]: (sid, "done", None),
                }
            state = {
                row.id: (row.status, row.done_by, row.done_at)
                for row in await db.execute(
                    text(
                        "SELECT id, status, done_by, done_at FROM lifecycle_tasks "
                        "WHERE id = ANY(:ids)"
                    ),
                    {"ids": list(tasks.values())},
                )
            }
            kept = entries["s_live"] if survivor_has_entry else entries["l_live"]
            if survivor_has_entry:
                # Zrobione u duplikatu przechodzi na to samo zadanie zachowanej
                # sprawy — z datą i osobą odhaczenia; reszta zostaje otwarta.
                assert state[tasks["s_nda"]] == ("done", ids["users"][0], ticked_at)
                assert state[tasks["s_other"]][0] == "open"
                mail_task = tasks["s_mail"]
            else:
                mail_task = tasks["l_mail"]
            # Kontrakt ma po scaleniu wysłany mail — zadanie maila zamknięte.
            assert state[mail_task][0] == "done"
            assert (
                await db.scalar(
                    text("SELECT lifecycle_case_id FROM admin_cases WHERE id = :id"),
                    {"id": admin_case},
                )
                == kept
            )
    finally:
        async with AsyncSessionLocal() as db:
            if ids.get("contracts"):
                await db.execute(
                    text("DELETE FROM lifecycle_cases WHERE contract_id = ANY(:ids)"),
                    {"ids": ids["contracts"]},
                )
            if ids.get("announcements"):
                await db.execute(
                    text("DELETE FROM care_announcements WHERE id = ANY(:ids)"),
                    {"ids": ids["announcements"]},
                )
            await db.commit()
        await _cleanup_merge(ids)


async def test_contract_merge_blocks_two_assigned_placement_bonuses_of_one_role():
    """Dwie zatwierdzone premie DL za jeden placement — scalenie czeka na Płace."""
    suffix = uuid.uuid4().hex[:10]
    ids: dict = {}
    try:
        async with AsyncSessionLocal() as db:
            owner, dl = await _merge_users(db)
            ids["users"] = [owner.id, dl.id]
            candidate, client, survivor, loser = await _merge_pair(db, suffix=suffix)
            ids.update(
                contracts=[survivor.id, loser.id],
                candidate=candidate.id,
                client=client.id,
            )
            first = await _bonus(db, survivor.id, dl.id, "dl", "assigned")
            second = await _bonus(db, loser.id, dl.id, "dl", "assigned")
            ids["bonuses"] = [first, second]
            await db.commit()
            audit = await build_contract_merge_plan(
                db,
                ContractMergeManifest(same_client_groups=((survivor.id, loser.id),)),
                today=business_today(),
            )
            await db.rollback()
        blockers = audit["groups"][0]["blockers"]
        assert {
            "code": "placement_bonus_assigned_twice",
            "items": [{"role": "dl", "bonus_ids": sorted([first, second])}],
        } in blockers
    finally:
        await _cleanup_merge(ids)


# ── A3: uczestnik Akademii ze sprzętem ────────────────────────────────────────


async def _academy_assignment(application_id: int, *, returned: bool) -> int:
    issued = datetime.now(timezone.utc) - timedelta(days=3)
    async with AsyncSessionLocal() as db:
        model = EquipmentModel(category="laptop", name=f"Laptop Akademii {_tag()}")
        db.add(model)
        await db.flush()
        item = EquipmentItem(model_id=model.id, serial_number=f"TESTAK{_tag()}")
        db.add(item)
        await db.flush()
        assignment = EquipmentAssignment(
            item_id=item.id,
            academy_application_id=application_id,
            issued_at=issued,
            returned_at=issued + timedelta(days=1) if returned else None,
            return_condition="sprawny" if returned else None,
        )
        db.add(assignment)
        await db.commit()
        return assignment.id


async def _assignment(assignment_id: int) -> EquipmentAssignment | None:
    async with AsyncSessionLocal() as db:
        return await db.get(EquipmentAssignment, assignment_id)


async def test_active_academy_assignment_cannot_lose_its_holder():
    """Schemat: aktywne wydanie z dokładnie jednym posiadaczem, zwrócone — z co
    najwyżej jednym. Baza sama odrzuci wyzerowanie aktywnego wydania."""
    person = await make_academy_participant()
    active = await _academy_assignment(person["application_id"], returned=False)
    returned = await _academy_assignment(person["application_id"], returned=True)
    async with AsyncSessionLocal() as db:
        await db.execute(
            text(
                "UPDATE equipment_assignments SET academy_application_id = NULL "
                "WHERE id = :id"
            ),
            {"id": returned},
        )
        await db.commit()
        with pytest.raises(IntegrityError):
            await db.execute(
                text(
                    "UPDATE equipment_assignments SET academy_application_id = NULL "
                    "WHERE id = :id"
                ),
                {"id": active},
            )
        await db.rollback()


async def test_candidate_delete_with_returned_academy_equipment_succeeds(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Przed poprawką FK ``RESTRICT`` wywracał usunięcie (RODO) na 500."""
    person = await make_academy_participant()
    assignment_id = await _academy_assignment(person["application_id"], returned=True)

    response = await app_client.delete(
        f"/api/candidates/{person['candidate_id']}", headers=app_auth_headers
    )
    assert response.status_code == 204, response.text

    kept = await _assignment(assignment_id)
    assert kept is not None and kept.academy_application_id is None
    assert kept.returned_at is not None
    async with AsyncSessionLocal() as db:
        history = await registry.assignment_history(
            db, where=EquipmentAssignment.id == assignment_id
        )
    assert history[0]["holder"]["name"] == registry.DELETED_PERSON


async def test_candidate_delete_with_active_academy_equipment_is_409(
    app_client: AsyncClient, app_auth_headers: dict
):
    person = await make_academy_participant()
    assignment_id = await _academy_assignment(person["application_id"], returned=False)

    response = await app_client.delete(
        f"/api/candidates/{person['candidate_id']}", headers=app_auth_headers
    )
    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "academy_equipment_active"
    assert "zwrot sprzętu" in detail["message"]
    async with AsyncSessionLocal() as db:
        assert await db.get(Candidate, person["candidate_id"]) is not None
        assert await db.get(AcademyApplication, person["application_id"]) is not None
    still = await _assignment(assignment_id)
    assert still is not None
    assert still.academy_application_id == person["application_id"]


async def test_candidate_merge_respects_academy_equipment(app_client: AsyncClient):
    """Scalenie kasuje przegrane zgłoszenie tego samego programu — z aktywnym
    wydaniem 409, ze zwróconym przechodzi, a wydanie traci posiadacza."""
    _, headers = await _login_user(app_client, UserRole.admin)
    duplicate = await make_academy_participant(status="rejected")
    survivor = await make_academy_participant(
        status="to_call", program_id=duplicate["program_id"]
    )
    async with AsyncSessionLocal() as db:
        # Odrzucenie wygrywa (Akademia pamięta „nie”), więc znika zgłoszenie
        # ocalałego — świeższe, bez decyzji.
        await db.execute(
            text(
                "UPDATE academy_applications SET applied_at = now(), "
                "closed_at = NULL WHERE id = :id"
            ),
            {"id": survivor["application_id"]},
        )
        await db.commit()
    assignment_id = await _academy_assignment(
        survivor["application_id"], returned=False
    )

    preview = await _preview(
        app_client, headers, survivor["candidate_id"], duplicate["candidate_id"]
    )
    assert preview.status_code == 200, preview.text
    refused = await _merge(
        app_client,
        headers,
        survivor["candidate_id"],
        duplicate["candidate_id"],
        preview.json()["fingerprint"],
    )
    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"]["code"] == "academy_equipment_active"
    async with AsyncSessionLocal() as db:
        assert await db.get(Candidate, duplicate["candidate_id"]) is not None

    async with AsyncSessionLocal() as db:
        row = await db.get(EquipmentAssignment, assignment_id)
        row.returned_at = datetime.now(timezone.utc)
        row.return_condition = "sprawny"
        await db.commit()
    preview = await _preview(
        app_client, headers, survivor["candidate_id"], duplicate["candidate_id"]
    )
    merged = await _merge(
        app_client,
        headers,
        survivor["candidate_id"],
        duplicate["candidate_id"],
        preview.json()["fingerprint"],
    )
    assert merged.status_code == 200, merged.text
    kept = await _assignment(assignment_id)
    assert kept is not None and kept.academy_application_id is None


# ── F26: zwrot sprzętu z kontraktu usuniętej osoby ────────────────────────────


async def test_equipment_on_contract_of_deleted_person_can_be_returned(
    app_client, modules_on, people
) -> None:
    headers = _headers(people["reception"])
    token = _tag()
    async with AsyncSessionLocal() as db:
        candidate = Candidate(
            name="Ewa", lastname=f"Usuwana-{token}", email=f"f26-{token}@example.com"
        )
        client = Client(name=f"Klient F26 {token}")
        db.add_all([candidate, client])
        await db.flush()
        contract = Contract(
            candidate_id=candidate.id,
            client_id=client.id,
            status=ContractStatus.active,
            start_date=business_today() - timedelta(days=10),
        )
        db.add(contract)
        await db.commit()
        contract_id, candidate_id = contract.id, candidate.id
    model = await _model(app_client, headers, "laptop", "1500.00")
    item = await _item(app_client, headers, model["id"])
    issued = await app_client.post(
        "/api/equipment/issue",
        json={
            "holder_kind": "contract",
            "holder_id": contract_id,
            "lines": [{"item_id": item["id"]}],
        },
        headers=headers,
    )
    assert issued.status_code == 201, issued.text

    # Usunięcie osoby (RODO) zostawia kontrakt z pustym ``candidate_id``.
    async with AsyncSessionLocal() as db:
        await db.execute(delete(Candidate).where(Candidate.id == candidate_id))
        await db.commit()
        assert (
            await db.scalar(
                select(Contract.candidate_id).where(Contract.id == contract_id)
            )
            is None
        )

    own = await app_client.get(
        f"/api/equipment/holders/contract/{contract_id}", headers=headers
    )
    assert own.status_code == 200, own.text
    assert own.json()["holder"]["name"] == registry.DELETED_PERSON
    assert own.json()["holder"]["email"] is None
    detail = await app_client.get(f"/api/equipment/items/{item['id']}", headers=headers)
    assert detail.json()["holder"]["name"] == registry.DELETED_PERSON

    returned = await app_client.post(
        "/api/equipment/return",
        json={
            "lines": [
                {
                    "assignment_id": own.json()["active"][0]["assignment_id"],
                    "condition": "sprawny",
                }
            ]
        },
        headers=headers,
    )
    assert returned.status_code == 201, returned.text
    after = await app_client.get(f"/api/equipment/items/{item['id']}", headers=headers)
    assert after.json()["status"] == "na_stanie"
    # Na kontrakt usuniętej osoby nowego sprzętu nie wydajemy (zwrot tak, wydanie nie).
    again = await app_client.post(
        "/api/equipment/issue",
        json={
            "holder_kind": "contract",
            "holder_id": contract_id,
            "lines": [{"item_id": item["id"]}],
        },
        headers=headers,
    )
    assert again.status_code == 422, again.text


# ── F27: D10 w lokalizacji, krótki PIN z etykietą ─────────────────────────────


@pytest.mark.parametrize(
    "value",
    [
        "Telefon służbowy, PIN 1234",
        "kod pin: 0000",
        "PIN do karty: 43210",
        "Zmieniono PIN-u 9876 na prośbę",
        "PIN-123456",
    ],
)
def test_short_pin_with_label_is_removed(value: str) -> None:
    cleaned = sanitize.clean_text(value)
    assert "kod PIN" in cleaned.reasons
    assert not any(ch.isdigit() for ch in cleaned.value or "")


@pytest.mark.parametrize(
    "value",
    [
        "Pokój 1234, szafa 2",
        "Zamówienie 4500123",
        "Pinezki 2000 szt.",
        "Shipping 1234",
        "PIN zmieniony",
    ],
)
def test_numbers_without_pin_label_stay(value: str) -> None:
    cleaned = sanitize.clean_text(value)
    assert cleaned.reasons == ()
    assert cleaned.value == value


def test_pin_rule_does_not_touch_identifier_columns() -> None:
    assert sanitize.clean_text("PIN1234", identifier=True).reasons == ()


async def test_item_location_goes_through_d10(app_client, modules_on, people) -> None:
    headers = _headers(people["reception"])
    model = await _model(app_client, headers, "telefon", "900.00")
    refused = await app_client.post(
        "/api/equipment/items",
        json={
            "model_id": model["id"],
            "serial_number": f"TEST{_tag()}",
            "location": "Szafa 3, PIN 4321",
        },
        headers=headers,
    )
    assert refused.status_code == 422, refused.text
    assert "Lokalizacja" in refused.text and "4321" not in refused.text
    private = await app_client.post(
        "/api/equipment/items",
        json={
            "model_id": model["id"],
            "serial_number": f"TEST{_tag()}",
            "location": "u jan.przykladowy@gmail.com",
        },
        headers=headers,
    )
    assert private.status_code == 422
    item = await _item(
        app_client, headers, model["id"], location="  Pokój   1234,  szafa 2 "
    )
    assert item["location"] == "Pokój 1234, szafa 2"
    patched = await app_client.patch(
        f"/api/equipment/items/{item['id']}",
        json={"location": "PIN: 0000"},
        headers=headers,
    )
    assert patched.status_code == 422


# ── F28: numer dłuższy niż kolumna ────────────────────────────────────────────


def test_identifier_limits_match_the_register_columns() -> None:
    columns = EquipmentItem.__table__.c
    assert identifiers.MAX_LENGTHS == {
        field: columns[field].type.length
        for field in equipment_schema.ITEM_UNIQUE_COLUMNS
    }


def test_too_long_identifier_is_a_polish_identifier_error() -> None:
    with pytest.raises(identifiers.IdentifierTooLong, match="najwyżej 40 znaków"):
        identifiers.normalize("inventory_number", "x" * 41)
    # „ß” → „SS”: 40 znaków na wejściu, 41 po normalizacji.
    with pytest.raises(identifiers.IdentifierTooLong):
        identifiers.normalize_identifiers({"inventory_number": "ß" + "a" * 39})
    assert identifiers.normalize("serial_number", "s" * 120) == "S" * 120


async def test_too_long_number_in_form_is_422(app_client, modules_on, people) -> None:
    headers = _headers(people["reception"])
    model = await _model(app_client, headers, "laptop", "1000.00")
    response = await app_client.post(
        "/api/equipment/items",
        json={"model_id": model["id"], "inventory_number": "ß" + "A" * 39},
        headers=headers,
    )
    assert response.status_code == 422, response.text
    assert "najwyżej 40 znaków" in response.text


def _long_serial_workbook(tag: str) -> bytes:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "LAPTOPY"
    sheet.append(["Nr\nLaptopa", "Model", "Numer seryjny / Service tag", "Użytkownik"])
    sheet.append([f"L1{tag}", "Dell Vostro 3530", "SN" + "7" * 130, "wolny"])
    sheet.append([None, "Dell Vostro 3530", "SN" + "8" * 130, "wolny"])
    sheet.append([f"L3{tag}", "Dell Vostro 3530", f"OK{tag}", "wolny"])
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


async def test_too_long_number_in_import_waits_for_review(
    app_client, modules_on, people
) -> None:
    """Przed poprawką wiersz szedł do „przyjmij”, a zatwierdzenie partii padało
    na VARCHAR(120) błędem 500 bez wskazania wiersza."""
    headers = _headers(people["reception"])
    tag = _tag()
    uploaded = await app_client.post(
        "/api/equipment/imports",
        files={
            "file": (
                "sprzet.xlsx",
                _long_serial_workbook(tag),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
        headers=headers,
    )
    assert uploaded.status_code == 201, uploaded.text
    batch = uploaded.json()
    detail = (
        await app_client.get(f"/api/equipment/imports/{batch['id']}", headers=headers)
    ).json()
    by_inventory = {row["data"].get("inventory_number"): row for row in detail["rows"]}
    with_inventory = by_inventory[f"L1{tag}"]
    assert with_inventory["decision"] == "do_wyjasnienia"
    assert with_inventory["data"]["serial_number"] is None
    assert "najwyżej 120 znaków" in with_inventory["reason"]
    only_long = by_inventory[None]
    assert only_long["decision"] == "do_wyjasnienia"
    assert "najwyżej 120 znaków" in only_long["reason"]
    assert by_inventory[f"L3{tag}"]["decision"] == "przyjmij"

    applied = await app_client.post(
        f"/api/equipment/imports/{batch['id']}/apply", headers=headers
    )
    assert applied.status_code == 200, applied.text
    assert applied.json() == {"created": 1, "conflicts": 0}


async def test_apply_of_a_legacy_row_with_too_long_number_is_not_500(
    app_client, modules_on, people
) -> None:
    """Partia zapisana przed sprawdzaniem długości: wiersz wraca „do wyjaśnienia”."""
    headers = _headers(people["reception"])
    tag = _tag()
    async with AsyncSessionLocal() as db:
        batch = EquipmentImportBatch(
            file_name="stary.xlsx", file_sha256="1" * 64, created_by=None
        )
        db.add(batch)
        await db.flush()
        db.add_all(
            [
                EquipmentImportRow(
                    batch_id=batch.id,
                    sheet="LAPTOPY",
                    row_number=2,
                    data={
                        "category": "laptop",
                        "model": "Dell Vostro 3530",
                        "inventory_number": "L" * 41,
                        "item_status": "na_stanie",
                    },
                    decision="przyjmij",
                ),
                EquipmentImportRow(
                    batch_id=batch.id,
                    sheet="LAPTOPY",
                    row_number=3,
                    data={
                        "category": "laptop",
                        "model": "Dell Vostro 3530",
                        "inventory_number": f"OK{tag}",
                        "item_status": "na_stanie",
                    },
                    decision="przyjmij",
                ),
            ]
        )
        await db.commit()
        batch_id = batch.id
    applied = await app_client.post(
        f"/api/equipment/imports/{batch_id}/apply", headers=headers
    )
    assert applied.status_code == 200, applied.text
    assert applied.json() == {"created": 1, "conflicts": 0}
    async with AsyncSessionLocal() as db:
        rows = {
            row.row_number: row
            for row in await db.scalars(
                select(EquipmentImportRow).where(
                    EquipmentImportRow.batch_id == batch_id
                )
            )
        }
    assert rows[2].decision == "do_wyjasnienia"
    assert "najwyżej 40 znaków" in rows[2].reason
    assert rows[3].applied_at is not None


def test_parser_keeps_the_row_and_marks_it_for_review() -> None:
    tag = _tag()
    parsed = importer.parse_workbook(_long_serial_workbook(tag))
    first = next(r for r in parsed.rows if r.data.get("inventory_number") == f"L1{tag}")
    assert first.data["serial_number"] is None
    assert first.needs_review and "120" in first.needs_review[0]
