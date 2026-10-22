"""Import skrzynki administracja@ z Compassa do „Spraw”: obszary, statusy, maile.

Paczki fikcyjne, rollback na końcu.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal
from app.models.admin_case import AdminCase, AdminCaseComment, AdminCaseMessage
from app.models.notification import Notification
from app.services.hr import compass_import
from tests.test_hr_compass_import_leave import (
    assert_report_clean,
    make_bundle,
    make_person,
    run_import,
)

CATEGORIES = {
    "inbox_administracja": str(uuid.uuid4()),
    "inbox_negocjacje": str(uuid.uuid4()),
    "inbox_wypowiedzenie": str(uuid.uuid4()),
    "inbox_marketing": str(uuid.uuid4()),
    "contractor_conversation": str(uuid.uuid4()),
    "konto": str(uuid.uuid4()),
}


def _ticket(slug: str, author: str, subject: str, **values) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "category_id": CATEGORIES[slug],
        "user_id": author,
        "assignee_id": None,
        "subject": subject,
        "body_md": f"Treść sprawy: {subject}",
        "status": "open",
        "priority": "normal",
        "resolved_at": None,
        "created_at": "2026-09-01T08:00:00+00:00",
        "updated_at": "2026-09-02T08:00:00+00:00",
        **values,
    }


def _meta(ticket: dict, **values) -> dict:
    return {
        "ticket_id": ticket["id"],
        "source": "manual_paste",
        "priority_level": "P3",
        "due_date": "2026-09-05T21:30:00+00:00",
        "planned_due_date": None,
        "follow_up_date": None,
        "work_area": "administration",
        "waiting_for": None,
        "checklist": [],
        "materials": [],
        "consultant_id": None,
        "consultant_name": None,
        "consultant_phone": None,
        "client_name": None,
        "external_message_id": None,
        "email_from": None,
        "email_subject": None,
        "email_received_at": None,
        **values,
    }


@pytest.mark.asyncio
async def test_cases_dry_run_apply_and_second_apply_changes_nothing() -> None:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        try:
            handler, h_id, h_row = await make_person(db, f"{tag}-handler")
            author, a_id, a_row = await make_person(db, f"{tag}-author")

            admin = _ticket(
                "inbox_administracja",
                a_id,
                f"RE: Aneks do umowy {tag}",
                assignee_id=h_id,
            )
            negotiation = _ticket(
                "inbox_negocjacje",
                a_id,
                f"Stawka {tag}",
                status="resolved",
                resolved_at="2026-09-10T08:00:00+00:00",
            )
            termination = _ticket("inbox_wypowiedzenie", a_id, f"Wypowiedzenie {tag}")
            marketing = _ticket(
                "inbox_marketing", a_id, f"Post {tag}", status="waiting_user"
            )
            relabelled = _ticket("inbox_administracja", a_id, f"Grafika {tag}")
            stale_resolution = _ticket(
                "inbox_administracja",
                a_id,
                f"Wróciła {tag}",
                resolved_at="2026-09-03T08:00:00+00:00",
                assignee_id=str(uuid.uuid4()),  # osoba bez konta w NEXUSIE
            )
            contractor = _ticket("contractor_conversation", a_id, "Rozmowa")
            helpdesk = _ticket("konto", a_id, "Nie działa logowanie")
            tickets = [
                admin,
                negotiation,
                termination,
                marketing,
                relabelled,
                stale_resolution,
                contractor,
                helpdesk,
            ]
            metas = [
                _meta(
                    admin,
                    priority_level="P1",
                    planned_due_date="2026-09-04",
                    follow_up_date="2026-09-08",
                    waiting_for="Podpis klienta",
                    checklist=[
                        {
                            "id": str(uuid.uuid4()),
                            "text": "Sprawdzić aneks",
                            "done": True,
                        },
                        {"id": str(uuid.uuid4()), "text": "Wysłać", "done": False},
                    ],
                    consultant_name="Konsultant Przykładowy",
                    client_name="Klient Przykładowy",
                    source="email",
                    external_message_id=f"<msg-{tag}@example.com>",
                    email_from="nadawca@example.com",
                    email_subject="RE: Aneks do umowy",
                    email_received_at="2026-09-01T07:59:00+00:00",
                ),
                _meta(negotiation, priority_level="P2"),
                _meta(termination),
                _meta(marketing, work_area="marketing"),
                _meta(relabelled, work_area="marketing"),
                _meta(stale_resolution),
            ]
            comments = [
                {
                    "id": str(uuid.uuid4()),
                    "ticket_id": admin["id"],
                    "author_id": h_id,
                    "body_md": "Zadzwonię do klienta jutro.",
                    "is_internal": True,
                    "created_at": "2026-09-02T09:00:00+00:00",
                },
                {
                    "id": str(uuid.uuid4()),
                    "ticket_id": admin["id"],
                    "author_id": h_id,
                    "body_md": "   ",
                    "is_internal": True,
                    "created_at": "2026-09-02T09:05:00+00:00",
                },
            ]
            archive = [
                {
                    "ticket_id": admin["id"],
                    "email_body_text": None,
                    "email_body_html": "<p>Dzień dobry,<br>przesyłam aneks.</p>",
                    "external_conversation_id": f"conv-{tag}",
                    "archived_at": "2026-08-25T00:00:00+00:00",
                }
            ]
            bundle = make_bundle(
                {
                    "profiles": [h_row, a_row],
                    "support_categories": [
                        {"id": cid, "slug": slug} for slug, cid in CATEGORIES.items()
                    ],
                    "support_tickets": tickets,
                    "support_inbox_meta": metas,
                    "support_ticket_comments": comments,
                    "support_inbox_email_archive": archive,
                }
            )
            importer = compass_import.IMPORTERS["cases"]

            batch, report, written = await run_import(db, "cases", bundle)
            assert report["counts"] == {"create": 6, "skip": 2}
            assert report["reasons"]["rozmowa kontraktora — skasowana w Compassie"] == 1
            assert report["reasons"]["zgłoszenie spoza skrzynki administracja@"] == 1
            assert (
                report["reasons"]["data rozwiązania przy sprawie otwartej — pominięta"]
                == 1
            )
            assert_report_clean(
                batch.report,
                "Aneks",
                "Konsultant Przykładowy",
                "przesyłam aneks",
                "Zadzwonię",
            )
            assert written == {
                "cases_created": 6,
                "comments_written": 1,
                "messages_written": 1,
                "contracts_linked": 0,
            }

            cases = {
                case.source_key: case
                for case in await db.scalars(
                    select(AdminCase).where(AdminCase.source == "compass_import")
                )
            }
            first = cases[f"compass:{admin['id']}"]
            assert first.title == f"Aneks do umowy {tag}"
            assert (first.area, first.priority, first.status) == (
                "administration",
                "P1",
                "new",
            )
            assert first.assignee_user_id == handler.id
            assert first.created_by == author.id
            assert first.due_on == date(2026, 9, 4)
            assert first.follow_up_on == date(2026, 9, 8)
            assert first.closed_at is None
            assert first.checklist == [
                {"text": "Sprawdzić aneks", "done": True},
                {"text": "Wysłać", "done": False},
            ]
            assert "Czeka na: Podpis klienta" in first.description
            assert "klient: Klient Przykładowy" in first.description
            message = await db.scalar(
                select(AdminCaseMessage).where(AdminCaseMessage.case_id == first.id)
            )
            assert message.graph_message_id == f"<msg-{tag}@example.com>"
            assert message.conversation_id == f"conv-{tag}"
            assert "przesyłam aneks" in message.body_text
            assert "<p>" not in message.body_text
            comment_bodies = list(
                await db.scalars(
                    select(AdminCaseComment.body).where(
                        AdminCaseComment.case_id == first.id
                    )
                )
            )
            assert comment_bodies == ["Zadzwonię do klienta jutro."]

            done = cases[f"compass:{negotiation['id']}"]
            assert (done.area, done.status) == ("negotiation", "done")
            assert done.closed_at is not None
            assert cases[f"compass:{termination['id']}"].area == "offboarding"
            assert cases[f"compass:{marketing['id']}"].status == "waiting"
            assert cases[f"compass:{relabelled['id']}"].area == "marketing"
            # Termin z P3 po północy w Warszawie: 05.09 21:30 UTC = 05.09 23:30.
            assert cases[f"compass:{termination['id']}"].due_on == date(2026, 9, 5)
            reopened = cases[f"compass:{stale_resolution['id']}"]
            assert reopened.status == "new"
            assert reopened.closed_at is None
            assert reopened.assignee_user_id is None

            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(Notification)
                    .where(Notification.user_id.in_([handler.id, author.id]))
                )
                == 0
            )

            batch2, _ = await compass_import.dry_run(
                db,
                module="cases",
                bundle=bundle,
                planner=importer.plan,
                actor_user_id=None,
            )
            assert batch2.report["dry_run"]["counts"] == {"unchanged": 6, "skip": 2}
            written2 = await compass_import.apply(
                db,
                batch=batch2,
                bundle=bundle,
                planner=importer.plan,
                applier=importer.apply,
                actor_user_id=None,
            )
            assert written2 == {
                "cases_created": 0,
                "comments_written": 0,
                "messages_written": 0,
                "contracts_linked": 0,
            }

            # Sprawa przesunięta w NEXUSIE: kolejny import jej nie cofa.
            moved = cases[f"compass:{marketing['id']}"]
            moved.status = "in_progress"
            await db.flush()
            batch3, plan3 = await compass_import.dry_run(
                db,
                module="cases",
                bundle=bundle,
                planner=importer.plan,
                actor_user_id=None,
            )
            assert plan3.counts() == {"unchanged": 5, "conflict": 1, "skip": 2}
            await compass_import.apply(
                db,
                batch=batch3,
                bundle=bundle,
                planner=importer.plan,
                applier=importer.apply,
                actor_user_id=None,
            )
            assert (await db.get(AdminCase, moved.id)).status == "in_progress"
        finally:
            await db.rollback()


@pytest.mark.asyncio
async def test_cases_dry_run_writes_nothing() -> None:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        try:
            _, a_id, a_row = await make_person(db, f"{tag}-author")
            ticket = _ticket("inbox_administracja", a_id, f"Sprawa {tag}")
            bundle = make_bundle(
                {
                    "profiles": [a_row],
                    "support_categories": [
                        {
                            "id": CATEGORIES["inbox_administracja"],
                            "slug": "inbox_administracja",
                        }
                    ],
                    "support_tickets": [ticket],
                    "support_inbox_meta": [_meta(ticket)],
                }
            )
            importer = compass_import.IMPORTERS["cases"]
            _, plan = await compass_import.dry_run(
                db,
                module="cases",
                bundle=bundle,
                planner=importer.plan,
                actor_user_id=None,
            )
            assert plan.counts() == {"create": 1}
            assert (
                await db.scalar(
                    select(AdminCase.id).where(
                        AdminCase.source_key == f"compass:{ticket['id']}"
                    )
                )
                is None
            )
        finally:
            await db.rollback()
