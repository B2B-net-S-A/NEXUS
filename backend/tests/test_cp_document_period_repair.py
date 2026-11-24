"""Okres dokumentu z nazwą pliku w NFD: Time Sheet za X zapisany przez czytnik na IX.

Przed #3866 ``mailbox.find_period`` nie łapał miesiąca w nazwie z Maca
(„paz” + akcent + „dziernik”) i okres brał się z tematu wątku („wrzesień”).
Naprawa przestawia przypięty dokument na okres z nazwy po NFC i przelicza
rozliczenia obu miesięcy; nie rusza dokumentu, który ktoś już zmienił.
"""

from __future__ import annotations

import uuid
import unicodedata
from datetime import date

import pytest
from sqlalchemy import select

from app.services.consultant_portal.mailbox import period_for
from app.services.cp_document_period_repair import (
    ERSTE_TIME_SHEET_X,
    TARGETS,
    period_from_nfd_name,
    summarize_for_log,
)

# Fikcyjna osoba; nazwa jak z Maca: „ź” rozłożone na „z” i akcent.
NFD_NAME = "Time Sheet - październik 2026 Jan Testowy.pdf"
NFC_NAME = unicodedata.normalize("NFC", NFD_NAME)


def test_nfd_name_gives_the_month_from_the_file_not_from_the_thread():
    assert NFC_NAME != NFD_NAME
    assert period_for(
        "Re: Timesheet wrzesień 2026 - Jan Testowy", NFD_NAME, date(2026, 11, 20)
    ) == (
        2026,
        10,
        False,
    )


def test_period_from_nfd_name_reads_only_decomposed_names():
    assert period_from_nfd_name(NFD_NAME) == (2026, 10)
    # Nazwa już w NFC: czytnik dał jej okres z nazwy, więc to nie ten błąd.
    assert period_from_nfd_name(NFC_NAME) is None
    assert period_from_nfd_name("Zaświadczenie.pdf") is None
    assert period_from_nfd_name(None) is None


def test_target_is_the_one_document_from_the_production_read():
    assert ERSTE_TIME_SHEET_X == (
        11,
        619,
        "report",
        "bbf003bfea50",
        (2026, 9),
        (2026, 10),
    )
    assert TARGETS == (ERSTE_TIME_SHEET_X,)


def test_summary_for_log_has_ids_periods_and_statuses_only():
    assert summarize_for_log(None) == "already applied"
    summary = {
        "fixed": 1,
        "requested": 2,
        "results": [
            {
                "document_id": 11,
                "old_period": "2026-09",
                "new_period": "2026-10",
                "skipped": None,
                "old_month": [
                    {"id": 1, "status_before": "checking", "status_after": "checking"}
                ],
                "new_month": [{"id": 7, "status_after": "ok"}],
            },
            {"document_id": 12, "skipped": "period_changed"},
        ],
    }
    assert summarize_for_log(summary) == (
        "fixed 1/2; document 11: 2026-09->2026-10; 2026-09 [#1 checking->checking]; "
        "2026-10 [#7 ok]; document 12: skipped period_changed"
    )


# ── na bazie ────────────────────────────────────────────────────────────────


async def _module_on() -> object:
    from sqlalchemy.dialects.postgresql import insert

    from app.core.database import AsyncSessionLocal
    from app.models.app_setting import AppSetting

    async with AsyncSessionLocal() as db:
        had = await db.get(AppSetting, "client_settlements")
        previous = had.value if had else None
        await db.execute(
            insert(AppSetting)
            .values(key="client_settlements", value={"enabled": True})
            .on_conflict_do_update(
                index_elements=[AppSetting.key], set_={"value": {"enabled": True}}
            )
        )
        await db.commit()
    return previous


