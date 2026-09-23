"""Wymagania przejścia na kolumnę Tablicy (Rekrutacja v5, 24.09.2026).

Reguła „co do której kolumny" (`build_requirements`) jest czysta i testowana
bez bazy; trasa `GET /api/pipeline/move-requirements` — na bazie (CI).
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from app.services.move_requirements import PairFacts, build_requirements

VERIFIED_READY = PairFacts(
    from_column="verified",
    stage_id=11,
    screening_done=True,
    candidate_rate=True,
    availability_known=True,
)


def _keys(result: dict) -> list[str]:
    return [item["key"] for item in result["items"]]


def _item(result: dict, key: str) -> dict:
    return next(item for item in result["items"] if item["key"] == key)


def test_screening_needs_nothing() -> None:
    result = build_requirements(PairFacts(from_column="new"), "screening")
    assert result["items"] == []
    assert result["skipped_columns"] == []
    assert result["primary"] == {"kind": "move", "label": "Przesuń na „Screening”"}


def test_verified_needs_the_sheet_and_the_rate_but_not_availability() -> None:
    result = build_requirements(
        PairFacts(from_column="screening", stage_id=5, screening_stage_id=4),
        "verified",
    )
    assert _keys(result) == ["screening_sheet", "candidate_rate", "availability"]
    sheet = _item(result, "screening_sheet")
    assert sheet["status"] == "missing" and sheet["blocking"] is True
    assert sheet["action"] == {
        "kind": "open_screening",
        "label": "Otwórz screening",
        "stage_id": 4,
    }
    assert _item(result, "candidate_rate")["action"]["kind"] == "set_candidate_rate"
    assert _item(result, "availability")["blocking"] is False
    assert result["primary"]["kind"] == "blocked"


def test_skipped_columns_add_up() -> None:
    result = build_requirements(PairFacts(from_column="new", stage_id=1), "cv_qc")
    assert result["skipped_columns"] == ["screening", "verified"]
    assert _keys(result) == [
        "screening_sheet",
        "candidate_rate",
        "availability",
        "company_cv",
    ]
    assert {item["column"] for item in result["items"]} == {"verified", "cv_qc"}


def test_qc_column_needs_the_company_cv() -> None:
    missing = build_requirements(VERIFIED_READY, "cv_qc")
    cv = _item(missing, "company_cv")
    assert cv["status"] == "missing"
    assert cv["action"]["kind"] == "generate_cv"
    assert missing["primary"]["kind"] == "blocked"

    ready = build_requirements(replace(VERIFIED_READY, company_cv=True), "cv_qc")
    assert ready["primary"] == {"kind": "move", "label": "Przesuń na „QC CV”"}


def test_recruiter_hands_the_send_to_the_delivery_lead() -> None:
    facts = replace(
        VERIFIED_READY,
        from_column="cv_qc",
        company_cv=True,
        qc_status="passed",
        qc_stage_def_id=41,
    )
    result = build_requirements(facts, "cv_sent")
    assert result["primary"]["kind"] == "hand_to_dl"
    # Osoba już stoi w „QC CV” — przekazanie niczego nie przesuwa.
    assert result["primary"]["target_stage_def_id"] is None
    assert _item(result, "client_rate")["status"] == "waiting"
    assert "Delivery Lead" in result["owner_note"]


def test_hand_to_dl_from_verified_targets_the_qc_stage() -> None:
    facts = replace(
        VERIFIED_READY, company_cv=True, qc_status="failed", qc_stage_def_id=41
    )
    result = build_requirements(facts, "cv_sent")
    assert result["skipped_columns"] == ["cv_qc"]
    # QC jest pokazane jako brak, ale do przekazania DL wystarczy CV firmowe —
    # to Delivery Lead decyduje po QC.
    assert _item(result, "cv_qc")["status"] == "missing"
    assert result["primary"] == {
        "kind": "hand_to_dl",
        "label": "Przekaż Delivery Leadowi",
        "target_stage_def_id": 41,
    }


def test_hand_to_dl_still_needs_the_company_cv() -> None:
    result = build_requirements(replace(VERIFIED_READY, qc_stage_def_id=41), "cv_sent")
    assert result["primary"]["kind"] == "blocked"


def test_delivery_lead_sends_after_qc_and_with_a_client_rate() -> None:
    base = replace(
        VERIFIED_READY, from_column="cv_qc", company_cv=True, is_client_sender=True
    )
    failed = build_requirements(replace(base, qc_status="failed"), "cv_sent")
    qc = _item(failed, "cv_qc")
    assert qc["status"] == "missing" and qc["action"]["kind"] == "open_qc"
    assert failed["primary"]["kind"] == "blocked"

    no_rate = build_requirements(replace(base, qc_status="passed"), "cv_sent")
    rate = _item(no_rate, "client_rate")
    assert rate["status"] == "missing" and rate["action"]["kind"] == "set_client_rate"

    ready = build_requirements(
        replace(base, qc_status="overridden", client_rate=True), "cv_sent"
    )
    assert ready["primary"] == {"kind": "move", "label": "Przesuń na „CV wysłane”"}


def test_nordea_hands_over_to_the_cpro_queue() -> None:
    facts = replace(
        VERIFIED_READY,
        from_column="cv_qc",
        company_cv=True,
        qc_status="passed",
        nordea=True,
        cpro_stage_def_id=44,
        cpro_sender_name="Kinga Sordyl",
    )
    result = build_requirements(facts, "cv_sent")
    assert result["primary"] == {
        "kind": "hand_to_cpro",
        "label": "Przekaż do kolejki Cpro",
        "target_stage_def_id": 44,
    }
    assert "client_rate" not in _keys(result)
    assert "Kinga Sordyl" in result["owner_note"]
    # QC blokuje także przekazanie do Cpro.
    failed = build_requirements(replace(facts, qc_status="failed"), "cv_sent")
    assert failed["primary"]["kind"] == "blocked"


def test_nordea_card_already_in_the_queue_moves_only_for_the_sender() -> None:
    facts = replace(
        VERIFIED_READY,
        from_column="cv_qc",
        company_cv=True,
        qc_status="passed",
        nordea=True,
        on_cpro_stage=True,
        cpro_sender_name="Kinga Sordyl",
    )
    blocked = build_requirements(facts, "cv_sent")
    assert blocked["primary"]["kind"] == "blocked"
    assert blocked["owner_note"] == "Do Cpro wrzuca Kinga Sordyl."
    sender = build_requirements(replace(facts, can_send_to_cpro=True), "cv_sent")
    assert sender["primary"] == {
        "kind": "move",
        "label": "Przesuń na „Wysłane do Cpro”",
    }


def test_client_interview_waits_for_slots_without_blocking() -> None:
    result = build_requirements(
        PairFacts(from_column="cv_sent", stage_id=9), "client_interview"
    )
    slot = _item(result, "client_slot")
    assert slot["status"] == "waiting" and slot["blocking"] is False
    assert slot["action"]["kind"] == "request_slots"
    assert result["primary"]["kind"] == "move"


def test_contract_needs_the_debrief() -> None:
    result = build_requirements(
        PairFacts(
            from_column="client_interview",
            stage_id=9,
            debrief_missing=True,
            debrief_event_id=77,
        ),
        "contract",
    )
    debrief = _item(result, "debrief")
    assert debrief["status"] == "missing"
    assert debrief["action"]["kind"] == "open_debrief"
    assert debrief["action"]["event_id"] == 77
    assert _item(result, "client_decision")["blocking"] is False
    assert result["primary"]["kind"] == "blocked"

    pending = build_requirements(
        PairFacts(
            from_column="client_interview", debrief_missing=True, debrief_pending=True
        ),
        "contract",
    )
    assert _item(pending, "debrief")["action"] is None


def test_hired_waits_for_the_signature() -> None:
    result = build_requirements(PairFacts(from_column="contract"), "hired")
    assert _item(result, "signature")["status"] == "waiting"
    assert result["primary"]["kind"] == "move"


@pytest.mark.parametrize(
    ("from_column", "to_column"),
    [("cv_sent", "verified"), ("cv_qc", "cv_qc"), ("new", "closed")],
)
def test_backwards_same_and_closing_moves_need_nothing(
    from_column: str, to_column: str
) -> None:
    result = build_requirements(PairFacts(from_column=from_column), to_column)
    assert result["items"] == []
    assert result["primary"]["kind"] == "move"


def test_reopening_a_closed_person_walks_the_whole_way() -> None:
    result = build_requirements(PairFacts(from_column="closed"), "verified")
    assert result["skipped_columns"] == ["screening"]
    assert "screening_sheet" in _keys(result)


# ── Trasa (baza) ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_move_requirements_route(monkeypatch: pytest.MonkeyPatch) -> None:
    from httpx import ASGITransport, AsyncClient

    from app.core.rate_limit import limiter
    from app.main import app
    from app.models.user import UserRole
    from tests.test_board_tasks import (
        _cleanup,
        _login,
        _move,
        _seed_user,
        _seed_world,
        restore_cpro_sender,
    )

    limiter.enabled = False
    world = await _seed_world()
    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", "")
    hor_id, hor_creds = await _seed_user(UserRole.head_of_recruitment)
    rec_id, rec_creds = await _seed_user(UserRole.recruiter)
    dl_id, dl_creds = await _seed_user(UserRole.delivery_lead)
    defs = world["defs"]
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as client:
        hor = await _login(client, hor_creds)
        rec = await _login(client, rec_creds)
        dl = await _login(client, dl_creds)

        async def req(headers: dict, stage_key: str, stage_def_id=None):
            return await client.get(
                "/api/pipeline/move-requirements",
                headers=headers,
                params={
                    "candidate_id": world["candidate_id"],
                    "job_id": world["job_id"],
                    "to_stage_def_id": stage_def_id or defs[stage_key],
                },
            )

        try:
            await _move(
                client,
                hor,
                world,
                "verified",
                expected_rate_value="140",
                expected_rate_unit="hourly",
                expected_rate_currency="PLN",
            )
            resp = await req(rec, "cv_sent")
            assert resp.status_code == 200, resp.text
            body = resp.json()
            assert body["from_column"] == "verified"
            assert body["to_column"] == "cv_sent"
            assert body["skipped_columns"] == ["cv_qc"]
            items = {item["key"]: item for item in body["items"]}
            assert items["company_cv"]["status"] == "missing"
            assert items["cv_qc"]["status"] == "missing"
            assert items["client_rate"]["status"] == "waiting"
            # Bez CV firmowego nie ma czego przekazać Delivery Leadowi.
            assert body["primary"]["kind"] == "blocked"

            dl_body = (await req(dl, "cv_sent")).json()
            assert {i["key"] for i in dl_body["items"]} >= {"client_rate"}
            assert dl_body["primary"]["kind"] == "blocked"

            missing_def = await req(rec, "cv_sent", stage_def_id=999_999_999)
            assert missing_def.status_code == 404

            # Nordea: ten sam ruch to przekazanie do kolejki Cpro.
            monkeypatch.setenv(
                "NORDEA_ORDER_NUMBER_CLIENT_IDS", str(world["client_id"])
            )
            async with restore_cpro_sender():
                nordea = (await req(rec, "cv_sent")).json()
            assert nordea["to_column"] == "cv_sent"
            assert "client_rate" not in {i["key"] for i in nordea["items"]}
        finally:
            await _cleanup(world, [hor_id, rec_id, dl_id])
