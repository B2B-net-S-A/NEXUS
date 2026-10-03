"""Stawka do klienta z wpisów Delivery Leada w notatkach (etap 8, 03.10.2026).

Reguła odczytu jest czysta (bez bazy); plan i zapis sprawdzamy przez trasę
admina. Dane wyłącznie fikcyjne.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.services.client_rate_notes import extract_client_rate

# ── bez bazy ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "content, expected",
    [
        ("Wyślijmy za 161 zł/h", "161.00"),
        ("<p>@Jan Testowy wyślijmy za 150</p>", "150.00"),
        ("wysyłamy za 145,5 zł", "145.50"),
        ("Wysłany za 85", "85.00"),
        ("wyślijmy po 120", "120.00"),
        ("Wyślijmy za 160 zł/h netto + VAT.", "160.00"),
        ("wyślijmy za 150 pln/godz", "150.00"),
    ],
)
def test_unambiguous_send_note_gives_the_hourly_rate(content: str, expected: str):
    assert extract_client_rate(content) == Decimal(expected)


@pytest.mark.parametrize(
    "content",
    [
        # Para kwot — nie wiadomo, która jest dla klienta.
        "150/110",
        "wyślijmy za 160, kandydat chce 140",
        # Sama liczba przy wzmiance — bez czasownika wysyłki.
        "@Jan Testowy 175",
        # Inna jednostka albo waluta.
        "wyślijmy za 1200 zł/dzień",
        "wyślijmy za 100 eur",
        "wyślijmy za 160 brutto",
        "wyślijmy za 160 GBP",
        "wyślijmy za 160 zł/mc",
        "wyślijmy za 160 zł/d",
        # Procent, tysiące i liczba z trzema miejscami po przecinku.
        "Wyślijmy za 150%",
        "Wyślijmy za 150 tys",
        "wysyłamy za 161,555",
        "wyślijmy za 150.000 zł",
        # Przeczenie, warunek, pytanie, wybór — to nie jest zapisana cena.
        "Nie wysyłamy za 160",
        "Jeśli klient zgodzi się, wyślijmy za 160",
        "wyślijmy za 160?",
        "wyślijmy za 160 albo 170",
        # Widełki.
        "wyślijmy za 150-160",
        # Termin, nie stawka; kwota spoza rozsądnego zakresu.
        "wyślij za 14 dni",
        "wyślijmy za 35",
        "",
        None,
    ],
)
def test_anything_ambiguous_stays_in_the_note(content):
    assert extract_client_rate(content) is None


# ── z bazą ───────────────────────────────────────────────────────────────────


async def _seed_pair(stages: list[tuple[str, str | None]], notes: list[str]) -> dict:
    """Para z wierszami etapów ``(etap, stawka do klienta)`` i notatkami DL."""
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.job import Job, JobStatus
    from app.models.note import Note
    from app.models.recruitment_pipeline import CandidateStage

    unique = uuid.uuid4().hex[:8]
    start = datetime.now(timezone.utc) - timedelta(days=30)
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Rate client {unique}")
        db.add(client)
        await db.flush()
        job = Job(
            title=f"Rate job {unique}", client_id=client.id, status=JobStatus.closed
        )
        candidate = Candidate(
            name="Tomasz", lastname=f"Stawkowy{unique}", email=f"rate-{unique}@x.com"
        )
        db.add_all([job, candidate])
        await db.flush()
        stage_ids = []
        for index, (stage, rate) in enumerate(stages):
            row = CandidateStage(
                candidate_id=candidate.id,
                job_id=job.id,
                stage=stage,
                moved_at=start + timedelta(days=index),
                client_rate_value=Decimal(rate) if rate else None,
                client_rate_unit="hourly" if rate else None,
                client_rate_currency="PLN" if rate else None,
            )
            db.add(row)
            await db.flush()
            stage_ids.append(row.id)
        for index, content in enumerate(notes):
            db.add(
                Note(
                    candidate_id=candidate.id,
                    job_id=job.id,
                    content=content,
                    created_at=start + timedelta(days=10 + index),
                )
            )
        await db.commit()
        return {"candidate_id": candidate.id, "job_id": job.id, "stages": stage_ids}


async def _rates(stage_ids: list[int]) -> dict[int, tuple]:
    from app.core.database import AsyncSessionLocal
    from app.models.recruitment_pipeline import CandidateStage

    async with AsyncSessionLocal() as db:
        rows = await db.execute(
            select(
                CandidateStage.id,
                CandidateStage.client_rate_value,
                CandidateStage.client_rate_unit,
                CandidateStage.client_rate_currency,
            ).where(CandidateStage.id.in_(stage_ids))
        )
        return {row.id: tuple(row)[1:] for row in rows.all()}


async def _setting(key: str) -> dict:
    from sqlalchemy import text

    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        value = await db.scalar(
            text("SELECT value FROM app_settings WHERE key = :key"), {"key": key}
        )
    return value if isinstance(value, dict) else {}


async def _dry_run(client: AsyncClient, headers: dict) -> dict:
    resp = await client.post("/api/admin/notes-insights/client-rates", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_dry_run_writes_nothing_and_apply_fills_only_empty_pairs(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    fillable = await _seed_pair(
        [("verified", None), ("cv_sent", None), ("client_interview", None)],
        ["Wyślijmy za 161 zł/h"],
    )
    has_rate = await _seed_pair([("cv_sent", "150.00")], ["Wyślijmy za 170 zł/h"])
    two_amounts = await _seed_pair(
        [("cv_sent", None)], ["Wyślijmy za 140", "Wyślijmy za 155"]
    )
    never_sent = await _seed_pair([("verified", None)], ["Wyślijmy za 130"])
    ambiguous = await _seed_pair([("cv_sent", None)], ["150/110"])
    # Czytelna cena i późniejszy wpis, którego nie da się odczytać — mógł ją
    # zmienić, więc para odpada.
    revised = await _seed_pair([("cv_sent", None)], ["Wyślijmy za 150", "160/130"])
    all_stages = [
        *fillable["stages"],
        *has_rate["stages"],
        *two_amounts["stages"],
        *never_sent["stages"],
        *ambiguous["stages"],
        *revised["stages"],
    ]
    before = await _rates(all_stages)

    report = await _dry_run(app_client, app_auth_headers)

    assert report["dry_run"] is True
    assert report["counts"]["to_fill"] >= 1
    # Próba niczego nie zapisuje.
    assert await _rates(all_stages) == before

    # Zapis bez liczby z próby albo z inną liczbą = odmowa i zero zmian.
    for params in ({"dry_run": "false"}, {"dry_run": "false", "expected": 0}):
        refused = await app_client.post(
            "/api/admin/notes-insights/client-rates",
            params=params,
            headers=app_auth_headers,
        )
        assert refused.status_code == 409, refused.text
    assert await _rates(all_stages) == before

    applied = await app_client.post(
        "/api/admin/notes-insights/client-rates",
        params={"dry_run": "false", "expected": report["counts"]["to_fill"]},
        headers=app_auth_headers,
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["counts"]["filled"] == report["counts"]["to_fill"]

    after = await _rates(all_stages)
    # Kwota trafia na pierwszy wiersz „CV wysłane”, nie na wcześniejszy etap.
    verified_row, sent_row, later_row = fillable["stages"]
    assert after[sent_row] == (Decimal("161.00"), "hourly", "PLN")
    assert after[verified_row] == (None, None, None)
    assert after[later_row] == (None, None, None)
    # Istniejąca stawka zostaje; dwie różne kwoty, para nigdy niewysłana
    # i wpis niejednoznaczny nie dają nic.
    assert after[has_rate["stages"][0]][0] == Decimal("150.00")
    for pair in (two_amounts, never_sent, ambiguous, revised):
        assert after[pair["stages"][0]] == (None, None, None)

    # Paragon niesie same liczby i id; kwoty leżą pod osobnym kluczem.
    receipt = await _setting("client_rate_notes_backfill_2026_10")
    details = await _setting("repair_details_client_rate_notes_backfill_2026_10")
    assert sent_row in receipt["runs"][-1]["stage_ids"]
    assert "161" not in str(receipt)
    assert {"stage_id": sent_row, "value": "161.00"}.items() <= next(
        row for row in details["rows"] if row["stage_id"] == sent_row
    ).items()

    # Drugi przebieg nie ma czego uzupełniać: odmowa, a ślad pierwszego zostaje
    # (pusty przebieg nie może nadpisać listy do odwrócenia zapisu).
    again = await _dry_run(app_client, app_auth_headers)
    assert again["counts"]["to_fill"] == 0
    empty = await app_client.post(
        "/api/admin/notes-insights/client-rates",
        params={"dry_run": "false", "expected": 0},
        headers=app_auth_headers,
    )
    assert empty.status_code == 409, empty.text
    kept = await _setting("repair_details_client_rate_notes_backfill_2026_10")
    assert any(row["stage_id"] == sent_row for row in kept["rows"])


@pytest.mark.asyncio
async def test_only_admin_can_run_the_backfill(app_client: AsyncClient):
    from app.core.database import AsyncSessionLocal
    from app.core.security import hash_password
    from app.models.user import User, UserRole

    unique = uuid.uuid4().hex[:8]
    password = f"T3st_{unique}!Rate"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=f"rate-dl-{unique}@example.com",
                password_hash=hash_password(password),
                name=f"Rate DL {unique}",
                role=UserRole.delivery_lead,
                roles=[UserRole.delivery_lead.value],
                is_active=True,
            )
        )
        await db.commit()
    login = await app_client.post(
        "/api/auth/login",
        json={"email": f"rate-dl-{unique}@example.com", "password": password},
    )
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    resp = await app_client.post(
        "/api/admin/notes-insights/client-rates", headers=headers
    )
    assert resp.status_code == 403
