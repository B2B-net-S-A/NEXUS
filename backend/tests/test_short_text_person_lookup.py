"""Krótki tekst w trakcie pisania nie może czytać całej bazy (26.11.2026).

Produkcja 26.11.2026, 09:45–09:48: ``GET /api/candidates`` z palety ⌘K
(``q`` z dwóch znaków, ``page_size=5``, ``sort=relevance``, bez
``semantics_version``) trwał 90 s, z tego 90 s w bazie, przy 16 zapytaniach.
Ścieżka v1 szuka podłańcucha w ``search_doc``, ``search_doc_unaccented``,
``raw_cv_text`` i notatkach, a dla dwóch znaków indeks trygramowy nie działa:
w ``pg_stat_statements`` jedno takie zapytanie trwało 66,6 s (946 tys. stron
z bufora, zero odczytów z dysku), na kopii produkcji „qa” 112 s, „c#” 74 s.
Przez ten czas zajmowało 3 z 8 vCPU serwera, więc inne listy czekały 7–9 s.

Paleta i wybieraki osób pytają odtąd w v2 z tekstem dosłownym, po trafności
(krótki tekst = całe słowo przez indeks, decyzja z 07.10.2026). W v2 każde
pojedyncze słowo przechodzi też przez ``interpret_text`` → ``person_token_exists``,
który filtrował wstępnie ``search_doc_unaccented ILIKE '%słowo%'``: bez trygramu
(„qz”) albo przy częstym trygramie bez dokładnego trafienia („kow”, „mar”) to
rozpakowanie profilu każdej osoby (kopia: „zx” 8 s, „kow” 5–31 s, „mar” 22–30 s).
Warunek ``ILIKE`` wynika z równości imienia albo nazwiska (``search_doc``
zaczyna się od ``name || ' ' || lastname``), więc zostaje sama równość: ten sam
wynik, 0,1–0,15 s na krótkich kolumnach bez TOAST-a.

Baza testowa jest wspólna i nieczyszczona — asercje dotyczą własnych wierszy.
"""

from __future__ import annotations

import re
import uuid
from contextlib import contextmanager

import pytest
from sqlalchemy import event, select
from sqlalchemy.dialects.postgresql.asyncpg import dialect as asyncpg_dialect

from app.core.database import AsyncSessionLocal, engine
from app.models.candidate import Candidate, CandidateStatus
from app.services import candidate_search_predicates as p
from app.services import keyword_corpus

# Parametry, z którymi paleta ⌘K i wybieraki osób pytają listę
# (`CANDIDATE_LOOKUP_PARAMS` w `frontend/src/lib/candidate-search-semantics.ts`).
LOOKUP_PARAMS = {"semantics_version": 2, "text_mode": "literal", "sort": "relevance"}

# Podłańcuch po długich kolumnach (TOAST) — bez trygramu to skan całej tabeli.
_WIDE_SUBSTRING = re.compile(
    r"\b(search_doc|search_doc_unaccented|raw_cv_text|content)\s+ILIKE\b",
    re.IGNORECASE,
)


class _Result:
    def first(self):
        return None


class _RecordingDb:
    """Sesja, która tylko zapisuje wysłane zapytania."""

    def __init__(self) -> None:
        self.statements: list = []

    async def execute(self, statement, *_args, **_kwargs):
        self.statements.append(statement)
        return _Result()


def _sql(statement) -> str:
    """SQL jak u sterownika aplikacji (asyncpg): ``ILIKE`` i ``%`` bez podwajania."""
    return str(
        statement.compile(
            dialect=asyncpg_dialect(), compile_kwargs={"literal_binds": True}
        )
    )


@contextmanager
def _capture_sql():
    seen: list[str] = []

    def _on(conn, cursor, statement, parameters, context, executemany):
        seen.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", _on)
    try:
        yield seen
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", _on)


