"""Runda 10 (IMPEX): importy CSV/XLSX nie wywracają się na jednym złym wierszu.

- R10-N13-2 — import CSV kandydatów szuka duplikatu e-maila bez wielkości liter,
- R10-N13-7 — import CSV zapisuje autora (``created_by``),
- R10-N13-9 — błąd wiersza nie niesie tekstu SQL, tylko kod i polski powód,
- R10-N13-8 — ``POST /api/candidates/bulk-import`` zapisuje intencję indeksu,
- R10-N13-3 — import stawek rynkowych: nadmiarowa kolumna i za długie pola
  kończą się pominięciem wiersza, nie 500 dla całego pliku,
- R10-N13-4 — numer umowy spoza zakresu ``Integer`` w rejestrze z Excela,
- R10-N13-5 — parser rejestru używa wspólnego strażnika OOXML.

Baza jest wspólna i nieczyszczona: każdy test ma własne, losowe dane i asercje
wyłącznie na nich. Dane są fikcyjne.
"""

from __future__ import annotations

import io
import uuid
import zipfile
from datetime import date

import pytest
from sqlalchemy import delete, select

from app.services.b2b_register_import.parser import (
    MAX_CONTRACT_SEQ,
    RegisterParseError,
    parse_register,
)
from tests.test_b2b_register_import_parser import build_register, contract_row


def _tag() -> str:
    return "Imp" + uuid.uuid4().hex[:10]


# ── rejestr z Excela: parser (bez bazy) ─────────────────────────────────────


def test_register_number_above_int32_is_kept_as_raw_number_with_flag():
    payload = build_register(
        [
            contract_row("Literówka Jan", 12_345_678_901, signing=date(2026, 2, 1)),
            contract_row("Poprawny Adam", 1517, signing=date(2026, 2, 1)),
        ]
    )
    rows = {row.name_raw: row for row in parse_register(payload).contracts}
    typo = rows["Literówka Jan"]
    assert typo.number_int is None
    assert typo.number_raw == "12345678901"
    assert "number_out_of_range" in typo.flags
    assert rows["Poprawny Adam"].number_int == 1517
    assert "number_out_of_range" not in rows["Poprawny Adam"].flags


def test_register_text_number_above_int32_is_flagged_too():
    payload = build_register(
        [contract_row("Tekstowy Jan", str(MAX_CONTRACT_SEQ + 1), signing=None)]
    )
    row = parse_register(payload).contracts[0]
    assert row.number_int is None
    assert "number_out_of_range" in row.flags


def test_register_parser_refuses_oversized_xml_part():
    """R9-N7-13 dał importom Finansów i MD ``assert_safe_ooxml`` — rejestr
    miał własny, luźny próg 200 MB łącznie."""
    source = build_register([contract_row("Testowa Anna", 1517)])
    buffer = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(source)) as original,
        zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as rebuilt,
    ):
        for info in original.infolist():
            rebuilt.writestr(info, original.read(info))
        # 11 MB XML-a (limit wspólnego strażnika to 10 MB na część) — po
        # kompresji kilka KB, więc limit uploadu go nie zatrzyma.
        rebuilt.writestr("customXml/item1.xml", "<a>" + "x" * (11 * 1024 * 1024))
    with pytest.raises(RegisterParseError):
        parse_register(buffer.getvalue())


# ── rejestr z Excela: podgląd przez API ─────────────────────────────────────


@pytest.fixture
def _register_router_mounted():
    from app.api import b2b_register_import
    from app.main import app

    path = "/api/b2b-generator/register-import"
    if not any(getattr(r, "path", "") == path for r in app.routes):
        app.include_router(b2b_register_import.router, prefix="/api/b2b-generator")
    yield


