"""Ekran Bezpieczeństwo (0800) na Postgresie: bramki, webhook, wyjątek po terminie, rutyny.

Dane fikcyjne: adresy z puli dokumentacyjnej, e-maile z ``example.com``.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.core.security import create_access_token
from app.models.notification import Notification, NotificationType
from app.models.security import (
    SecurityEvent,
    SecurityFinding,
    SecurityRoutine,
    SecuritySourceState,
)
from app.models.user import User, UserRole
from app.services.security_screen import expire_exceptions, notify_overdue_routines
from tests.test_service_accounts import _account_with_key

GRAFANA_EXAMPLE = (
    Path(__file__).resolve().parent
    / "data"
    / "security"
    / "grafana_webhook_example.json"
)

API = "/api/security"


@pytest.fixture(autouse=True)
async def _free_sources():
    """Każdy test zakłada własne konto serwisowe; źródło przypina się do pierwszego,
    więc między testami zdejmujemy przypięcie (na produkcji robi to tylko
    wyłączenie albo usunięcie konta)."""
    async with AsyncSessionLocal() as db:
        await db.execute(delete(SecuritySourceState))
        await db.commit()
    yield


async def _user(role: UserRole) -> User:
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"sec-{role.value}-{uuid.uuid4().hex[:8]}@example.com",
            name=f"Test {role.value}",
            role=role,
            is_active=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


def _headers(user: User) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {create_access_token(subject=user.id, role=user.role.value)}"
    }


async def _finding(**over) -> SecurityFinding:
    values = {
        "source": "ci",
        "fingerprint": f"test:{uuid.uuid4().hex}",
        "severity": "high",
        "title": "Testowe znalezisko",
        "status": "open",
        "steps": [],
    }
    values.update(over)
    async with AsyncSessionLocal() as db:
        row = SecurityFinding(**values)
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row


async def _key(
    app_client: AsyncClient, headers: dict, scopes: list[str]
) -> dict[str, str]:
    _, api_key, _ = await _account_with_key(app_client, headers, scopes)
    return {"X-API-Key": api_key}


# ── Bramki ───────────────────────────────────────────────────────────────────

ADMIN_ROUTES = [
    ("GET", f"{API}/overview", None),
    ("GET", f"{API}/findings", None),
    ("GET", f"{API}/routines", None),
    ("GET", f"{API}/events", None),
    ("POST", f"{API}/findings/1/close", {}),
    (
        "POST",
        f"{API}/findings/1/exception",
        {"reason": "Powód dłuższy niż dziesięć", "until": "2099-01-01"},
    ),
    ("POST", f"{API}/routines/1/done", {}),
]


@pytest.mark.parametrize(
    "role", [UserRole.recruiter, UserRole.delivery_lead, UserRole.finance]
)
async def test_non_admin_is_refused_everywhere(
    app_client: AsyncClient, role: UserRole
) -> None:
    headers = _headers(await _user(role))
    for method, path, body in ADMIN_ROUTES:
        response = await app_client.request(method, path, json=body, headers=headers)
        assert response.status_code == 403, (method, path, response.text)


async def test_anonymous_is_refused(app_client: AsyncClient) -> None:
    response = await app_client.get(f"{API}/overview")
    assert response.status_code == 401


async def test_admin_sees_overview_with_seeded_routines(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    response = await app_client.get(f"{API}/overview", headers=app_auth_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body["tiles"]) == {"ci", "waiting", "traffic", "logins"}
    assert {s["key"] for s in body["sources"]} >= {
        "ci",
        "crowdsec",
        "falco",
        "wazuh",
        "defectdojo",
    }
    routines = (
        await app_client.get(f"{API}/routines", headers=app_auth_headers)
    ).json()
    assert {r["key"] for r in routines} >= {
        "ci_weekly",
        "pentest_staging",
        "accounts_review",
    }


# ── Webhook ──────────────────────────────────────────────────────────────────


async def test_ingest_requires_key_with_scope(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    body = {"source": "crowdsec", "events": []}
    assert (await app_client.post(f"{API}/ingest", json=body)).status_code == 401
    # Admin z przeglądarki też nie — wejście jest tylko dla kluczy.
    assert (
        await app_client.post(f"{API}/ingest", json=body, headers=app_auth_headers)
    ).status_code == 401
    other = await _key(app_client, app_auth_headers, ["traffit:read"])
    assert (
        await app_client.post(f"{API}/ingest", json=body, headers=other)
    ).status_code == 403
    # Klucz `security:ingest` nie czyta ekranu.
    ingest = await _key(app_client, app_auth_headers, ["security:ingest"])
    assert (await app_client.get(f"{API}/overview", headers=ingest)).status_code == 401


async def test_ingest_scrubs_and_deduplicates(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    key = await _key(app_client, app_auth_headers, ["security:ingest"])
    ref = f"crowdsec:alert:{uuid.uuid4().hex[:8]}"
    body = {
        "source": "crowdsec",
        "events": [
            {
                "occurred_at": datetime.now(timezone.utc).isoformat(),
                "kind": "ban",
                "summary": "Ban 4 h: 203.0.113.9 skan /.env",
                "count": 7,
                "ref": ref,
            }
        ],
    }
    first = await app_client.post(f"{API}/ingest", json=body, headers=key)
    assert first.status_code == 202, first.text
    assert first.json()["accepted_events"] == 1
    again = await app_client.post(f"{API}/ingest", json=body, headers=key)
    assert again.json() == {
        **again.json(),
        "accepted_events": 0,
        "skipped_duplicates": 1,
    }
    async with AsyncSessionLocal() as db:
        row = await db.scalar(select(SecurityEvent).where(SecurityEvent.ref == ref))
    assert row.summary == "Ban 4 h: [adres IP] skan /.env"
    overview = (
        await app_client.get(f"{API}/overview", headers=app_auth_headers)
    ).json()
    assert overview["tiles"]["traffic"]["blocked"] >= 7


async def test_ingest_rejects_invalid_body(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    key = await _key(app_client, app_auth_headers, ["security:ingest"])
    bad = {
        "source": "crowdsec",
        "events": [{"occurred_at": "wczoraj", "kind": "ban", "summary": "x"}],
    }
    assert (
        await app_client.post(f"{API}/ingest", json=bad, headers=key)
    ).status_code == 422
    falco = {"rule": "x", "priority": "Warning"}  # bez `time`
    assert (
        await app_client.post(f"{API}/ingest/falco", json=falco, headers=key)
    ).status_code == 422


async def test_full_scan_closes_missing_and_reopens_returning(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    key = await _key(app_client, app_auth_headers, ["security:ingest"])
    scanner = f"zizmor{uuid.uuid4().hex[:6]}"
    a, b = f"{scanner}:a", f"{scanner}:b"

    def finding(fp: str) -> dict:
        return {
            "fingerprint": fp,
            "severity": "medium",
            "title": fp,
            "location": ".github/workflows/x.yml:1",
        }

    def batch(*fps: str) -> dict:
        return {
            "source": "ci",
            "scanner": scanner,
            "complete": True,
            "findings": [finding(f) for f in fps],
        }

    first = (
        await app_client.post(f"{API}/ingest", json=batch(a, b), headers=key)
    ).json()
    assert first["findings_new"] == 2
    second = (await app_client.post(f"{API}/ingest", json=batch(a), headers=key)).json()
    assert second["findings_closed"] == 1
    async with AsyncSessionLocal() as db:
        statuses = dict(
            (
                await db.execute(
                    select(SecurityFinding.fingerprint, SecurityFinding.status).where(
                        SecurityFinding.scanner == scanner
                    )
                )
            ).all()
        )
    assert statuses == {a: "open", b: "fixed"}
    await app_client.post(f"{API}/ingest", json=batch(a, b), headers=key)
    async with AsyncSessionLocal() as db:
        back = await db.scalar(
            select(SecurityFinding.status).where(SecurityFinding.fingerprint == b)
        )
    assert back == "open"


# ── Wyjątek ──────────────────────────────────────────────────────────────────


async def test_exception_needs_reason_and_future_date(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    row = await _finding()
    url = f"{API}/findings/{row.id}/exception"
    today = business_today()
    short = {"reason": "bo tak", "until": (today + timedelta(days=10)).isoformat()}
    assert (
        await app_client.post(url, json=short, headers=app_auth_headers)
    ).status_code == 422
    past = {"reason": "Czekamy na okno serwisowe", "until": today.isoformat()}
    assert (
        await app_client.post(url, json=past, headers=app_auth_headers)
    ).status_code == 422
    too_far = {
        "reason": "Czekamy na okno serwisowe",
        "until": (today + timedelta(days=400)).isoformat(),
    }
    assert (
        await app_client.post(url, json=too_far, headers=app_auth_headers)
    ).status_code == 422
    ok = {
        "reason": "Czekamy na okno serwisowe 05.12",
        "until": (today + timedelta(days=8)).isoformat(),
    }
    response = await app_client.post(url, json=ok, headers=app_auth_headers)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "excepted"
    overview = (
        await app_client.get(f"{API}/overview", headers=app_auth_headers)
    ).json()
    assert row.id not in {f["id"] for f in overview["waiting"]}
    assert row.id in {f["id"] for f in overview["excepted"]}


async def test_expired_exception_returns_to_waiting(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    today = business_today()
    row = await _finding(
        status="excepted",
        exception_reason="Czekamy na okno serwisowe",
        exception_until=today - timedelta(days=1),
    )
    # Ekran nie czeka na pętlę: od razu na liście, oznaczone jako wyjątek po terminie.
    overview = (
        await app_client.get(f"{API}/overview", headers=app_auth_headers)
    ).json()
    waiting = {f["id"]: f for f in overview["waiting"]}
    assert (
        waiting[row.id]["status"] == "open"
        and waiting[row.id]["exception_expired"] is True
    )
    # Pętla przestawia status i zostawia ślad.
    async with AsyncSessionLocal() as db:
        assert await expire_exceptions(db, today) >= 1
        await db.commit()
        stored = await db.get(SecurityFinding, row.id)
        trail = await db.scalar(
            select(SecurityEvent).where(
                SecurityEvent.ref.like(f"exception_expired:{row.id}:%")
            )
        )
    assert stored.status == "open" and trail is not None


async def test_close_as_fixed(app_client: AsyncClient, app_auth_headers: dict) -> None:
    row = await _finding()
    response = await app_client.post(
        f"{API}/findings/{row.id}/close",
        json={"note": "PR z poprawką"},
        headers=app_auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "fixed"
    exc = await app_client.post(
        f"{API}/findings/{row.id}/exception",
        json={
            "reason": "Czekamy na okno serwisowe",
            "until": (business_today() + timedelta(days=5)).isoformat(),
        },
        headers=app_auth_headers,
    )
    assert exc.status_code == 409


# ── Rutyny ───────────────────────────────────────────────────────────────────


async def test_overdue_routine_rings_admins_once_a_day_and_done_moves_the_date(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    today = business_today()
    async with AsyncSessionLocal() as db:
        routine = await db.scalar(
            select(SecurityRoutine).where(SecurityRoutine.key == "accounts_review")
        )
        routine.next_due_on = today - timedelta(days=2)
        await db.commit()
        await db.execute(
            delete(Notification).where(
                Notification.notification_type
                == NotificationType.security_routine_overdue
            )
        )
        await db.commit()
        first = await notify_overdue_routines(db, today)
        await db.commit()
        second = await notify_overdue_routines(db, today)
        await db.commit()
    assert first >= 1 and second == 0
    done = await app_client.post(
        f"{API}/routines/{routine.id}/done",
        json={"note": "przegląd kont"},
        headers=app_auth_headers,
    )
    assert done.status_code == 200, done.text
    body = done.json()
    assert body["last_done_on"] == today.isoformat() and body["state"] == "ok"
    assert date.fromisoformat(body["next_due_on"]) > today + timedelta(days=80)
    future = await app_client.post(
        f"{API}/routines/{routine.id}/done",
        json={"done_on": (today + timedelta(days=1)).isoformat()},
        headers=app_auth_headers,
    )
    assert future.status_code == 422


async def test_full_scan_in_several_batches_closes_by_run_id(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    """DefectDojo wysyła aktywne znaleziska paczkami po 200; `complete` idzie tylko
    w ostatniej. Zamyka się to, czego nie było w ŻADNEJ paczce tego `run_id`."""
    key = await _key(app_client, app_auth_headers, ["security:ingest"])
    scanner = f"dojo{uuid.uuid4().hex[:6]}"

    def batch(run_id: str, fps: list[str], complete: bool) -> dict:
        return {
            "source": "defectdojo",
            "scanner": scanner,
            "run_id": run_id,
            "complete": complete,
            "findings": [
                {
                    "fingerprint": f"defectdojo:{scanner}:{fp}",
                    "severity": "high",
                    "title": fp,
                }
                for fp in fps
            ],
        }

    await app_client.post(
        f"{API}/ingest", json=batch("r1", ["a", "b", "c"], True), headers=key
    )
    first = await app_client.post(
        f"{API}/ingest", json=batch("r2", ["a"], False), headers=key
    )
    assert first.json()["findings_closed"] == 0
    last = await app_client.post(
        f"{API}/ingest", json=batch("r2", ["b"], True), headers=key
    )
    assert last.status_code == 202, last.text
    assert last.json()["findings_closed"] == 1
    async with AsyncSessionLocal() as db:
        statuses = dict(
            (
                await db.execute(
                    select(SecurityFinding.fingerprint, SecurityFinding.status).where(
                        SecurityFinding.scanner == scanner
                    )
                )
            ).all()
        )
    assert statuses == {
        f"defectdojo:{scanner}:a": "open",
        f"defectdojo:{scanner}:b": "open",
        f"defectdojo:{scanner}:c": "fixed",
    }
    overview = (
        await app_client.get(f"{API}/overview", headers=app_auth_headers)
    ).json()
    dojo = next(s for s in overview["sources"] if s["key"] == "defectdojo")
    assert dojo["state"] == "live"


async def test_source_belongs_to_the_account_that_wrote_it_first(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    dojo = await _key(app_client, app_auth_headers, ["security:ingest"])
    falco = await _key(app_client, app_auth_headers, ["security:ingest"])
    body = {
        "source": "defectdojo",
        "scanner": "defectdojo",
        "complete": True,
        "findings": [],
    }
    assert (
        await app_client.post(f"{API}/ingest", json=body, headers=dojo)
    ).status_code == 202
    # Klucz Falco (leży w konfiguracji na serwerze NEXUSA) nie zamknie znalezisk DefectDojo.
    stolen = await app_client.post(f"{API}/ingest", json=body, headers=falco)
    assert stolen.status_code == 403, stolen.text
    assert (
        await app_client.post(f"{API}/ingest", json=body, headers=dojo)
    ).status_code == 202


# ── Grafana ──────────────────────────────────────────────────────────────────


def _grafana(status: str, fingerprint: str, **alert) -> dict:
    return {
        "receiver": "nexus-security",
        "status": status,
        "alerts": [
            {
                "status": status,
                "labels": {
                    "alertname": "Wolne odpowiedzi API",
                    "grafana_folder": "NEXUS",
                    "severity": "critical",
                    "instance": "203.0.113.9:8000",
                },
                "annotations": {"summary": "p95 powyżej 2 s"},
                "startsAt": "2026-11-28T09:00:00Z",
                "endsAt": "0001-01-01T00:00:00Z",
                "fingerprint": fingerprint,
                **alert,
            }
        ],
    }


async def _grafana_findings(fingerprint: str) -> list[SecurityFinding]:
    async with AsyncSessionLocal() as db:
        return list(
            await db.scalars(
                select(SecurityFinding).where(
                    SecurityFinding.source == "grafana",
                    SecurityFinding.fingerprint == fingerprint,
                )
            )
        )


async def test_grafana_firing_once_repeat_does_not_duplicate_resolved_closes(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    key = await _key(app_client, app_auth_headers, ["security:ingest"])
    fp = uuid.uuid4().hex[:16]
    url = f"{API}/ingest/grafana"

    first = await app_client.post(url, json=_grafana("firing", fp), headers=key)
    assert first.status_code == 202, first.text
    assert first.json()["findings_new"] == 1
    # Grafana powtarza ten sam alert co kilka minut.
    again = await app_client.post(url, json=_grafana("firing", fp), headers=key)
    assert again.json() == {
        "accepted_events": 0,
        "skipped_duplicates": 1,
        "findings_new": 0,
        "findings_updated": 1,
        "findings_closed": 0,
    }
    rows = await _grafana_findings(fp)
    assert len(rows) == 1
    assert rows[0].status == "open" and rows[0].severity == "high"
    assert rows[0].title == "Wolne odpowiedzi API"
    assert "203.0.113" not in (rows[0].location or "") + (rows[0].evidence or "")

    overview = (
        await app_client.get(f"{API}/overview", headers=app_auth_headers)
    ).json()
    assert any(f["id"] == rows[0].id for f in overview["waiting"])
    grafana = next(s for s in overview["sources"] if s["key"] == "grafana")
    assert grafana["state"] == "live"

    done = await app_client.post(
        url,
        json=_grafana("resolved", fp, endsAt="2026-11-28T09:20:00Z"),
        headers=key,
    )
    assert done.status_code == 202, done.text
    assert done.json()["findings_closed"] == 1
    rows = await _grafana_findings(fp)
    assert rows[0].status == "fixed" and rows[0].closed_at is not None
    async with AsyncSessionLocal() as db:
        kinds = list(
            await db.scalars(
                select(SecurityEvent.kind).where(
                    SecurityEvent.source == "grafana",
                    SecurityEvent.ref.like(f"grafana:{fp}:%"),
                )
            )
        )
    assert sorted(kinds) == ["alert_firing", "alert_resolved"]

    # Alert wraca → to samo znalezisko otwiera się ponownie, bez nowego wiersza.
    back = _grafana("firing", fp, startsAt="2026-11-28T11:00:00Z")
    assert (await app_client.post(url, json=back, headers=key)).status_code == 202
    rows = await _grafana_findings(fp)
    assert len(rows) == 1 and rows[0].status == "open"


async def test_grafana_needs_ingest_key_and_own_source(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    url = f"{API}/ingest/grafana"
    body = _grafana("firing", uuid.uuid4().hex[:16])
    assert (await app_client.post(url, json=body)).status_code == 401
    assert (
        await app_client.post(url, json=body, headers={"X-API-Key": "nx_zly_klucz"})
    ).status_code == 401
    assert (
        await app_client.post(url, json=body, headers=app_auth_headers)
    ).status_code == 401
    other_scope = await _key(app_client, app_auth_headers, ["traffit:read"])
    assert (
        await app_client.post(url, json=body, headers=other_scope)
    ).status_code == 403

    grafana = await _key(app_client, app_auth_headers, ["security:ingest"])
    falco = await _key(app_client, app_auth_headers, ["security:ingest"])
    assert (await app_client.post(url, json=body, headers=grafana)).status_code == 202
    # Klucz innego źródła nie pisze w imieniu Grafany.
    stolen = await app_client.post(url, json=body, headers=falco)
    assert stolen.status_code == 403
    assert stolen.json()["detail"]["error"] == "source_owned_by_other_account"


async def test_grafana_documentation_example_is_accepted(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    key = await _key(app_client, app_auth_headers, ["security:ingest"])
    payload = json.loads(GRAFANA_EXAMPLE.read_text())
    resp = await app_client.post(f"{API}/ingest/grafana", json=payload, headers=key)
    assert resp.status_code == 202, resp.text
    assert resp.json()["findings_new"] + resp.json()["findings_updated"] == 1
    rows = await _grafana_findings("c6eadffa33fcdf37")
    assert rows[0].evidence == "Pamięć powyżej 90% na [adres IP]"
    assert rows[0].severity == "medium"


async def test_grafana_rejects_body_that_is_not_a_grafana_webhook(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    key = await _key(app_client, app_auth_headers, ["security:ingest"])
    bad = await app_client.post(
        f"{API}/ingest/grafana",
        json={"status": "firing", "alerts": [{"status": "pending"}]},
        headers=key,
    )
    assert bad.status_code == 422
