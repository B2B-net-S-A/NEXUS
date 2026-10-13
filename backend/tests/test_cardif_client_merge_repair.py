"""Pełne scalenie klienta-duplikatu (BNP Paribas Cardif 52 → 38335, 13.10.2026).

Jednorazowa korekta przenosi wszystko, co wisi na duplikacie (rekrutacje
z procesami, kontakty, kartę klienta, alerty DL), wiąże podpisaną umowę bez
kontraktu z właściwym kontraktem i oznacza duplikat jako scalony. Wpis katalogu
duplikatu (zakres portfela, przydział DL) zostaje.

Baza testowa wspólna i nieczyszczona — własni klienci, własny token nazwy
i własny marker.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select, update

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.core.security import hash_password
from app.models.activity import Activity
from app.models.app_setting import AppSetting
from app.models.b2b_contract_detail import B2BContractDetail
from app.models.b2b_generated_contract import B2BGeneratedContract
from app.models.b2b_generated_contract_status_event import (
    B2BGeneratedContractStatusEvent,
)
from app.models.candidate import Candidate
from app.models.client import Client, ClientStatus
from app.models.client_directory import ClientPortfolioScope, PortfolioCategory
from app.models.client_playbook import ClientPlaybook
from app.models.client_playbook_event import ClientPlaybookEvent
from app.models.contact import Contact
from app.models.contract import Contract, ContractStatus, RateUnit
from app.models.critical_event import CriticalEvent
from app.models.dl_alert import DL_ALERT_STATUS_RESOLVED, DlAlert
from app.models.index_outbox import IndexOutboxEvent
from app.models.job import Job, JobStatus
from app.models.recruitment_process import RecruitmentProcess
from app.models.team_structure import DeliveryLeadClientAssignment
from app.models.user import User, UserRole
from app.services.cardif_client_merge_repair import (
    AgreementLink,
    CardifMergeTarget,
    run_cardif_client_merge,
    run_cardif_contract_fill,
    summarize_for_log,
)
from tests.test_client_deletion import _client
from tests.test_ezdrowie_client_merge_repair import _process

pytestmark = pytest.mark.asyncio

BACKEND = Path(__file__).resolve().parents[1]


async def _pair() -> tuple[int, int, str]:
    """Klient docelowy i duplikat z Traffita o wspólnym tokenie w nazwie."""

    token = f"scal{uuid.uuid4().hex[:8]}"
    canonical = await _client(f"{token} cel")
    source = await _client(
        f"{token} duplikat",
        status=ClientStatus.inactive,
        category=PortfolioCategory.inactive,
        external_id=f"tr{uuid.uuid4().hex[:8]}",
    )
    return canonical, source, token


async def _candidate() -> int:
    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        candidate = Candidate(
            name="Jan", lastname=f"Scalany-{suffix}", email=f"scal-{suffix}@example.com"
        )
        db.add(candidate)
        await db.commit()
        return candidate.id


async def _live_contract(client_id: int, candidate_id: int) -> int:
    async with AsyncSessionLocal() as db:
        contract = Contract(
            candidate_id=candidate_id,
            client_id=client_id,
            status=ContractStatus.active,
            start_date=business_today() - timedelta(days=30),
            rate_candidate=Decimal("100.000"),
            rate_client=Decimal("140.000"),
            rate_unit=RateUnit.hourly,
        )
        db.add(contract)
        await db.commit()
        return contract.id


async def _signed_agreement(
    client_id: int, candidate_id: int, *, contract_id: int | None = None
) -> tuple[int, str]:
    seq = 100000 + (uuid.uuid4().int % 800000)
    async with AsyncSessionLocal() as db:
        row = B2BGeneratedContract(
            year=2026,
            seq=seq,
            contract_number=f"{seq}/2026",
            partner_name="Jan Scalany",
            client_name="Nazwa wydrukowana",
            language="pl",
            candidate_id=candidate_id,
            client_id=client_id,
            contract_id=contract_id,
            signature_status="signed_both",
            contract_status="active",
            render_payload={"language": "pl", "client_name": "Nazwa wydrukowana"},
        )
        db.add(row)
        await db.commit()
        return row.id, row.contract_number


async def _closed_job(client_id: int) -> int:
    async with AsyncSessionLocal() as db:
        job = Job(
            title=f"Scalana-{uuid.uuid4().hex[:6]}",
            status=JobStatus.closed,
            client_id=client_id,
        )
        db.add(job)
        await db.commit()
        return job.id


async def _delivery_lead(*client_ids: int) -> int:
    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"scal-dl-{unique}@example.com",
            password_hash=hash_password(f"P4ss_{unique}!X"),
            name=f"Tester DL {unique}",
            role=UserRole.delivery_lead,
            roles=[UserRole.delivery_lead.value],
            is_active=True,
            profile_completed=True,
        )
        db.add(user)
        await db.flush()
        for client_id in client_ids:
            db.add(
                DeliveryLeadClientAssignment(
                    delivery_lead_user_id=user.id, client_id=client_id, is_head=True
                )
            )
        await db.commit()
        return user.id


async def _job_reindex_events(job_id: int) -> int:
    async with AsyncSessionLocal() as db:
        return int(
            await db.scalar(
                select(func.count(IndexOutboxEvent.id)).where(
                    IndexOutboxEvent.entity_type == "job",
                    IndexOutboxEvent.entity_id == job_id,
                )
            )
        )


async def _client_row(client_id: int) -> Client:
    async with AsyncSessionLocal() as db:
        return await db.get(Client, client_id)


async def _run(target: CardifMergeTarget, marker: str) -> dict | None:
    async with AsyncSessionLocal() as db:
        summary = await run_cardif_client_merge(db, target=target, marker=marker)
        await db.commit()
        return summary


async def test_merge_moves_everything_links_agreement_and_marks_duplicate():
    canonical, source, token = await _pair()
    dl_user = await _delivery_lead(canonical, source)
    job_id = await _closed_job(source)
    process_id = await _process(job_id, source)
    person = await _candidate()
    contract_id = await _live_contract(canonical, person)
    agreement_id, number = await _signed_agreement(source, person)
    async with AsyncSessionLocal() as db:
        contact = Contact(client_id=source, name="Kontakt Testowy")
        alert = DlAlert(
            alert_type="draft_consultant_unassigned",
            user_id=dl_user,
            client_id=source,
            title="Alert testowy",
            message="Alert testowy",
            link=f"/clients/{source}?tab=zamowienia",
            dedupe_key=f"scal-test:{uuid.uuid4().hex}",
            status=DL_ALERT_STATUS_RESOLVED,
            handled_at=datetime.now(timezone.utc),
        )
        db.add_all(
            [
                contact,
                alert,
                ClientPlaybook(client_id=source),
                ClientPlaybookEvent(
                    client_id=source, playbook_version=1, action="saved"
                ),
            ]
        )
        await db.commit()
        contact_id, alert_id = contact.id, alert.id
    reindex_before = await _job_reindex_events(job_id)

    target = CardifMergeTarget(
        source_id=source,
        target_id=canonical,
        name_token=token,
        agreement=AgreementLink(
            generated_id=agreement_id, contract_number=number, contract_id=contract_id
        ),
    )
    marker = f"test_cardif_merge_{token}"
    summary = await _run(target, marker)

    assert summary is not None and summary["skipped"] is None
    assert summary["jobs_moved"] == [job_id]
    assert summary["processes_moved"] == 1
    assert summary["contracts_moved"] == [] and summary["contracts_blocked"] == []
    assert summary["materials_moved"] == {
        "contacts": 1,
        "playbook": 1,
        "playbook_events": 1,
    }
    assert summary["alerts_moved"] == 1
    assert summary["agreement"]["skipped"] is None
    assert summary["merged"] is True and summary["merge_blockers"] == []
    assert summary["unexpected_references"] == {}
    # Wpis katalogu duplikatu zostaje — zakres portfela i przydział DL.
    assert summary["remaining_references"] == {
        "client_portfolio_scopes.client_id": 1,
        "delivery_lead_client_assignments.client_id": 1,
    }
    assert "merged True" in summarize_for_log(summary)

    async with AsyncSessionLocal() as db:
        assert await db.scalar(select(Job.client_id).where(Job.id == job_id)) == (
            canonical
        )
        assert (
            await db.scalar(
                select(RecruitmentProcess.client_id).where(
                    RecruitmentProcess.id == process_id
                )
            )
            == canonical
        )
        assert (await db.get(Contact, contact_id)).client_id == canonical
        assert (
            await db.scalar(
                select(ClientPlaybook.client_id).where(
                    ClientPlaybook.client_id.in_((source, canonical))
                )
            )
            == canonical
        )
        moved_alert = await db.get(DlAlert, alert_id)
        assert moved_alert.client_id == canonical
        assert moved_alert.link == f"/clients/{canonical}?tab=zamowienia"
        row = await db.get(B2BGeneratedContract, agreement_id)
        assert row.contract_id == contract_id
        assert row.client_id == canonical
        canonical_row = await db.get(Client, canonical)
        assert row.client_name == canonical_row.name
        # Treść podpisanego dokumentu zostaje.
        assert row.render_payload == {
            "language": "pl",
            "client_name": "Nazwa wydrukowana",
        }
        assert row.contract_number == number
        assert row.signature_status == "signed_both"
        assert (
            await db.scalar(
                select(B2BContractDetail.contract_number).where(
                    B2BContractDetail.contract_id == contract_id
                )
            )
            == number
        )
        event = await db.scalar(
            select(B2BGeneratedContractStatusEvent).where(
                B2BGeneratedContractStatusEvent.generated_contract_id == agreement_id
            )
        )
        assert event.details["source"] == "linked_to_contract"
        assert event.details["previous_client_id"] == source
        assert event.changed_by is None
        assert (
            await db.scalar(
                select(Activity.id).where(
                    Activity.entity_type == "contract",
                    Activity.entity_id == contract_id,
                    Activity.action == "generated_contract_linked",
                )
            )
            is not None
        )

        duplicate = await db.get(Client, source)
        assert duplicate.merged_into_client_id == canonical
        assert duplicate.archived_at is not None
        assert duplicate.hidden is False and duplicate.deleted_at is None
        assert canonical_row.merged_into_client_id is None
        assert canonical_row.archived_at is None
        assert (
            await db.scalar(
                select(ClientPortfolioScope.id).where(
                    ClientPortfolioScope.client_id == source,
                    ClientPortfolioScope.archived_at.is_(None),
                )
            )
            is not None
        )
        merged_activity = await db.scalar(
            select(Activity).where(
                Activity.entity_type == "client",
                Activity.entity_id == source,
                Activity.action == "merged",
            )
        )
        assert merged_activity.details["merged_into_client_id"] == canonical
        history = await db.scalar(
            select(CriticalEvent).where(
                CriticalEvent.event_type == "client.merge",
                CriticalEvent.entity_id == source,
            )
        )
        assert history.client_id == canonical and history.actor_user_id is None
        assert history.details["moved"]["jobs"] == 1
    # Payload wektora rekrutacji niesie klienta — jedna nowa intencja reindeksu.
    assert await _job_reindex_events(job_id) == reindex_before + 1

    assert await _run(target, marker) is None


@pytest.mark.parametrize(
    "case", ["identity_mismatch", "target_not_live", "duplicate_singletons"]
)
async def test_gate_skips_whole_repair_and_writes_only_the_marker(case: str):
    canonical, source, token = await _pair()
    job_id = await _closed_job(source)
    async with AsyncSessionLocal() as db:
        if case == "target_not_live":
            await db.execute(
                update(Client)
                .where(Client.id == canonical)
                .values(archived_at=datetime.now(timezone.utc))
            )
        if case == "duplicate_singletons":
            db.add_all(
                [ClientPlaybook(client_id=source), ClientPlaybook(client_id=canonical)]
            )
        await db.commit()
    target = CardifMergeTarget(
        source_id=source,
        target_id=canonical,
        name_token="inna-firma" if case == "identity_mismatch" else token,
    )
    marker = f"test_cardif_merge_{case}_{token}"
    summary = await _run(target, marker)

    assert summary is not None and summary["skipped"] == case
    assert summarize_for_log(summary) == f"skipped: {case}"
    async with AsyncSessionLocal() as db:
        assert await db.scalar(select(Job.client_id).where(Job.id == job_id)) == source
        assert (await db.get(Client, source)).merged_into_client_id is None
        assert await db.get(AppSetting, marker) is not None
    assert await _run(target, marker) is None


async def test_missing_client_is_a_skip_not_an_error():
    canonical, _, token = await _pair()
    async with AsyncSessionLocal() as db:
        missing = (await db.scalar(select(Client.id).order_by(Client.id.desc()))) + (
            1_000_000
        )
    summary = await _run(
        CardifMergeTarget(source_id=missing, target_id=canonical, name_token=token),
        f"test_cardif_merge_missing_{token}",
    )
    assert summary is not None and summary["skipped"] == "client_missing"


async def test_duplicate_merged_into_another_client_is_left_alone():
    canonical, source, token = await _pair()
    other = await _client(f"{token} trzeci")
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Client)
            .where(Client.id == source)
            .values(merged_into_client_id=other)
        )
        await db.commit()
    summary = await _run(
        CardifMergeTarget(source_id=source, target_id=canonical, name_token=token),
        f"test_cardif_merge_elsewhere_{token}",
    )
    assert summary is not None and summary["skipped"] == "source_merged_elsewhere"
    assert (await _client_row(source)).merged_into_client_id == other


@pytest.mark.parametrize("case", ["other_person", "contract_has_other_agreement"])
async def test_agreement_gate_skips_only_the_link_and_holds_the_merge_flag(case: str):
    canonical, source, token = await _pair()
    job_id = await _closed_job(source)
    person = await _candidate()
    contract_id = await _live_contract(canonical, person)
    agreement_person = await _candidate() if case == "other_person" else person
    agreement_id, number = await _signed_agreement(source, agreement_person)
    if case == "contract_has_other_agreement":
        await _signed_agreement(canonical, person, contract_id=contract_id)

    summary = await _run(
        CardifMergeTarget(
            source_id=source,
            target_id=canonical,
            name_token=token,
            agreement=AgreementLink(
                generated_id=agreement_id,
                contract_number=number,
                contract_id=contract_id,
            ),
        ),
        f"test_cardif_merge_{case}_{token}",
    )

    assert summary is not None and summary["skipped"] is None
    assert summary["agreement"]["skipped"] == case
    assert summary["jobs_moved"] == [job_id]
    # Umowa została na duplikacie, więc nie jest on pusty — flaga czeka.
    assert summary["unexpected_references"] == {"b2b_generated_contracts.client_id": 1}
    assert summary["merged"] is False
    async with AsyncSessionLocal() as db:
        row = await db.get(B2BGeneratedContract, agreement_id)
        assert row.contract_id is None and row.client_id == source
        assert row.client_name == "Nazwa wydrukowana"
        assert await db.scalar(select(Job.client_id).where(Job.id == job_id)) == (
            canonical
        )
    assert (await _client_row(source)).merged_into_client_id is None


async def test_blocked_contract_stays_and_duplicate_is_not_marked_merged():
    canonical, source, token = await _pair()
    job_id = await _closed_job(source)
    person = await _candidate()
    # Ta sama osoba ma już żywy kontrakt u klienta docelowego — przepięcie
    # zrobiłoby duplikat kontraktora, więc ścieżka przepięcia odmawia.
    await _live_contract(canonical, person)
    stuck = await _live_contract(source, person)

    summary = await _run(
        CardifMergeTarget(source_id=source, target_id=canonical, name_token=token),
        f"test_cardif_merge_blocked_{token}",
    )

    assert summary is not None and summary["skipped"] is None
    assert summary["jobs_moved"] == [job_id]
    assert summary["contracts_moved"] == []
    assert summary["contracts_blocked"] == [
        {"contract_id": stuck, "codes": ["duplicate_contract_at_target"]}
    ]
    assert summary["merged"] is False
    assert "active_contractors" in summary["merge_blockers"]
    async with AsyncSessionLocal() as db:
        assert (await db.get(Contract, stuck)).client_id == source
    assert (await _client_row(source)).merged_into_client_id is None


async def _linked_pair(*, linked: bool) -> tuple[CardifMergeTarget, int, int, int, str]:
    """Kontrakt u klienta docelowego i podpisana umowa z rekrutacją tego klienta."""

    canonical, source, token = await _pair()
    job_id = await _closed_job(canonical)
    person = await _candidate()
    contract_id = await _live_contract(canonical, person)
    agreement_id, number = await _signed_agreement(
        canonical, person, contract_id=contract_id if linked else None
    )
    async with AsyncSessionLocal() as db:
        (await db.get(B2BGeneratedContract, agreement_id)).job_id = job_id
        await db.commit()
    target = CardifMergeTarget(
        source_id=source,
        target_id=canonical,
        name_token=token,
        agreement=AgreementLink(
            generated_id=agreement_id, contract_number=number, contract_id=contract_id
        ),
    )
    return target, contract_id, job_id, agreement_id, number


async def test_contract_fill_gives_the_linked_contract_its_job_and_agreement_number():
    """Bieg z 13.10.2026 powiązał umowę, zanim powiązanie uzupełniało kontrakt."""

    target, contract_id, job_id, _, number = await _linked_pair(linked=True)
    marker = f"test_cardif_fill_{uuid.uuid4().hex[:8]}"
    async with AsyncSessionLocal() as db:
        summary = await run_cardif_contract_fill(db, target=target, marker=marker)
        await db.commit()

    assert summary is not None and summary["skipped"] is None
    assert summary["filled"] == ["job_id", "b2b_detail"]
    async with AsyncSessionLocal() as db:
        assert (await db.get(Contract, contract_id)).job_id == job_id
        detail = await db.scalar(
            select(B2BContractDetail).where(
                B2BContractDetail.contract_id == contract_id
            )
        )
        assert detail.contract_number == number
        trace = await db.scalar(
            select(Activity).where(
                Activity.entity_type == "contract",
                Activity.entity_id == contract_id,
                Activity.action == "updated",
            )
        )
        assert trace.details == {
            "filled_fields": ["job_id", "b2b_detail"],
            "source": marker,
        }
        again = await run_cardif_contract_fill(db, target=target, marker=marker)
    assert again is None


async def test_contract_fill_leaves_an_unlinked_pair_alone():
    target, contract_id, _, _, _ = await _linked_pair(linked=False)
    marker = f"test_cardif_fill_{uuid.uuid4().hex[:8]}"
    async with AsyncSessionLocal() as db:
        summary = await run_cardif_contract_fill(db, target=target, marker=marker)
        await db.commit()

    assert summary is not None and summary["skipped"] == "not_linked"
    async with AsyncSessionLocal() as db:
        assert (await db.get(Contract, contract_id)).job_id is None
        assert (
            await db.scalar(
                select(B2BContractDetail.id).where(
                    B2BContractDetail.contract_id == contract_id
                )
            )
            is None
        )
        assert await db.get(AppSetting, marker) is not None


def test_entrypoint_runs_the_merge_and_logs_only_the_summary():
    source = (BACKEND / "entrypoint.sh").read_text(encoding="utf-8")
    block = source.split("run_cardif_client_merge", 1)[1].split("\nPY\n", 1)[0]
    assert "summarize_for_log(summary)" in block
    assert "await db.commit()" in block
    assert "await db.rollback()" in block


def test_repair_imports_in_a_bare_interpreter():
    """Heredoc entrypointu startuje bez aplikacji, a ``|| echo`` ukryłby błąd.

    Korekta jako pierwsza sięga z tego miejsca po funkcje z ``app.api``
    (leniwie, wewnątrz kroków) — import musi przejść bez ``app.main``.
    """

    code = (
        "import app.models\n"
        "import app.services.cardif_client_merge_repair\n"
        "from app.api.clients import _move_client_materials_on_merge\n"
        "from app.api.b2b_contract_generator import apply_contract_link\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", code],
        cwd=BACKEND,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert done.returncode == 0, done.stderr[-2000:]
