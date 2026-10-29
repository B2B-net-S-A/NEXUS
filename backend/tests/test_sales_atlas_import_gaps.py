"""Import Atlasa — luki z audytu 28.10.2026.

Ochrona zmian w NEXUSIE (``synced_at``), opiekun i wykonawca bez czyszczenia,
etykieta opiekuna bez konta, osoba w wielu firmach, firmy-nazwiska z domeną,
pola Outlooka, notatki z przygotowań kandydata, wartości spoza słowników,
zapisy rozmów Fireflies, leady (bez ogłoszeń). Źródło to fikcyjny Atlas
w pamięci; identyfikatory niosą losowy tag (baza testowa jest wspólna).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pytest
from sqlalchemy import select, update

from app.core.database import AsyncSessionLocal
from app.models.sales import (
    SalesActivity,
    SalesCompany,
    SalesCompanyContact,
    SalesContact,
    SalesLead,
    SalesOpportunity,
    SalesPipeline,
    SalesPipelineStage,
)
from app.models.user import User, UserRole
from app.services.sales.merge import merge_companies
from app.services.sales.atlas_import import (
    ATLAS_REVIEW_TAG,
    ImportReport,
    company_merge_targets,
    is_candidate_prep_note,
    is_candidate_prep_title,
    run_import,
)

NOW = datetime(2026, 10, 27, 9, tzinfo=timezone.utc)
LATER = NOW + timedelta(hours=2)
PREP_NOTE = (
    "PODSUMOWANIE SPOTKANIA (Fireflies)\n"
    "Przygotowanie do spotkania z klientem — doświadczenie, dostępność"
)


class FakeAtlas:
    """Atlas w pamięci: każda lista z ``data`` to metoda źródła."""

    def __init__(self, data: dict[str, list[dict[str, Any]]]) -> None:
        self.data = {
            name: []
            for name in (
                "people",
                "pipelines",
                "stages",
                "companies",
                "contacts",
                "company_contacts",
                "deals",
                "deal_contacts",
                "deal_activities",
                "company_activities",
                "deal_notes",
                "company_notes",
                "linkedin_leads",
                "press_signals",
            )
        }
        self.data.update(data)

    def __getattr__(self, name):
        if name in self.data:

            async def loader():
                return self.data[name]

            return loader
        raise AttributeError(name)

    async def attachments_count(self) -> int:
        return 0


async def _users(*labels: str) -> dict[str, tuple[int, str]]:
    """Konta NEXUSA: etykieta → (id, e-mail)."""

    out = {}
    async with AsyncSessionLocal() as db:
        for label in labels:
            email = f"{label}-{uuid.uuid4().hex[:8]}@example.com"
            user = User(
                email=email,
                name="Osoba Testowa",
                role=UserRole.recruiter,
                roles=["recruiter"],
                is_active=True,
                profile_completed=True,
            )
            db.add(user)
            await db.flush()
            out[label] = (user.id, email)
        await db.commit()
    return out


async def _import(source: FakeAtlas, now: datetime = NOW) -> dict[str, int]:
    async with AsyncSessionLocal() as db:
        report = (await run_import(db, source, now=now)).as_dict()
        await db.commit()
    return report


async def _one(model: Any, ref: str) -> Any:
    async with AsyncSessionLocal() as db:
        return (
            await db.execute(select(model).where(model.external_ref == ref))
        ).scalar_one()


def _sales_pipeline(tag: str) -> dict[str, list[dict[str, Any]]]:
    return {
        "pipelines": [{"id": "sales", "name": "Sprzedaż"}],
        "stages": [
            {"id": "stage-lead", "pipeline_id": "sales", "position": 0},
            {"id": "stage-proposal", "pipeline_id": "sales", "position": 3},
        ],
    }


def test_candidate_prep_recognised_by_meeting_title_with_client_name() -> None:
    # Na produkcji 146 ze 153 przygotowań miało nazwę klienta w tytule
    # („…z Bankiem Przykładowym – kandydat”), a nie słowo „Klientem”.
    note = (
        "📝 **Podsumowanie spotkania (Fireflies.ai)**\n\n"
        "**Spotkanie:** Przygotowanie do spotkania z Bank Przykładowy - Kandydat Testowy\n"
        "**Uczestnicy:** kandydat@example.com\n\n**Overview:** stawka, dostępność"
    )
    assert is_candidate_prep_note(note)
    assert is_candidate_prep_title("przygotowanie do spotkania z Firmą Testową")
    assert not is_candidate_prep_title("Spotkanie z Bank Przykładowy — oferta")
    # Fraza w treści, ale tytuł handlowy — to nie przygotowanie kandydata.
    sales = (
        "📝 **Podsumowanie spotkania (Fireflies.ai)**\n\n"
        "**Spotkanie:** Przegląd oferty\n\n**Overview:** przygotowanie do spotkania z zarządem"
    )
    assert not is_candidate_prep_note(sales)


def test_candidate_prep_needs_both_markers_case_insensitive() -> None:
    assert is_candidate_prep_note(PREP_NOTE)
    assert is_candidate_prep_note(PREP_NOTE.lower())
    assert not is_candidate_prep_note("Podsumowanie spotkania (Fireflies) z klientem")
    assert not is_candidate_prep_note("Przygotowanie do spotkania z Klientem")
    assert not is_candidate_prep_note(None)


@pytest.mark.asyncio
async def test_rows_edited_in_nexus_keep_user_fields_and_owners_are_never_wiped() -> (
    None
):
    tag = uuid.uuid4().hex[:8]
    people = await _users("ala", "ola", "ela")
    (ala, ala_mail), (ola, ola_mail), (ela, _) = (
        people["ala"],
        people["ola"],
        people["ela"],
    )
    source = FakeAtlas(
        {
            **_sales_pipeline(tag),
            "people": [
                {"user_id": f"u-ala-{tag}", "email": ala_mail},
                {"user_id": f"u-ola-{tag}", "email": ola_mail},
            ],
            "companies": [
                {
                    "id": f"c1-{tag}",
                    "name": f"Ochrona Edytowana {tag}",
                    "owner_user_id": f"u-ala-{tag}",
                    "description": "z Atlasa",
                },
                {
                    "id": f"c2-{tag}",
                    "name": f"Ochrona Nietknięta {tag}",
                    "owner_user_id": f"u-ola-{tag}",
                },
            ],
            "contacts": [
                {
                    "id": f"p1-{tag}",
                    "full_name": "Kontakt Testowy",
                    "primary_company_id": f"c1-{tag}",
                    "title": "CTO",
                    "department": "IT",
                }
            ],
            "deals": [
                {
                    "id": f"d1-{tag}",
                    "title": "Szansa edytowana",
                    "company_id": f"c1-{tag}",
                    "stage_id": "stage-lead",
                    "status": "open",
                    "description": "opis v1",
                    "owner_user_id": f"u-ala-{tag}",
                },
                {
                    "id": f"d2-{tag}",
                    "title": "Szansa nietknięta",
                    "company_id": f"c2-{tag}",
                    "stage_id": "stage-lead",
                    "status": "open",
                },
            ],
            "deal_activities": [
                {
                    "id": f"a1-{tag}",
                    "deal_id": f"d1-{tag}",
                    "activity_type": "task",
                    "subject": "Zadanie",
                    "done": False,
                    "owner_user_id": f"u-ola-{tag}",
                }
            ],
        }
    )
    await _import(source)
    deal_ref, company_ref = f"atlas:deals:d1-{tag}", f"atlas:companies:c1-{tag}"
    first = await _one(SalesOpportunity, deal_ref)
    assert first.synced_at == NOW and first.updated_at == NOW

    edited_at = NOW + timedelta(hours=1)
    async with AsyncSessionLocal() as db:
        # Zmiany w NEXUSIE po imporcie (``updated_at`` po ``synced_at``).
        await db.execute(
            update(SalesOpportunity)
            .where(SalesOpportunity.external_ref == deal_ref)
            .values(title="Tytuł z NEXUSA", owner_user_id=ela, updated_at=edited_at)
        )
        await db.execute(
            update(SalesCompany)
            .where(SalesCompany.external_ref == company_ref)
            .values(
                name="Nazwa z NEXUSA", description="opis z NEXUSA", updated_at=edited_at
            )
        )
        await db.execute(
            update(SalesActivity)
            .where(SalesActivity.external_ref == f"atlas:deal_activities:a1-{tag}")
            .values(done_at=edited_at, updated_at=edited_at)
        )
        await db.execute(
            update(SalesContact)
            .where(SalesContact.external_ref == f"atlas:contacts:p1-{tag}")
            .values(title="CEO", updated_at=edited_at)
        )
        # Niezmieniony wiersz (``updated_at`` = ``synced_at``) z opiekunem
        # wpisanym bez śladu edycji — import go odświeża, opiekuna nie rusza.
        await db.execute(
            update(SalesOpportunity)
            .where(SalesOpportunity.external_ref == f"atlas:deals:d2-{tag}")
            .values(owner_user_id=ela, updated_at=NOW)
        )
        await db.commit()

    for deal in source.data["deals"]:
        deal["title"] = f"{deal['title']} v2"
    source.data["deals"][0]["description"] = "opis v2"
    source.data["deals"][1]["owner_user_id"] = f"u-ola-{tag}"
    source.data["companies"][0]["name"] = "Nazwa z Atlasa v2"
    source.data["companies"][0]["legal_name"] = "Pełna nazwa v2"
    source.data["contacts"][0]["title"] = "CIO"
    source.data["contacts"][0]["department"] = "Zarząd"
    source.data["deal_activities"][0]["subject"] = "Zadanie v2"
    await _import(source, LATER)

    opp = await _one(SalesOpportunity, deal_ref)
    assert (opp.title, opp.owner_user_id) == ("Tytuł z NEXUSA", ela)
    assert opp.description == "opis v2"  # pole spoza ochrony idzie za Atlasem
    # Znaczniki zostają, żeby kolejny bieg też widział edycję.
    assert (opp.synced_at, opp.updated_at) == (NOW, edited_at)
    company = await _one(SalesCompany, company_ref)
    assert (company.name, company.description, company.legal_name) == (
        "Nazwa z NEXUSA",
        "opis z NEXUSA",
        "Pełna nazwa v2",
    )
    contact = await _one(SalesContact, f"atlas:contacts:p1-{tag}")
    assert (contact.title, contact.department) == ("CEO", "Zarząd")
    task = await _one(SalesActivity, f"atlas:deal_activities:a1-{tag}")
    assert (task.done_at, task.subject, task.assignee_user_id) == (
        edited_at,
        "Zadanie",
        ola,
    )

    # Niezmieniony = pełne odświeżenie, ale opiekun z NEXUSA zostaje (COALESCE).
    first_import = await _one(SalesOpportunity, f"atlas:deals:d2-{tag}")
    assert (first_import.title, first_import.owner_user_id) == (
        "Szansa nietknięta v2",
        ela,
    )
    assert (first_import.synced_at, first_import.updated_at) == (LATER, LATER)
    untouched = await _one(SalesCompany, f"atlas:companies:c2-{tag}")
    assert (untouched.owner_user_id, untouched.synced_at) == (ola, LATER)
    assert ala  # konto opiekuna z Atlasa istnieje, ale edycja w NEXUSIE wygrała


@pytest.mark.asyncio
async def test_missing_owner_and_assignee_get_filled_on_rerun() -> None:
    tag = uuid.uuid4().hex[:8]
    (ala, ala_mail) = (await _users("ala"))["ala"]
    source = FakeAtlas(
        {
            **_sales_pipeline(tag),
            "people": [{"user_id": f"u-ala-{tag}", "email": ala_mail}],
            "companies": [
                {"id": f"c1-{tag}", "name": f"Uzupełnij {tag}", "owner_user_id": "x"}
            ],
            "deals": [
                {
                    "id": f"d1-{tag}",
                    "title": "Szansa",
                    "company_id": f"c1-{tag}",
                    "stage_id": "stage-lead",
                    "owner_user_id": "x",
                }
            ],
            "deal_activities": [
                {
                    "id": f"a1-{tag}",
                    "deal_id": f"d1-{tag}",
                    "activity_type": "task",
                    "subject": "Zadanie",
                }
            ],
        }
    )
    await _import(source)
    assert (await _one(SalesCompany, f"atlas:companies:c1-{tag}")).owner_user_id is None
    task = await _one(SalesActivity, f"atlas:deal_activities:a1-{tag}")
    assert task.assignee_user_id is None

    source.data["companies"][0]["owner_user_id"] = f"u-ala-{tag}"
    source.data["deals"][0]["owner_user_id"] = f"u-ala-{tag}"
    await _import(source, LATER)
    assert (await _one(SalesCompany, f"atlas:companies:c1-{tag}")).owner_user_id == ala
    assert (await _one(SalesOpportunity, f"atlas:deals:d1-{tag}")).owner_user_id == ala
    # Wykonawca zadania przy szansie = opiekun szansy.
    task = await _one(SalesActivity, f"atlas:deal_activities:a1-{tag}")
    assert task.assignee_user_id == ala

    # Opiekun bez konta w kolejnym biegu nie czyści ani opiekuna, ani wykonawcy.
    source.data["companies"][0]["owner_user_id"] = "x"
    source.data["deals"][0]["owner_user_id"] = "x"
    await _import(source, LATER + timedelta(hours=1))
    assert (await _one(SalesCompany, f"atlas:companies:c1-{tag}")).owner_user_id == ala
    task = await _one(SalesActivity, f"atlas:deal_activities:a1-{tag}")
    assert task.assignee_user_id == ala


@pytest.mark.asyncio
async def test_task_assignee_follows_atlas_task_center_rules() -> None:
    tag = uuid.uuid4().hex[:8]
    people = await _users("deal", "row", "author", "company")
    mail = {label: value[1] for label, value in people.items()}
    ids = {label: value[0] for label, value in people.items()}
    source = FakeAtlas(
        {
            **_sales_pipeline(tag),
            "people": [
                {"user_id": f"u-{label}-{tag}", "email": mail[label]}
                for label in ("deal", "row", "company")
            ],
            "companies": [
                {
                    "id": f"c1-{tag}",
                    "name": f"Zadania {tag}",
                    "owner_user_id": f"u-company-{tag}",
                }
            ],
            "deals": [
                {
                    "id": f"d1-{tag}",
                    "title": "Szansa",
                    "company_id": f"c1-{tag}",
                    "stage_id": "stage-lead",
                    "owner_user_id": f"u-deal-{tag}",
                }
            ],
            "deal_activities": [
                # Każdy rodzaj przy szansie: właściciel wiersza, inaczej opiekun szansy.
                {
                    "id": f"da-row-{tag}",
                    "deal_id": f"d1-{tag}",
                    "activity_type": "call",
                    "subject": "Telefon",
                    "owner_user_id": f"u-row-{tag}",
                    "duration_minutes": 25,
                },
                {
                    "id": f"da-deal-{tag}",
                    "deal_id": f"d1-{tag}",
                    "activity_type": "meeting",
                    "subject": "Spotkanie",
                    "done": True,
                    "occurred_at": NOW,
                },
            ],
            "company_activities": [
                {
                    "id": f"ca-author-{tag}",
                    "company_id": f"c1-{tag}",
                    "activity_type": "task",
                    "subject": "Zadanie autora",
                    "created_by": mail["author"],
                    "due_date": NOW,
                },
                {
                    "id": f"ca-owner-{tag}",
                    "company_id": f"c1-{tag}",
                    "activity_type": "call",
                    "subject": "Oddzwonić",
                    "due_date": NOW,
                    "created_at": NOW - timedelta(days=1),
                },
                {
                    "id": f"ca-done-{tag}",
                    "company_id": f"c1-{tag}",
                    "activity_type": "task",
                    "subject": "Zrobione",
                    "done": True,
                    "created_at": NOW,
                },
                {
                    "id": f"ca-mail-{tag}",
                    "company_id": f"c1-{tag}",
                    "activity_type": "call",
                    "subject": "Z Outlooka",
                    "external_source": "msgraph-event",
                    "due_date": NOW,
                },
            ],
        }
    )
    await _import(source)

    async def assignee(ref: str) -> Any:
        return (await _one(SalesActivity, ref)).assignee_user_id

    assert await assignee(f"atlas:deal_activities:da-row-{tag}") == ids["row"]
    assert await assignee(f"atlas:deal_activities:da-deal-{tag}") == ids["deal"]
    assert await assignee(f"atlas:company_activities:ca-author-{tag}") == ids["author"]
    assert await assignee(f"atlas:company_activities:ca-owner-{tag}") == ids["company"]
    assert await assignee(f"atlas:company_activities:ca-done-{tag}") is None
    assert await assignee(f"atlas:company_activities:ca-mail-{tag}") is None
    open_call = await _one(SalesActivity, f"atlas:company_activities:ca-owner-{tag}")
    assert (open_call.done_at, open_call.due_at) == (None, NOW)
    call = await _one(SalesActivity, f"atlas:deal_activities:da-row-{tag}")
    assert call.duration_minutes == 25


@pytest.mark.asyncio
async def test_owner_label_people_in_many_companies_and_kept_junk_companies() -> None:
    tag = uuid.uuid4().hex[:8]
    (ala, ala_mail) = (await _users("ala"))["ala"]
    source = FakeAtlas(
        {
            **_sales_pipeline(tag),
            "people": [{"user_id": f"u-ala-{tag}", "email": ala_mail}],
            "companies": [
                {
                    "id": f"c1-{tag}",
                    "name": f"Etykieta {tag}",
                    "owner_user_id": "bez-konta",
                    "owner_name": "Handlowiec Archiwalny",
                },
                {
                    "id": f"c2-{tag}",
                    "name": f"Pipedrive {tag}",
                    "custom_fields": {"pipedrive_owner_name": "Opiekun Pipedrive"},
                },
                {
                    "id": f"c3-{tag}",
                    "name": f"Z kontem {tag}",
                    "owner_user_id": f"u-ala-{tag}",
                    "owner_name": "Nie kopiuj",
                },
                # Wyglądają na nazwiska, ale coś je trzyma w kartotece.
                {"id": f"j1-{tag}", "name": "Adam Domena", "domain": "przyklad.pl"},
                {"id": f"j2-{tag}", "name": "Bartek Rejestr", "krs_id": "0000123456"},
                {"id": f"j3-{tag}", "name": "Cezary Lead"},
                {"id": f"j4-{tag}", "name": "Daria Zespol"},
                {"id": f"j5-{tag}", "name": "Edward Plik"},
                {"id": f"j6-{tag}", "name": "Filip Sygnal"},
                {"id": f"j7-{tag}", "name": "Grzegorz Nikt"},
            ],
            "contacts": [
                {
                    "id": f"p1-{tag}",
                    "full_name": "Osoba Wielofirmowa",
                    "primary_company_id": f"c1-{tag}",
                }
            ],
            "company_contacts": [
                {
                    "company_id": f"c1-{tag}",
                    "contact_id": f"p1-{tag}",
                    "role": "Doradca",
                    "is_primary_employer": False,
                    "is_current": False,
                    "ended_at": date(2025, 12, 31),
                },
                {
                    "company_id": f"c2-{tag}",
                    "contact_id": f"p1-{tag}",
                    "title_at_company": "Dyrektor IT",
                    "is_primary_employer": True,
                    "is_current": True,
                    "started_at": date(2026, 1, 1),
                },
                {
                    "company_id": "nie-zaimportowana",
                    "contact_id": f"p1-{tag}",
                },
            ],
            "linkedin_leads": [
                {"id": f"l-{tag}", "company_id": f"j3-{tag}", "status": "archived"}
            ],
            "press_signals": [
                {"id": f"s-{tag}", "company_id": f"j6-{tag}", "status": "archived"}
            ],
            "company_team_members": [{"company_id": f"j4-{tag}", "user_id": "u"}],
            "company_attachments": [{"id": "f", "company_id": f"j5-{tag}"}],
        }
    )
    report = await _import(source)

    assert report["companies_owner_label"] == 2
    assert report["companies_kept_by_domain_or_registry"] == 2
    assert report["companies_skipped_junk"] == 1  # tylko Grzegorz Nikt
    assert report["company_contacts_imported"] == 2
    assert report["company_contacts_skipped_unresolved"] == 1

    labels = {}
    for key in ("c1", "c2", "c3"):
        row = await _one(SalesCompany, f"atlas:companies:{key}-{tag}")
        labels[key] = (row.owner_user_id, row.owner_label)
    assert labels == {
        "c1": (None, "Handlowiec Archiwalny"),
        "c2": (None, "Opiekun Pipedrive"),
        "c3": (ala, None),
    }
    for key in ("j1", "j2", "j3", "j4", "j5", "j6"):
        kept = await _one(SalesCompany, f"atlas:companies:{key}-{tag}")
        assert ATLAS_REVIEW_TAG in kept.tags

    # Firma główna: obecny główny pracodawca wygrywa z ``primary_company_id``.
    c1 = await _one(SalesCompany, f"atlas:companies:c1-{tag}")
    c2 = await _one(SalesCompany, f"atlas:companies:c2-{tag}")
    contact = await _one(SalesContact, f"atlas:contacts:p1-{tag}")
    assert contact.company_id == c2.id
    async with AsyncSessionLocal() as db:
        links = {
            link.company_id: link
            for link in (
                await db.execute(
                    select(SalesCompanyContact).where(
                        SalesCompanyContact.contact_id == contact.id
                    )
                )
            ).scalars()
        }
    assert set(links) == {c1.id, c2.id}
    old, current = links[c1.id], links[c2.id]
    assert (old.role, old.is_current, old.is_primary, old.ended_at) == (
        "Doradca",
        False,
        False,
        date(2025, 12, 31),
    )
    assert (current.title, current.is_current, current.is_primary) == (
        "Dyrektor IT",
        True,
        True,
    )
    assert current.external_ref == "atlas:company_contacts"

    # Drugi bieg niczego nie dubluje, a firma główna zmieniona w NEXUSIE
    # przenosi znacznik „główna”.
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(SalesContact)
            .where(SalesContact.id == contact.id)
            .values(company_id=c1.id, updated_at=LATER + timedelta(hours=1))
        )
        await db.commit()
    await _import(source, LATER)
    async with AsyncSessionLocal() as db:
        primary = (
            await db.execute(
                select(SalesCompanyContact.company_id, SalesCompanyContact.is_primary)
                .where(SalesCompanyContact.contact_id == contact.id)
                .order_by(SalesCompanyContact.company_id)
            )
        ).all()
    assert dict(primary) == {c1.id: True, c2.id: False}


@pytest.mark.asyncio
async def test_outlook_fields_and_dictionary_misses_are_counted() -> None:
    tag = uuid.uuid4().hex[:8]
    sent = NOW - timedelta(days=3)
    source = FakeAtlas(
        {
            **_sales_pipeline(tag),
            "companies": [
                {
                    "id": f"c1-{tag}",
                    "name": f"Outlook {tag}",
                    "lifecycle_stage": "partner",
                    "account_tier": "gold",
                    "status": "paused",
                }
            ],
            "deals": [
                {
                    "id": f"d1-{tag}",
                    "title": "Szansa",
                    "company_id": f"c1-{tag}",
                    "stage_id": "stage-lead",
                    "status": "frozen",
                    "service_line": "outsourcing",
                }
            ],
            "deal_contacts": [],
            "deal_activities": [
                {
                    "id": f"a1-{tag}",
                    "deal_id": f"d1-{tag}",
                    "activity_type": "task",
                    "subject": "Pilne",
                    "priority": "urgent",
                }
            ],
            "company_activities": [
                {
                    "id": f"m1-{tag}",
                    "company_id": f"c1-{tag}",
                    "activity_type": "email",
                    "subject": "Odpowiedź klienta",
                    "external_source": "msgraph-mail",
                    "external_id": "<abc@example.com>",
                    "external_web_link": "https://outlook.example.com/m/1",
                    "direction": "incoming",
                    "due_date": sent,
                    "created_at": NOW,
                },
                {
                    "id": f"m2-{tag}",
                    "company_id": f"c1-{tag}",
                    "activity_type": "meeting",
                    "subject": "Spotkanie",
                    "external_source": "msgraph-event",
                    "external_id": "x" * 300,
                    "direction": "sideways",
                    "duration_minutes": 45,
                    "due_date": sent,
                },
                {
                    "id": f"m3-{tag}",
                    "company_id": f"c1-{tag}",
                    "activity_type": "fax",
                    "subject": "Nieznany rodzaj",
                    "direction": "outgoing",
                    "created_at": NOW,
                },
            ],
        }
    )
    report = await _import(source)
    for field in (
        "lifecycle_stage",
        "tier",
        "company_status",
        "opportunity_status",
        "service_line",
        "priority",
        "direction",
        "activity_kind",
    ):
        assert report[f"invalid_{field}"] == 1, field
    assert report["activities_external_id_too_long"] == 1

    mail = await _one(SalesActivity, f"atlas:company_activities:m1-{tag}")
    assert (mail.occurred_at, mail.due_at, mail.done_at) == (sent, None, sent)
    assert (mail.external_id, mail.web_link, mail.direction) == (
        "<abc@example.com>",
        "https://outlook.example.com/m/1",
        "in",
    )
    meeting = await _one(SalesActivity, f"atlas:company_activities:m2-{tag}")
    assert (meeting.external_id, meeting.direction, meeting.duration_minutes) == (
        None,
        None,
        45,
    )
    other = await _one(SalesActivity, f"atlas:company_activities:m3-{tag}")
    assert (other.kind, other.direction) == ("note", "out")
    company = await _one(SalesCompany, f"atlas:companies:c1-{tag}")
    assert (company.lifecycle_stage, company.tier, company.status) == (
        "lead",
        None,
        "active",
    )


@pytest.mark.asyncio
async def test_candidate_prep_notes_are_dropped_and_transcripts_become_meetings() -> (
    None
):
    tag = uuid.uuid4().hex[:8]
    meeting_at = NOW - timedelta(days=2)
    source = FakeAtlas(
        {
            **_sales_pipeline(tag),
            "companies": [{"id": f"c1-{tag}", "name": f"Fireflies {tag}"}],
            "deals": [
                {
                    "id": f"d1-{tag}",
                    "title": "Szansa",
                    "company_id": f"c1-{tag}",
                    "stage_id": "stage-lead",
                }
            ],
            "deal_notes": [
                {"id": f"n1-{tag}", "deal_id": f"d1-{tag}", "content": PREP_NOTE},
                {"id": f"n2-{tag}", "deal_id": f"d1-{tag}", "content": "Zwykła"},
            ],
            "company_notes": [
                {"id": f"n3-{tag}", "company_id": f"c1-{tag}", "content": PREP_NOTE}
            ],
            "meeting_transcripts": [
                {
                    "id": f"t1-{tag}",
                    "deal_id": f"d1-{tag}",
                    "status": "matched",
                    "meeting_title": "Warsztat z klientem",
                    "meeting_date": meeting_at,
                    "duration_minutes": 50,
                    "summary_overview": "Ustalenia",
                    "summary_action_items": ["Wysłać ofertę", ""],
                    "transcript_text": "Pełna rozmowa",
                },
                {
                    "id": f"t2-{tag}",
                    "deal_id": f"d1-{tag}",
                    "status": "internal",
                    "meeting_title": "Daily",
                },
                {
                    "id": f"t3-{tag}",
                    "deal_id": f"d1-{tag}",
                    "status": "matched",
                    "meeting_title": "Przygotowanie do spotkania z Klientem",
                },
                {"id": f"t4-{tag}", "deal_id": None, "meeting_title": "Bez szansy"},
                {"id": f"t5-{tag}", "deal_id": "nie-ma", "meeting_title": "Obca"},
            ],
        }
    )
    # Pierwszy import (sprzed poprawki) wpuścił notatki z przygotowań; wiersz
    # z innym źródłem i tym samym kluczem nie należy do importu.
    async with AsyncSessionLocal() as db:
        db.add_all(
            [
                SalesActivity(
                    kind="note",
                    body=PREP_NOTE,
                    external_source="atlas",
                    external_ref=f"atlas:deal_notes:n1-{tag}",
                ),
                SalesActivity(
                    kind="note",
                    body=PREP_NOTE,
                    external_source="reczne",
                    external_ref=f"atlas:company_notes:n3-{tag}",
                ),
            ]
        )
        await db.commit()

    report = await _import(source)
    assert report["notes_candidate_prep_skipped"] == 2
    assert report["notes_candidate_prep_removed"] == 1
    assert report["transcripts_imported"] == 1
    assert report["transcripts_candidate_prep_skipped"] == 1
    assert report["transcripts_skipped_deal_not_imported"] == 1

    async with AsyncSessionLocal() as db:
        refs = set(
            (
                await db.execute(
                    select(SalesActivity.external_ref).where(
                        SalesActivity.external_ref.like(f"atlas:%-{tag}")
                    )
                )
            ).scalars()
        )
    assert refs == {
        f"atlas:deal_notes:n2-{tag}",
        f"atlas:company_notes:n3-{tag}",  # nie z importu — zostaje
        f"atlas:meeting_transcripts:t1-{tag}",
    }
    meeting = await _one(SalesActivity, f"atlas:meeting_transcripts:t1-{tag}")
    company = await _one(SalesCompany, f"atlas:companies:c1-{tag}")
    assert (meeting.kind, meeting.external_source, meeting.subject) == (
        "meeting",
        "fireflies",
        "Warsztat z klientem",
    )
    assert (meeting.occurred_at, meeting.duration_minutes, meeting.company_id) == (
        meeting_at,
        50,
        company.id,
    )
    assert meeting.body == (
        "Ustalenia\n\nDo zrobienia:\n- Wysłać ofertę\n\n---\n\nPełna rozmowa"
    )


@pytest.mark.asyncio
async def test_leads_keep_structure_and_job_board_leads_from_atlas_go_away() -> None:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        db.add_all(
            [
                SalesLead(
                    source="job_board",
                    status=status,
                    title="Ogłoszenie",
                    fingerprint=fingerprint,
                )
                for status, fingerprint in (
                    ("new", f"atlas:press_signals:old-{tag}"),
                    ("dismissed", f"atlas:press_signals:kept-{tag}"),
                    ("new", f"reczny:{tag}"),
                )
            ]
        )
        await db.commit()
    source = FakeAtlas(
        {
            **_sales_pipeline(tag),
            "linkedin_leads": [
                {
                    "id": f"l1-{tag}",
                    "status": "new",
                    "summary": "Szukają zespołu",
                    "company_name": f"Lead Firma {tag}",
                    "person": {
                        "name": "Osoba Publiczna",
                        "headline": "CTO",
                        "email": "nie@example.com",
                        "phone_number": "+48 000",
                    },
                    "score_breakdown": {"intent": 30},
                }
            ],
            "press_signals": [
                {
                    "id": f"s1-{tag}",
                    "status": "new",
                    "article_title": "Nowe centrum IT",
                    "company_name": f"Prasa Firma {tag}",
                    "source_category": "press",
                    "trigger_details": {"kind": "expansion"},
                    "score_breakdown": {"recency": 10},
                },
                {
                    "id": f"s2-{tag}",
                    "status": "new",
                    "article_title": "Ogłoszenie",
                    "company_name": f"Ogłoszenie Firma {tag}",
                    "source_category": "job_board",
                },
            ],
        }
    )
    report = await _import(source)
    assert report["leads_skipped_job_board"] == 1
    assert report["leads_job_board_removed"] >= 1

    async with AsyncSessionLocal() as db:
        leads = {
            lead.fingerprint: lead
            for lead in (
                await db.execute(
                    select(SalesLead).where(SalesLead.fingerprint.like(f"%{tag}"))
                )
            ).scalars()
        }
    assert set(leads) == {
        f"atlas:linkedin_leads:l1-{tag}",
        f"atlas:press_signals:s1-{tag}",
        f"atlas:press_signals:kept-{tag}",
        f"reczny:{tag}",
    }
    linkedin = leads[f"atlas:linkedin_leads:l1-{tag}"].payload
    assert linkedin["person"] == {"name": "Osoba Publiczna", "headline": "CTO"}
    assert linkedin["score_breakdown"] == {"intent": 30}
    press = leads[f"atlas:press_signals:s1-{tag}"].payload
    assert press["trigger_details"] == {"kind": "expansion"}
    assert press["score_breakdown"] == {"recency": 10}


@pytest.mark.asyncio
async def test_script_source_reads_missing_optional_tables_as_empty() -> None:
    import asyncpg

    from scripts.import_atlas_sales import AsyncpgSource

    class Connection:
        async def fetch(self, query: str):
            if "meeting_transcripts" in query or "deals" in query:
                raise asyncpg.UndefinedTableError("brak tabeli")
            return [{"company_id": "c1"}]

    source = AsyncpgSource(Connection())
    assert await source.meeting_transcripts() == []
    assert await source.company_team_members() == [{"company_id": "c1"}]
    with pytest.raises(asyncpg.UndefinedTableError):
        await source.deals()  # tabela obowiązkowa — błąd nie jest połykany


@pytest.mark.asyncio
async def test_reimport_follows_company_merges_made_in_nexus() -> None:
    tag = uuid.uuid4().hex[:8]
    source = FakeAtlas(
        {
            **_sales_pipeline(tag),
            "companies": [
                {"id": f"a-{tag}", "name": f"Scalona Docelowa {tag}"},
                {
                    "id": f"b-{tag}",
                    "name": f"Scalona Źródłowa {tag}",
                    "custom_fields": {"segment": "IT"},
                },
            ],
            "contacts": [
                {
                    "id": f"p-{tag}",
                    "full_name": "Osoba Scalana",
                    "primary_company_id": f"b-{tag}",
                }
            ],
            "company_contacts": [
                {"company_id": f"b-{tag}", "contact_id": f"p-{tag}", "role": "CTO"}
            ],
            "deals": [
                {
                    "id": f"d-{tag}",
                    "title": "Szansa źródłowej",
                    "company_id": f"b-{tag}",
                    "stage_id": "stage-lead",
                }
            ],
            "company_activities": [
                {
                    "id": f"ca-{tag}",
                    "company_id": f"b-{tag}",
                    "activity_type": "email",
                    "subject": "Mail",
                    "created_at": NOW,
                }
            ],
        }
    )
    await _import(source)
    a_ref, b_ref = f"atlas:companies:a-{tag}", f"atlas:companies:b-{tag}"
    async with AsyncSessionLocal() as db:
        target = (
            await db.execute(
                select(SalesCompany).where(SalesCompany.external_ref == a_ref)
            )
        ).scalar_one()
        merged = (
            await db.execute(
                select(SalesCompany).where(SalesCompany.external_ref == b_ref)
            )
        ).scalar_one()
        a_id = target.id
        await merge_companies(
            db, target=target, source=merged, now=NOW + timedelta(hours=1)
        )
        await db.commit()

    report = await _import(source, LATER)
    assert report["companies_redirected_to_merge_target"] == 1

    assert (await _one(SalesOpportunity, f"atlas:deals:d-{tag}")).company_id == a_id
    assert (await _one(SalesContact, f"atlas:contacts:p-{tag}")).company_id == a_id
    activity = await _one(SalesActivity, f"atlas:company_activities:ca-{tag}")
    assert activity.company_id == a_id
    async with AsyncSessionLocal() as db:
        contact_id = (await _one(SalesContact, f"atlas:contacts:p-{tag}")).id
        links = dict(
            (
                await db.execute(
                    select(
                        SalesCompanyContact.company_id, SalesCompanyContact.is_primary
                    ).where(SalesCompanyContact.contact_id == contact_id)
                )
            ).all()
        )
    assert links == {a_id: True}
    archived = await _one(SalesCompany, b_ref)
    assert archived.archived_at is not None
    assert archived.custom_fields["merged_into"] == a_id
    assert archived.custom_fields["atlas"] == {"segment": "IT"}


@pytest.mark.asyncio
async def test_merge_chains_resolve_to_last_target_and_cycles_are_left_alone() -> None:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        made = [
            SalesCompany(
                name=f"Łańcuch {n} {tag}", normalized_name=f"lancuch {n} {tag}"
            )
            for n in range(5)
        ]
        db.add_all(made)
        await db.flush()
        a, b, c, x, y = (company.id for company in made)
        for company, target in zip(made, (b, c, None, y, x)):
            if target is not None:
                company.custom_fields = {"merged_into": target}
        await db.flush()
        report = ImportReport()
        targets = await company_merge_targets(db, report)
        await db.rollback()
    assert (targets[a], targets[b]) == (c, c)
    assert c not in targets and x not in targets and y not in targets
    assert report.as_dict()["companies_merge_cycle"] == 2


@pytest.mark.asyncio
async def test_first_reimport_keeps_edits_made_after_the_first_import() -> None:
    tag = uuid.uuid4().hex[:8]
    first_import = datetime(2026, 10, 1, 18, 20, tzinfo=timezone.utc)
    source = FakeAtlas(
        {
            **_sales_pipeline(tag),
            "companies": [{"id": f"c-{tag}", "name": f"Pierwszy Import {tag}"}],
            "deals": [
                {
                    "id": f"d{n}-{tag}",
                    "title": f"Szansa {n}",
                    "company_id": f"c-{tag}",
                    "stage_id": "stage-lead",
                }
                for n in (1, 2)
            ],
            "deal_activities": [
                {
                    "id": f"a{n}-{tag}",
                    "deal_id": f"d1-{tag}",
                    "activity_type": "task",
                    "subject": f"Zadanie {n}",
                }
                for n in (1, 2)
            ],
        }
    )
    await _import(source)
    proposal = await _one(SalesOpportunity, f"atlas:deals:d2-{tag}")
    async with AsyncSessionLocal() as db:
        # Stan po imporcie 28.10: bez ``synced_at``, jeden ``updated_at``.
        for model in (SalesCompany, SalesOpportunity, SalesActivity):
            await db.execute(
                update(model)
                .where(model.external_ref.like(f"atlas:%-{tag}"))
                .values(synced_at=None, updated_at=first_import)
            )
        edited_at = first_import + timedelta(days=1)
        await db.execute(
            update(SalesActivity)
            .where(SalesActivity.external_ref == f"atlas:deal_activities:a1-{tag}")
            .values(done_at=edited_at, updated_at=edited_at)
        )
        stage_id = (
            await db.execute(
                select(SalesPipelineStage.id)
                .join(SalesPipeline, SalesPipeline.id == SalesPipelineStage.pipeline_id)
                .where(
                    SalesPipeline.key == "sales", SalesPipelineStage.key == "qualified"
                )
            )
        ).scalar_one()
        await db.execute(
            update(SalesOpportunity)
            .where(SalesOpportunity.external_ref == f"atlas:deals:d1-{tag}")
            .values(stage_id=stage_id, title="Etap z NEXUSA", updated_at=edited_at)
        )
        await db.commit()
    assert proposal.stage_id != stage_id

    for deal in source.data["deals"]:
        deal["title"] = f"{deal['title']} v2"
        deal["stage_id"] = "stage-proposal"
    for activity in source.data["deal_activities"]:
        activity["subject"] = f"{activity['subject']} v2"
    report = await _import(source, LATER)
    assert report["edited_in_nexus_sales_activities"] >= 1
    assert report["edited_in_nexus_sales_opportunities"] >= 1

    edited = await _one(SalesOpportunity, f"atlas:deals:d1-{tag}")
    untouched = await _one(SalesOpportunity, f"atlas:deals:d2-{tag}")
    assert edited.title == "Etap z NEXUSA"
    assert untouched.title == "Szansa 2 v2"
    assert untouched.stage_id not in (stage_id, proposal.stage_id)  # etap z Atlasa
    assert edited.stage_id == stage_id  # zostaje etap ustawiony w NEXUSIE
    done = await _one(SalesActivity, f"atlas:deal_activities:a1-{tag}")
    fresh = await _one(SalesActivity, f"atlas:deal_activities:a2-{tag}")
    assert (done.done_at, done.subject) == (edited_at, "Zadanie 1")
    assert (fresh.done_at, fresh.subject) == (None, "Zadanie 2 v2")


@pytest.mark.asyncio
async def test_link_removed_in_nexus_does_not_come_back() -> None:
    tag = uuid.uuid4().hex[:8]
    source = FakeAtlas(
        {
            **_sales_pipeline(tag),
            "companies": [
                {"id": f"c1-{tag}", "name": f"Główna {tag}"},
                {"id": f"c2-{tag}", "name": f"Druga {tag}"},
            ],
            "contacts": [
                {
                    "id": f"p-{tag}",
                    "full_name": "Osoba Odpięta",
                    "primary_company_id": f"c1-{tag}",
                }
            ],
            "company_contacts": [
                {"company_id": f"c1-{tag}", "contact_id": f"p-{tag}"},
                {
                    "company_id": f"c2-{tag}",
                    "contact_id": f"p-{tag}",
                    "is_primary_employer": False,
                },
            ],
        }
    )
    await _import(source)
    contact = await _one(SalesContact, f"atlas:contacts:p-{tag}")
    c2 = await _one(SalesCompany, f"atlas:companies:c2-{tag}")
    async with AsyncSessionLocal() as db:
        link = await db.get(SalesCompanyContact, (c2.id, contact.id))
        assert link is not None
        await db.delete(link)  # jak DELETE /api/sales/contacts/{id}/companies/{id}
        await db.commit()

    report = await _import(source, LATER)
    assert report["company_contacts_not_reinserted"] == 1
    async with AsyncSessionLocal() as db:
        assert await db.get(SalesCompanyContact, (c2.id, contact.id)) is None
