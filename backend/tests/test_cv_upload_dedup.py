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
from types import SimpleNamespace
from typing import Any, Optional

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.candidate_document import CandidateDocument, CandidateDocumentKind
from app.services.cv_upload_dedup import profile_holds_read_of_file


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


async def test_known_phone_in_header_does_not_block_a_new_person(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Ten sam telefon, inny (albo żaden) e-mail = inna osoba (12.10.2026).

    Do tej decyzji telefon z nagłówka odmawiał bez czytania CV, a scraper
    wgrywał wtedy plik do wskazanego profilu — wspólny numer (np. agencji)
    wrzucał CV obcej osobie.
    """
    phone = "+48 512 700 " + f"{uuid.uuid4().int % 1000:03d}"
    existing = await _seed_candidate(phone=phone)
    _patch_extractor(monkeypatch, _cv_text(phone=phone))
    _patch_post_ingest(monkeypatch)
    calls = _expect_model(
        monkeypatch,
        {"first_name": "Jan", "last_name": f"Telefon{uuid.uuid4().hex[:6]}"},
    )
    created: list[int] = []
    try:
        resp = await _post(app_client, app_auth_headers, _pdf_bytes(uuid.uuid4().hex))
        assert calls, "telefon z nagłówka nie może już odmawiać przed odczytem"
        assert resp.status_code == 201, resp.text
        created.append(resp.json()["candidate"]["id"])
        assert created[0] != existing
    finally:
        await _cleanup(existing, *created)


async def test_linkedin_only_cv_is_not_sieved(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Sito pyta wyłącznie o e-mail (plik + adres); LinkedIn niczego nie blokuje."""
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
        "app.services.cv_upload_dedup.find_candidate_by_email", _boom, raising=True
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


async def test_kill_switch_restores_the_old_behaviour(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """`FROM_CV_SIEVE_ENABLED=False` wraca do zachowania sprzed zmiany.

    Wyłącznik istnieje, bo sito czyta kontakt REGEXEM, a `BulkImportCVsV2` nie
    ma przycisku „zapisz mimo wszystko" — więc fałszywe trafienie zablokowałoby
    import masowy bez wyjścia z UI.
    """
    from app.core.config import settings

    monkeypatch.setattr(settings, "FROM_CV_SIEVE_ENABLED", False, raising=False)
    content = _pdf_bytes(f"wylacznik-{uuid.uuid4().hex[:8]}")
    existing = await _seed_candidate(digest=hashlib.sha256(content).hexdigest())
    _patch_extractor(monkeypatch, _cv_text())
    _patch_post_ingest(monkeypatch)
    calls = _expect_model(
        monkeypatch,
        {"first_name": "Jan", "last_name": f"Wyl{uuid.uuid4().hex[:6]}"},
    )
    created: list[int] = []
    try:
        resp = await _post(app_client, app_auth_headers, content)
        assert calls, "przy wyłączonym sicie płatny odczyt musi dojść do skutku"
        if resp.status_code == 201:
            created.append(resp.json()["candidate"]["id"])
    finally:
        await _cleanup(existing, *created)


async def test_sieve_runs_before_the_paid_read():
    """Kolejność kroków w handlerze — czytana ze ŹRÓDŁA, nie z zachowania.

    Zachowanie da się spełnić przypadkiem (np. gdy sito trafi także po odczycie);
    kolejność wywołań jest tym, co faktycznie oszczędza pieniądze.
    """
    import ast
    import inspect

    from app.api import candidates as module

    tree = ast.parse(inspect.getsource(module))

    def _function(name: str):
        found = next(
            (
                n
                for n in ast.walk(tree)
                if isinstance(n, ast.AsyncFunctionDef) and n.name == name
            ),
            None,
        )
        assert found is not None, (
            f"{name} nie istnieje — jeśli przemianowano, zaktualizuj test"
        )
        return found

    # Od 29.09.2026 odczyt CV (sito + płatny odczyt, z pamięcią procesu) żyje
    # w jednym pomocniku, który wołają `/from-cv` i `/cv/preview`.
    handler = _function("_read_cv_for_new_candidate")
    for route in ("create_candidate_from_cv", "preview_candidate_cv"):
        route_calls = {
            getattr(node.func, "id", None)
            for node in ast.walk(_function(route))
            if isinstance(node, ast.Call)
        }
        assert "_read_cv_for_new_candidate" in route_calls, (
            f"{route} musi czytać CV przez `_read_cv_for_new_candidate`"
        )
        assert "parse_cv" not in route_calls, (
            f"{route} woła parse_cv z pominięciem sita"
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


def _sieve_without_db(monkeypatch, rows=()):
    """Sito z podmienionymi zapytaniami: zwraca listę adresów, o które zapytało."""
    from app.services import cv_upload_dedup

    asked: list[str] = []

    async def _no_file_match(*_a, **_kw):
        return []

    async def _by_email(_db, email, **_kw):
        asked.append(email)
        return list(rows)

    monkeypatch.setattr(cv_upload_dedup, "_duplicates_by_file_hash", _no_file_match)
    monkeypatch.setattr(cv_upload_dedup, "find_candidate_by_email", _by_email)
    return asked


async def test_sieve_asks_only_about_header_email(monkeypatch):
    from app.services.cv_upload_dedup import find_duplicates_without_llm

    hit = {"candidate_id": 7, "match_reasons": ["email_exact"]}
    asked = _sieve_without_db(monkeypatch, rows=[hit])

    rows = await find_duplicates_without_llm(
        None,
        content=b"cv",
        raw_text=_cv_text(email="Jan.Testowy@Example.com", phone="+48 512 700 321"),
    )

    assert asked == ["jan.testowy@example.com"]
    assert rows == [hit]


async def test_sieve_ignores_header_phone(monkeypatch):
    """Sam telefon w nagłówku to za mało, żeby odmówić — sito nie pyta bazy."""
    from app.services.cv_upload_dedup import find_duplicates_without_llm

    asked = _sieve_without_db(monkeypatch, rows=[{"candidate_id": 7}])

    rows = await find_duplicates_without_llm(
        None, content=b"cv", raw_text=_cv_text(phone="+48 512 700 321")
    )

    assert asked == []
    assert rows == []


async def test_form_email_replaces_header_email(monkeypatch):
    """Adres wpisany w formularzu wygrywa z odczytem — także w sicie."""
    from app.services.cv_upload_dedup import find_duplicates_without_llm

    asked = _sieve_without_db(monkeypatch)

    await find_duplicates_without_llm(
        None,
        content=b"cv",
        raw_text=_cv_text(email="z.naglowka@example.com"),
        form_email="z.formularza@example.com",
    )

    assert asked == ["z.formularza@example.com"]


async def test_cleared_form_email_skips_the_email_step(monkeypatch):
    """Rekruter wyczyścił adres z CV — nagłówek pliku nie może blokować zapisu."""
    from app.services.cv_upload_dedup import find_duplicates_without_llm

    asked = _sieve_without_db(monkeypatch, rows=[{"candidate_id": 7}])

    rows = await find_duplicates_without_llm(
        None,
        content=b"cv",
        raw_text=_cv_text(email="z.naglowka@example.com"),
        form_email="",
    )

    assert asked == []
    assert rows == []


async def test_hash_sieve_skips_files_quarantined_as_someone_elses():
    """Plik uznany za CV innej osoby (kwarantanna tożsamości) leży w profilu,
    ale nie dowodzi, że to CV tej osoby.

    Bez tego warunku poczta podpinała mail do profilu z plikiem w kwarantannie
    i właściwa osoba nigdy nie dostawała profilu, a `/from-cv` wskazywał ten
    profil klientowi, który dogrywa tam CV. 12.10.2026 w profilach leżało
    155 takich plików.
    """
    from types import SimpleNamespace

    from sqlalchemy.dialects import postgresql

    from app.services.cv_upload_dedup import _duplicates_by_file_hash

    captured = {}

    class _Db:
        async def execute(self, stmt):
            captured["stmt"] = stmt
            return SimpleNamespace(all=lambda: [])

    assert await _duplicates_by_file_hash(_Db(), digest="a" * 64) == []

    sql = str(
        captured["stmt"].compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "NOT (EXISTS" in sql
    assert "candidate_source_identity_reviews" in sql
    assert "confirmed_mismatch" in sql


async def test_candidate_without_contact_is_not_sieved():
    """Brak e-maila → sito milczy (poza skrótem pliku)."""
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


# Ten sam plik wgrany drugi raz nie płaci za drugi odczyt (03.11.2026).
# `_store_candidate_document` po tym samym SHA-256 aktualizuje istniejący wiersz,
# ale zadanie w tle i tak czytało plik modelem: 793 z 7853 odczytów w 30 dni.
# Testy bez bazy: sesja to atrapa, bo sednem jest to, czy `parse_cv` zostanie
# wywołane, a nie zapis wyniku.

_SHA = "a" * 64
_READ_BY_MODEL = "claude:cv_enrichment:v8"


def _extracted(**overrides: Any) -> dict[str, Any]:
    highlights = {"source_hash": _SHA, "extractor_version": _READ_BY_MODEL}
    highlights.update(overrides.pop("highlights", {}))
    return {"cv_highlights": highlights, **overrides}


def _holds(extracted: Any, *, text: Optional[str] = "CV", sha: Optional[str] = _SHA):
    return profile_holds_read_of_file(extracted, raw_cv_text=text, content_sha256=sha)


class TestProfileHoldsReadOfFile:
    def test_same_file_read_by_model(self):
        assert _holds(_extracted()) is True

    def test_older_rich_prompt_counts_too(self):
        # v8 zmienił tylko wcięcia JSON-a; nowa wersja promptu sama w sobie nie
        # jest powodem, żeby płacić drugi raz. Odświeżenie: `/cv/reparse`.
        extracted = _extracted(
            highlights={"extractor_version": "claude:cv_enrichment:v7"}
        )
        assert _holds(extracted) is True

    def test_other_file_is_a_new_read(self):
        assert _holds(_extracted(highlights={"source_hash": "b" * 64})) is False

    @pytest.mark.parametrize(
        "version",
        ["regex", "claude:cv_enrichment:v6", "claude:cv_enrichment_bulk:v2", None],
    )
    def test_read_without_full_profile_is_repeated(self, version):
        # Regex to awaria modelu; starsze odczyty nie niosą pełnego profilu.
        assert _holds(_extracted(highlights={"extractor_version": version})) is False

    def test_truncated_read_is_repeated(self):
        assert _holds(_extracted(_truncated=True)) is False

    def test_profile_marked_after_quarantine_is_read_again(self):
        # Znacznik „wgrane CV nie zasiliło profilu” znika dopiero z odczytem.
        extracted = _extracted(
            _identity_quarantine_source={"kind": "document", "id": 1}
        )
        assert _holds(extracted) is False

    @pytest.mark.parametrize("text", [None, "", "   "])
    def test_profile_without_cv_text_is_read(self, text):
        assert _holds(_extracted(), text=text) is False

    @pytest.mark.parametrize("sha", [None, ""])
    def test_document_without_hash_is_read(self, sha):
        assert _holds({"cv_highlights": {"source_hash": sha}}, sha=sha) is False

    @pytest.mark.parametrize(
        "extracted", [None, {}, {"cv_highlights": None}, {"cv_highlights": "x"}, "x"]
    )
    def test_profile_without_marker_is_read(self, extracted):
        assert _holds(extracted) is False


class _ModelCalled(Exception):
    """Zatrzymuje zadanie w miejscu płatnego wywołania."""


class _Session:
    """Kolejne `scalar` zadania: dokument, kandydat, recenzja tożsamości."""

    def __init__(self, *answers: Any) -> None:
        self._answers = list(answers)

    async def __aenter__(self) -> "_Session":
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        return None

    async def scalar(self, _stmt: Any) -> Any:
        return self._answers.pop(0)

    async def execute(self, _stmt: Any) -> Any:
        # Pliki osoby w kwarantannie: żadnego, więc bez porównywania bajtów.
        return SimpleNamespace(all=lambda: [])

    async def refresh(self, *_a: Any, **_kw: Any) -> None:
        return None

    async def rollback(self) -> None:
        return None


@pytest.fixture
def run_task(monkeypatch):
    """Zadanie w tle na atrapie sesji; zwraca liczbę wywołań `parse_cv`."""
    from app.api import candidates as candidates_api
    from app.services import cv_parser, cv_text_extractor

    calls: list[str] = []

    async def _parse_cv(text: str, **_kw: Any) -> dict:
        calls.append(text)
        raise _ModelCalled

    monkeypatch.setattr(cv_parser, "parse_cv", _parse_cv)
    monkeypatch.setattr(cv_text_extractor, "extract_text", lambda *_a: "Jan Testowy")

    async def _run(*, marker: str = _SHA, review: Any, **task_kwargs: Any) -> int:
        document = SimpleNamespace(
            id=2,
            filename="cv.txt",
            content_sha256=_SHA,
            storage_key=None,
            file_content=b"Jan Testowy",
        )
        candidate = SimpleNamespace(
            id=1,
            raw_cv_text="Jan Testowy",
            cv_extracted_data=_extracted(highlights={"source_hash": marker}),
        )
        session = _Session(document, candidate, review)
        monkeypatch.setattr("app.core.database.AsyncSessionLocal", lambda: session)
        await candidates_api._enrich_candidate_from_document_task(
            1, 2, _SHA, **task_kwargs
        )
        return len(calls)

    return _run


_CONFIRMED = SimpleNamespace(is_quarantined=False)


async def test_second_upload_of_read_file_does_not_call_the_model(run_task):
    assert await run_task(review=_CONFIRMED) == 0


async def test_reparse_reads_even_when_the_profile_holds_this_file(run_task):
    assert await run_task(review=_CONFIRMED, force_read=True) == 1


async def test_other_file_in_profile_means_a_paid_read(run_task):
    assert await run_task(marker="b" * 64, review=_CONFIRMED) == 1


async def test_file_in_quarantine_goes_through_the_identity_gate(run_task):
    # Odczyt prowadzi do bramki, która oddaje główne CV poprzedniemu plikowi.
    review = SimpleNamespace(is_quarantined=True)
    assert await run_task(review=review) == 1


async def test_file_without_identity_review_is_read(run_task):
    assert await run_task(review=None) == 1


async def test_reparse_endpoint_asks_for_a_forced_read():
    """Bez `force_read` przycisk „ponów odczyt” przestałby cokolwiek robić."""
    import ast
    import inspect

    from app.api import candidates as candidates_api

    tree = ast.parse(inspect.getsource(candidates_api.reparse_primary_cv))
    add_task = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "add_task"
    )
    forced = {kw.arg: getattr(kw.value, "value", None) for kw in add_task.keywords}
    assert forced.get("force_read") is True
