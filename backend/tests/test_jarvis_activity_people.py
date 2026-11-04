"""Jarvis: liczby z jednego dnia i imienne listy (27.10.2026).

Na produkcji „ile osób w piątek zweryfikowano?” kończyło się po 14
wiadomościach bez odpowiedzi: ``evaluate_metric`` ma najkrótszy okres 7 dni
i podział tygodniowy. ``activity_people`` czyta tę samą listę, co klik
w liczbę lejka w Insights (`/recruitment-activity/details`).
"""

from __future__ import annotations

import pytest

from app.models.user import UserRole
from app.services.jarvis.agent import execute_read
from app.services.jarvis.tools import TOOLS_BY_NAME
from app.services.jarvis.transport import CallerIdentity, JarvisTransport
from tests._jarvis_helpers import make_user

TOOL = TOOLS_BY_NAME["activity_people"]
DAY = {"metric": "verification", "window": "day", "day": "2026-10-23"}


async def _ask_as(headers: dict[str, str], args: dict) -> tuple[bool, str, object]:
    identity = CallerIdentity(authorization=headers["Authorization"])
    async with JarvisTransport(identity) as transport:
        return await execute_read(transport, TOOL, args)


def test_one_day_for_the_whole_team():
    spec = TOOL.build(
        {
            "metric": "verification",
            "window": "day",
            "day": "2026-10-23",
            "scope": "team",
        }
    )
    assert spec.method == "GET"
    assert spec.path == "/api/dashboard/v2/recruitment-activity/details"
    assert spec.params == {
        "metric": "verification",
        "window": "day",
        "day": "2026-10-23",
        "scope": "team",
        "page_size": 20,
    }


def test_range_defaults_to_my_own_numbers():
    spec = TOOL.build(
        {
            "metric": "placement",
            "window": "range",
            "date_from": "2026-10-01",
            "date_to": "2026-10-27",
        }
    )
    assert spec.params["scope"] == "auto"
    assert spec.params["date_from"] == "2026-10-01"
    assert "day" not in spec.params


def test_shape_keeps_who_where_when_and_drops_links():
    data = {
        "total": 2,
        "people": 2,
        "period_start": "2026-10-23",
        "period_end": "2026-10-23",
        "scope": "team",
        "items": [
            {
                "candidate": {
                    "id": 1,
                    "name": "Ola Przykładowa",
                    "href": "/candidates/1",
                },
                "job": {
                    "id": 9,
                    "title": "Java Developer",
                    "working_title": "Java Dev (ZOB-1)",
                    "client_name": "Klient Testowy",
                    "href": "/jobs/9",
                },
                "credited_user": {"id": 5, "name": "Rekruterka", "role": "recruiter"},
                "reached_at": "2026-10-23T10:00:00+02:00",
                "state": "before_client",
            }
        ],
    }
    shaped = TOOL.shape(data, {})
    assert shaped["total"] == 2 and shaped["period_start"] == "2026-10-23"
    assert shaped["has_more"] is False
    row = shaped["items"][0]
    assert row == {
        "candidate_id": 1,
        "candidate": "Ola Przykładowa",
        "job_id": 9,
        "job": "Java Dev (ZOB-1)",
        "client": "Klient Testowy",
        "credited": "Rekruterka",
        "reached_at": "2026-10-23T10:00:00+02:00",
        "state": "before_client",
    }
    assert "href" not in str(shaped)


def test_count_matches_the_tile_and_next_page_is_reachable():
    """Tydzień sprzed 12.10 ma w liczbie wpisy DynaReportera, których lista nie ma."""
    shaped = TOOL.shape(
        {
            "total": 45,
            "period_total": 52,
            "history_total": 7,
            "page": 2,
            "page_size": 20,
            "items": [],
        },
        {},
    )
    assert shaped["period_total"] == 52 and shaped["history_total"] == 7
    assert shaped["page"] == 2 and shaped["has_more"] is True
    assert TOOL.build({**DAY, "page": 2}).params["page"] == 2


def test_empty_day_keeps_the_zero():
    shaped = TOOL.shape({"total": 0, "people": 0, "period_total": 0, "items": []}, {})
    assert shaped["period_total"] == 0 and shaped["total"] == 0


def test_model_cannot_widen_the_scope_or_pick_another_person():
    """Trasa pozwala wskazać osobę i kamienie bez zasługi, narzędzie już nie."""
    spec = TOOL.build({**DAY, "scope": "unattributed", "subject_user_id": 7})
    assert spec.params["scope"] == "auto"
    assert "subject_user_id" not in spec.params


@pytest.mark.asyncio
async def test_recruiter_is_refused_the_team_list():
    _, headers = await make_user(UserRole.recruiter)
    ok, message, shaped = await _ask_as(headers, {**DAY, "scope": "team"})
    assert ok is False and shaped is None
    assert "Brak" in message


@pytest.mark.asyncio
async def test_recruiter_without_scope_gets_only_their_own_list():
    _, headers = await make_user(UserRole.recruiter)
    ok, _, shaped = await _ask_as(headers, DAY)
    assert ok is True
    assert shaped["scope"] == "person"


@pytest.mark.asyncio
async def test_team_role_gets_the_team_list():
    _, headers = await make_user(UserRole.head_of_recruitment)
    ok, _, shaped = await _ask_as(headers, {**DAY, "scope": "team"})
    assert ok is True
    assert shaped["scope"] == "team"


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [UserRole.user, UserRole.trainee, UserRole.automation])
async def test_role_outside_the_list_is_refused(role):
    _, headers = await make_user(role)
    for args in (DAY, {**DAY, "scope": "team"}):
        ok, message, shaped = await _ask_as(headers, args)
        assert ok is False and shaped is None, (role, args, message)
