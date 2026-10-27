"""Jarvis: liczby z jednego dnia i imienne listy (27.10.2026).

Na produkcji „ile osób w piątek zweryfikowano?” kończyło się po 14
wiadomościach bez odpowiedzi: ``evaluate_metric`` ma najkrótszy okres 7 dni
i podział tygodniowy. ``activity_people`` czyta tę samą listę, co klik
w liczbę lejka w Insights (`/recruitment-activity/details`).
"""

from __future__ import annotations

from app.services.jarvis.tools import TOOLS_BY_NAME

TOOL = TOOLS_BY_NAME["activity_people"]


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
        "page_size": 100,
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