# ── Kształt zapytania (bez bazy) ─────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("token", ["Qz", "kow", "Kowalski"])
async def test_kazde_slowo_sprawdza_sama_rownosc(token: str) -> None:
    p._person_token_cache.clear()
    db = _RecordingDb()
    assert await p.person_token_exists(db, token) is False
    [statement] = db.statements
    sql = _sql(statement)
    assert "search_doc_unaccented" not in sql
    assert "ILIKE" not in sql
    assert "candidates.lastname" in sql


@pytest.mark.parametrize(
    ("tokens", "patterns"),
    [
        (["Jo", "Li"], []),
        (["Jan", "Li"], ["%jan%"]),
        (["Łukasz", "Grądzki"], ["%lukasz%", "%gradzki%"]),
        # Myślnik dzieli słowa trygramów tak samo jak spacja.
        (["Al-Ba"], []),
    ],
)
def test_prefiltr_osoby_tylko_dla_slow_z_trygramem(tokens, patterns) -> None:
    clauses = p._exact_person_prefilter(tokens)
    assert [re.search(r"'(%[^']*%)'", _sql(c)).group(1) for c in clauses] == patterns


# ── Ten sam wynik na prawdziwym Postgresie ───────────────────────────────────


@pytest.mark.asyncio
async def test_dwuznakowe_imie_i_nazwisko_dalej_sa_osoba() -> None:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        db.add_all(
            [
                Candidate(
                    name="Ewa",
                    lastname="Ąx",
                    email=f"ax-{tag}@example.com",
                    status=CandidateStatus.active,
                ),
                Candidate(
                    name="Jo",
                    lastname=f"Nowak-Ęq{tag[:2]}",
                    email=f"eq-{tag}@example.com",
                    status=CandidateStatus.active,
                ),
            ]
        )
        await db.commit()
        p._person_token_cache.clear()
        p._person_name_cache.clear()
        # Bez polskich znaków i bez wielkości liter, jak dotąd.
        assert await p.person_token_exists(db, "AX") is True
        assert await p.person_token_exists(db, "jo") is True
        # Człon nazwiska z myślnikiem (tu trzy znaki: ścieżka z indeksem).
        assert await p.person_token_exists(db, f"eq{tag[:2]}") is True
        # Nikt tak się nie nazywa — znaki spoza mapy składania.
        assert await p.person_token_exists(db, "ýw") is False
        assert await p.person_name_exists(db, ["Ewa", "Ąx"]) is True
        assert await p.person_name_exists(db, ["Ąx", "Ewa"]) is True
        assert await p.person_name_exists(db, ["Ýw", "Ąx"]) is False


@pytest.mark.asyncio
async def test_dokladna_osoba_z_krotkich_slow_bez_skanu_profili() -> None:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        person = Candidate(
            name="Oý",
            lastname="Ąy",
            email=f"oy-{tag}@example.com",
            status=CandidateStatus.active,
        )
        db.add(person)
        await db.commit()
        clause = p.exact_person_filter(["Oý", "Ąy"])
        assert clause is not None
        assert not _WIDE_SUBSTRING.search(_sql(clause))
        found = set((await db.scalars(select(Candidate.id).where(clause))).all())
    assert person.id in found


# ── Paleta ⌘K: cała trasa bez podłańcucha po CV i profilach ──────────────────


@pytest.mark.asyncio
async def test_paleta_z_dwoma_znakami_nie_czyta_cv_ani_profili(
    app_client, app_auth_headers
) -> None:
    """Parametry palety: dwa znaki to całe słowo przez indeks, a sprawdzenie
    „czy to czyjeś imię” — sama równość. Żadne zapytanie trasy nie szuka
    podłańcucha w długich kolumnach."""
    p._person_token_cache.clear()
    with keyword_corpus.force_folded_search(True), _capture_sql() as seen:
        resp = await app_client.get(
            "/api/candidates",
            params={"q": "qz", "page_size": 5, **LOOKUP_PARAMS},
            headers=app_auth_headers,
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()["text_mode_applied"] == "literal"
    scans = [s for s in seen if _WIDE_SUBSTRING.search(s)]
    assert scans == []
