"""Import Atlasa do Sprzedaży: etapy, śmieci, sieroty, kontakty, notatki, idempotencja.

Źródło to fikcyjny Atlas w pamięci; identyfikatory Atlasa niosą losowy tag,
bo baza testowa jest wspólna dla przebiegu.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal
from app.models.client import Client
from app.models.sales import (
    SalesActivity,
    SalesCompany,
    SalesContact,
    SalesLead,
    SalesOpportunity,
    SalesOpportunityContact,
    SalesOpportunityEvent,
    SalesPipeline,
    SalesPipelineStage,
)
from app.models.user import User, UserRole
from app.services.sales.atlas_import import (
    ATLAS_REVIEW_TAG,
    is_junk_company,
    looks_like_person_name,
    run_import,
)

NOW = datetime(2026, 10, 27, 9, tzinfo=timezone.utc)


def test_person_like_names_are_junk_but_companies_are_not() -> None:
    assert looks_like_person_name("Jan Kowalski")
    assert not looks_like_person_name("Bank Przykładowy")
    assert not looks_like_person_name("Kowalski Consulting")
    assert not looks_like_person_name("Visa Inc")
    assert is_junk_company("  ")
    assert is_junk_company(None)
    assert not is_junk_company("Żuraw Systemy Sp. z o.o.")


class FakeAtlas:
    def __init__(self, tag: str, owner_email: str, nip: str) -> None:
        t = tag
        self.data = {
            "people": [{"user_id": f"u-{t}", "email": owner_email}],
            "pipelines": [
                {"id": "sales", "name": "Sprzedaż", "is_hidden": False},
                {"id": f"tenders-{t}", "name": f"Przetargi {t}", "is_hidden": True},
            ],
            "stages": [
                {
                    "id": "stage-lead",
                    "pipeline_id": "sales",
                    "position": 0,
                    "is_won": False,
                    "is_lost": False,
                },
                {
                    "id": "stage-proposal",
                    "pipeline_id": "sales",
                    "position": 3,
                    "is_won": False,
                    "is_lost": False,
                },
                {
                    "id": "stage-won",
                    "pipeline_id": "sales",
                    "position": 5,
                    "is_won": True,
                    "is_lost": False,
                },
                {
                    "id": f"t-open-{t}",
                    "pipeline_id": f"tenders-{t}",
                    "name": "Ogłoszony",
                    "position": 0,
                    "probability": 10,
                },
                {
                    "id": f"t-won-{t}",
                    "pipeline_id": f"tenders-{t}",
                    "name": "Wygrany",
                    "position": 1,
                    "probability": 100,
                    "is_won": True,
                },
            ],
            "companies": [
                {
                    "id": f"c1-{t}",
                    "name": f"Żuraw Systemy {t}",
                    "nip": f"PL {nip}",
                    "owner_user_id": f"u-{t}",
                    "lifecycle_stage": "prospect",
                    "account_tier": "enterprise",
                },
                {
                    "id": f"c2-{t}",
                    "name": f"Żuraw Leasing {t}",
                    "parent_company_id": f"c1-{t}",
                },
                {"id": f"c3-{t}", "name": "Jan Kowalski"},
                {"id": f"c4-{t}", "name": "Anna Nowak"},
                {"id": f"c5-{t}", "name": "   "},
            ],
            "contacts": [
                {
                    "id": f"p1-{t}",
                    "full_name": "Ewa Przykładowa",
                    "email": "Ewa.P@Example.com",
                    "primary_company_id": f"c1-{t}",
                    "is_cxo": True,
                },
                {
                    "id": f"p2-{t}",
                    "full_name": None,
                    "first_name": None,
                    "last_name": None,
                },
            ],
            "company_contacts": [],
            "deals": [
                {
                    "id": f"d1-{t}",
                    "title": "Zespół QA",
                    "company_id": f"c1-{t}",
                    "stage_id": "stage-proposal",
                    "status": "open",
                    "mrr_value": Decimal("40000"),
                    "one_off_value": Decimal("5000"),
                    "value": Decimal("45000"),
                    "probability": 60,
                    "service_line": "bodyleasing",
                    "owner_user_id": f"u-{t}",
                    "primary_contact_id": f"p1-{t}",
                    "contact_role": "CTO",
                },
                {
                    "id": f"d2-{t}",
                    "title": "Freelancer",
                    "company_id": f"c3-{t}",
                    "stage_id": "stage-won",
                    "status": "won",
                    "won_at": NOW,
                },
                {
                    "id": f"d3-{t}",
                    "title": "Sierota",
                    "company_id": None,
                    "company_name": f"Bocian Dane {t}",
                    "stage_id": f"t-open-{t}",
                    "status": "open",
                },
                {
                    "id": f"d4-{t}",
                    "title": "Zły etap",
                    "company_id": f"c1-{t}",
                    "stage_id": "nie-ma",
                    "status": "open",
                },
            ],
            "deal_contacts": [
                {
                    "deal_id": f"d1-{t}",
                    "contact_id": f"p1-{t}",
                    "role": "decision_maker",
                }
            ],
            "deal_activities": [
                {
                    "id": f"a1-{t}",
                    "deal_id": f"d1-{t}",
                    "activity_type": "call",
                    "subject": "Rozmowa",
                    "occurred_at": NOW,
                    "done": True,
                    "created_by": owner_email,
                },
                {
                    "id": f"a2-{t}",
                    "deal_id": f"d1-{t}",
                    "activity_type": "task",
                    "subject": "Oferta",
                    "due_date": NOW,
                    "done": False,
                    "owner_user_id": f"u-{t}",
                },
            ],
            "company_activities": [
                {
                    "id": f"ca1-{t}",
                    "company_id": f"c2-{t}",
                    "activity_type": "email",
                    "subject": "Mail",
                    "created_at": NOW,
                }
            ],
            "deal_notes": [
                {
                    "id": f"n1-{t}",
                    "deal_id": f"d1-{t}",
                    "content": "Budżet na Q1",
                    "is_pinned": True,
                }
            ],
            "company_notes": [
                {"id": f"n2-{t}", "company_id": f"c1-{t}", "content": "  "}
            ],
            "linkedin_leads": [
                {
                    "id": f"l1-{t}",
                    "status": "reviewing",
                    "summary": "Szukają lidera QA",
                    "company_name": f"Mewa Soft {t}",
                    "score": 70,
                    "person": {"email": "nie-kopiuj@example.com"},
                },
                {"id": f"l2-{t}", "status": "converted", "summary": "Już szansa"},
            ],
            "press_signals": [
                {
                    "id": f"s1-{t}",
                    "status": "new",
                    "article_title": "Rusza centrum IT",
                    "company_name": f"Klient Żuraw {t}",
                    "source_category": "press",
                },
                {
                    "id": f"s2-{t}",
                    "status": "new",
                    "article_title": "8 ogłoszeń QA",
                    "company_name": f"Sowa Dane {t}",
                    "source_category": "job_board",
                    "score": 300,
                },
            ],
        }

    def __getattr__(self, name):
        if name in self.data:

            async def loader():
                return self.data[name]

            return loader
        raise AttributeError(name)

    async def attachments_count(self) -> int:
        return 3


async def _count(db, model, *where) -> int:
    return int(await db.scalar(select(func.count()).select_from(model).where(*where)))


@pytest.mark.asyncio
async def test_import_maps_everything_and_second_run_updates_instead_of_duplicating() -> (
    None
):
    tag = uuid.uuid4().hex[:8]
    nip = f"{uuid.uuid4().int % 10**10:010d}"
    email = f"handlowiec-{tag}@example.com"
    async with AsyncSessionLocal() as db:
        owner = User(
            email=email,
            name="Handlowiec Przykładowy",
            role=UserRole.recruiter,
            roles=["recruiter"],
            is_active=True,
            profile_completed=True,
        )
        client = Client(name=f"Klient Żuraw {tag}", nip=nip)
        db.add_all([owner, client])
        await db.commit()
        owner_id, client_id = owner.id, client.id

    source = FakeAtlas(tag, email, nip)
    async with AsyncSessionLocal() as db:
        report = (await run_import(db, source, now=NOW)).as_dict()
        await db.commit()

    assert (
        report["companies_skipped_junk"] == 2
    )  # Anna Nowak i pusta nazwa — nic do nich nie wskazuje
    assert report["companies_review"] == 1  # Jan Kowalski ma szansę
    assert report["opportunities_skipped_unknown_stage"] == 1
    assert report["opportunities_company_created"] == 1
    assert report["contacts_skipped_nameless"] == 1
    assert report["notes_skipped_empty"] == 1
    assert report["files_pending_storage_copy"] == 3
    assert report["leads_imported"] == 1  # l1
    assert report["leads_skipped_job_board"] == 1  # s2 — ogłoszenia odrzucone 27.10
    assert report["leads_skipped_closed"] == 1  # l2 zamieniony w Atlasie
    assert report["leads_skipped_existing_client"] == 1  # s1 to klient NEXUSA

    async with AsyncSessionLocal() as db:
        c1 = (
            await db.execute(
                select(SalesCompany).where(
                    SalesCompany.external_ref == f"atlas:companies:c1-{tag}"
                )
            )
        ).scalar_one()
        assert (c1.nip, c1.owner_user_id, c1.lifecycle_stage, c1.tier) == (
            nip,
            owner_id,
            "prospect",
            "enterprise",
        )
        assert c1.client_id == client_id  # ten sam NIP co klient NEXUSA
        c2 = (
            await db.execute(
                select(SalesCompany).where(
                    SalesCompany.external_ref == f"atlas:companies:c2-{tag}"
                )
            )
        ).scalar_one()
        assert c2.parent_company_id == c1.id
        junk = (
            await db.execute(
                select(SalesCompany).where(
                    SalesCompany.external_ref == f"atlas:companies:c3-{tag}"
                )
            )
        ).scalar_one()
        assert ATLAS_REVIEW_TAG in junk.tags

        d1 = (
            await db.execute(
                select(SalesOpportunity).where(
                    SalesOpportunity.external_ref == f"atlas:deals:d1-{tag}"
                )
            )
        ).scalar_one()
        stage = await db.get(SalesPipelineStage, d1.stage_id)
        assert stage.key == "offer-sent"
        # `contact_role` w Atlasie to stanowisko osoby u klienta („CTO”), nie rola
        # do obsadzenia — nie trafia do `roles`, z których powstaje rekrutacja.
        assert (d1.value, d1.owner_user_id, d1.roles) == (
            Decimal("45000.00"),
            owner_id,
            [],
        )
        assert d1.custom_fields["atlas"]["contact_role"] == "CTO"
        contact = (
            await db.execute(
                select(SalesContact).where(
                    SalesContact.external_ref == f"atlas:contacts:p1-{tag}"
                )
            )
        ).scalar_one()
        assert (contact.email, contact.company_id, contact.is_executive) == (
            "ewa.p@example.com",
            c1.id,
            True,
        )
        assert d1.primary_contact_id == contact.id
        link = await db.get(SalesOpportunityContact, (d1.id, contact.id))
        assert link.role == "decision_maker"

        d3 = (
            await db.execute(
                select(SalesOpportunity).where(
                    SalesOpportunity.external_ref == f"atlas:deals:d3-{tag}"
                )
            )
        ).scalar_one()
        orphan_company = await db.get(SalesCompany, d3.company_id)
        assert orphan_company.name == f"Bocian Dane {tag}"
        tenders = await db.get(SalesPipeline, d3.pipeline_id)
        assert tenders.key == f"atlas-tenders-{tag}" and tenders.archived_at is not None

        acts = {
            a.external_ref: a
            for a in (
                await db.execute(
                    select(SalesActivity).where(
                        SalesActivity.external_ref.like(f"atlas:%-{tag}")
                    )
                )
            ).scalars()
        }
        call = acts[f"atlas:deal_activities:a1-{tag}"]
        assert (call.company_id, call.opportunity_id, call.created_by_user_id) == (
            c1.id,
            d1.id,
            owner_id,
        )
        task = acts[f"atlas:deal_activities:a2-{tag}"]
        assert (task.kind, task.done_at, task.assignee_user_id) == (
            "task",
            None,
            owner_id,
        )
        note = acts[f"atlas:deal_notes:n1-{tag}"]
        assert (note.kind, note.is_pinned, note.body) == ("note", True, "Budżet na Q1")
        assert acts[f"atlas:company_activities:ca1-{tag}"].company_id == c2.id

        leads = {
            lead.fingerprint: lead
            for lead in (
                await db.execute(
                    select(SalesLead).where(
                        SalesLead.fingerprint.like(f"atlas:%-{tag}")
                    )
                )
            ).scalars()
        }
        linkedin = leads[f"atlas:linkedin_leads:l1-{tag}"]
        assert (linkedin.source, linkedin.status, linkedin.score) == (
            "linkedin",
            "new",
            70,
        )
        assert "nie-kopiuj" not in str(linkedin.payload)
        assert f"atlas:press_signals:s2-{tag}" not in leads
        linkedin.status = "dismissed"
        await db.commit()

        before = {
            model.__tablename__: await _count(
                db, model, model.external_ref.like(f"atlas:%{tag}%")
            )
            for model in (SalesCompany, SalesContact, SalesOpportunity, SalesActivity)
        }

    # Drugi bieg: zmieniony tytuł w Atlasie aktualizuje, liczby wierszy stoją.
    source.data["deals"][0]["title"] = "Zespół QA i automatyzacji"
    async with AsyncSessionLocal() as db:
        await run_import(db, source, now=NOW)
        await db.commit()
    async with AsyncSessionLocal() as db:
        after = {
            model.__tablename__: await _count(
                db, model, model.external_ref.like(f"atlas:%{tag}%")
            )
            for model in (SalesCompany, SalesContact, SalesOpportunity, SalesActivity)
        }
        assert after == before
        title = await db.scalar(
            select(SalesOpportunity.title).where(
                SalesOpportunity.external_ref == f"atlas:deals:d1-{tag}"
            )
        )
        assert title == "Zespół QA i automatyzacji"
        kept = await db.scalar(
            select(SalesLead.status).where(
                SalesLead.fingerprint == f"atlas:linkedin_leads:l1-{tag}"
            )
        )
        assert kept == "dismissed"  # decyzja handlowca przetrwała drugi bieg
        # Import nie pisze historii zmian — zaczyna się od pracy w NEXUSIE.
        events = await db.scalar(
            select(func.count())
            .select_from(SalesOpportunityEvent)
            .join(
                SalesOpportunity,
                SalesOpportunity.id == SalesOpportunityEvent.opportunity_id,
            )
            .where(SalesOpportunity.external_ref.like(f"atlas:%{tag}%"))
        )
        assert events == 0


# ── Bieg na produkcji przez coolify-ops (action=atlas-import) ─────────────────
# Cron Coolify odpala jednorazowe zadanie co minutę, a log Actions jest publiczny.


def _ops_lock() -> str:
    return f"/tmp/nexus-atlas-import-{uuid.uuid4().int % 10**12}"


def test_lock_accepts_only_the_ops_shape() -> None:
    import argparse

    from scripts.import_atlas_sales import _lock_path

    assert (
        str(_lock_path("/tmp/nexus-atlas-import-123")) == "/tmp/nexus-atlas-import-123"
    )
    for bad in (
        "/tmp/x",
        "/app/nexus-atlas-import-1",
        "/tmp/nexus-atlas-import-1/../../etc",
    ):
        with pytest.raises(argparse.ArgumentTypeError):
            _lock_path(bad)


def test_second_firing_with_the_same_lock_does_not_import_again(
    monkeypatch, capsys
) -> None:
    import shutil

    from scripts import import_atlas_sales as script

    calls: list[tuple[bool, bool]] = []

    async def fake_main(apply: bool, files: bool) -> int:
        calls.append((apply, files))
        return 0

    monkeypatch.setattr(script, "_main", fake_main)
    lock = _ops_lock()
    try:
        assert script.main(["--apply", "--lock", lock]) == 0
        assert script.main(["--apply", "--lock", lock]) == 3
    finally:
        shutil.rmtree(lock, ignore_errors=True)
    assert calls == [(True, False)]
    assert "already ran" in capsys.readouterr().err


def test_failure_under_lock_prints_only_the_error_type(monkeypatch, capsys) -> None:
    import shutil
    from pathlib import Path

    from scripts import import_atlas_sales as script

    async def failing_main(apply: bool, files: bool) -> int:
        raise RuntimeError("Firma Testowa sp. z o.o. — kontakt@example.com")

    monkeypatch.setattr(script, "_main", failing_main)
    lock = _ops_lock()
    try:
        assert script.main(["--lock", lock]) == 1
        out = capsys.readouterr()
        assert "RuntimeError" in out.out
        assert "Firma Testowa" not in out.out + out.err
        assert "Firma Testowa" in (Path(lock) / "error.log").read_text()
    finally:
        shutil.rmtree(lock, ignore_errors=True)
