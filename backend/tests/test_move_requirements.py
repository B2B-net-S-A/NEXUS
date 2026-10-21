"""Wymagania przejścia na kolumnę Tablicy (Rekrutacja v5, 24.09.2026).

Reguła „co do której kolumny" (`build_requirements`) jest czysta i testowana
bez bazy; trasa `GET /api/pipeline/move-requirements` — na bazie (CI).
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from app.services.move_requirements import (
    PairFacts,
    build_requirements,
    card_screening_state,
    minimum_missing,
    required_card_fields,
    screening_requirement,
)

VERIFIED_READY = PairFacts(
    from_column="verified",
    stage_id=11,
    screening_done=True,
    candidate_rate=True,
    availability_known=True,
    card_present=frozenset({"location", "work_mode", "recommendation"}),
)
# Minimum dla Delivery Leada (decyzja Artura 21.10.2026) — w kolejności okna.
MINIMUM_KEYS = ["location", "work_mode", "availability", "recommendation"]


def _keys(result: dict) -> list[str]:
    return [item["key"] for item in result["items"]]


def _item(result: dict, key: str) -> dict:
    return next(item for item in result["items"] if item["key"] == key)


def test_screening_needs_nothing() -> None:
    result = build_requirements(PairFacts(from_column="new"), "screening")
    assert result["items"] == []
    assert result["skipped_columns"] == []
    assert result["primary"] == {"kind": "move", "label": "Przesuń na „Screening”"}


def test_verified_needs_the_sheet_the_rate_and_the_minimum_for_dl() -> None:
    result = build_requirements(
        PairFacts(from_column="screening", stage_id=5, screening_stage_id=4),
        "verified",
    )
    assert _keys(result) == [
        "screening_sheet",
        "candidate_rate",
        *MINIMUM_KEYS,
        "recommendation_card",
    ]
    sheet = _item(result, "screening_sheet")
    assert sheet["status"] == "missing" and sheet["blocking"] is True
    assert sheet["action"] == {
        "kind": "open_screening",
        "label": "Otwórz screening",
        "stage_id": 4,
    }
    assert _item(result, "candidate_rate")["action"]["kind"] == "set_candidate_rate"
    for key in MINIMUM_KEYS:
        item = _item(result, key)
        assert item["status"] == "missing" and item["blocking"] is True
        assert item["action"]["kind"] == "open_card"
    assert _item(result, "recommendation")["label"] == "Dlaczego ten kandydat"
    assert _item(result, "recommendation_card")["blocking"] is False
    assert result["primary"]["kind"] == "blocked"


def test_skipped_columns_add_up() -> None:
    result = build_requirements(PairFacts(from_column="new", stage_id=1), "cv_qc")
    assert result["skipped_columns"] == ["screening", "verified"]
    assert _keys(result) == [
        "screening_sheet",
        "candidate_rate",
        *MINIMUM_KEYS,
        "recommendation_card",
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
    # 14.10.2026: sekcji „Czeka na Ciebie” z przeglądami DL-a już nie ma —
    # zdanie mówi, gdzie osoba czeka naprawdę.
    assert "Czeka na Ciebie" not in result["owner_note"]
    assert "„QC CV”" in result["owner_note"]


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
    # Okno stawki pyta o nią w samym ruchu — brak nie blokuje przycisku.
    assert rate["status"] == "waiting" and rate["blocking"] is False
    assert rate["action"]["kind"] == "set_client_rate"
    assert no_rate["primary"]["kind"] == "move"

    ready = build_requirements(
        replace(base, qc_status="overridden", client_rate=True), "cv_sent"
    )
    assert ready["primary"] == {"kind": "move", "label": "Przesuń na „CV wysłane”"}


def test_nordea_recruiter_hands_over_to_the_delivery_lead() -> None:
    """13.10.2026: do kolejki Cpro wkłada Delivery Lead po akceptacji —
    rekruter przekazuje osobę DL-owi jak u innych klientów."""
    facts = replace(
        VERIFIED_READY,
        from_column="cv_qc",
        company_cv=True,
        qc_status="passed",
        nordea=True,
        cpro_stage_def_id=44,
        qc_stage_def_id=41,
        cpro_sender_name="Kinga Sordyl",
    )
    result = build_requirements(facts, "cv_sent")
    assert result["primary"] == {
        "kind": "hand_to_dl",
        "label": "Przekaż Delivery Leadowi",
        # Osoba już stoi w „QC CV” — przekazanie to sam ten stan.
        "target_stage_def_id": None,
    }
    assert "dl_acceptance" in _keys(result)
    assert "client_rate" not in _keys(result)
    assert "Kinga Sordyl" in result["owner_note"]
    # Ze „Zweryfikowanego” przekazanie = ruch na etap QC CV szablonu, a wynik
    # QC (liczony dopiero w „QC CV”) nie blokuje przekazania.
    from_verified = build_requirements(
        replace(facts, from_column="verified", qc_status="unchecked"), "cv_sent"
    )
    assert from_verified["primary"]["kind"] == "hand_to_dl"
    assert from_verified["primary"]["target_stage_def_id"] == 41


def test_nordea_delivery_lead_accepts_to_the_cpro_queue() -> None:
    facts = replace(
        VERIFIED_READY,
        from_column="cv_qc",
        company_cv=True,
        qc_status="passed",
        nordea=True,
        cpro_stage_def_id=44,
        cpro_sender_name="Kinga Sordyl",
        is_client_sender=True,
    )
    result = build_requirements(facts, "cv_sent")
    assert result["primary"] == {
        "kind": "hand_to_cpro",
        "label": "Przejrzyj i zaakceptuj do Cpro",
        "target_stage_def_id": 44,
    }
    rate = _item(result, "client_rate")
    assert rate["label"] == "Stawka do Cpro" and rate["blocking"] is False
    assert rate["action"]["kind"] == "set_client_rate"
    assert "Kinga Sordyl" in result["owner_note"]
    # QC blokuje akceptację do Cpro.
    failed = build_requirements(replace(facts, qc_status="failed"), "cv_sent")
    assert failed["primary"]["kind"] == "blocked"


def test_nordea_delivery_lead_before_qc_moves_the_card_to_qc_first() -> None:
    """Przegląd i akceptacja do Cpro są w „QC CV” — z wcześniejszej kolumny
    Delivery Lead dostaje ruch do „QC CV”, nie goły ruch do kolejki (przegląd
    kodu 13.10.2026: front nie otwierał przeglądu i serwer dawał 422)."""
    facts = replace(
        VERIFIED_READY,
        from_column="verified",
        company_cv=True,
        qc_status="passed",
        nordea=True,
        cpro_stage_def_id=44,
        qc_stage_def_id=41,
        cpro_sender_name="Kinga Sordyl",
        is_client_sender=True,
    )
    result = build_requirements(facts, "cv_sent")
    assert result["primary"] == {
        "kind": "hand_to_dl",
        "label": "Przenieś do „QC CV” do akceptacji",
        "target_stage_def_id": 41,
    }


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


@pytest.mark.parametrize("qc_status", ["unchecked", "failed"])
def test_cpro_queue_upload_is_not_blocked_by_qc(qc_status: str) -> None:
    """Audyt 25.09.2026: serwer przy „✓ Wrzucone" QC nie liczy (osoba weszła
    do kolejki po QC albo po przeglądzie DZ), więc okno nie może blokować."""
    facts = replace(
        VERIFIED_READY,
        from_column="cv_qc",
        qc_status=qc_status,
        nordea=True,
        on_cpro_stage=True,
        can_send_to_cpro=True,
        cpro_sender_name="Kinga Sordyl",
    )
    result = build_requirements(facts, "cv_sent")
    qc_item = _item(result, "cv_qc")
    assert qc_item["blocking"] is False and qc_item["status"] == "ok"
    assert "cpro_upload" in _keys(result)
    assert result["primary"] == {
        "kind": "move",
        "label": "Przesuń na „Wysłane do Cpro”",
    }
    # Przed kolejką Cpro QC nadal blokuje akceptację Delivery Leada.
    before = build_requirements(
        replace(facts, on_cpro_stage=False, is_client_sender=True), "cv_sent"
    )
    assert _item(before, "cv_qc")["blocking"] is True
    assert before["primary"]["kind"] == "blocked"


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
        seed_entry_row,
    )
    from app.core.config import settings

    limiter.enabled = False
    world = await _seed_world()
    await seed_entry_row(world["candidate_id"], world["job_id"])
    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", "")
    # Okno ruchu pokazuje bramkę QC tylko przy włączonym QC (R9-V2-6);
    # conftest wyłącza je dla wszystkich testów.
    monkeypatch.setattr(settings, "CV_QC_GATE_ENABLED", True)
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


def test_recommendation_card_gaps_are_listed_but_never_block() -> None:
    """0413: braki karty to podpowiedź — Delivery Lead zobaczy je przed wysłaniem."""
    ready = replace(VERIFIED_READY, from_column="screening")
    empty = _item(build_requirements(ready, "verified"), "recommendation_card")
    assert empty["status"] == "missing" and empty["blocking"] is False
    # 09.10.2026: ekran nie używa nazwy „karta rekomendacji”.
    assert empty["label"] == "Warunki i ocena"
    assert empty["detail"] == "jeszcze nic nie wpisano"
    assert empty["action"] == {
        "kind": "open_card",
        "label": "Uzupełnij w screeningu",
        "stage_id": 11,
    }
    assert build_requirements(ready, "verified")["primary"]["kind"] == "move"

    partial = _item(
        build_requirements(
            replace(ready, card_exists=True, card_missing=("Angielski", "Motywacja")),
            "verified",
        ),
        "recommendation_card",
    )
    assert partial["status"] == "missing"
    assert partial["detail"] == "brakuje: Angielski, Motywacja"

    complete = _item(
        build_requirements(replace(ready, card_exists=True), "verified"),
        "recommendation_card",
    )
    assert complete["status"] == "ok" and complete["action"] is None


def test_card_facts_are_not_reported_as_unknown() -> None:
    """Test na produkcji 03.10.2026: karta miała stawkę i dostępność, a okno
    „Przesuń dalej” mówiło „brak stawki” i „nie wiemy, od kiedy może zacząć”."""
    facts = PairFacts(
        from_column="screening",
        stage_id=5,
        screening_done=True,
        card_exists=True,
        card_availability=True,
        card_rate_hourly=130.0,
    )
    result = build_requirements(facts, "verified")

    availability = _item(result, "availability")
    assert availability["status"] == "ok"
    assert availability["detail"] == "jest w screeningu"

    # Stawka z karty nie zastępuje stawki etapu — okno stawki ją podpowiada.
    rate = _item(result, "candidate_rate")
    assert rate["status"] == "missing"
    assert rate["detail"] == "z notatki: 130 zł/h — potwierdź w oknie stawki"
    assert rate["action"]["kind"] == "set_candidate_rate"

    without_card = build_requirements(replace(facts, card_rate_hourly=None), "verified")
    assert (
        _item(without_card, "candidate_rate")["detail"]
        == "brak stawki w profilu i w procesie"
    )


def test_answers_written_in_the_note_count_as_the_screening_sheet() -> None:
    facts = PairFacts(
        from_column="screening",
        stage_id=5,
        candidate_rate=True,
        card_exists=True,
        card_answers=True,
    )
    sheet = _item(build_requirements(facts, "verified"), "screening_sheet")
    assert sheet["status"] == "ok"
    assert sheet["detail"] == "odpowiedzi są w notatce rekrutera"
    assert sheet["action"] is None


# ── Rekrutacja bez pytań screeningowych (12.10.2026) ─────────────────────────

NO_QUESTIONS = PairFacts(
    from_column="screening",
    stage_id=5,
    candidate_rate=True,
    has_screening_questions=False,
    availability_known=True,
    card_present=frozenset({"location", "work_mode"}),
)


def test_job_without_questions_asks_for_the_assessment_instead_of_the_sheet() -> None:
    """Zgłoszenie 12.10.2026: rekrutacja z Traffita bez Profilu Championa nie
    ma pytań, więc arkusza nie da się zapisać, a okno kazało go uzupełnić."""
    result = build_requirements(NO_QUESTIONS, "verified")
    # „Dlaczego ten kandydat” stoi raz — jako wymaganie rozmowy.
    assert _keys(result) == [
        "why_candidate",
        "candidate_rate",
        "location",
        "work_mode",
        "availability",
        "recommendation_card",
    ]
    item = _item(result, "why_candidate")
    assert item["label"] == "Dlaczego ten kandydat"
    assert item["status"] == "missing" and item["blocking"] is True
    assert "nie ma pytań screeningowych" in item["detail"]
    assert item["action"] == {
        "kind": "open_card",
        "label": "Uzupełnij w screeningu",
        "stage_id": 5,
    }
    assert result["primary"] == {
        "kind": "blocked",
        "label": "Najpierw uzupełnij: Dlaczego ten kandydat",
    }


def test_job_without_questions_moves_once_the_assessment_is_written() -> None:
    facts = replace(
        NO_QUESTIONS,
        card_exists=True,
        card_recommendation=True,
        card_present=NO_QUESTIONS.card_present | {"recommendation"},
    )
    result = build_requirements(facts, "verified")
    item = _item(result, "why_candidate")
    assert item["status"] == "ok" and item["action"] is None
    assert result["primary"] == {"kind": "move", "label": "Przesuń na „Zweryfikowany”"}


def test_assessment_does_not_replace_the_sheet_when_the_job_has_questions() -> None:
    facts = PairFacts(
        from_column="screening",
        stage_id=5,
        candidate_rate=True,
        card_exists=True,
        card_recommendation=True,
    )
    result = build_requirements(facts, "verified")
    assert _item(result, "screening_sheet")["status"] == "missing"
    assert result["primary"]["kind"] == "blocked"


@pytest.mark.parametrize(
    ("facts", "expected"),
    [
        (PairFacts(from_column="new"), ("screening_sheet", False)),
        (PairFacts(from_column="new", screening_done=True), ("screening_sheet", True)),
        (PairFacts(from_column="new", card_answers=True), ("screening_sheet", True)),
        (
            PairFacts(from_column="new", card_recommendation=True),
            ("screening_sheet", False),
        ),
        (NO_QUESTIONS, ("why_candidate", False)),
        (replace(NO_QUESTIONS, card_recommendation=True), ("why_candidate", True)),
        # Arkusz zapisany, zanim pytania zniknęły z profilu, dalej się liczy.
        (replace(NO_QUESTIONS, screening_done=True), ("why_candidate", True)),
        (replace(NO_QUESTIONS, card_answers=True), ("why_candidate", True)),
    ],
)
def test_screening_requirement(facts: PairFacts, expected: tuple[str, bool]) -> None:
    assert screening_requirement(facts) == expected


# ── Karta Tablicy i „Czeka na Ciebie” w rekrutacji bez pytań (13.10.2026) ────

CARD_WITH_ASSESSMENT = {"missing": ["rate", "motivation"], "answers": 0}
CARD_WITHOUT_ASSESSMENT = {"missing": ["recommendation", "motivation"], "answers": 0}


def test_card_in_a_job_with_questions_keeps_the_sheet_rule() -> None:
    """Rekrutacja z pytaniami: karta mówi o arkuszu jak dotąd — ocena go nie
    zastępuje, a pole wymagania zostaje puste."""
    assert card_screening_state(
        has_questions=True, sheet=False, card=CARD_WITH_ASSESSMENT
    ) == (False, None)
    assert card_screening_state(has_questions=True, sheet=True, card=None) == (
        True,
        None,
    )


@pytest.mark.parametrize(
    ("sheet", "card", "done"),
    [
        (False, None, False),
        (False, CARD_WITHOUT_ASSESSMENT, False),
        (False, CARD_WITH_ASSESSMENT, True),
        # Odpowiedzi zapisane w notatce i arkusz sprzed usunięcia pytań też
        # spełniają bramkę — karta nie może wtedy prosić o ocenę.
        (False, {"missing": ["recommendation"], "answers": 2}, True),
        (True, None, True),
    ],
)
def test_card_in_a_job_without_questions_follows_the_gate(
    sheet: bool, card: dict | None, done: bool
) -> None:
    """Zgłoszenie 13.10.2026: po poprawce bramki karta w „Screeningu” dalej
    pisała „Uzupełnij arkusz screeningu”, choć arkusza tam nie ma."""
    assert card_screening_state(has_questions=False, sheet=sheet, card=card) == (
        done,
        "why_candidate",
    )


# ── Minimum dla Delivery Leada (decyzja Artura 21.10.2026) ──────────────────


def test_minimum_blocks_until_every_field_is_written() -> None:
    """Zgłoszenie DL 21.10: rekomendacje bez lokalizacji i trybu pracy."""
    facts = replace(VERIFIED_READY, from_column="screening", card_present=frozenset())
    assert minimum_missing(facts) == ["location", "work_mode", "recommendation"]
    result = build_requirements(facts, "verified")
    assert result["primary"] == {
        "kind": "blocked",
        "label": "Najpierw uzupełnij: Lokalizacja",
    }
    ready = build_requirements(
        replace(VERIFIED_READY, from_column="screening"), "verified"
    )
    assert ready["primary"]["kind"] == "move"
    assert all(_item(ready, key)["status"] == "ok" for key in MINIMUM_KEYS)


def test_availability_from_the_profile_or_the_card_counts() -> None:
    base = replace(
        VERIFIED_READY,
        from_column="screening",
        availability_known=False,
        card_availability=False,
    )
    assert "availability" in minimum_missing(base)
    assert "availability" not in minimum_missing(replace(base, card_availability=True))
    assert "availability" not in minimum_missing(replace(base, availability_known=True))


def test_switch_off_restores_the_old_window() -> None:
    facts = replace(
        VERIFIED_READY,
        from_column="screening",
        card_present=frozenset(),
        minimum_enabled=False,
    )
    assert minimum_missing(facts) == []
    result = build_requirements(facts, "verified")
    assert _keys(result) == [
        "screening_sheet",
        "candidate_rate",
        "availability",
        "recommendation_card",
    ]
    assert result["primary"]["kind"] == "move"


def test_client_extra_fields_join_the_minimum_with_the_client_name() -> None:
    facts = replace(
        VERIFIED_READY,
        from_column="screening",
        client_required_fields=("motivation", "location"),
        client_name="Bank A",
    )
    assert required_card_fields(facts) == (*MINIMUM_KEYS, "motivation")
    result = build_requirements(facts, "verified")
    item = _item(result, "motivation")
    assert item["label"] == "Motywacja"
    assert item["detail"] == "wymaga Bank A" and item["blocking"] is True
    done = replace(facts, card_present=facts.card_present | {"motivation"})
    assert minimum_missing(done) == []


def test_job_without_questions_still_needs_why_when_note_answers_met_the_talk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Przegląd 21.10.2026: odpowiedzi z notatki spełniają `why_candidate` bez
    oceny — minimum dalej wymaga „Dlaczego ten kandydat”, raz."""
    facts = replace(
        NO_QUESTIONS,
        card_answers=True,
        card_present=frozenset({"location", "work_mode"}),
    )
    assert screening_requirement(facts) == ("why_candidate", True)
    assert minimum_missing(facts) == ["recommendation"]
    result = build_requirements(facts, "verified")
    assert _item(result, "why_candidate")["status"] == "ok"
    assert _item(result, "recommendation")["status"] == "missing"
    assert result["primary"]["kind"] == "blocked"
    # Bez odpowiedzi — „Dlaczego” stoi tylko jako wymaganie rozmowy.
    bare = replace(facts, card_answers=False)
    assert minimum_missing(bare) == []
    assert "recommendation" not in _keys(build_requirements(bare, "verified"))
    # Tablica: ta sama reguła z flagi `screening_done` karty.
    from app.core.config import settings
    from app.services.move_requirements import board_minimum_missing

    monkeypatch.setattr(settings, "VERIFIED_MINIMUM_FIELDS_ENABLED", True)
    card = {"present": ["location", "work_mode"], "availability": False}
    assert board_minimum_missing(
        card, has_questions=False, availability_known=True, screening_met=True
    ) == ["recommendation"]
    assert (
        board_minimum_missing(
            card, has_questions=False, availability_known=True, screening_met=False
        )
        == []
    )
