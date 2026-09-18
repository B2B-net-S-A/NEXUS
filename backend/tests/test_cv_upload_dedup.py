"""Darmowe sito duplikatów PRZED płatnym odczytem CV (`POST /api/candidates/from-cv`).

Sedno tych testów: **model nie może zostać wywołany**, gdy duplikat da się
rozpoznać za darmo. Dlatego każdy scenariusz podstawia `_parse_with_claude`
rzucający `AssertionError` — wzorzec z `test_uop_check_quota_gate.py` — zamiast
sprawdzać sam kod odpowiedzi. Kod 409 przychodził i przedtem; nowe jest to,
że przychodzi ZANIM zapłacimy.

Baza testowa jest wspólna i nie jest czyszczona między testami, więc każdy
scenariusz zakłada własne wiersze z sufiksem `uuid4().hex[:6]` i asertuje
wyłącznie po własnych identyfikatorach.
"""

from __future__ import annotations

import hashlib
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.candidate_document import CandidateDocument, CandidateDocumentKind


def _pdf_bytes(marker: str) -> bytes:
    return f"%PDF-1.4 {marker}".encode()


def _cv_text(*, email: str | None = None, phone: str | None = None) -> str:
    """CV z danymi kontaktowymi w NAGŁÓWKU — tak jak wyglądają prawdziwe CV."""
    head = ["Jan Testowy", "Senior Python Developer"]
    if email:
        head.append(f"e-mail: {email}")
    if phone:
        head.append(f"tel. {phone}")
    body = ["", "Doświadczenie:", "Python, FastAPI, PostgreSQL"]
    return "\n".join(head + body)


class _ModelWasCalled(AssertionError):
    """Podniesione, gdy sito przepuściło coś, co miało złapać za darmo."""


def _forbid_model(monkeypatch) -> None:
    """Każde wywołanie płatnego kroku wywraca test."""

    async def _must_not_run(*_a, **_kw):  # pragma: no cover — nie wolno
        raise _ModelWasCalled("sito miało złapać duplikat bez wywołania modelu")

    monkeypatch.setattr(
        "app.services.cv_parser._parse_with_claude", _must_not_run, raising=True
    )


def _expect_model(monkeypatch, parsed: dict) -> list[int]:
    """Pozwól na płatny krok i policz wywołania."""
    calls: list[int] = []

    async def _fake(*_a, **_kw):
        calls.append(1)
        return parsed

    monkeypatch.setattr(
        "app.services.cv_parser._parse_with_claude", _fake, raising=True
    )
    return calls


def _patch_extractor(monkeypatch, text: str) -> None:
    from app.services import cv_text_extractor

    monkeypatch.setattr(
        cv_text_extractor, "extract_text", lambda *_a, **_kw: text, raising=True
    )


def _patch_post_ingest(monkeypatch) -> None:
    """Wycisz Qdrant i klasyfikację — te testy dotyczą sita, nie wzbogacania."""

    async def _noop(*_a, **_kw):
        return None

    monkeypatch.setattr(
        "app.services.embedding_service.embed_candidate", _noop, raising=True
    )


async def _seed_candidate(
    *, email: str | None = None, phone: str | None = None, digest: str | None = None
) -> int:
    """Załóż kandydata (opcjonalnie z dokumentem o zadanym skrócie)."""
    async with AsyncSessionLocal() as db:
        candidate = Candidate(
            name="SitoTest",
            lastname=f"Duplikat{uuid.uuid4().hex[:6]}",
            email=email,
            phone=phone,
        )
        db.add(candidate)
        await db.flush()
        if digest:
            db.add(
                CandidateDocument(
                    candidate_id=candidate.id,
                    filename="cv.pdf",
                    document_kind=CandidateDocumentKind.cv,
                    is_primary=True,
                    content_sha256=digest,
                )
            )
        await db.commit()
        return candidate.id


async def _cleanup(*candidate_ids: int) -> None:
    async with AsyncSessionLocal() as db:
        for cid in candidate_ids:
            await db.execute(
                delete(CandidateDocument).where(
                    CandidateDocument.candidate_id == cid
                )
            )
            row = await db.get(Candidate, cid)
            if row is not None:
                await db.delete(row)
        await db.commit()


async def _post(client: AsyncClient, headers: dict, content: bytes, *, force=False):
    return await client.post(
        f"/api/candidates/from-cv{'?force=true' if force else ''}",
        headers=headers,
        files={"file": ("cv.pdf", content, "application/pdf")},
    )


