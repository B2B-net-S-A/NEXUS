"""Uwaga dla rekrutera przy decyzji i „Wróć do poprawy” (03.10.2026).

Delivery Lead zostawiał rekruterowi uwagi wpisem w notatkach kandydata, a karta
cofnięta z „QC CV” nie dawała dzwonka. Teraz uwaga jedzie z ruchem
(``recruiter_remark``), zapisuje się jako notatka pary i trafia do dzwonka oraz
na listę „Twoje CV w drodze”. Dane w testach są fikcyjne.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.note import Note, NoteType
from app.models.notification import NotificationType
from app.models.recommendation_card import RecommendationCard
from app.services import board_tasks, note_kinds, stage_remarks
from app.services import stage_handoff_recipients as handoff
from app.services import stage_notification_emitter as emitter
from tests.test_board_tasks import _cleanup, _login, _move
from tests.test_cv_in_transit import (
    _mine,
    _non_nordea_world,
    _rejected_def_id,
    _seed_screening,
    _transit,
)
from tests.test_stage_handoff_notifications import _def, _stage_bells

# ── Bez bazy ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "content",
    [
        "Kandydat chce 150, wróć z 140 zł/h",
        "Wyślijmy za 161 zł/h",
        "Must-have trafione: python",
        "Dopisz Spring Boot do ostatniego projektu",
    ],
)
def test_remark_kind_comes_from_the_origin_not_from_the_content(content: str) -> None:
    """Uwaga z kwotą nie może stać się wpisem o stawce do klienta — byłaby
    zakryta rekruterowi, do którego jest skierowana. Także po edycji."""

    assert (
        note_kinds.classify(content, external_source=note_kinds.REMARK_SOURCE)
        == note_kinds.DL_REVIEW
    )
    assert not note_kinds.hides_client_rate(note_kinds.DL_REVIEW)


def test_models_do_not_read_remarks() -> None:
    assert f"'{note_kinds.DL_REVIEW}'" in note_kinds.ai_readable_sql("n")


def test_short_remark_is_one_trimmed_line() -> None:
    assert stage_remarks.short("  Dopisz\n\nSpring  Boot ") == "Dopisz Spring Boot"
    assert stage_remarks.short("   ") is None
    assert stage_remarks.short(None) is None
    long = stage_remarks.short("a" * 500)
    assert long is not None and len(long) == stage_remarks.SHORT_CHARS
    assert long.endswith("…")


def test_card_moved_back_from_qc_is_a_handoff_outside_nordea(monkeypatch) -> None:
    qc, verified = _def("QC CV", "interview"), _def("Zweryfikowany", "verified")
    screening = _def("Screening", "screening")
    monkeypatch.setattr(handoff, "cpro_enabled_for_client", lambda _cid: False)
    assert (
        handoff.handoff_kind(verified, client_id=7, previous_def=qc)
        == handoff.REASON_QC_RETURNED
    )
    assert (
        handoff.handoff_kind(screening, client_id=7, previous_def=qc)
        == handoff.REASON_QC_RETURNED
    )
    # Cofnięcie między wcześniejszymi kolumnami to nie zwrot z przeglądu.
    assert handoff.handoff_kind(screening, client_id=7, previous_def=verified) is None
    assert handoff.handoff_kind(verified, client_id=7) is None
    # U Nordei „QC CV” to praca rekrutera — jego własne cofnięcie karty.
    monkeypatch.setattr(handoff, "cpro_enabled_for_client", lambda _cid: True)
    assert handoff.handoff_kind(verified, client_id=7, previous_def=qc) is None


def test_return_for_fixes_is_a_task_and_a_backward_handoff() -> None:
    assert handoff.REASON_QC_RETURNED in handoff.TASK_REASONS
    assert handoff.BACKWARD_REASONS == {
        handoff.REASON_CPRO_RETURNED,
        handoff.REASON_QC_RETURNED,
    }


def _bell(reason, remark=None):
    return emitter._inapp_content(
        reason=reason,
        candidate=SimpleNamespace(id=9),
        candidate_full_name="Jan Testowy",
        stage_display_name="CV Wysłane",
        job=SimpleNamespace(id=3, title="ZOB-1 Java", working_title="Java · Spring"),
        mover=SimpleNamespace(name="Daria D."),
        remark=remark,
    )


def test_bell_carries_the_remark_and_never_a_rate() -> None:
    title, message, link = _bell(handoff.REASON_QC_RETURNED, "Dopisz Spring Boot")
    assert title == "Wróciło do poprawy: Jan Testowy"
    assert "Daria D. cofnął(-ęła) CV kandydata Jan Testowy z QC" in message
    assert message.endswith("Uwaga: „Dopisz Spring Boot”")
    assert link == "/jobs/3?candidate=9"

    _title, message, _link = _bell(handoff.REASON_CV_SENT, "Rozmowa możliwa od środy")
    assert message.endswith("Uwaga: „Rozmowa możliwa od środy”")
    # Bez uwagi treść jest taka jak przed zmianą.
    _title, plain, _link = _bell(handoff.REASON_CV_SENT)
    assert "Uwaga" not in plain


def test_template_knows_where_a_card_returns_for_fixes() -> None:
    stages = board_tasks.classify_template(
        [
            SimpleNamespace(
                id=2,
                name="Zweryfikowany",
                order=2,
                legacy_enum_value="verified",
                is_terminal=False,
                terminal_type=None,
            ),
            SimpleNamespace(
                id=3,
                name="Zweryfikowany (#2)",
                order=3,
                legacy_enum_value="verified",
                is_terminal=False,
                terminal_type=None,
            ),
        ]
    )
    # Powrót do poprawy celuje w pierwszy etap „Zweryfikowany” szablonu.
    assert stages.verified_id == 2


# ── Z bazą: prawdziwe ruchy ──────────────────────────────────────────────────


@pytest_asyncio.fixture
async def api_client():
    from app.core.rate_limit import limiter as _limiter
    from app.main import app

    _limiter.enabled = False
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as c:
        yield c


async def _remarks(candidate_id: int) -> list[Note]:
    async with AsyncSessionLocal() as db:
        rows = await db.scalars(
            select(Note)
            .where(
                Note.candidate_id == candidate_id,
                Note.external_source == note_kinds.REMARK_SOURCE,
            )
            .order_by(Note.id)
        )
        return list(rows.all())


async def _cleanup_with_notes(world: dict, user_ids: list[int]) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(delete(Note).where(Note.candidate_id == world["candidate_id"]))
        await db.commit()
    await _cleanup(world, user_ids)


@pytest.mark.asyncio
async def test_return_for_fixes_rings_the_recruiter_with_the_remark(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    (
        world,
        (rec_id, rec_creds),
        (other_id, _),
        (dl_id, dl_creds),
    ) = await _non_nordea_world(monkeypatch)
    rec = await _login(api_client, rec_creds)
    dl = await _login(api_client, dl_creds)
    cid, jid = world["candidate_id"], world["job_id"]
    try:
        await _seed_screening(world, rec_id)
        await _move(api_client, rec, world, "verified")
        await _move(api_client, rec, world, "qc")

        # Wiersz przeglądu mówi, dokąd cofnąć kartę.
        review = [
            r
            for r in (await api_client.get("/api/board-tasks", headers=dl)).json()[
                "dl_review"
            ]
            if r["candidate_id"] == cid
        ]
        assert review[0]["return_stage_def_id"] == world["defs"]["verified"]
        assert review[0]["card_status"] is None and review[0]["card_missing"] == 0

        resp = await _move(
            api_client,
            dl,
            world,
            "verified",
            recruiter_remark="  Kandydat chce 150, wróć z 140 zł/h  ",
        )
        stage_id = resp.json()["id"]

        notes = await _remarks(cid)
        assert len(notes) == 1
        note = notes[0]
        assert note.content == "Kandydat chce 150, wróć z 140 zł/h"
        assert note.kind == note_kinds.DL_REVIEW
        assert (note.job_id, note.author_id) == (jid, dl_id)
        assert note.external_id == str(stage_id)

        bells = [
            b
            for b in await _stage_bells(rec_id, cid)
            if b.title.startswith("Wróciło do poprawy")
        ]
        assert len(bells) == 1
        assert bells[0].notification_type == NotificationType.board_task_waiting
        assert bells[0].message.endswith("Uwaga: „Kandydat chce 150, wróć z 140 zł/h”")
        assert bells[0].link == f"/jobs/{jid}?candidate={cid}"

        returned = _mine(await _transit(api_client, rec), "returned", cid)
        assert [r["kind"] for r in returned] == ["sent_back"]
        assert returned[0]["remark"] == "Kandydat chce 150, wróć z 140 zł/h"

        # Rekruter widzi uwagę w notatkach rekrutacji — nie jest zakryta.
        listed = await api_client.get(
            "/api/notes", headers=rec, params={"candidate_id": cid, "job_id": jid}
        )
        assert listed.status_code == 200, listed.text
        payload = listed.json()
        items = payload["items"] if isinstance(payload, dict) else payload
        assert any(n["id"] == note.id and "wróć z 140" in n["content"] for n in items)
    finally:
        await _cleanup_with_notes(world, [rec_id, other_id, dl_id])


@pytest.mark.asyncio
async def test_edited_remark_keeps_its_kind(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    (
        world,
        (rec_id, rec_creds),
        (other_id, _),
        (dl_id, dl_creds),
    ) = await _non_nordea_world(monkeypatch)
    rec = await _login(api_client, rec_creds)
    dl = await _login(api_client, dl_creds)
    cid = world["candidate_id"]
    try:
        await _seed_screening(world, rec_id)
        await _move(api_client, rec, world, "verified")
        await _move(api_client, rec, world, "qc")
        await _move(api_client, dl, world, "verified", recruiter_remark="Popraw daty")
        note_id = (await _remarks(cid))[0].id
        async with AsyncSessionLocal() as db:
            note = await db.get(Note, note_id)
            note.content = "Wyślijmy za 161 zł/h"
            await db.commit()
        async with AsyncSessionLocal() as db:
            assert (await db.get(Note, note_id)).kind == note_kinds.DL_REVIEW
    finally:
        await _cleanup_with_notes(world, [rec_id, other_id, dl_id])


@pytest.mark.asyncio
async def test_send_and_rejection_carry_the_remark_to_the_recruiter(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    (
        world,
        (rec_id, rec_creds),
        (other_id, _),
        (dl_id, dl_creds),
    ) = await _non_nordea_world(monkeypatch)
    rec = await _login(api_client, rec_creds)
    dl = await _login(api_client, dl_creds)
    cid, jid = world["candidate_id"], world["job_id"]
    try:
        await _seed_screening(world, rec_id)
        await _move(api_client, rec, world, "verified")
        await _move(api_client, rec, world, "qc")
        await _move(
            api_client,
            dl,
            world,
            "cv_sent",
            client_rate_value="170",
            client_rate_unit="hourly",
            client_rate_currency="PLN",
            recruiter_remark="Klient odpowie do piątku",
        )
        sent = _mine(await _transit(api_client, rec), "sent", cid)
        assert sent[0]["remark"] == "Klient odpowie do piątku"
        bell = [
            b
            for b in await _stage_bells(rec_id, cid)
            if b.title.startswith("CV wysłane")
        ][0]
        assert bell.message.endswith("Uwaga: „Klient odpowie do piątku”")
        # Stawka do klienta ma własne pole — nie trafia ani do dzwonka, ani do uwagi.
        assert "170" not in bell.message
        assert "170" not in (await _remarks(cid))[0].content

        resp = await api_client.post(
            "/api/pipeline/move",
            headers=dl,
            json={
                "candidate_id": cid,
                "job_id": jid,
                "stage_def_id": await _rejected_def_id(world),
                "ended_by": "delivery_lead",
                "rejection_reason": "klient wstrzymał nabór",
                "recruiter_remark": "Zostaw go w swoich ludziach",
            },
        )
        assert resp.status_code == 200, resp.text
        returned = _mine(await _transit(api_client, rec), "returned", cid)
        assert returned[0]["kind"] == "rejected_by_dl"
        assert returned[0]["reason"] == "klient wstrzymał nabór"
        assert returned[0]["remark"] == "Zostaw go w swoich ludziach"
        # Ruch bez uwagi nie zakłada pustej notatki.
        assert len(await _remarks(cid)) == 2
    finally:
        await _cleanup_with_notes(world, [rec_id, other_id, dl_id])


@pytest.mark.asyncio
async def test_remark_longer_than_the_limit_is_refused(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    (
        world,
        (rec_id, rec_creds),
        (other_id, _),
        (dl_id, _dl),
    ) = await _non_nordea_world(monkeypatch)
    rec = await _login(api_client, rec_creds)
    try:
        await _seed_screening(world, rec_id)
        resp = await api_client.post(
            "/api/pipeline/move",
            headers=rec,
            json={
                "candidate_id": world["candidate_id"],
                "job_id": world["job_id"],
                "stage_def_id": world["defs"]["verified"],
                "recruiter_remark": "x" * (stage_remarks.MAX_CHARS + 1),
            },
        )
        assert resp.status_code == 422
        assert await _remarks(world["candidate_id"]) == []
    finally:
        await _cleanup_with_notes(world, [rec_id, other_id, dl_id])


@pytest.mark.asyncio
async def test_review_queue_shows_the_card_state(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    (
        world,
        (rec_id, rec_creds),
        (other_id, _),
        (dl_id, dl_creds),
    ) = await _non_nordea_world(monkeypatch)
    rec = await _login(api_client, rec_creds)
    dl = await _login(api_client, dl_creds)
    cid, jid = world["candidate_id"], world["job_id"]
    try:
        await _seed_screening(world, rec_id)
        await _move(api_client, rec, world, "verified")
        await _move(api_client, rec, world, "qc")
        saved = await api_client.put(
            "/api/recommendation-cards",
            headers=rec,
            json={
                "candidate_id": cid,
                "job_id": jid,
                "fields": {"rate": "140 zł/h B2B", "availability": "od zaraz"},
            },
        )
        assert saved.status_code == 200, saved.text
        missing = len(saved.json()["completeness"]["missing"])

        review = [
            r
            for r in (await api_client.get("/api/board-tasks", headers=dl)).json()[
                "dl_review"
            ]
            if r["candidate_id"] == cid
        ]
        assert review[0]["card_status"] == "partial"
        assert review[0]["card_missing"] == missing > 0
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(RecommendationCard).where(RecommendationCard.candidate_id == cid)
            )
            await db.commit()
        await _cleanup_with_notes(world, [rec_id, other_id, dl_id])


def test_note_type_of_a_remark_is_general() -> None:
    """Follow-up liczy za kontakt z kandydatem notatki typu telefon/spotkanie/
    mail — uwaga dla rekrutera nie jest rozmową z kandydatem."""

    stage = SimpleNamespace(id=5, candidate_id=1, job_id=2)
    added: list[Note] = []
    note = stage_remarks.record(
        SimpleNamespace(add=added.append),  # type: ignore[arg-type]
        stage=stage,  # type: ignore[arg-type]
        author_id=3,
        text="Popraw daty",
    )
    assert note is not None and added == [note]
    assert note.note_type == NoteType.general
    assert (
        stage_remarks.record(
            SimpleNamespace(add=added.append),  # type: ignore[arg-type]
            stage=stage,  # type: ignore[arg-type]
            author_id=3,
            text="  ",
        )
        is None
    )