async def test_register_preview_reports_out_of_range_number_instead_of_500(
    app_client, app_auth_headers, _register_router_mounted
):
    tag = _tag()
    payload = build_register(
        [
            contract_row(
                f"{tag} Jan",
                12_345_678_901,
                signing=date(2026, 2, 1),
                start=date(2026, 2, 10),
            )
        ]
    )
    resp = await app_client.post(
        "/api/b2b-generator/register-import?dry_run=true",
        headers=app_auth_headers,
        files={
            "file": (
                "rejestr.xlsx",
                payload,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["counters"]["created"] == 1
    reasons = [
        item
        for item in body["number_collisions"]
        if item["reason"] == "number_out_of_range"
    ]
    assert reasons and reasons[0]["number"] == "12345678901"


# ── import CSV kandydatów ───────────────────────────────────────────────────


async def _admin_id(app_client, headers) -> int:
    me = await app_client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    return int(me.json()["id"])


async def test_csv_import_dedups_email_case_insensitively_and_sets_author(
    app_client, app_auth_headers
):
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate, CandidateStatus

    tag = _tag()
    stored_email = f"{tag}@Firma.Example.PL"
    async with AsyncSessionLocal() as db:
        existing = Candidate(
            name="Jan",
            lastname=tag,
            email=stored_email,
            status=CandidateStatus.active,
        )
        db.add(existing)
        await db.commit()
        existing_id = existing.id

    new_email = f"{tag}-nowy@example.com"
    csv_body = (
        "name,lastname,email\n"
        f"Jan,{tag},{stored_email.lower()}\n"
        f"Anna,{tag},{new_email}\n"
    )
    try:
        resp = await app_client.post(
            "/api/import/candidates",
            files={"file": ("kandydaci.csv", csv_body, "text/csv")},
            headers=app_auth_headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["skipped"] == 1
        assert body["imported"] == 1
        admin_id = await _admin_id(app_client, app_auth_headers)
        async with AsyncSessionLocal() as db:
            created = (
                await db.execute(
                    select(Candidate).where(
                        Candidate.lastname == tag, Candidate.name == "Anna"
                    )
                )
            ).scalar_one()
        assert created.created_by == admin_id
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(Candidate).where(Candidate.lastname == tag))
            await db.commit()
    assert existing_id


async def test_csv_import_row_error_has_code_not_sql(app_client, app_auth_headers):
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate

    tag = _tag()
    csv_body = f"name,lastname,email\n{'A' * 500},{tag},{tag}@example.com\n"
    try:
        resp = await app_client.post(
            "/api/import/candidates",
            files={"file": ("kandydaci.csv", csv_body, "text/csv")},
            headers=app_auth_headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["errors"] == 1
        detail = body["details"][0]
        assert detail["code"] == "candidate_import_failed"
        assert "INSERT" not in detail["reason"]
        assert "SQL" not in detail["reason"]
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(Candidate).where(Candidate.lastname == tag))
            await db.commit()


# ── bulk-import ─────────────────────────────────────────────────────────────


async def test_bulk_import_records_index_intent(app_client, app_auth_headers):
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.index_outbox import IndexOutboxEvent

    tag = _tag()
    resp = await app_client.post(
        "/api/candidates/bulk-import",
        json=[{"name": "Jan", "lastname": tag, "email": f"{tag}@example.com"}],
        headers=app_auth_headers,
    )
    assert resp.status_code == 201, resp.text
    ids = resp.json()["ids"]
    assert len(ids) == 1
    try:
        async with AsyncSessionLocal() as db:
            events = (
                await db.execute(
                    select(IndexOutboxEvent.id).where(
                        IndexOutboxEvent.entity_type == "candidate",
                        IndexOutboxEvent.entity_id == ids[0],
                    )
                )
            ).all()
        assert events, "bulk-import nie zapisał intencji indeksu"
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(IndexOutboxEvent).where(
                    IndexOutboxEvent.entity_type == "candidate",
                    IndexOutboxEvent.entity_id.in_(ids),
                )
            )
            await db.execute(delete(Candidate).where(Candidate.id.in_(ids)))
            await db.commit()


# ── import stawek rynkowych ─────────────────────────────────────────────────


async def test_rate_benchmark_import_skips_bad_rows_and_keeps_good_ones(
    app_client, app_auth_headers
):
    from app.core.database import AsyncSessionLocal
    from app.models.rate_benchmark import RateBenchmark

    tag = _tag()
    csv_body = (
        "role,rate_unit,market_median,source,source_date\n"
        f"{tag} ok,hourly,100,x,2026-01-01\n"
        f"{tag} extra,hourly,100,x,2026-01-01,EXTRA\n"
        f"{tag}{'A' * 200},hourly,100,x,2026-01-01\n"
        f"{tag} big,hourly,99999999999,x,2026-01-01\n"
        f"{tag} src,hourly,100,{'s' * 201},2026-01-01\n"
    )
    try:
        resp = await app_client.post(
            "/api/rate-benchmarks/import",
            files={"file": ("stawki.csv", csv_body, "text/csv")},
            headers=app_auth_headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # Nadmiarowa kolumna jest pomijana — wiersz „extra” się zapisuje.
        assert body["created"] == 2
        assert body["skipped"] == 3
        assert all("INSERT" not in error for error in body["errors"])
        async with AsyncSessionLocal() as db:
            roles = set(
                (
                    await db.execute(
                        select(RateBenchmark.role).where(
                            RateBenchmark.role.like(f"{tag}%")
                        )
                    )
                ).scalars()
            )
        assert roles == {f"{tag} ok", f"{tag} extra"}
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(RateBenchmark).where(RateBenchmark.role.like(f"{tag}%"))
            )
            await db.commit()
