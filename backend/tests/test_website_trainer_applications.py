"""„Zostań trenerem” ze strony B2B Network (0806). Dane fikcyjne — repo jest publiczne.

Kontrakt strony: ``POST /api/public/website-trainer-applications``, multipart,
``Authorization: Bearer`` (ten sam token co aplikacje), 2xx = przyjęte.
Pokrywa: token, walidację pól (tematy tylko z listy, link http(s), jedna linia),
ponowne wysłanie z tego samego adresu, dopasowanie kontraktu konsultanta, listę
„Kandydaci na trenerów” i statusy TCM z odmowami oraz zgodność tematów z panelem
konsultanta i ze stroną.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

import pytest
from sqlalchemy import func, select, update

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.website_intake import MarketTrainerApplication
from app.models.user import UserRole
from app.services import website_intake_schema as schema
from tests.care_announcements_seed import headers, make_user
from tests.consultant_portal_seed import make_person

URL = "/api/public/website-trainer-applications"
STAFF = "/api/trainings/market-applications"
TOKEN = "test-website-applications-token-not-a-secret"
CONSENT = (
    "Wyrażam zgodę na przetwarzanie moich danych osobowych przez B2B.NET S.A. "
    "w celu rozpatrzenia zgłoszenia i współpracy przy szkoleniach."
)
_REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def token(monkeypatch) -> None:
    monkeypatch.setattr(settings, "WEBSITE_APPLICATIONS_TOKEN", TOKEN)


def _auth(value: str = TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {value}"}


def _email(label: str) -> str:
    return f"trener-{label}-{uuid.uuid4().hex[:8]}@example.com"


def _form(email: str, **extra) -> dict:
    return {
        "full_name": "Anna Przykładowa",
        "email": email,
        "linkedin": "https://linkedin.com/in/anna-przykladowa",
        "topic": ["Kubernetes", "Python"],
        "other_topic": "Rust w systemach wbudowanych",
        "first_training": "Kafka od środka",
        "experience": "Prowadzę warsztaty od 2019.\nWystąpienia na konferencjach.",
        "sample_url": "https://example.com/program.pdf",
        "consent": [CONSENT],
        **extra,
    }


async def _row(email: str) -> MarketTrainerApplication | None:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(MarketTrainerApplication).where(
                func.lower(MarketTrainerApplication.email) == email.lower()
            )
        )


async def test_application_is_saved_with_literal_consent(app_client, token) -> None:
    email = _email("nowe")

    resp = await app_client.post(URL, data=_form(email), headers=_auth())

    assert resp.status_code == 201, resp.text
    assert resp.json() == {"ok": True, "status": "received"}
    row = await _row(email)
    assert row is not None
    assert (row.full_name, row.status, row.submissions) == (
        "Anna Przykładowa",
        "new",
        1,
    )
    assert row.topics == ["Kubernetes", "Python"]
    assert row.other_topic == "Rust w systemach wbudowanych"
    assert row.first_training == "Kafka od środka"
    assert row.experience.startswith("Prowadzę warsztaty")
    assert row.sample_url == "https://example.com/program.pdf"
    assert row.contract_id is None
    assert [c["text"] for c in row.consents] == [CONSENT]
    assert len(row.consents[0]["sha256"]) == 64


@pytest.mark.parametrize(
    "auth",
    [None, "Bearer zly-token", "Basic " + TOKEN, "Bearer "],
)
async def test_wrong_or_missing_token_is_refused(app_client, token, auth) -> None:
    email = _email("token")
    hdrs = {} if auth is None else {"Authorization": auth}

    resp = await app_client.post(URL, data=_form(email), headers=hdrs)

    assert resp.status_code == 401
    assert await _row(email) is None


async def test_empty_server_token_refuses_everything(app_client, monkeypatch) -> None:
    monkeypatch.setattr(settings, "WEBSITE_APPLICATIONS_TOKEN", "")
    email = _email("pusty")

    resp = await app_client.post(URL, data=_form(email), headers=_auth(""))

    assert resp.status_code == 401
    assert await _row(email) is None


@pytest.mark.parametrize(
    ("change", "field"),
    [
        ({"topic": ["Kubernetes", "Haskell"]}, "topic"),
        ({"topic": ["Python", "Python"]}, "topic"),
        ({"topic": [], "other_topic": ""}, "topic"),
        ({"sample_url": "javascript:alert(1)"}, "sample_url"),
        ({"sample_url": "example.com/bez-schematu"}, "sample_url"),
        ({"full_name": "Anna\nUdawany wiersz: tak"}, "full_name"),
        ({"full_name": "A" * (schema.NAME_MAX + 1)}, "full_name"),
        ({"first_training": ""}, "first_training"),
        ({"experience": "   "}, "experience"),
        ({"email": "to-nie-adres"}, "email"),
        ({"consent": []}, "consent"),
    ],
)
async def test_invalid_fields_get_422_and_nothing_is_saved(
    app_client, token, change, field
) -> None:
    email = _email("pole")
    form = {**_form(email), **change}

    resp = await app_client.post(URL, data=form, headers=_auth())

    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"][0]["loc"] == ["body", field]
    assert await _row(email) is None


async def test_file_upload_is_refused(app_client, token) -> None:
    """Próbka idzie linkiem; plik od osoby z internetu nie ma tu skanu."""
    email = _email("plik")

    resp = await app_client.post(
        URL,
        data=_form(email),
        files={"sample": ("program.pdf", b"%PDF-1.4", "application/pdf")},
        headers=_auth(),
    )

    assert resp.status_code == 400
    assert await _row(email) is None


async def test_resubmission_updates_the_same_row_and_reopens_rejected(
    app_client, token
) -> None:
    email = _email("powtorka")
    assert (
        await app_client.post(URL, data=_form(email), headers=_auth())
    ).status_code == 201
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(MarketTrainerApplication)
            .where(func.lower(MarketTrainerApplication.email) == email)
            .values(status="rejected", status_note="Temat już mamy.")
        )
        await db.commit()

    again = await app_client.post(
        URL,
        data=_form(email.upper(), topic=["AWS"], first_training="AWS od zera"),
        headers=_auth(),
    )

    assert again.status_code == 201
    assert again.json() == {"ok": True, "status": "received"}
    async with AsyncSessionLocal() as db:
        rows = list(
            await db.scalars(
                select(MarketTrainerApplication).where(
                    func.lower(MarketTrainerApplication.email) == email
                )
            )
        )
    assert len(rows) == 1
    row = rows[0]
    assert (row.submissions, row.status, row.topics) == (2, "new", ["AWS"])
    assert row.first_training == "AWS od zera"
    # Notatka TCM zostaje — widać, dlaczego wcześniej odrzucił.
    assert row.status_note == "Temat już mamy."


async def test_live_consultant_is_matched_by_contract_email(app_client, token) -> None:
    person = await make_person(activated=False)

    resp = await app_client.post(URL, data=_form(person.email), headers=_auth())

    assert resp.status_code == 201
    row = await _row(person.email)
    assert row is not None and row.contract_id == person.contract_id


async def test_tcm_moves_application_through_statuses(app_client, token) -> None:
    email = _email("tcm")
    await app_client.post(URL, data=_form(email), headers=_auth())
    row = await _row(email)
    assert row is not None
    tcm = headers(await make_user(UserRole.talent_community_manager))

    listed = await app_client.get(STAFF, headers=tcm, params={"status": "new"})
    assert listed.status_code == 200
    assert email in {a["email"] for a in listed.json()["applications"]}

    skip = await app_client.post(
        f"{STAFF}/{row.id}/status", headers=tcm, json={"status": "accepted"}
    )
    assert skip.status_code == 409

    talk = await app_client.post(
        f"{STAFF}/{row.id}/status",
        headers=tcm,
        json={"status": "interview", "note": " Rozmowa we wtorek. "},
    )
    assert talk.status_code == 200, talk.text
    assert talk.json()["application"]["status_note"] == "Rozmowa we wtorek."

    base = await app_client.post(
        f"{STAFF}/{row.id}/status",
        headers=tcm,
        json={"status": "accepted", "note": "  "},
    )
    assert base.status_code == 200
    assert base.json()["application"]["status"] == "accepted"
    # Przejście bez notatki (puste pole okna) nie kasuje wcześniejszej notatki.
    assert base.json()["application"]["status_note"] == "Rozmowa we wtorek."
    saved = await _row(email)
    assert saved is not None and saved.status_changed_by is not None

    missing = await app_client.post(
        f"{STAFF}/999999999/status", headers=tcm, json={"status": "interview"}
    )
    assert missing.status_code == 404

    unknown = await app_client.post(
        f"{STAFF}/{row.id}/status", headers=tcm, json={"status": "hired"}
    )
    assert unknown.status_code == 422


@pytest.mark.parametrize(
    "role", [UserRole.recruiter, UserRole.delivery_lead, UserRole.finance]
)
async def test_only_tcm_and_admin_see_and_decide(app_client, token, role) -> None:
    email = _email("rola")
    await app_client.post(URL, data=_form(email), headers=_auth())
    row = await _row(email)
    assert row is not None
    other = headers(await make_user(role))

    assert (await app_client.get(STAFF, headers=other)).status_code == 403
    decide = await app_client.post(
        f"{STAFF}/{row.id}/status", headers=other, json={"status": "interview"}
    )
    assert decide.status_code == 403
    assert (await _row(email)).status == "new"


def _ts_topics(path: Path) -> tuple[str, ...]:
    source = path.read_text(encoding="utf-8")
    match = re.search(r"TRAINER_TOPICS\s*=\s*\[(.*?)\]", source, re.S)
    assert match, f"brak TRAINER_TOPICS w {path}"
    return tuple(re.findall(r'"([^"]+)"', match.group(1)))


def test_topics_match_consultant_panel() -> None:
    """Zgłoszenie z panelu i ze strony mają ten sam słownik tematów."""
    panel = _REPO / "frontend/src/components/consultant-portal/PanelScreens.tsx"
    assert _ts_topics(panel) == schema.TRAINER_TOPICS