async def _restore(previous: object, client_id: int, markers: list[str]) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.app_setting import AppSetting
    from app.models.client_settlement import ClientSettlement
    from app.models.consultant_portal import CpDocument
    from app.models.contract import Contract
    from tests.test_client_audit_2026_09_24 import _cleanup

    async with AsyncSessionLocal() as db:
        contract_ids = select(Contract.id).where(Contract.client_id == client_id)
        await db.execute(
            ClientSettlement.__table__.delete().where(
                ClientSettlement.client_id == client_id
            )
        )
        await db.execute(
            CpDocument.__table__.delete().where(
                CpDocument.contract_id.in_(contract_ids)
            )
        )
        await db.execute(
            AppSetting.__table__.delete().where(AppSetting.key.in_(markers))
        )
        if previous is None:
            await db.execute(
                AppSetting.__table__.delete().where(
                    AppSetting.key == "client_settlements"
                )
            )
        else:
            await db.execute(
                AppSetting.__table__.update()
                .where(AppSetting.key == "client_settlements")
                .values(value=previous)
            )
        await db.commit()
    await _cleanup(client_id)


async def _stored(contract_id: int, name: str, month: int) -> tuple[int, str]:
    """Plik z poczty, jak w czytniku: zapis zakłada i liczy rozliczenie miesiąca."""

    from app.core.database import AsyncSessionLocal
    from app.core.scheduling import local_now
    from app.services.consultant_portal import documents

    async with AsyncSessionLocal() as db:
        stored = await documents.store(
            db,
            contract_id=contract_id,
            kind="report",
            year=2026,
            month=month,
            content=b"%PDF-1.4 fikcyjny time sheet " + uuid.uuid4().hex.encode(),
            file_name=name,
            channel="mailbox",
            now=local_now(),
            graph_message_id=f"test-nfd-{uuid.uuid4().hex}",
        )
        await db.commit()
        return stored.document.id, stored.document.sha256


async def _settlements(contract_id: int) -> dict[str, tuple[str, int | None]]:
    from app.core.database import AsyncSessionLocal
    from app.models.client_settlement import ClientSettlement

    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(
                    ClientSettlement.period_month,
                    ClientSettlement.status,
                    ClientSettlement.report_document_id,
                ).where(ClientSettlement.contract_id == contract_id)
            )
        ).all()
    return {month: (status, report) for month, status, report in rows}


async def _period(document_id: int) -> tuple[int, int]:
    from app.core.database import AsyncSessionLocal
    from app.models.consultant_portal import CpDocument

    async with AsyncSessionLocal() as db:
        document = await db.get(CpDocument, document_id)
        return document.period_year, document.period_month


@pytest.mark.asyncio
async def test_repair_moves_the_document_recomputes_both_months_and_runs_once(
    tmp_path, monkeypatch
):
    from app.core.database import AsyncSessionLocal
    from app.models.app_setting import AppSetting
    from app.services import storage_service
    from app.services.cp_document_period_repair import (
        Target,
        run_cp_document_period_repair,
    )
    from tests.test_client_audit_2026_09_24 import _candidate, _client, _contract

    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    marker = f"test_nfd_period_{uuid.uuid4().hex[:8]}"
    previous = await _module_on()
    client_id = await _client()
    try:
        contract_id = await _contract(client_id, await _candidate())
        document_id, sha = await _stored(contract_id, NFD_NAME, 9)
        before = await _settlements(contract_id)
        assert before["2026-09"][1] == document_id
        assert "2026-10" not in before

        target = Target(
            document_id, contract_id, "report", sha[:12], (2026, 9), (2026, 10)
        )
        async with AsyncSessionLocal() as db:
            summary = await run_cp_document_period_repair(
                db, targets=(target,), marker=marker
            )
            await db.commit()

        assert summary["fixed"] == 1
        result = summary["results"][0]
        assert result["skipped"] is None
        assert await _period(document_id) == (2026, 10)
        after = await _settlements(contract_id)
        # IX bez pliku: przeliczone, bez dokumentu; X liczy się z pliku za X.
        assert after["2026-09"][1] is None
        assert after["2026-10"][1] == document_id
        assert [s["report_document_id"] for s in result["old_month"]] == [None]
        assert [s["report_document_id"] for s in result["new_month"]] == [document_id]
        assert [s["kind"] for s in result["new_month"]] == ["actual"]

        async with AsyncSessionLocal() as db:
            receipt = await db.get(AppSetting, marker)
            assert receipt is not None and receipt.value == summary
            again = await run_cp_document_period_repair(
                db, targets=(target,), marker=marker
            )
            await db.rollback()
        assert again is None
    finally:
        await _restore(previous, client_id, [marker])


