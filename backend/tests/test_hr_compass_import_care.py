"""Import mapy technologicznej i rozmów opiekunów z Compassa.

Klucz do kontraktu NEXUSA: kotwica osoby z Compassa (``nexus_candidate_id``
albo ``nexus_contract_id``) + klient + okres, a bez kotwicy — klient, imię
i nazwisko i dzień (karty i rozmowy). Niepewne = „conflict”.
Paczki i dane NEXUSA fikcyjne, rollback na końcu.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus, RateUnit
from app.models.contract_care import (
    CareConversation,
    ClientArea,
    SkillReviewItem,
    TechCard,
    TechCardSkill,
    TechCardVendor,
)
from app.models.skill import Skill, SkillAlias
from app.services.hr import compass_import
from app.services.care import card_linking
from app.services.hr.compass_import import care as care_import
from tests.test_hr_compass_import_leave import (
    assert_report_clean,
    make_bundle,
    make_person,
    run_import,
)


async def _contract(db, candidate: Candidate, client: Client, start: date) -> Contract:
    contract = Contract(
        candidate_id=candidate.id,
        client_id=client.id,
        status=ContractStatus.active,
        start_date=start,
        end_date=None,
        rate_candidate=Decimal("100.000"),
        rate_client=Decimal("130.000"),
        rate_unit=RateUnit.hourly,
    )
    db.add(contract)
    await db.flush()
    return contract


def _card(contractor: str, client: str, **values) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "contractor_id": contractor,
        "client_id": client,
        "client_area_id": None,
        "tcm_id": None,
        "created_by": None,
        "interview_date": "2026-08-10",
        "status": "ok",
        "is_draft": False,
        "finalized_at": "2026-08-10T12:00:00+00:00",
        "satisfaction": 4,
        "satisfaction_comment": None,
        "hiring": False,
        "hiring_source": None,
        "hiring_roles": [],
        "project_end_month": None,
        "project_end_year": None,
        "project_end_unknown": True,
        "team_size": "8",
        "team_externals": 2,
        "memorable_quote": None,
        "tech_old_new": None,
        "vendors_note": None,
        "title": None,
        "professional_insurance": None,
        "created_at": "2026-08-10T12:00:00+00:00",
        **values,
    }


def _conversation(contractor: str, day: str, client: str, **values) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "contractor_id": contractor,
        "conversation_date": day,
        "client_snapshot": client,
        "category": "follow_up",
        "status": "w_toku",
        "note": "Konsultant zadowolony z projektu.",
        "follow_up_date": None,
        "tcm_id": None,
        "created_by": None,
        "created_at": f"{day}T12:00:00+00:00",
        **values,
    }


@pytest.mark.asyncio
async def test_care_dry_run_apply_and_second_apply_changes_nothing() -> None:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        try:
            tcm, t_id, t_row = await make_person(db, f"{tag}-tcm")
            client = Client(name=f"Bank Przykładowy {tag} S.A.")
            linked = Candidate(
                name="Konsultant", lastname=f"Jeden{tag}", email=f"k1-{tag}@example.com"
            )
            twice = Candidate(
                name="Konsultant", lastname=f"Dwa{tag}", email=f"k2-{tag}@example.com"
            )
            db.add_all([client, linked, twice])
            await db.flush()
            contract = await _contract(db, linked, client, date(2026, 1, 1))
            await _contract(db, twice, client, date(2026, 1, 1))
            await _contract(db, twice, client, date(2026, 3, 1))
            kotlin = Skill(canonical_name=f"kotlin{tag}")
            spring = Skill(canonical_name=f"spring{tag}")
            db.add_all([kotlin, spring])
            await db.flush()
            db.add(SkillAlias(skill_id=spring.id, alias=f"sb{tag}"))
            await db.flush()

            compass_client = str(uuid.uuid4())
            area = {
                "id": str(uuid.uuid4()),
                "client_id": compass_client,
                "name": "Płatności",
            }
            vendor = {"id": str(uuid.uuid4()), "name": f"Dostawca {tag}"}
            techs = [
                {"id": str(uuid.uuid4()), "name": f"Kotlin{tag}", "aliases": []},
                {
                    "id": str(uuid.uuid4()),
                    "name": f"Spring Boot {tag}",
                    "aliases": [f"SB{tag}"],
                },
                {"id": str(uuid.uuid4()), "name": f"Nieznana{tag}", "aliases": []},
            ]
            contractors = [
                {
                    "id": str(uuid.uuid4()),
                    "full_name": "Konsultant Jeden",
                    "nexus_candidate_id": linked.id,
                },
                {
                    "id": str(uuid.uuid4()),
                    "full_name": "Konsultant Dwa",
                    "nexus_candidate_id": twice.id,
                },
                {
                    "id": str(uuid.uuid4()),
                    "full_name": "Konsultant Trzy",
                    "nexus_candidate_id": None,
                },
                {
                    "id": str(uuid.uuid4()),
                    "full_name": "Konsultant Jeden",
                    "nexus_candidate_id": None,
                    "nexus_contract_id": contract.id,
                },
            ]
            ca, cb, cn, cc = (row["id"] for row in contractors)

            full = _card(
                ca,
                compass_client,
                client_area_id=area["id"],
                tcm_id=t_id,
                title="Migracja płatności",
                hiring=True,
                hiring_source="widzial",
                hiring_roles=["Tester"],
            )
            ambiguous = _card(cb, compass_client)
            # Opiekun bez konta w NEXUSIE → karta bez autora (nie pominięta).
            unlinked = _card(cn, compass_client, tcm_id=str(uuid.uuid4()))
            unknown_tech = _card(ca, compass_client, interview_date="2026-09-01")
            no_client = _card(ca, str(uuid.uuid4()))
            card_techs = [
                {"card_id": full["id"], "technology_id": techs[0]["id"]},
                {"card_id": full["id"], "technology_id": techs[1]["id"]},
                {"card_id": ambiguous["id"], "technology_id": techs[0]["id"]},
                {"card_id": unknown_tech["id"], "technology_id": techs[2]["id"]},
            ]
            conversations = [
                _conversation(
                    cc, "2026-08-12", f"BANK PRZYKŁADOWY {tag} s.a.", tcm_id=t_id
                ),
                _conversation(cb, "2026-08-12", f"Bank Przykładowy {tag} S.A."),
                _conversation(cn, "2026-08-12", f"Bank Przykładowy {tag} S.A."),
                _conversation(ca, "2025-06-02", f"Bank Przykładowy {tag} S.A."),
            ]
            bundle = make_bundle(
                {
                    "profiles": [t_row],
                    "clients": [
                        {"id": compass_client, "name": f"bank przykładowy {tag} s.a."}
                    ],
                    "client_areas": [area],
                    "vendors": [vendor],
                    "technologies": techs,
                    "contractors": contractors,
                    "tech_interview_cards": [
                        full,
                        ambiguous,
                        unlinked,
                        unknown_tech,
                        no_client,
                    ],
                    "tech_interview_card_technologies": card_techs,
                    "tech_interview_card_vendors": [
                        {"card_id": full["id"], "vendor_id": vendor["id"]}
                    ],
                    "tech_interview_card_initiatives": [
                        {
                            "card_id": full["id"],
                            "name": "Nowy system płatności",
                            "kind": "nowy_system",
                            "priority": "wysoki",
                        }
                    ],
                    "contractor_conversations": conversations,
                }
            )
            importer = compass_import.IMPORTERS["care"]

            batch, report, written = await run_import(db, "care", bundle)
            assert report["counts"] == {"create": 2, "conflict": 6, "skip": 1}
            reasons = report["reasons"]
            assert reasons[care_import.UNSURE_CONTRACT] == 1
            assert reasons[care_import.UNKNOWN_SKILL] == 1
            # Karta i rozmowa bez kotwicy szukają kontraktu po nazwisku (tu
            # nikogo takiego nie ma) — obie czekają.
            assert care_import.NO_LINK not in reasons
            assert reasons[care_import.NAME_NOT_FOUND] == 2
            assert reasons["kontrakt rozmowy niepewny"] == 2
            assert reasons["klient karty bez odpowiednika w NEXUSIE"] == 1
            assert_report_clean(
                batch.report, "Konsultant", "Migracja płatności", "zadowolony"
            )
            assert written == {
                "cards_written": 4,
                "cards_without_contract": 2,
                "conversations_written": 1,
                "rhythms_written": 0,
                "owners_written": 0,
            }

            cards = {
                str(card.compass_card_id): card
                for card in await db.scalars(
                    select(TechCard).where(TechCard.client_id == client.id)
                )
            }
            first = cards[full["id"]]
            assert first.contract_id == contract.id
            assert first.author_user_id == tcm.id
            assert first.is_draft is False
            assert first.hiring_source == "widzial"
            assert first.hiring_roles == ["Tester"]
            assert first.initiatives == [
                {
                    "name": "Nowy system płatności",
                    "kind": "nowy_system",
                    "priority": "wysoki",
                }
            ]
            assert "Temat: Migracja płatności" in first.note
            skills = set(
                await db.scalars(
                    select(TechCardSkill.skill_id).where(
                        TechCardSkill.card_id == first.id
                    )
                )
            )
            assert skills == {kotlin.id, spring.id}
            assert (
                await db.scalar(
                    select(TechCardVendor.vendor_id).where(
                        TechCardVendor.card_id == first.id
                    )
                )
                is not None
            )
            assert (
                await db.scalar(
                    select(ClientArea.name).where(ClientArea.id == first.client_area_id)
                )
                == "Płatności"
            )
            assert cards[ambiguous["id"]].contract_id is None
            assert cards[unlinked["id"]].contract_id is None
            assert cards[unlinked["id"]].author_user_id is None
            queued = cards[unknown_tech["id"]]
            assert queued.contract_id == contract.id
            assert queued.unrecognized_skills == [f"nieznana{tag}"]
            review = await db.scalar(
                select(SkillReviewItem).where(
                    SkillReviewItem.name_key == f"nieznana{tag}"
                )
            )
            assert (review.status, review.occurrences) == ("open", 1)
            assert no_client["id"] not in cards

            conversation = await db.scalar(
                select(CareConversation).where(
                    CareConversation.compass_source_id == conversations[0]["id"]
                )
            )
            assert conversation.contract_id == contract.id
            assert conversation.author_user_id == tcm.id
            assert conversation.note.startswith("Follow-up · w toku")
            assert (
                await db.scalar(
                    select(CareConversation.id).where(
                        CareConversation.compass_source_id == conversations[1]["id"]
                    )
                )
                is None
            )

            batch2, _ = await compass_import.dry_run(
                db,
                module="care",
                bundle=bundle,
                planner=importer.plan,
                actor_user_id=None,
            )
            assert batch2.report["dry_run"]["counts"] == {
                "unchanged": 5,
                "conflict": 3,
                "skip": 1,
            }
            written2 = await compass_import.apply(
                db,
                batch=batch2,
                bundle=bundle,
                planner=importer.plan,
                applier=importer.apply,
                actor_user_id=None,
            )
            assert written2 == {
                "cards_written": 0,
                "cards_without_contract": 0,
                "conversations_written": 0,
                "rhythms_written": 0,
                "owners_written": 0,
            }
            await db.refresh(review)
            assert review.occurrences == 1
        finally:
            await db.rollback()


@pytest.mark.asyncio
async def test_card_without_anchor_links_by_client_name_and_date() -> None:
    """18.10.2026: kolejka „Tożsamość NEXUS” jest pusta, więc karta łączy się
    z kontraktem po kliencie (także bez formy prawnej), imieniu i nazwisku
    (bez polskich znaków, kolejności i dopisków Traffita) i dniu rozmowy.
    Niepewne czekają bez kontraktu, z nazwiskiem z Compassa na karcie."""

    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        try:
            client = Client(name=f"Spółka Testowa {tag} sp. z o.o.")
            other = Client(name=f"Inna Spółka {tag}")
            sure = Candidate(
                name="Łukasz", lastname=f"Żółw{tag}", email=f"z-{tag}@example.com"
            )
            twice = Candidate(
                name="Anna", lastname=f"Nowak{tag}", email=f"n-{tag}@example.com"
            )
            later = Candidate(
                name="Ewa", lastname=f"Kot{tag}", email=f"k-{tag}@example.com"
            )
            elsewhere = Candidate(
                name="Jan", lastname=f"Obcy{tag}", email=f"o-{tag}@example.com"
            )
            # Dwa nie scalone rekordy tego samego klienta (duplikat z Traffita)
            # i klient przemianowany („ex”).
            dup_a = Client(name=f"Fundusz {tag}")
            dup_b = Client(name=f"Fundusz {tag}")
            renamed = Client(name=f"Bank {tag} (ex Stary{tag})")
            at_dup = Candidate(
                name="Olga", lastname=f"Dubel{tag}", email=f"d-{tag}@example.com"
            )
            db.add_all(
                [client, other, sure, twice, later, elsewhere]
                + [dup_a, dup_b, renamed, at_dup]
            )
            await db.flush()
            dup_contract = await _contract(db, at_dup, dup_b, date(2026, 1, 1))
            sure_contract = await _contract(db, sure, client, date(2026, 1, 1))
            sure_contract.end_date = date(2026, 12, 31)
            twice_first = await _contract(db, twice, client, date(2026, 1, 1))
            twice_second = await _contract(db, twice, client, date(2026, 3, 1))
            later_contract = await _contract(db, later, client, date(2026, 9, 1))
            await _contract(db, elsewhere, other, date(2026, 1, 1))
            await db.flush()

            compass_client = str(uuid.uuid4())
            compass_dup = str(uuid.uuid4())
            compass_renamed = str(uuid.uuid4())
            contractors = [
                {"id": str(uuid.uuid4()), "full_name": f"zolw{tag} lukasz [ACTIVE]"},
                {"id": str(uuid.uuid4()), "full_name": f"Anna Nowak{tag}"},
                {"id": str(uuid.uuid4()), "full_name": f"Ewa Kot{tag}"},
                {"id": str(uuid.uuid4()), "full_name": f"Jan Obcy{tag}"},
            ]
            ids = [row["id"] for row in contractors]
            cards = [_card(contractor, compass_client) for contractor in ids]
            dup_person = {"id": str(uuid.uuid4()), "full_name": f"Olga Dubel{tag}"}
            contractors.append(dup_person)
            dup_card = _card(dup_person["id"], compass_dup)
            renamed_card = _card(ids[3], compass_renamed)
            bundle = make_bundle(
                {
                    "clients": [
                        {"id": compass_client, "name": f"SPÓŁKA TESTOWA {tag}"},
                        {"id": compass_dup, "name": f"Fundusz {tag}"},
                        {"id": compass_renamed, "name": f"Bank {tag} / Stary{tag}"},
                    ],
                    "contractors": contractors,
                    "tech_interview_cards": [*cards, dup_card, renamed_card],
                }
            )
            batch, report, written = await run_import(db, "care", bundle)
            assert report["extra"]["cards"] == {
                "linked_by_anchor": 0,
                "linked_by_name": 2,
                "to_confirm_with_suggestions": 2,
                "to_confirm_without_match": 2,
                "without_client": 0,
            }
            assert report["reasons"][care_import.NAME_LINKED] == 2
            assert report["reasons"][care_import.NAME_SUGGESTED] == 2
            assert report["reasons"][care_import.NAME_NOT_FOUND] == 2
            assert_report_clean(batch.report, "Nowak", "Kot", "Obcy", "lukasz")
            assert written["cards_written"] == 6
            assert written["cards_without_contract"] == 4
            by_source = {
                str(card.compass_card_id): card
                for card in await db.scalars(
                    select(TechCard).where(
                        TechCard.client_id.in_([dup_a.id, dup_b.id, renamed.id])
                    )
                )
            }
            assert by_source[dup_card["id"]].client_id == dup_b.id
            assert by_source[dup_card["id"]].contract_id == dup_contract.id
            assert by_source[renamed_card["id"]].client_id == renamed.id
            assert by_source[renamed_card["id"]].contract_id is None

            stored = {
                str(card.compass_card_id): card
                for card in await db.scalars(
                    select(TechCard).where(TechCard.client_id == client.id)
                )
            }
            assert stored[cards[0]["id"]].contract_id == sure_contract.id
            assert stored[cards[1]["id"]].contract_id is None
            assert stored[cards[2]["id"]].contract_id is None
            assert stored[cards[2]["id"]].compass_person_name == f"Ewa Kot{tag}"
            assert stored[cards[3]["id"]].contract_id is None

            # Kontrakt osoby zaczął się po rozmowie — po imporcie zmienia się
            # okres umowy, więc ponowny import łączy kartę sam („update”).
            later_contract.start_date = date(2026, 8, 1)
            await db.flush()
            importer = compass_import.IMPORTERS["care"]
            batch2, plan2 = await compass_import.dry_run(
                db,
                module="care",
                bundle=bundle,
                planner=importer.plan,
                actor_user_id=None,
            )
            assert plan2.counts().get("update") == 1
            await compass_import.apply(
                db,
                batch=batch2,
                bundle=bundle,
                planner=importer.plan,
                applier=importer.apply,
                actor_user_id=None,
            )
            await db.refresh(stored[cards[2]["id"]])
            assert stored[cards[2]["id"]].contract_id == later_contract.id

            # Delivery Lead wybrał drugi kontrakt z propozycji; potem jego
            # okres się zmienia i „pewny” po dacie staje się pierwszy. Ponowny
            # import nie przepina wyboru człowieka.
            stored[cards[1]["id"]].contract_id = twice_second.id
            twice_second.start_date = date(2026, 9, 1)
            await db.flush()
            batch3, plan3 = await compass_import.dry_run(
                db,
                module="care",
                bundle=bundle,
                planner=importer.plan,
                actor_user_id=None,
            )
            assert not plan3.counts().get("update")
            await compass_import.apply(
                db,
                batch=batch3,
                bundle=bundle,
                planner=importer.plan,
                applier=importer.apply,
                actor_user_id=None,
            )
            await db.refresh(stored[cards[1]["id"]])
            assert stored[cards[1]["id"]].contract_id == twice_second.id
            assert twice_first.id != twice_second.id
        finally:
            await db.rollback()


@pytest.mark.asyncio
async def test_conversation_without_anchor_links_by_name_or_follows_card() -> None:
    """18.10.2026 (Artur: „jak karty”): rozmowa bez kotwicy łączy się po
    kliencie z ``client_snapshot`` (pusty = obecny klient), imieniu i nazwisku
    i dniu rozmowy. Kilka kontraktów = czeka, a po połączeniu karty osoby przez
    DL ponowny import bierze kontrakt karty, gdy dzień jest w umowie."""

    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        try:
            client = Client(name=f"Spółka Rozmów {tag} sp. z o.o.")
            sure = Candidate(
                name="Łukasz", lastname=f"Żółw{tag}", email=f"z-{tag}@example.com"
            )
            twice = Candidate(
                name="Anna", lastname=f"Nowak{tag}", email=f"n-{tag}@example.com"
            )
            db.add_all([client, sure, twice])
            await db.flush()
            sure_contract = await _contract(db, sure, client, date(2026, 1, 1))
            sure_contract.end_date = date(2026, 12, 31)
            first_twice = await _contract(db, twice, client, date(2026, 1, 1))
            second_twice = await _contract(db, twice, client, date(2026, 3, 1))
            first_twice.end_date = date(2026, 12, 31)
            await db.flush()

            snapshot = f"SPÓŁKA ROZMÓW {tag}"
            compass_client = str(uuid.uuid4())
            contractors = [
                {
                    "id": str(uuid.uuid4()),
                    "full_name": f"zolw{tag} lukasz",
                    "current_client": snapshot,
                },
                {"id": str(uuid.uuid4()), "full_name": f"Anna Nowak{tag}"},
                {"id": str(uuid.uuid4()), "full_name": f"Jan Obcy{tag}"},
            ]
            cs, ct, cn = (row["id"] for row in contractors)
            twice_card = _card(ct, compass_client)
            conversations = [
                _conversation(cs, "2026-08-12", snapshot),
                _conversation(cs, "2026-09-01", "", note="Bez klienta w rozmowie."),
                _conversation(ct, "2026-08-12", snapshot),
                _conversation(cn, "2026-08-12", snapshot),
                _conversation(cs, "2026-08-12", f"Nieznany Klient {tag}"),
            ]
            bundle = make_bundle(
                {
                    "clients": [{"id": compass_client, "name": snapshot}],
                    "contractors": contractors,
                    "tech_interview_cards": [twice_card],
                    "contractor_conversations": conversations,
                }
            )
            batch, report, written = await run_import(db, "care", bundle)
            assert report["extra"]["conversations"] == {
                "linked_by_anchor": 0,
                "linked_by_card": 0,
                "linked_by_name": 2,
                "waiting_with_suggestions": 1,
                "waiting_without_match": 1,
                "without_client": 1,
            }
            assert report["reasons"][care_import.CONVERSATION_WAITS] == 1
            assert report["reasons"][care_import.CONVERSATION_NO_CLIENT] == 1
            assert_report_clean(batch.report, "Nowak", "Obcy", "lukasz", "Bez klienta")
            assert written["conversations_written"] == 2

            def stored(index: int):
                return db.scalar(
                    select(CareConversation.contract_id).where(
                        CareConversation.compass_source_id == conversations[index]["id"]
                    )
                )

            assert await stored(0) == sure_contract.id
            assert await stored(1) == sure_contract.id
            assert await stored(2) is None
            assert await stored(3) is None
            assert await stored(4) is None

            # DL łączy kartę Anny z drugim kontraktem → rozmowa idzie za kartą.
            card = await db.scalar(
                select(TechCard).where(
                    TechCard.compass_card_id == uuid.UUID(twice_card["id"])
                )
            )
            assert card.contract_id is None
            card.contract_id = second_twice.id
            await db.flush()
            importer = compass_import.IMPORTERS["care"]
            batch2, plan2 = await compass_import.dry_run(
                db,
                module="care",
                bundle=bundle,
                planner=importer.plan,
                actor_user_id=None,
            )
            assert plan2.counts() == {
                "unchanged": 3,
                "create": 1,
                "conflict": 1,
                "skip": 1,
            }
            await compass_import.apply(
                db,
                batch=batch2,
                bundle=bundle,
                planner=importer.plan,
                applier=importer.apply,
                actor_user_id=None,
            )
            assert await stored(2) == second_twice.id
            # Dzień poza umową karty → karta nie decyduje, rozmowa dalej czeka.
            assert (
                care_import.Links(
                    clients_by_key={},
                    compass_clients={},
                    contractors={},
                    card_contracts={
                        ct: [
                            card_linking.ContractRow(
                                contract_id=second_twice.id,
                                candidate_id=twice.id,
                                client_id=client.id,
                                start=date(2026, 3, 1),
                                end=None,
                            )
                        ]
                    },
                ).card_contract_for(ct, client.id, date(2026, 2, 1))
                is None
            )
        finally:
            await db.rollback()


@pytest.mark.asyncio
async def test_care_dry_run_writes_nothing() -> None:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        try:
            client = Client(name=f"Klient Próbny {tag}")
            db.add(client)
            await db.flush()
            compass_client = str(uuid.uuid4())
            contractor = {
                "id": str(uuid.uuid4()),
                "full_name": "X",
                "nexus_candidate_id": None,
            }
            card = _card(contractor["id"], compass_client)
            bundle = make_bundle(
                {
                    "clients": [{"id": compass_client, "name": f"Klient Próbny {tag}"}],
                    "contractors": [contractor],
                    "tech_interview_cards": [card],
                }
            )
            importer = compass_import.IMPORTERS["care"]
            _, plan = await compass_import.dry_run(
                db,
                module="care",
                bundle=bundle,
                planner=importer.plan,
                actor_user_id=None,
            )
            assert plan.counts() == {"conflict": 1}
            assert (
                await db.scalar(
                    select(TechCard.id).where(TechCard.client_id == client.id)
                )
                is None
            )
        finally:
            await db.rollback()


def _rhythm(contractor: str, **values) -> dict:
    return {
        "contractor_id": contractor,
        "monitoring_status": "active",
        "check_in_cadence_days": 30,
        "onboarding_program_ends_on": None,
        "onboarding_program_completed_at": None,
        **values,
    }


@pytest.mark.asyncio
async def test_care_import_brings_rhythm_and_owner_only_for_sure_contracts() -> None:
    """Etap 3: rytm z ``contractor_success_settings`` i opiekun z
    ``contractors.owner_tcm_id`` — tylko przy pewnym kontrakcie (kotwica osoby
    + klient + okres), opiekun ustawiony w NEXUSIE zostaje."""

    from app.models.contract_care import CONTRACTS_CARE, CareCadencePeriod
    from app.models.user import UserRole

    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        try:
            tcm, t_id, t_row = await make_person(
                db, f"{tag}-tcm", role=UserRole.talent_community_manager
            )
            other, _o_id, _o_row = await make_person(
                db, f"{tag}-inny", role=UserRole.talent_community_manager
            )
            rec, r_id, r_row = await make_person(db, f"{tag}-rek")
            client = Client(name=f"Bank Rytmu {tag} S.A.")
            people = [
                Candidate(
                    name="Konsultant",
                    lastname=f"R{index}{tag}",
                    email=f"r{index}-{tag}@example.com",
                )
                for index in range(8)
            ]
            db.add_all([client, *people])
            await db.flush()
            contracts = [
                await _contract(db, person, client, date(2026, 1, 1))
                for person in people
            ]
            # Dwa trwające kontrakty tej samej osoby — kontrakt niepewny.
            await _contract(db, people[7], client, date(2026, 3, 1))
            await db.execute(
                CONTRACTS_CARE.update()
                .where(CONTRACTS_CARE.c.id == contracts[5].id)
                .values(care_owner_user_id=other.id)
            )
            await db.flush()

            def contractor(index: int, owner: str | None, anchor: bool = True) -> dict:
                return {
                    "id": str(uuid.uuid4()),
                    "nexus_candidate_id": people[index].id if anchor else None,
                    "nexus_contract_id": None,
                    "owner_tcm_id": owner,
                    "current_client": f"bank rytmu {tag} s.a.",
                }

            rows = [
                contractor(0, t_id),  # co 14 dni → co 2 tygodnie, opiekun TCM
                contractor(
                    1, r_id
                ),  # co 60 dni → co kwartał; rekruter nie jest opiekunem
                contractor(2, None),  # wstrzymany
                contractor(3, None),  # monitoring nieaktywny
                contractor(4, None),  # w programie wejścia do 01.12
                contractor(5, t_id),  # co 120 dni; opiekun ustawiony w NEXUSIE
                contractor(6, t_id, anchor=False),  # bez kotwicy
                contractor(7, t_id),  # dwa kontrakty
            ]
            ids = [row["id"] for row in rows]
            settings = [
                _rhythm(ids[0], check_in_cadence_days=14),
                _rhythm(ids[1], check_in_cadence_days=60),
                _rhythm(ids[2], monitoring_status="paused"),
                _rhythm(ids[3], monitoring_status="inactive"),
                _rhythm(
                    ids[4],
                    check_in_cadence_days=14,
                    onboarding_program_ends_on="2026-12-01",
                ),
                _rhythm(ids[5], check_in_cadence_days=120),
                _rhythm(ids[6]),
                _rhythm(ids[7]),
            ]
            bundle = make_bundle(
                {
                    "profiles": [t_row, r_row],
                    "contractors": rows,
                    "contractor_success_settings": settings,
                }
            )
            batch, report, written = await run_import(db, "care", bundle)
            reasons = report["reasons"]
            assert reasons[care_import.NO_LINK] == 2  # rytm i opiekun bez kotwicy
            assert reasons[care_import.RHYTHM_UNSURE] == 1
            assert reasons[care_import.OWNER_UNSURE] == 1
            assert reasons[care_import.RHYTHM_INACTIVE] == 1
            assert reasons[care_import.OWNER_NOT_CARE] == 1
            assert reasons[care_import.OWNER_SET_IN_NEXUS] == 1
            assert written["rhythms_written"] == 5
            assert written["owners_written"] == 1
            assert_report_clean(batch.report, "Konsultant")

            periods = {
                period.contract_id: period
                for period in await db.scalars(
                    select(CareCadencePeriod).where(
                        CareCadencePeriod.contract_id.in_([c.id for c in contracts])
                    )
                )
            }
            levels = {
                index: (periods[c.id].level, periods[c.id].until_on)
                for index, c in enumerate(contracts)
                if c.id in periods
            }
            assert levels == {
                0: ("biweekly", None),
                1: ("quarterly", None),
                2: ("paused", None),
                4: ("biweekly", date(2026, 12, 1)),
                5: ("milestones", None),
            }
            first = periods[contracts[0].id]
            assert (first.reason, first.starts_on, first.created_by) == (
                "imported",
                date(2026, 11, 13),
                None,
            )
            owners = dict(
                (
                    await db.execute(
                        select(
                            CONTRACTS_CARE.c.id, CONTRACTS_CARE.c.care_owner_user_id
                        ).where(CONTRACTS_CARE.c.id.in_([c.id for c in contracts]))
                    )
                ).all()
            )
            assert owners[contracts[0].id] == tcm.id
            assert owners[contracts[1].id] is None
            assert owners[contracts[5].id] == other.id

            importer = compass_import.IMPORTERS["care"]
            batch2, _ = await compass_import.dry_run(
                db,
                module="care",
                bundle=bundle,
                planner=importer.plan,
                actor_user_id=None,
            )
            counts = batch2.report["dry_run"]["counts"]
            assert counts["unchanged"] == 6
            assert "create" not in counts and "update" not in counts
        finally:
            await db.rollback()


@pytest.mark.asyncio
async def test_care_import_leaves_rhythm_set_in_nexus() -> None:
    from app.models.contract_care import CareCadencePeriod

    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        try:
            client = Client(name=f"Bank Ręczny {tag}")
            person = Candidate(
                name="Konsultant", lastname=f"M{tag}", email=f"m-{tag}@example.com"
            )
            db.add_all([client, person])
            await db.flush()
            contract = await _contract(db, person, client, date(2026, 1, 1))
            db.add(
                CareCadencePeriod(
                    contract_id=contract.id,
                    level="monthly",
                    starts_on=date(2026, 9, 1),
                    reason="stable",
                )
            )
            await db.flush()
            row = {
                "id": str(uuid.uuid4()),
                "nexus_candidate_id": person.id,
                "nexus_contract_id": None,
                "owner_tcm_id": None,
                "current_client": None,
            }
            bundle = make_bundle(
                {
                    "contractors": [row],
                    "contractor_success_settings": [
                        _rhythm(row["id"], check_in_cadence_days=90)
                    ],
                }
            )
            _batch, report, written = await run_import(db, "care", bundle)
            assert report["counts"] == {"conflict": 1}
            assert report["reasons"] == {care_import.RHYTHM_SET_IN_NEXUS: 1}
            assert written["rhythms_written"] == 0
        finally:
            await db.rollback()