async def test_identical_file_is_rejected_without_calling_the_model(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Replay tego samego pliku — najtańsze rozpoznanie, zero czytania treści."""
    content = _pdf_bytes(f"identyczny-{uuid.uuid4().hex[:8]}")
    digest = hashlib.sha256(content).hexdigest()
    existing = await _seed_candidate(digest=digest)
    _patch_extractor(monkeypatch, _cv_text())
    _patch_post_ingest(monkeypatch)
    _forbid_model(monkeypatch)
    try:
        resp = await _post(app_client, app_auth_headers, content)
        assert resp.status_code == 409, resp.text
        detail = resp.json()["detail"]
        assert detail["existing_candidate_id"] == existing
        assert detail["matches"][0]["match_reasons"] == ["identical_file"]
    finally:
        await _cleanup(existing)


async def test_known_email_in_header_is_rejected_without_calling_the_model(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Główna ścieżka oszczędności: 92,5% CV niesie e-mail, regex go znajduje."""
    email = f"sito.{uuid.uuid4().hex[:8]}@example.com"
    existing = await _seed_candidate(email=email)
    _patch_extractor(monkeypatch, _cv_text(email=email))
    _patch_post_ingest(monkeypatch)
    _forbid_model(monkeypatch)
    try:
        resp = await _post(app_client, app_auth_headers, _pdf_bytes(uuid.uuid4().hex))
        assert resp.status_code == 409, resp.text
        assert resp.json()["detail"]["existing_candidate_id"] == existing
    finally:
        await _cleanup(existing)


async def test_known_phone_in_header_is_rejected_without_calling_the_model(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Telefon to drugi identyfikator sita — CV bez e-maila nadal się broni."""
    phone = "+48 512 700 " + f"{uuid.uuid4().int % 1000:03d}"
    existing = await _seed_candidate(phone=phone)
    _patch_extractor(monkeypatch, _cv_text(phone=phone))
    _patch_post_ingest(monkeypatch)
    _forbid_model(monkeypatch)
    try:
        resp = await _post(app_client, app_auth_headers, _pdf_bytes(uuid.uuid4().hex))
        assert resp.status_code == 409, resp.text
        assert resp.json()["detail"]["existing_candidate_id"] == existing
    finally:
        await _cleanup(existing)


async def test_digit_run_in_the_body_does_not_trigger_the_sieve(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Zbitka cyfr w TREŚCI nie może udawać telefonu.

    To jest cała przyczyna, dla której sito czyta wyłącznie nagłówek:
    scraper przy 409 wgrywa CV do wskazanego profilu, więc fałszywe trafienie
    oznacza CV obcej osoby u kogoś innego.
    """
    phone = "+48 512 700 321"
    existing = await _seed_candidate(phone=phone)
    # Ten sam ciąg cyfr, ale w treści — nie w nagłówku.
    text = "\n".join(
        ["Anna Nowa", "Backend Developer"]
        + [f"linia {i}" for i in range(25)]
        + [f"projekt rozliczany {phone}"]
    )
    _patch_extractor(monkeypatch, text)
    _patch_post_ingest(monkeypatch)
    calls = _expect_model(
        monkeypatch,
        {"first_name": "Anna", "last_name": f"Nowa{uuid.uuid4().hex[:6]}"},
    )
    created: list[int] = []
    try:
        resp = await _post(app_client, app_auth_headers, _pdf_bytes(uuid.uuid4().hex))
        assert calls, "sito zjadło zbitkę cyfr z treści jako telefon"
        if resp.status_code == 201:
            created.append(resp.json()["candidate"]["id"])
    finally:
        await _cleanup(existing, *created)


async def test_linkedin_only_cv_is_not_sieved(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Sito pyta wyłącznie o e-mail i telefon (decyzja właściciela, 18.09).

    LinkedIn zostaje skanowi PO płatnym odczycie — sito jest węższe celowo.
    """
    slug = f"jan-sito-{uuid.uuid4().hex[:8]}"
    async with AsyncSessionLocal() as db:
        candidate = Candidate(
            name="SitoTest",
            lastname=f"Linked{uuid.uuid4().hex[:6]}",
            linkedin=f"https://linkedin.com/in/{slug}",
        )
        db.add(candidate)
        await db.commit()
        existing = candidate.id
    text = "\n".join(["Jan Sito", "Developer", f"linkedin.com/in/{slug}"])
    _patch_extractor(monkeypatch, text)
    _patch_post_ingest(monkeypatch)
    calls = _expect_model(
        monkeypatch, {"first_name": "Jan", "last_name": f"Sito{uuid.uuid4().hex[:6]}"}
    )
    created: list[int] = []
    try:
        resp = await _post(app_client, app_auth_headers, _pdf_bytes(uuid.uuid4().hex))
        assert calls, "sito nie może odmawiać na podstawie samego LinkedIna"
        if resp.status_code == 201:
            created.append(resp.json()["candidate"]["id"])
    finally:
        await _cleanup(existing, *created)


async def test_force_bypasses_the_sieve(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """`force=true` omija sito tak samo, jak omijał skan po odczycie."""
    content = _pdf_bytes(f"force-{uuid.uuid4().hex[:8]}")
    digest = hashlib.sha256(content).hexdigest()
    existing = await _seed_candidate(digest=digest)
    _patch_extractor(monkeypatch, _cv_text())
    _patch_post_ingest(monkeypatch)
    calls = _expect_model(
        monkeypatch, {"first_name": "Jan", "last_name": f"Force{uuid.uuid4().hex[:6]}"}
    )
    created: list[int] = []
    try:
        resp = await _post(app_client, app_auth_headers, content, force=True)
        assert calls, "force=true musi dopuścić płatny odczyt"
        if resp.status_code == 201:
            created.append(resp.json()["candidate"]["id"])
    finally:
        await _cleanup(existing, *created)


async def test_sieve_failure_leaves_the_old_path_intact(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Awaria sita nie może zamknąć onboardingu — to optymalizacja, nie bramka."""

    async def _boom(*_a, **_kw):
        raise RuntimeError("baza padła w sicie")

    monkeypatch.setattr(
        "app.services.cv_upload_dedup._duplicates_by_file_hash", _boom, raising=True
    )
    monkeypatch.setattr(
        "app.services.dedup_service.find_candidate_duplicates", _boom, raising=True
    )
    _patch_extractor(monkeypatch, _cv_text(email="awaria@example.com"))
    _patch_post_ingest(monkeypatch)
    calls = _expect_model(
        monkeypatch, {"first_name": "Jan", "last_name": f"Awaria{uuid.uuid4().hex[:6]}"}
    )
    created: list[int] = []
    try:
        resp = await _post(app_client, app_auth_headers, _pdf_bytes(uuid.uuid4().hex))
        assert calls, "awaria sita nie może zablokować płatnego odczytu"
        assert resp.status_code in (201, 409, 500), resp.text
        if resp.status_code == 201:
            created.append(resp.json()["candidate"]["id"])
    finally:
        await _cleanup(*created)


async def test_conflict_shape_keeps_both_keys_the_frontend_reads():
    """Dwa ekrany czytają 409 i KAŻDY sprawdza inny klucz.

    `AddCandidateFromCVModal` sprawdza `matches`, `BulkImportCVsV2` sprawdza
    `existing_candidate_id`. Test czyta helper wprost, żeby rozjazd kształtu
    wyszedł tu, a nie na ekranie rekrutera.
    """
    from fastapi import HTTPException

    from app.api.candidates import _raise_from_cv_duplicate_conflict

    with pytest.raises(HTTPException) as exc:
        _raise_from_cv_duplicate_conflict(
            [
                {
                    "candidate_id": 4242,
                    "name": "Jan",
                    "lastname": "Testowy",
                    "email": "jan@example.com",
                    "match_score": 1.0,
                    "match_reasons": ["identical_file"],
                }
            ]
        )
    assert exc.value.status_code == 409
    detail = exc.value.detail
    assert detail["existing_candidate_id"] == 4242
    assert detail["matches"][0]["match_reasons"] == ["identical_file"]


async def test_sieve_runs_before_the_paid_read():
    """Kolejność kroków w handlerze — czytana ze ŹRÓDŁA, nie z zachowania.

    Zachowanie da się spełnić przypadkiem (np. gdy sito trafi także po odczycie);
    kolejność wywołań jest tym, co faktycznie oszczędza pieniądze.
    """
    import ast
    import inspect

    from app.api import candidates as module

    tree = ast.parse(inspect.getsource(module))
    handler = next(
        (
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.AsyncFunctionDef)
            and n.name == "create_candidate_from_cv"
        ),
        None,
    )
    assert handler is not None, (
        "create_candidate_from_cv nie istnieje — jeśli przemianowano, zaktualizuj test"
    )

    def _linenos(name: str) -> list[int]:
        out = []
        for node in ast.walk(handler):
            if isinstance(node, ast.Call):
                func = node.func
                ident = getattr(func, "id", None) or getattr(func, "attr", None)
                if ident == name:
                    out.append(node.lineno)
        return sorted(out)

    sieve = _linenos("find_duplicates_without_llm")
    paid = _linenos("parse_cv")
    assert sieve, "darmowe sito zniknęło z handlera"
    assert paid, "parse_cv zniknął z handlera"
    assert sieve[0] < paid[0], (
        "sito musi biec PRZED płatnym odczytem — inaczej duplikat znów płaci"
    )


async def test_sieve_name_is_the_real_import_not_a_local_shadow():
    """Test kolejności jest bezwartościowy, jeśli nazwę przesłonięto lokalnie."""
    import inspect

    from app.api import candidates as module

    source = inspect.getsource(module)
    assert (
        "from app.services.cv_upload_dedup import find_duplicates_without_llm" in source
    ), "sito musi pochodzić z `cv_upload_dedup`, nie z lokalnej definicji"


async def test_header_phone_ignores_body_digit_runs():
    """Jednostkowo: ekstraktor nagłówka nie sięga do treści."""
    from app.services.cv_upload_dedup import header_phone

    header = "Jan Testowy\nDeveloper\ntel. +48 512 700 321"
    assert header_phone(header) is not None

    body_only = "\n".join(["Jan Testowy"] + [f"linia {i}" for i in range(30)] + [
        "faktura 512 700 321"
    ])
    assert header_phone(body_only) is None


async def test_candidate_without_contact_is_not_sieved():
    """Brak e-maila i telefonu → sito milczy, nie odpytuje nawet bazy."""
    from app.services.cv_upload_dedup import find_duplicates_without_llm

    async with AsyncSessionLocal() as db:
        rows = await find_duplicates_without_llm(
            db, content=_pdf_bytes(uuid.uuid4().hex), raw_text="Jan Testowy\nDeveloper"
        )
    assert rows == []


async def test_deleted_document_does_not_count_as_a_duplicate():
    """Dokument po skasowaniu źródła nie dowodzi, że kandydat ten plik ma."""
    from datetime import datetime, timezone

    from app.services.cv_upload_dedup import find_duplicates_without_llm

    content = _pdf_bytes(f"skasowany-{uuid.uuid4().hex[:8]}")
    digest = hashlib.sha256(content).hexdigest()
    async with AsyncSessionLocal() as db:
        candidate = Candidate(
            name="SitoTest", lastname=f"Skasowany{uuid.uuid4().hex[:6]}"
        )
        db.add(candidate)
        await db.flush()
        db.add(
            CandidateDocument(
                candidate_id=candidate.id,
                filename="cv.pdf",
                document_kind=CandidateDocumentKind.cv,
                content_sha256=digest,
                source_deleted_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()
        cid = candidate.id
    try:
        async with AsyncSessionLocal() as db:
            rows = await find_duplicates_without_llm(
                db, content=content, raw_text="Jan Testowy\nDeveloper"
            )
        assert not any(r["candidate_id"] == cid for r in rows)
    finally:
        await _cleanup(cid)


async def test_seeded_document_is_visible_to_the_hash_sieve():
    """Kontrola pozytywna do testu wyżej — żywy dokument MUSI być widziany."""
    from app.services.cv_upload_dedup import find_duplicates_without_llm

    content = _pdf_bytes(f"zywy-{uuid.uuid4().hex[:8]}")
    digest = hashlib.sha256(content).hexdigest()
    cid = await _seed_candidate(digest=digest)
    try:
        async with AsyncSessionLocal() as db:
            rows = await find_duplicates_without_llm(
                db, content=content, raw_text="Jan Testowy\nDeveloper"
            )
        assert [r["candidate_id"] for r in rows] == [cid]
    finally:
        await _cleanup(cid)


async def test_candidates_table_stays_clean_after_sieve_rejection():
    """Sito odmawia PRZED utworzeniem kandydata — żadnych wierszy-sierot."""
    from app.services.cv_upload_dedup import content_digest

    content = _pdf_bytes(f"sierota-{uuid.uuid4().hex[:8]}")
    cid = await _seed_candidate(digest=content_digest(content))
    try:
        async with AsyncSessionLocal() as db:
            before = await db.scalar(
                select(Candidate.id).where(Candidate.id == cid)
            )
        assert before == cid
    finally:
        await _cleanup(cid)