@pytest.mark.asyncio
async def test_repair_skips_documents_that_are_not_the_nfd_case(tmp_path, monkeypatch):
    from app.core.database import AsyncSessionLocal
    from app.services import storage_service
    from app.services.cp_document_period_repair import (
        Target,
        run_cp_document_period_repair,
    )
    from tests.test_client_audit_2026_09_24 import _candidate, _client, _contract

    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    marker = f"test_nfd_period_skip_{uuid.uuid4().hex[:8]}"
    previous = await _module_on()
    client_id = await _client()
    try:
        contract_id = await _contract(client_id, await _candidate())
        composed_id, composed_sha = await _stored(contract_id, NFC_NAME, 9)
        nfd_id, nfd_sha = await _stored(contract_id, NFD_NAME, 9)
        fixed_id, fixed_sha = await _stored(
            contract_id, NFD_NAME.replace("Time", "Arkusz"), 10
        )
        before = await _settlements(contract_id)
        old, new = (2026, 9), (2026, 10)
        targets = (
            Target(composed_id, contract_id, "report", composed_sha[:12], old, new),
            Target(nfd_id, contract_id, "report", nfd_sha[:12], (2026, 8), new),
            Target(nfd_id, contract_id, "report", "0" * 12, old, new),
            Target(nfd_id, contract_id + 1, "report", nfd_sha[:12], old, new),
            Target(-1, contract_id, "report", nfd_sha[:12], old, new),
            Target(fixed_id, contract_id, "report", fixed_sha[:12], old, new),
        )
        async with AsyncSessionLocal() as db:
            summary = await run_cp_document_period_repair(
                db, targets=targets, marker=marker
            )
            await db.commit()

        assert summary["fixed"] == 0
        assert [r["skipped"] for r in summary["results"]] == [
            "name_period_mismatch",
            "period_changed",
            "identity_mismatch",
            "identity_mismatch",
            "document_missing",
            "already_fixed",
        ]
        assert await _period(composed_id) == old
        assert await _period(nfd_id) == old
        assert await _settlements(contract_id) == before
    finally:
        await _restore(previous, client_id, [marker])


@pytest.mark.asyncio
async def test_accepted_old_month_is_left_to_people(tmp_path, monkeypatch):
    from sqlalchemy import update

    from app.core.database import AsyncSessionLocal
    from app.models.client_settlement import ClientSettlement
    from app.services import storage_service
    from app.services.cp_document_period_repair import (
        Target,
        run_cp_document_period_repair,
    )
    from tests.test_client_audit_2026_09_24 import _candidate, _client, _contract

    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    marker = f"test_nfd_period_accepted_{uuid.uuid4().hex[:8]}"
    previous = await _module_on()
    client_id = await _client()
    try:
        contract_id = await _contract(client_id, await _candidate())
        document_id, sha = await _stored(contract_id, NFD_NAME, 9)
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(ClientSettlement)
                .where(
                    ClientSettlement.contract_id == contract_id,
                    ClientSettlement.period_month == "2026-09",
                )
                .values(status="accepted")
            )
            await db.commit()

        target = Target(
            document_id, contract_id, "report", sha[:12], (2026, 9), (2026, 10)
        )
        async with AsyncSessionLocal() as db:
            summary = await run_cp_document_period_repair(
                db, targets=(target,), marker=marker
            )
            await db.commit()

        old_month = summary["results"][0]["old_month"]
        assert [(s["status_before"], s["status_after"]) for s in old_month] == [
            ("accepted", "accepted")
        ]
        after = await _settlements(contract_id)
        assert after["2026-09"] == ("accepted", document_id)
        assert after["2026-10"][1] == document_id
    finally:
        await _restore(previous, client_id, [marker])
