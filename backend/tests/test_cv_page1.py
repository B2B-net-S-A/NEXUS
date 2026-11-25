"""„Najmocniejszy wynik” na stronie 1 „Nowego CV” z edytora (22.11.2026).

- PATCH …/cv/page1 zapisuje zdanie rekrutera albo wybór z listy sprawdzonych
  wyników w `page1_extras`, nie dotyka treści szkicu,
- wybór z listy czyści wpisane zdanie, gdy edytor wyśle `result_text: null`,
- niesprawdzony wynik, pusty żądanie i za długie zdanie — 422,
- zatwierdzona wersja, CV po „CV wysłane” i wyłączona flaga — 409,
- GET …/cv/branded niesie `page1_extras` (edytor pokazuje „Inny wynik (N)”).
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.activity import Activity
from app.models.candidate_stage_cv import CandidateStageCV
from tests.test_candidate_stage_cv_branded import _seed_draft, _seed_full_stage

HTML = (
    "<h1>Tester – Jan Przykładowy</h1><hr>"
    '<h2 data-cv-section="why_points">Dlaczego nasz kandydat?</h2>'
    "<ul><li><p>Ponad 8 lat w QA.</p></li></ul>"
    '<p data-cv-section="rodo">Wyrażam zgodę na przetwarzanie danych.</p>'
)
RESULTS = [
    {
        "text": "Skrócił testy regresji o 40%.",
        "quote": "o 40%",
        "company": "Firma A",
        "verified": True,
    },
    {"text": "Wymyślony wynik.", "quote": "", "company": "Firma B", "verified": False},
    {
        "text": "Wdrożył 120 testów API.",
        "quote": "120 testów",
        "company": "Firma C",
        "verified": True,
    },
]


@pytest.fixture
def flag_on(monkeypatch):
    monkeypatch.setattr(settings, "CV_NEW_LAYOUT_ENABLED", True)


async def _csv(sid: int) -> CandidateStageCV:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(CandidateStageCV).where(CandidateStageCV.candidate_stage_id == sid)
        )


async def _set(sid: int, **fields) -> None:
    async with AsyncSessionLocal() as db:
        csv = await db.scalar(
            select(CandidateStageCV).where(CandidateStageCV.candidate_stage_id == sid)
        )
        for key, value in fields.items():
            setattr(csv, key, value)
        await db.commit()


async def _draft(extras: dict | None = None) -> int:
    sid, _, _ = await _seed_full_stage()
    await _seed_draft(sid, HTML)
    await _set(sid, cv_layout="new", page1_extras=extras)
    return sid


def _url(sid: int) -> str:
    return f"/api/candidates/stages/{sid}/cv/page1"


@pytest.mark.asyncio
async def test_typed_result_is_saved_without_touching_the_draft(
    app_client: AsyncClient, app_auth_headers: dict, flag_on
):
    sid = await _draft({"results": RESULTS, "why": ["zostaje"]})
    before = await _csv(sid)
    res = await app_client.patch(
        _url(sid),
        json={"result_text": "  Obniżył   liczbę defektów o 30%.  "},
        headers=app_auth_headers,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["page1_extras"]["result_text"] == "Obniżył liczbę defektów o 30%."
    after = await _csv(sid)
    assert after.page1_extras["results"] == RESULTS
    assert after.page1_extras["why"] == ["zostaje"]
    assert after.branded_draft_html == before.branded_draft_html
    assert after.edit_revision == before.edit_revision
    async with AsyncSessionLocal() as db:
        logged = await db.scalar(
            select(Activity).where(
                Activity.entity_type == "candidate_stage_cv",
                Activity.entity_id == after.id,
                Activity.action == "cv_page1_changed",
            )
        )
    assert logged is not None
    assert logged.details["result_text"] is True
    # Historia zdarzeń nie niesie treści zdania.
    assert "defektów" not in str(logged.details)


@pytest.mark.asyncio
async def test_highlight_is_saved_and_logged_without_its_text(
    app_client: AsyncClient, app_auth_headers: dict, flag_on
):
    """Wyróżnik pod nazwiskiem (25.11.2026): wpis rekrutera w dodatkach strony 1."""
    sid = await _draft({"results": RESULTS, "why": ["zostaje"]})
    res = await app_client.patch(
        _url(sid),
        json={
            "highlight": {
                "mode": "custom",
                "label": "Wyróżnienie",
                "token": "2015",
                "text": "Best IT Project Manager w klastrze bałtyckim.",
            }
        },
        headers=app_auth_headers,
    )
    assert res.status_code == 200, res.text
    extras = (await _csv(sid)).page1_extras
    assert extras["highlight"]["mode"] == "custom"
    assert extras["highlight"]["token"] == "2015"
    assert extras["why"] == ["zostaje"]
    async with AsyncSessionLocal() as db:
        logged = await db.scalar(
            select(Activity)
            .where(
                Activity.entity_type == "candidate_stage_cv",
                Activity.action == "cv_page1_changed",
            )
            .order_by(Activity.id.desc())
        )
    assert logged.details["highlight"] == "custom"
    assert "Best IT" not in str(logged.details)
    empty = await app_client.patch(
        _url(sid),
        json={"highlight": {"mode": "custom", "label": "Wyróżnienie"}},
        headers=app_auth_headers,
    )
    assert empty.status_code == 422


@pytest.mark.asyncio
async def test_picking_a_verified_result_clears_the_typed_one(
    app_client: AsyncClient, app_auth_headers: dict, flag_on
):
    sid = await _draft({"results": RESULTS, "result_text": "Wpisane wcześniej."})
    res = await app_client.patch(
        _url(sid),
        json={"result_index": 2, "result_text": None},
        headers=app_auth_headers,
    )
    assert res.status_code == 200, res.text
    extras = (await _csv(sid)).page1_extras
    assert extras["result_index"] == 2
    assert "result_text" not in extras


@pytest.mark.asyncio
async def test_empty_text_removes_the_typed_result(
    app_client: AsyncClient, app_auth_headers: dict, flag_on
):
    sid = await _draft({"result_text": "Wpisane wcześniej."})
    res = await app_client.patch(
        _url(sid), json={"result_text": "   "}, headers=app_auth_headers
    )
    assert res.status_code == 200, res.text
    assert "result_text" not in (await _csv(sid)).page1_extras


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"result_index": 1},  # niesprawdzony wynik modelu nie trafia na stronę 1
        {"result_index": 7},
        {"result_index": -1},
        {"result_text": "x" * 401},
    ],
)
async def test_bad_requests_are_refused(
    app_client: AsyncClient, app_auth_headers: dict, flag_on, payload
):
    sid = await _draft({"results": RESULTS})
    res = await app_client.patch(_url(sid), json=payload, headers=app_auth_headers)
    assert res.status_code == 422, res.text
    assert (await _csv(sid)).page1_extras == {"results": RESULTS}


@pytest.mark.asyncio
async def test_finalized_version_is_refused(
    app_client: AsyncClient, app_auth_headers: dict, flag_on
):
    sid = await _draft()
    await _set(sid, branded_status="finalized")
    res = await app_client.patch(
        _url(sid), json={"result_text": "Nowy wynik."}, headers=app_auth_headers
    )
    assert res.status_code == 409
    assert "nowy szkic" in res.json()["detail"]
    assert (await _csv(sid)).page1_extras is None


@pytest.mark.asyncio
async def test_after_send_is_refused(
    app_client: AsyncClient, app_auth_headers: dict, flag_on, monkeypatch
):
    from app.services import new_cv_company_cv

    async def sent(db, csv):
        return True

    monkeypatch.setattr(new_cv_company_cv, "locked_after_send", sent)
    sid = await _draft()
    res = await app_client.patch(
        _url(sid), json={"result_text": "Nowy wynik."}, headers=app_auth_headers
    )
    assert res.status_code == 409
    assert "u klienta" in res.json()["detail"]


@pytest.mark.asyncio
async def test_flag_off_and_empty_stage_are_refused(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    monkeypatch.setattr(settings, "CV_NEW_LAYOUT_ENABLED", False)
    sid = await _draft()
    res = await app_client.patch(
        _url(sid), json={"result_text": "Nowy wynik."}, headers=app_auth_headers
    )
    assert res.status_code == 409
    monkeypatch.setattr(settings, "CV_NEW_LAYOUT_ENABLED", True)
    empty, _, _ = await _seed_full_stage()
    await app_client.get(
        f"/api/candidates/stages/{empty}/cv/branded", headers=app_auth_headers
    )
    res = await app_client.patch(
        _url(empty), json={"result_text": "Nowy wynik."}, headers=app_auth_headers
    )
    assert res.status_code in (404, 409)


@pytest.mark.asyncio
async def test_branded_state_carries_page1_extras(
    app_client: AsyncClient, app_auth_headers: dict, flag_on
):
    sid = await _draft({"results": RESULTS, "result_index": 0})
    got = await app_client.get(
        f"/api/candidates/stages/{sid}/cv/branded", headers=app_auth_headers
    )
    assert got.status_code == 200
    assert got.json()["page1_extras"]["results"][0]["company"] == "Firma A"
    # szkic bez stanowisk — nie ma czego ostrzegać
    assert got.json()["new_layout_role_gaps"] is None


@pytest.mark.asyncio
async def test_branded_state_warns_about_roles_without_dates_or_company(
    app_client: AsyncClient, app_auth_headers: dict, flag_on
):
    """Decyzja Artura 25.11.2026: CV w obcym formacie (daty i „Nazwa firmy:” nad
    stanowiskiem) — Nowe CV gubi daty i firmy; karta i edytor ostrzegają."""
    sid, _, _ = await _seed_full_stage()
    await _seed_draft(
        sid,
        HTML
        + '<h2 data-cv-section="experience">DOŚWIADCZENIE</h2>'
        + "<p>12.2018 – obecnie<br><strong>Nazwa firmy: </strong>Amber</p>"
        + '<p data-cv-section="role"><strong>Tester</strong></p>',
    )
    await _set(sid, cv_layout="new")
    got = await app_client.get(
        f"/api/candidates/stages/{sid}/cv/branded", headers=app_auth_headers
    )
    assert got.status_code == 200
    assert got.json()["new_layout_role_gaps"] == {
        "without_dates": 1,
        "without_company": 1,
    }


def test_merge_rules_without_database():
    from fastapi import HTTPException

    from app.api.cv_page1 import Page1Update, _merged

    extras = {"results": RESULTS, "why": ["a"], "result_text": "stare"}
    picked = _merged(extras, Page1Update(result_index=0, result_text=None))
    assert picked == {"results": RESULTS, "why": ["a"], "result_index": 0}
    # Samo `result_index` nie czyści wpisanego zdania — edytor wysyła oba pola.
    assert _merged(extras, Page1Update(result_index=2))["result_text"] == "stare"
    assert _merged(None, Page1Update(result_text=" a\n b "))["result_text"] == "a b"
    assert "result_index" not in _merged(
        {"result_index": 1}, Page1Update(result_index=None)
    )
    with pytest.raises(HTTPException) as refused:
        _merged(extras, Page1Update(result_index=1))
    assert refused.value.status_code == 422
    with pytest.raises(HTTPException):
        _merged({"results": "nie lista"}, Page1Update(result_index=0))
