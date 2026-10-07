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

from app.services.client_rate_notes import (
    extract_client_rate,
    note_has_dl_pair,
    parse_dl_pair,
)

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
        # Para kwot czyta `parse_dl_pair`, nie ta reguła.
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


# ── wpis „X/Y” (07.10.2026) ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    "content, client_rate, candidate_rate",
    [
        ("160/115 @Jan Testowy", "160", "115"),
        ("<p>160/115 @osoba</p>", "160", "115"),
        ("190/145 1520 MD", "190", "145"),
        ("160 / 115 zł/h netto", "160", "115"),
        ("wyślijmy za 160/115", "160", "115"),
        ("Stawka 170/140 dla klienta", "170", "140"),
    ],
)
def test_short_dl_pair_gives_client_and_candidate_rate(
    content, client_rate, candidate_rate
):
    assert parse_dl_pair(content) == (Decimal(client_rate), Decimal(candidate_rate))


@pytest.mark.parametrize(
    "content",
    [
        # Widełki kandydata — pierwsza liczba niższa albo równa.
        "Rate: 100/110 PLN/h",
        "150/155",
        "150/150",
        # Procent, liczba klientów, wynik dopasowania.
        "60/70 %",
        "60/70 klientów",
        "score: 67/100",
        "Auto-match score: 167/100",
        # MD niezgodne z X × 8, inna liczba, waluta, jednostka dzienna.
        "190/145 1500 MD",
        "160/115 od 01.11",
        "160/115 eur",
        "170/140 zł/dzień",
        "160/115 brutto",
        # Pytanie, przeczenie, dwie pary, poza zakresem.
        "160/115?",
        "nie 160/115",
        "160/115 i 150/110",
        "50/30",
        "450/300",
        # Wynik testu i widełki oczekiwań kandydata (przegląd #2062).
        "Codility 85/60",
        "HackerRank 95/70",
        "wynik 90/45",
        "zadanie: 100/60",
        "test 90/50 pkt",
        "oczekiwania 130/120",
        "140/120 zakres",
        "120/100 widełki",
        "120/100 widelki",
        "ocena 90/60",
        # Długa notatka to rozmowa, nie wpis DL-a.
        "Rozmowa z kandydatem o projekcie w banku, zespół 8 osób, "
        "Java i Spring, pracuje zdalnie, oczekiwania omówione wcześniej, "
        "wszystko ustalone z klientem przy okazji poprzedniej rekrutacji 160/115",
        "",
        None,
    ],
)
def test_anything_else_is_not_a_dl_pair(content):
    assert parse_dl_pair(content) is None


def test_dl_pair_only_in_dl_and_human_notes():
    assert note_has_dl_pair("dl_rate", "160/115")
    assert note_has_dl_pair("human", "160/115")
    for kind in ("card", "automatch", "application_form", "email", None):
        assert not note_has_dl_pair(kind, "160/115"), kind


def test_plain_note_pair_counts_only_from_a_delivery_lead_or_admin():
    from app.services.client_rate_notes import dl_pair_from_note

    pair = (Decimal("170"), Decimal("140"))
    # Wpis `dl_rate` — zawsze, niezależnie od autora.
    assert dl_pair_from_note("dl_rate", "170/140", author_is_dl=False) == pair
    # Zwykła notatka rekrutera („170/140” bywa wynikiem albo widełkami) — nie.
    assert dl_pair_from_note("human", "Stawka 170/140", author_is_dl=False) is None
    assert dl_pair_from_note("human", "Stawka 170/140", author_is_dl=True) == pair
    # Słowa testu wykluczają też notatkę DL-a.
    assert dl_pair_from_note("human", "Codility 85/60", author_is_dl=True) is None
    for kind in ("card", "automatch", "email", None):
        assert dl_pair_from_note(kind, "170/140", author_is_dl=True) is None, kind


def test_author_sql_checks_the_primary_role_and_the_roles_list():
    from app.services import client_rate_notes

    sql = client_rate_notes.DL_PAIR_AUTHOR_SQL
    for role in client_rate_notes.DL_PAIR_AUTHOR_ROLES:
        assert sql.count(f"'{role}'") == 2, role
    assert "u.role::text" in sql and "u.roles" in sql


def test_schema_trigger_mirrors_the_parser_prefilter():
    from app.services import client_rate_notes, notes_facts_schema

    trigger = notes_facts_schema.TRIGGER_DDL[0]
    assert client_rate_notes.DL_PAIR_SQL_PATTERN in trigger
    for kind in client_rate_notes.DL_PAIR_KINDS:
        assert f"'{kind}'" in trigger
    for stmt in notes_facts_schema.ALL_DDL:
        # entrypoint wykonuje instrukcje wprost — dwukropek byłby parametrem.
        assert ":" not in stmt.replace("::", ""), stmt[:60]


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
    # Krótki wpis DL-a „X/Y” (07.10.2026): wyższa liczba to stawka do klienta.
    dl_pair = await _seed_pair([("cv_sent", None)], ["150/110 @Jan Testowy"])
    # Pierwsza liczba niższa = widełki kandydata, nie para DL-a.
    ambiguous = await _seed_pair([("cv_sent", None)], ["100/110"])
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
        *dl_pair["stages"],
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
    assert after[dl_pair["stages"][0]] == (Decimal("150.00"), "hourly", "PLN")
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
