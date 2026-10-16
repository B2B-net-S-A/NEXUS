"""Import mapy technologicznej i rozmów opiekunów z Compassa.

Klucz do kontraktu NEXUSA: kotwica osoby z Compassa (``nexus_candidate_id``
albo ``nexus_contract_id``) + klient + okres. Niepewne = „conflict”.
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
            assert report["counts"] == {"create": 2, "conflict": 5, "skip": 2}
            reasons = report["reasons"]
            assert reasons[care_import.UNSURE_CONTRACT] == 1
            assert reasons[care_import.UNKNOWN_SKILL] == 1
            assert reasons[care_import.NO_LINK] == 2  # karta i rozmowa bez kotwicy
            assert reasons["kontrakt rozmowy niepewny"] == 2
            assert reasons["klient karty bez odpowiednika w NEXUSIE"] == 1
            assert_report_clean(
                batch.report, "Konsultant", "Migracja płatności", "zadowolony"
            )
            assert written == {
                "cards_written": 4,
                "cards_without_contract": 2,
                "conversations_written": 1,
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
                "conflict": 2,
                "skip": 2,
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
            }
            await db.refresh(review)
            assert review.occurrences == 1
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
