"""Regression tests for Module 6 finding P0.1 / P0.2 (fake email success).

The legacy ``POST /api/emails/send`` never talked to SMTP/Graph — it logged the
message and wrote ``Activity(action="email_sent")``, so the UI reported a send
that never happened. It now returns ``410 Gone`` and writes nothing.

``_render_template`` used to substitute hardcoded business values ("Senior Java
Developer", a fixed salary band, a 2025 date, a fake recruiter). It now
substitutes only the real candidate name and leaves every other ``{{token}}``
unresolved so it is visibly a blank to fill.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.api.emails import _render_template
from app.core.database import AsyncSessionLocal
from app.models.activity import Activity
from app.models.candidate import Candidate


@pytest.mark.asyncio
async def test_template_test_send_is_gone(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    """The template test-send stub is permanently disabled too (410)."""
    resp = await app_client.post(
        "/api/email-templates/1/send", headers=app_auth_headers
    )
    assert resp.status_code == 410
    assert resp.json()["detail"]["code"] == "LEGACY_EMAIL_SIMULATION_DISABLED"


@pytest.mark.asyncio
async def test_send_endpoint_is_gone_and_writes_nothing(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    async with AsyncSessionLocal() as db:
        before = await db.scalar(
            select(func.count())
            .select_from(Activity)
            .where(Activity.action == "email_sent")
        )

    resp = await app_client.post(
        "/api/emails/send",
        headers=app_auth_headers,
        json={
            "to_email": "someone@example.com",
            "subject": "Cześć",
            "body": "Treść",
            "candidate_id": 999_999,
        },
    )
    assert resp.status_code == 410
    detail = resp.json()["detail"]
    assert detail["code"] == "LEGACY_EMAIL_SIMULATION_DISABLED"

    # No Activity(email_sent) row was created by the call.
    async with AsyncSessionLocal() as db:
        after = await db.scalar(
            select(func.count())
            .select_from(Activity)
            .where(Activity.action == "email_sent")
        )
    assert after == before


def test_render_template_leaves_business_tokens_unresolved():
    """No fabricated job title / salary / date / recruiter."""
    subject = "{{job_title}} — {{candidate_name}}"
    body = "Widełki: {{salary}}, termin {{interview_date}}, {{recruiter_name}}"

    rendered_subject, rendered_body = _render_template(subject, body, candidate=None)

    # Nothing fabricated — every token the composer can't resolve stays literal.
    for fake in (
        "Senior Java Developer",
        "20 000",
        "2025-02-15",
        "Rekruter",
        "rekrutacja@b2bnet.pl",
    ):
        assert fake not in rendered_subject
        assert fake not in rendered_body
    assert "{{job_title}}" in rendered_subject
    assert "{{salary}}" in rendered_body


def test_render_template_substitutes_real_candidate_name():
    cand = Candidate(name="Anna", lastname="Nowak")
    rendered_subject, rendered_body = _render_template(
        "Cześć {{candidate_name}}", "Witaj {{candidate_name}}", candidate=cand
    )
    assert rendered_subject == "Cześć Anna Nowak"
    assert rendered_body == "Witaj Anna Nowak"
