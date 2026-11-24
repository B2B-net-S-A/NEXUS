"""Radar przepisów z bazą: token biegu, przyjęcie raportów, bramka, ekran „Przepisy”.

Baza testowa jest wspólna dla przebiegu: adresy pozycji niosą losowy tag,
a asercje patrzą na własne wiersze, nie na liczby całej tabeli.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import select, update

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.law_radar import (
    LawChange,
    LawChangeEvent,
    LawChangeProbe,
    LawChangeTask,
    LawRadarItem,
    LawRadarRun,
)
from app.services.law_radar import flow, runs
from tests.test_sales_companies_api import _headers, _user

URL = "/api/integrations/law-radar/runs"
API = "/api/compliance"


@pytest.fixture(autouse=True)
def _no_background_gate(monkeypatch):
    """Trasa nie startuje w testach bramki w tle (prawdziwe API Sejmu)."""

    spawned: list[int] = []

    async def _record(run_id: int) -> None:
        spawned.append(run_id)

    monkeypatch.setattr(flow, "after_collect_in_background", _record)
    return spawned


async def _run(
    kind: str = "collect", request: dict | None = None, *, schema_version: int = 1, **over
) -> tuple[int, str]:
    async with AsyncSessionLocal() as db:
        run, token = runs.new_run(kind, request or {}, now=datetime.now(timezone.utc))
        # Existing fixtures represent callbacks already in flight before v2.
        if schema_version == 1:
            run.request = {k: v for k, v in run.request.items() if k != "_schema_version"}
        for key, value in over.items():
            setattr(run, key, value)
        db.add(run)
        await db.commit()
        return run.id, token


def _item(tag: str, **over) -> dict:
    base = {
        "source": "sejm",
        "title": f"Ustawa {tag}",
        "url": f"https://api.sejm.gov.pl/eli/acts/DU/2026/{tag}",
        "published": "2026-11-14",
    }
    return {**base, **over}


async def _items(run_id: int) -> list[LawRadarItem]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.execute(
                    select(LawRadarItem)
                    .where(LawRadarItem.run_id == run_id)
                    .order_by(LawRadarItem.id)
                )
            ).scalars()
        )


@pytest.mark.asyncio
async def test_wrong_expired_or_missing_token_gets_the_same_401(app_client) -> None:
    run_id, token = await _run()
    expired_id, expired_token = await _run(
        token_expires_at=datetime.now(timezone.utc) - timedelta(minutes=1)
    )
    cases = [
        (run_id, {"X-Run-Token": "zly"}),
        (run_id, {}),
        (expired_id, {"X-Run-Token": expired_token}),
        (run_id + 100_000, {"X-Run-Token": token}),
    ]
    for rid, headers in cases:
        resp = await app_client.post(
            f"{URL}/{rid}", json={"items": []}, headers=headers
        )
        assert resp.status_code == 401, (rid, resp.text)
        assert resp.json()["detail"] == runs.INVALID_TOKEN_DETAIL
    admin = await _user(role="admin")
    resp = await app_client.post(
        f"{URL}/{run_id}", json={"items": []}, headers=_headers(admin)
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_collect_report_413_422_then_once(
    app_client, _no_background_gate, monkeypatch
) -> None:
    tag = uuid.uuid4().hex[:8]
    run_id, token = await _run()
    big = b'{"items": [], "pad": "' + b"x" * (600 * 1024) + b'"}'
    resp = await app_client.post(
        f"{URL}/{run_id}",
        content=big,
        headers={"X-Run-Token": token, "Content-Type": "application/json"},
    )
    assert resp.status_code == 413
    bad = await app_client.post(
        f"{URL}/{run_id}",
        json={"items": [_item(tag, act_ref="DU/26/1")]},
        headers={"X-Run-Token": token},
    )
    assert bad.status_code == 422
    body = {
        "items": [
            _item(tag, act_ref="DU/2026/473"),
            _item(tag, act_ref="DU/2026/473"),
            _item(tag, source="lex", url=f"https://sip.lex.pl/{tag}"),
        ],
        "gofin_skipped": True,
        "gofin_skip_reason": "device_approval",
    }
    ok = await app_client.post(
        f"{URL}/{run_id}", json=body, headers={"X-Run-Token": token}
    )
    assert ok.status_code == 200, ok.text
    assert ok.json() == {
        "status": "received",
        "items_in": 3,
        "new": 2,
        "known": 0,
        "duplicates": 1,
        "by_class": {"official": 1, "lex": 1, "practice": 0},
        "lex_skipped": False,
        "gofin_skipped": True,
    }
    assert _no_background_gate == [run_id]
    again = await app_client.post(
        f"{URL}/{run_id}", json=body, headers={"X-Run-Token": token}
    )
    assert again.status_code == 401
    items = await _items(run_id)
    assert [(i.klass, i.gate) for i in items] == [
        ("official", "pending"),
        ("lex", "pending"),
    ]

    # Te same pozycje w kolejnym biegu nie tworzą nowych wierszy.
    second_id, second_token = await _run()
    resp = await app_client.post(
        f"{URL}/{second_id}", json=body, headers={"X-Run-Token": second_token}
    )
    assert resp.json()["new"] == 0 and resp.json()["known"] == 2
    assert _no_background_gate == [run_id]
    monkeypatch.setattr(settings, "LAW_RADAR_ENABLED", True)
    viewer = await _user("finance_module")
    response = await app_client.get(f"{API}/runs", headers=_headers(viewer))
    assert response.status_code == 200
    summaries = {row["id"]: row["summary"] for row in response.json()["runs"]}
    assert summaries[run_id]["gofin_skip_reason"] == "device_approval"
    assert summaries[run_id]["saved_sources"] == {"lex": 1, "gofin": 0}
    assert summaries[second_id]["saved_sources"] == {"lex": 0, "gofin": 0}


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def _close_open_analyze() -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(LawRadarRun)
            .where(LawRadarRun.kind == "analyze", LawRadarRun.status == "started")
            .values(status="expired", token_hash=None)
        )
        await db.commit()


@pytest.mark.asyncio
async def test_gate_then_analyst_gets_only_items_that_passed(app_client, monkeypatch) -> None:
    monkeypatch.setattr(
        settings, "GROK_BOT_LAW_ANALYZE_WEBHOOK_URL", "https://bot.example/a"
    )
    monkeypatch.setattr(settings, "GROK_BOT_LAW_ANALYZE_WEBHOOK_KEY", "test-key")
    await _close_open_analyze()
    tag = uuid.uuid4().hex[:8]
    run_id, _token = await _run()
    async with AsyncSessionLocal() as db:
        run = await db.get(LawRadarRun, run_id)
        from app.services.law_radar import collect

        report = collect.CollectReport.model_validate(
            {
                "items": [
                    _item(f"{tag}-ok", act_ref="DU/2026/473"),
                    _item(f"{tag}-bad", act_ref="DU/2026/99999"),
                    _item(f"{tag}-none", url=f"https://doradca.example.pl/{tag}"),
                ]
            }
        )
        await collect.ingest(db, run, report, now=datetime.now(timezone.utc))
        await db.commit()

    def sejm(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/eli/acts/DU/2026/473":
            return httpx.Response(
                200, json={"title": "Akt", "entryIntoForce": "2027-01-01"}
            )
        return httpx.Response(404)

    sent: list[dict] = []

    def bot(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer test-key"
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"runUuid": "x"})

    async with AsyncSessionLocal() as db:
        result = await flow.after_collect(
            db, run_id, gate_client=_client(sejm), bot_client=_client(bot)
        )
    assert (result["verified"], result["rejected"], result["unverified"]) == (1, 1, 1)
    gates = {i.title.rsplit("-", 1)[-1]: i.gate for i in await _items(run_id)}
    assert gates == {"ok": "verified", "bad": "rejected", "none": "unverified"}
    assert result["analyze_run_id"] is not None and len(sent) == 1
    trigger = sent[0]
    assert set(trigger) == {
        "schema_version",
        "run_id",
        "request_url",
        "token",
        "expires_at",
    }
    assert trigger["schema_version"] == 2
    assert trigger["request_url"].endswith(f"/runs/{result['analyze_run_id']}")
    assert len(json.dumps(trigger, ensure_ascii=False).encode()) < 2048
    fetched = await app_client.get(
        f"{URL}/{result['analyze_run_id']}", headers={"X-Run-Token": trigger["token"]}
    )
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["callback_url"] == trigger["request_url"]
    request = fetched.json()["request"]
    titles = {item["title"] for item in request["items"]}
    assert f"Ustawa {tag}-ok" in titles and f"Ustawa {tag}-none" in titles
    assert f"Ustawa {tag}-bad" not in titles
    verified = next(
        i for i in request["items"] if i["title"] == f"Ustawa {tag}-ok"
    )
    assert verified["entry_into_force"] == "2027-01-01"
    await _close_open_analyze()


async def _analysis_items(count: int = 2) -> list[dict]:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        rows = [
            LawRadarItem(
                fingerprint=uuid.uuid4().hex,
                source="sejm",
                klass="official",
                gate="verified",
                title=f"Ustawa testowa {tag} {index}",
                url=f"https://sejm.gov.pl/{tag}/{index}",
                published=date(2026, 11, 14),
                quote="Zmiana obowiązków sprawozdawczych. " * 10,
            )
            for index in range(count)
        ]
        db.add_all(rows)
        await db.commit()
        return [{"id": row.id, "title": row.title, "quote": row.quote} for row in rows]


@pytest.mark.asyncio
async def test_v2_get_returns_the_complete_stored_request_without_consuming_token(app_client):
    items = await _analysis_items(25)
    request = {
        "items": items,
        "topics": ["VAT", "Kadry i płace"],
        "open_changes": [{"id": 123, "title": "Zmiana testowa", "legal_ref": "DU/2026/473"}],
        "probes": [{"key": "test", "description": "Umowy B2B"}],
        "roles": ["accounting", "payroll"],
        "stages": ["sejm", "journal"],
        "urgencies": ["now", "soon"],
        "max_changes": 50,
    }
    assert len(json.dumps(request, ensure_ascii=False).encode()) > 10_000
    run_id, token = await _run("analyze", request, schema_version=2)
    headers = {"X-Run-Token": token}
    for _ in range(2):
        fetched = await app_client.get(f"{URL}/{run_id}", headers=headers)
        assert fetched.status_code == 200, fetched.text
        assert "no-store" in fetched.headers.get("cache-control", "")
        body = fetched.json()
        assert body["request"] == request  # includes the last item and trailing context
        assert "_schema_version" not in body["request"]
        assert "request.items" in body["task"]
        assert "reviewed_item_ids" in body["report_format"]
        assert token not in fetched.text
    async with AsyncSessionLocal() as db:
        stored = await db.get(LawRadarRun, run_id)
        assert stored.status == "started" and stored.received_at is None
        assert stored.token_hash == runs.hash_token(token)
        assert stored.request["_schema_version"] == 2


@pytest.mark.asyncio
async def test_analysis_request_get_rejects_missing_wrong_expired_cross_run_and_cross_kind_tokens(app_client):
    request = {"items": [], "open_changes": []}
    run_id, token = await _run("analyze", request, schema_version=2)
    other_id, _ = await _run("analyze", request, schema_version=2)
    expired_id, expired_token = await _run(
        "analyze", request, schema_version=2,
        token_expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    collect_id, collect_token = await _run()
    consumed_id, consumed_token = await _run(
        "analyze", request, schema_version=2, status="received", token_hash=None,
    )
    cases = [
        (run_id, {}),
        (run_id, {"X-Run-Token": "wrong"}),
        (other_id, {"X-Run-Token": token}),
        (run_id + 100_000, {"X-Run-Token": token}),
        (expired_id, {"X-Run-Token": expired_token}),
        (collect_id, {"X-Run-Token": collect_token}),
        (consumed_id, {"X-Run-Token": consumed_token}),
    ]
    for rid, auth in cases:
        response = await app_client.get(f"{URL}/{rid}", headers=auth)
        assert response.status_code == 401, (rid, response.text)
        assert response.json()["detail"] == runs.INVALID_TOKEN_DETAIL


@pytest.mark.asyncio
async def test_v2_rejects_incomplete_review_without_writing_and_accepts_full_coverage_once(app_client):
    items = await _analysis_items()
    ids = [item["id"] for item in items]
    run_id, token = await _run("analyze", {"items": items, "open_changes": []}, schema_version=2)
    headers = {"X-Run-Token": token}
    change = {
        "title": f"Zmiana testowa {uuid.uuid4().hex[:8]}",
        "summary": ["Opis zmiany."],
        "roles": ["accounting"],
        "urgency": "soon",
        "stage": "sejm",
        "item_ids": [ids[0]],
    }
    invalid_reports = [
        {"changes": [change]},
        {"changes": [change], "reviewed_item_ids": []},
        {"changes": [change], "reviewed_item_ids": ids[:1]},
        {"changes": [change], "reviewed_item_ids": [*ids, ids[0]]},
        {"changes": [change], "reviewed_item_ids": [*ids, 999_999_999]},
        {"changes": [change], "reviewed_item_ids": [str(cid) for cid in ids]},
        {"changes": [change], "reviewed_item_ids": None},
    ]
    for payload in invalid_reports:
        rejected = await app_client.post(f"{URL}/{run_id}", json=payload, headers=headers)
        assert rejected.status_code == 422, rejected.text
        async with AsyncSessionLocal() as db:
            stored = await db.get(LawRadarRun, run_id)
            assert stored.status == "started" and stored.received_at is None
            assert stored.token_hash == runs.hash_token(token) and stored.report == {}
            assert await db.scalar(select(LawChange.id).where(LawChange.title == change["title"])) is None
            untouched = (await db.scalars(select(LawRadarItem).where(LawRadarItem.id.in_(ids)))).all()
            assert all(item.analyzed_at is None and item.change_id is None and item.analyze_run_id is None for item in untouched)
        # Validation failure must not consume the GET capability either.
        assert (await app_client.get(f"{URL}/{run_id}", headers=headers)).status_code == 200

    # Explicitly reviewed but irrelevant items may yield no changes. Order is immaterial.
    accepted = await app_client.post(
        f"{URL}/{run_id}", json={"changes": [], "reviewed_item_ids": list(reversed(ids))}, headers=headers
    )
    assert accepted.status_code == 200, accepted.text
    async with AsyncSessionLocal() as db:
        stored = await db.get(LawRadarRun, run_id)
        reviewed = (await db.scalars(select(LawRadarItem).where(LawRadarItem.id.in_(ids)))).all()
        assert stored.status == "received" and stored.token_hash is None
        assert all(item.analyzed_at is not None and item.analyze_run_id == run_id for item in reviewed)
    assert (await app_client.get(f"{URL}/{run_id}", headers=headers)).status_code == 401
    assert (await app_client.post(f"{URL}/{run_id}", json={"changes": [], "reviewed_item_ids": ids}, headers=headers)).status_code == 401


@pytest.mark.asyncio
async def test_analyst_updates_content_and_stage_never_status(app_client) -> None:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        item = LawRadarItem(
            fingerprint=uuid.uuid4().hex,
            source="sejm",
            klass="official",
            gate="verified",
            title=f"Ustawa {tag}",
            url=f"https://sejm.gov.pl/{tag}",
            published=date(2026, 11, 14),
        )
        db.add(item)
        await db.commit()
        item_id = item.id
    request = {"items": [{"id": item_id}], "open_changes": []}
    run_id, token = await _run("analyze", request)
    first = {
        "changes": [
            {
                "title": f"Zmiana {tag}",
                "summary": ["Co się zmienia."],
                "roles": ["accounting"],
                "urgency": "soon",
                "stage": "sejm",
                "item_ids": [item_id, 999_999_999],
                "probes": ["ksef_sales_invoices", "nieznana"],
                "todo": [{"text": "Sprawdzić KSeF", "role": "accounting"}],
            }
        ]
    }
    resp = await app_client.post(
        f"{URL}/{run_id}", json=first, headers={"X-Run-Token": token}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["created"] == 1 and resp.json()["dropped"]["foreign_items"] == 1
    async with AsyncSessionLocal() as db:
        change = await db.scalar(
            select(LawChange).where(LawChange.title == f"Zmiana {tag}")
        )
        change_id = change.id
        assert (change.status, change.stage, change.probe_keys) == (
            "new",
            "sejm",
            ["ksef_sales_invoices"],
        )
        probe = await db.scalar(
            select(LawChangeProbe).where(LawChangeProbe.change_id == change_id)
        )
        assert probe.probe_key == "ksef_sales_invoices" and isinstance(probe.value, int)
        linked = await db.get(LawRadarItem, item_id)
        assert linked.change_id == change_id and linked.analyzed_at is not None
        # Człowiek decyduje: „W toku”.
        change.status = "in_progress"
        await db.commit()

    request = {"items": [{"id": item_id}], "open_changes": [{"id": change_id}]}
    run_id, token = await _run("analyze", request)
    second = {
        "changes": [
            {
                **first["changes"][0],
                "change_ref": change_id,
                "title": f"Zmiana {tag} po Senacie",
                "stage": "president",
                "item_ids": [item_id],
                "todo": [
                    {"text": "sprawdzić ksef", "role": "accounting"},
                    {"text": "Nowe zadanie", "role": "board"},
                ],
            }
        ]
    }
    resp = await app_client.post(
        f"{URL}/{run_id}", json=second, headers={"X-Run-Token": token}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["updated"] == 1 and resp.json()["stage_changes"] == 1
    async with AsyncSessionLocal() as db:
        change = await db.get(LawChange, change_id)
        assert (change.status, change.stage, change.title) == (
            "in_progress",
            "president",
            f"Zmiana {tag} po Senacie",
        )
        tasks = (
            (
                await db.execute(
                    select(LawChangeTask.text).where(
                        LawChangeTask.change_id == change_id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert sorted(tasks) == ["Nowe zadanie", "Sprawdzić KSeF"]
        kinds = (
            await db.execute(
                select(LawChangeEvent.kind, LawChangeEvent.to_value).where(
                    LawChangeEvent.change_id == change_id
                )
            )
        ).all()
        assert ("stage", "president") in kinds and ("created", None) in kinds


@pytest.mark.asyncio
async def test_compliance_screen_gates_flag_and_decisions(
    app_client, monkeypatch
) -> None:
    recruiter = await _user()
    finance = await _user("finance_module")
    head = await _user(role="head_of_recruitment")
    monkeypatch.setattr(settings, "LAW_RADAR_ENABLED", False)
    resp = await app_client.get(f"{API}/changes", headers=_headers(finance))
    assert resp.status_code == 200 and resp.json() == {"enabled": False, "changes": []}
    assert (
        await app_client.get(f"{API}/changes", headers=_headers(recruiter))
    ).status_code == 403
    assert (
        await app_client.get(f"{API}/summary", headers=_headers(head))
    ).status_code == 200

    monkeypatch.setattr(settings, "LAW_RADAR_ENABLED", True)
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        change = LawChange(
            title=f"Jawność płac {tag}",
            summary=["Widełki w ogłoszeniach."],
            roles=["recruitment"],
            urgency="now",
            stage="journal",
            deadline=business_today() + timedelta(days=10),
        )
        db.add(change)
        await db.commit()
        change_id = change.id

    listed = await app_client.get(
        f"{API}/changes", params={"role": "recruitment"}, headers=_headers(head)
    )
    assert next(c for c in listed.json()["changes"] if c["id"] == change_id)["verified_sources"] == 0
    other = await app_client.get(
        f"{API}/changes", params={"role": "payroll"}, headers=_headers(head)
    )
    assert change_id not in {c["id"] for c in other.json()["changes"]}

    no_note = await app_client.patch(
        f"{API}/changes/{change_id}",
        json={"status": "not_applicable"},
        headers=_headers(finance),
    )
    assert no_note.status_code == 422
    done = await app_client.patch(
        f"{API}/changes/{change_id}",
        json={"status": "not_applicable", "note": "Nie publikujemy ogłoszeń."},
        headers=_headers(finance),
    )
    assert (
        done.status_code == 200 and done.json()["change"]["status"] == "not_applicable"
    )

    task = await app_client.post(
        f"{API}/changes/{change_id}/tasks",
        json={"text": "Dopisać widełki", "role": "recruitment"},
        headers=_headers(head),
    )
    assert task.status_code == 201, task.text
    ticked = await app_client.patch(
        f"{API}/tasks/{task.json()['id']}", json={"done": True}, headers=_headers(head)
    )
    assert ticked.json()["done"] is True

    detail = await app_client.get(
        f"{API}/changes/{change_id}", headers=_headers(finance)
    )
    kinds = [event["kind"] for event in detail.json()["events"]]
    assert kinds[:3] == ["task_done", "task_added", "status"]
    status_event = detail.json()["events"][2]
    assert status_event["note"] == "Nie publikujemy ogłoszeń."

    collect = await app_client.post(f"{API}/runs/collect", headers=_headers(finance))
    assert collect.status_code == 403


@pytest.mark.asyncio
async def test_webhook_failure_closes_run_and_timeout_keeps_it_open(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        settings, "GROK_BOT_LAW_COLLECT_WEBHOOK_URL", "https://bot.example/c"
    )
    monkeypatch.setattr(settings, "GROK_BOT_LAW_COLLECT_WEBHOOK_KEY", "test-key")

    def refused(_request):
        return httpx.Response(503)

    def slow(_request):
        raise httpx.ReadTimeout("slow")

    async with AsyncSessionLocal() as db:
        failed = await runs.start_run(db, "collect", {}, client=_client(refused))
        assert (failed.status, failed.error, failed.token_hash) == (
            "failed",
            "webhook HTTP 503",
            None,
        )
        open_run = await runs.start_run(db, "collect", {}, client=_client(slow))
        assert open_run.status == "started" and open_run.token_hash is not None
        await runs.expire_runs(db, now=datetime.now(timezone.utc) + timedelta(hours=3))
        await db.refresh(open_run)
        assert open_run.status == "expired"
