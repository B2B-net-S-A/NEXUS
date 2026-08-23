"""``candidates.embedding_id`` — znacznik "ma wektor", który kłamał w obie strony.

Kolumna jest zapisywana jako ``str(candidate_id)`` (`embedding_service.embed_candidate`),
więc jej jedyną treścią jest "NULL czy nie". Mierzyła obecność wektora w Qdrancie,
a rozjeżdżała się z nim na dwa sposoby:

* **na TAK** — kwarantanna tożsamości kasowała punkt z Qdranta i kolumny nie
  czyściła, więc kandydat bez wektora dalej twierdził, że go ma;
* **na NIE** — ``scripts/reembed_collections.py`` upsertował wektory i kolumny nie
  ustawiał; na produkcji 2026-08-07 kolumna mówiła 45 317, a Qdrant trzymał
  47 921 punktów (~2 604 kandydatów z wektorem i pustą kolumną).

Obie luki są tu domknięte, ale kolumna **nadal nie jest autorytetem** i te testy
tego pilnują: wektor da się usunąć poza każdą ścieżką zapisu, którą ten kod
kontroluje (ręczny ``delete`` w Qdrancie, przebudowa kolekcji, odtworzenie ze
starszej migawki). Autorytetem jest wyłącznie
``embedding_service.indexed_candidate_ids`` — pyta Qdranta i zwraca ``None``,
gdy nie umie odpowiedzieć.

Każda z tych regresji jest CICHA: nic nie pada, tylko liczby przestają się
zgadzać, a predykat na tej kolumnie albo pomija kandydatów z wektorem, albo
zapętla się na kandydatach bez niego (tak było w narzędziu do #130).
"""

from __future__ import annotations

import ast
import pathlib
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.dialects import postgresql

import scripts.reembed_collections as reembed
from app.models.index_outbox import IndexOutboxEvent
from app.services import candidate_identity_quarantine as quarantine
from app.services.candidate_column_coverage import ColumnCoverage

BACKEND_ROOT = pathlib.Path(__file__).resolve().parent.parent


# ── Kwarantanna: kolumna nie może przeżyć wektora, który unieważnia ──────────


class _Rows:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    def all(self) -> list:
        return self._rows


class _ProjectionDB:
    """Minimalne lustro `AsyncSession` używane przez `_clear_quarantined_cv_projection`."""

    def __init__(self, *scalars, language_batches: list[list] | None = None) -> None:
        self._scalars = list(scalars)
        self._language_batches = list(language_batches or [[], []])
        self.added: list[object] = []

    async def scalar(self, *_args, **_kwargs):
        return self._scalars.pop(0)

    async def scalars(self, *_args, **_kwargs):
        return _Rows(self._language_batches.pop(0))

    def add(self, value: object) -> None:
        self.added.append(value)


def _quarantined_candidate() -> SimpleNamespace:
    return SimpleNamespace(
        id=11,
        cv_extracted_data={},
        raw_cv_text="wrong raw text",
        cv_filename="wrong.pdf",
        cv_parsed_at=datetime.now(timezone.utc),
        ai_summary=None,
        skills=[],
        education=[],
        experience=[],
        years_it_experience=None,
        email=None,
        phone=None,
        city=None,
        country="PL",
        location="PL",
        linkedin=None,
        languages_version=1,
        languages=[],
        # Stan sprzed kwarantanny: kolumna mówi "wektor jest".
        embedding_id="11",
    )


async def _run_quarantine(
    monkeypatch: pytest.MonkeyPatch,
    *,
    delete_succeeds: bool,
) -> tuple[SimpleNamespace, _ProjectionDB]:
    async def noop(*_args, **_kwargs):
        return None

    monkeypatch.setattr("app.services.match_score_cache.mark_stale_for_candidate", noop)
    monkeypatch.setattr(
        "app.services.embedding_service.delete_candidate_embedding",
        AsyncMock(return_value=delete_succeeds),
    )

    candidate = _quarantined_candidate()
    document = SimpleNamespace(
        id=22, filename="wrong.pdf", content_sha256="a" * 64, is_primary=True
    )
    db = _ProjectionDB(candidate, document, language_batches=[[], []])
    await quarantine._clear_quarantined_cv_projection(
        db,  # type: ignore[arg-type]
        candidate_id=11,
        source_kind="document",
        source_id=22,
    )
    return candidate, db


@pytest.mark.asyncio
async def test_quarantine_clears_the_column_together_with_the_vector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate, _db = await _run_quarantine(monkeypatch, delete_succeeds=True)

    assert candidate.embedding_id is None, (
        "punkt zniknął z Qdranta, więc kolumna nie może dalej twierdzić, "
        "że kandydat ma wektor"
    )


@pytest.mark.asyncio
async def test_column_is_cleared_even_when_the_immediate_delete_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nieudane kasowanie nie jest powodem, żeby zostawić kolumnę na "TAK".

    Intencją kwarantanny jest brak wektora; nieudane kasowanie ma trwały retry
    w outboksie. Warunkowanie zapisu wynikiem kasowania zostawiałoby kolumnę
    twierdzącą "wektor jest" akurat w tym przypadku, w którym system NIE WIE,
    czy jest — czyli tam, gdzie kłamstwo jest najkosztowniejsze.
    """
    candidate, db = await _run_quarantine(monkeypatch, delete_succeeds=False)

    assert candidate.embedding_id is None
    retries = [e for e in db.added if isinstance(e, IndexOutboxEvent)]
    assert [e.operation for e in retries] == ["delete"]


# ── Skrypt masowego re-embedu: wektor bez znacznika ──────────────────────────


class _FakeResult:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    def all(self) -> list:
        return self._rows

    def scalars(self) -> _Rows:
        return _Rows(self._rows)


class _RecordingSession:
    """Sesja, która oddaje zaplanowane wyniki i zapamiętuje każde zapytanie."""

    def __init__(self, results: list, log: list) -> None:
        self._results = results
        self._log = log
        self.commits = 0

    async def __aenter__(self) -> "_RecordingSession":
        return self

    async def __aexit__(self, *_exc) -> bool:
        return False

    async def execute(self, statement, *_args, **_kwargs) -> _FakeResult:
        self._log.append(statement)
        return _FakeResult(self._results.pop(0) if self._results else [])

    async def commit(self) -> None:
        self.commits += 1


@pytest.mark.asyncio
async def test_bulk_reembed_marks_every_row_it_pushed_into_qdrant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    statements: list = []
    sessions: list[_RecordingSession] = []
    # Kolejno: lista id → wiersze kandydatów → UPDATE znacznika.
    scripted = [
        [(1,), (2,)],
        [
            SimpleNamespace(id=1, competence_category="dev"),
            SimpleNamespace(id=2, competence_category=None),
        ],
        [],
    ]

    def _session_factory() -> _RecordingSession:
        session = _RecordingSession(scripted, statements)
        sessions.append(session)
        return session

    monkeypatch.setattr(reembed, "AsyncSessionLocal", _session_factory)
    monkeypatch.setattr(reembed, "_collection", lambda: "nexus_candidates")
    monkeypatch.setattr(reembed, "_build_candidate_text", lambda _c: "cv text")
    monkeypatch.setattr(
        reembed, "_voyage_embed_batch", AsyncMock(return_value=[[0.1], [0.2]])
    )
    upsert = AsyncMock(return_value=2)
    monkeypatch.setattr(reembed, "_bulk_upsert_qdrant", upsert)

    processed, succeeded, failed = await reembed._reembed_candidates(
        commit=True, batch=10, limit=None, log_every=1000
    )

    assert (processed, succeeded, failed) == (2, 2, 0)
    assert upsert.await_count == 1

    updates = [s for s in statements if s.__visit_name__ == "update"]
    assert len(updates) == 1, (
        "wektory poszły do Qdranta, więc znacznik MUSI zostać dopisany — bez "
        "tego kolumna nadal mówi 'brak wektora' dla świeżo zaindeksowanych"
    )
    compiled = updates[0].compile(
        dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
    )
    sql = str(compiled)
    assert "UPDATE candidates" in sql
    assert "embedding_id" in sql
    # Znacznik jest KOPIĄ identyfikatora — parytet z `embed_candidate`, który
    # zapisuje `str(candidate_id)`. Inna wartość zmieniłaby znaczenie kolumny.
    assert "CAST(candidates.id AS VARCHAR)" in sql
    assert "IN (1, 2)" in sql
    assert sessions[-1].commits == 1


@pytest.mark.asyncio
async def test_failed_qdrant_upsert_does_not_mark_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Znacznik bez wektora to dokładnie to kłamstwo, które naprawiamy."""
    statements: list = []
    scripted = [[(1,)], [SimpleNamespace(id=1, competence_category=None)], []]

    monkeypatch.setattr(
        reembed, "AsyncSessionLocal", lambda: _RecordingSession(scripted, statements)
    )
    monkeypatch.setattr(reembed, "_collection", lambda: "nexus_candidates")
    monkeypatch.setattr(reembed, "_build_candidate_text", lambda _c: "cv text")
    monkeypatch.setattr(reembed, "_voyage_embed_batch", AsyncMock(return_value=[[0.1]]))
    monkeypatch.setattr(
        reembed,
        "_bulk_upsert_qdrant",
        AsyncMock(side_effect=RuntimeError("qdrant down")),
    )

    _processed, succeeded, failed = await reembed._reembed_candidates(
        commit=True, batch=10, limit=None, log_every=1000
    )

    assert (succeeded, failed) == (0, 1)
    assert [s for s in statements if s.__visit_name__ == "update"] == []


@pytest.mark.asyncio
async def test_marking_failure_never_reports_the_embed_as_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Wektor jest w Qdrancie — to on jest autorytetem, nie znacznik.

    Gdyby padnięty UPDATE przewracał `_reembed_candidates`, awaria bazy
    kasowałaby raport z pracy, za którą już zapłaciliśmy Voyage'owi.
    """

    class _ExplodingSession(_RecordingSession):
        async def execute(self, statement, *args, **kwargs):
            if getattr(statement, "__visit_name__", "") == "update":
                raise RuntimeError("db down")
            return await super().execute(statement, *args, **kwargs)

    scripted = [[(1,)], [SimpleNamespace(id=1, competence_category=None)], []]
    monkeypatch.setattr(
        reembed, "AsyncSessionLocal", lambda: _ExplodingSession(scripted, [])
    )
    monkeypatch.setattr(reembed, "_collection", lambda: "nexus_candidates")
    monkeypatch.setattr(reembed, "_build_candidate_text", lambda _c: "cv text")
    monkeypatch.setattr(reembed, "_voyage_embed_batch", AsyncMock(return_value=[[0.1]]))
    monkeypatch.setattr(reembed, "_bulk_upsert_qdrant", AsyncMock(return_value=1))

    _processed, succeeded, failed = await reembed._reembed_candidates(
        commit=True, batch=10, limit=None, log_every=1000
    )

    assert (succeeded, failed) == (1, 0)


# ── Strażnik: kolumna nadal NIE jest autorytetem ─────────────────────────────


def _reads_in_tree(tree: ast.AST, rel: str) -> list[str]:
    """Dopasowanie jednego drzewa — WSPÓLNE dla sweepu po repo i dla testu niżej.

    Wydzielone celowo: dopóki `test_the_guard_actually_sees_reads_of_this_column`
    powtarzał ten przebieg u siebie, literówka w nazwie atrybutu TUTAJ zostawiała
    oba testy zielone (zweryfikowane: jednoznakowa podmiana + realny odczyt
    w `candidate_column_coverage` → 8 passed). Enumerujący strażnik potrzebuje
    dowodu przechodzącego przez TEN SAM kod, nie przez jego kopię.
    """
    hits: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute) or node.attr != "embedding_id":
            continue
        if not isinstance(node.ctx, ast.Load):
            continue
        base = node.value
        base_name = base.id if isinstance(base, ast.Name) else None
        if base_name in {"Candidate", "candidate"}:
            hits.append(f"{rel}:{node.lineno}")
    return hits


def _candidate_embedding_id_reads() -> list[str]:
    """Odczyty ``Candidate.embedding_id`` / ``candidate.embedding_id`` w kodzie.

    Zapis (`ctx=Store`) jest w porządku — od tego kolumna jest. Problemem jest
    ODCZYT, bo każdy odczyt tej kolumny jest predykatem "ma wektor", a ona na to
    pytanie nie odpowiada wiarygodnie. ``Job.embedding_id`` i
    ``CompetenceCategory.embedding_id`` są poza zakresem: to inne encje i inne
    kolekcje, o których to ustalenie nic nie mówi.

    Granice strażnika, świadome, żeby nie sprzedawał pewności, której nie ma:
    łapie wyłącznie bazy nazwane ``Candidate``/``candidate``, więc odczyt przez
    alias (``c.embedding_id`` w pętli skryptu) przez niego przejdzie —
    poszerzenie listy o krótkie nazwy dałoby fałszywe trafienia na ofertach
    i kategoriach kompetencji. Nie widzi też surowego SQL-a: jedyny dziś
    istniejący odczyt tej kolumny — ``candidate_column_coverage._COLUMNS`` —
    jest stringiem i pilnuje go osobno
    ``test_coverage_block_labels_the_number_as_an_estimate``. Dlatego lista
    dozwolonych jest PUSTA: w warstwie ORM ta kolumna nie ma dziś ani jednego
    czytelnika i nie powinna go zyskać po cichu.
    """
    hits: list[str] = []
    for root in ("app", "scripts"):
        for path in sorted((BACKEND_ROOT / root).rglob("*.py")):
            rel = path.relative_to(BACKEND_ROOT).as_posix()
            tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
            hits.extend(_reads_in_tree(tree, rel))
    return hits


def test_no_code_path_reads_candidates_embedding_id_as_a_predicate() -> None:
    """Naprawa obu rozjazdów NIE czyni z kolumny prawdy.

    Wektor da się usunąć poza każdą ścieżką, którą ten kod kontroluje, więc
    predykat na tej kolumnie znów zacznie się mylić — tyle że rzadziej i przez
    to trudniej. Narzędzie z #130 kupiło na takim predykacie nieskończoną pętlę
    (kandydat po kwarantannie wracał po każdym przeliczeniu) i trwałe pomijanie
    ~2 604 kandydatów naraz. Pytaj `embedding_service.indexed_candidate_ids`.
    """
    offenders = _candidate_embedding_id_reads()
    assert offenders == [], (
        "candidates.embedding_id użyte jako predykat 'ma wektor' w: "
        f"{offenders}. Autorytetem jest embedding_service.indexed_candidate_ids "
        "(pyta Qdranta, zwraca None przy awarii zamiast udawać pustkę)."
    )


def test_the_guard_actually_sees_reads_of_this_column() -> None:
    """Strażnik enumerujący potrzebuje dowodu, że nie enumeruje pustki.

    Dowód MUSI iść przez `_reads_in_tree` — tę samą funkcję, której używa sweep
    po repo. Powtórzenie przebiegu AST u siebie sprawdzałoby moduł `ast`, a nie
    strażnika: literówka w nazwie atrybutu w matcherze zostawiała wtedy oba testy
    zielone, także przy realnym odczycie kolumny w kodzie.
    """
    source = "def f(candidate):\n    return candidate.embedding_id\n"
    assert _reads_in_tree(ast.parse(source), "fixture.py") == ["fixture.py:2"]

    # Zapis przechodzi — od tego kolumna jest; strażnik ma łapać wyłącznie ODCZYT.
    write = "def f(candidate):\n    candidate.embedding_id = None\n"
    assert _reads_in_tree(ast.parse(write), "fixture.py") == []


def test_coverage_block_labels_the_number_as_an_estimate() -> None:
    """80,1% w prompcie czytane jak zmierzony fakt prowadzi do zbędnego backfillu.

    Marker celowo NIE używa "←": ten znak niesie w bloku inne znaczenie
    ("kolumna zbyt rzadka, żeby po niej filtrować"), a tu liczba jest niepewna,
    nie niska. Blok jest też parsowany po pierwszym "%", więc marker nie może
    go zawierać.
    """
    block = ColumnCoverage(
        total=56769,
        pct={"embedding_id": 80.1, "raw_cv_text": 69.0, "skills": 0.5},
    ).as_prompt_block()

    line = next(
        ln for ln in block.splitlines() if ln.strip().startswith("embedding_id")
    )
    assert "dolna granica" in line
    assert "←" not in line
    assert line.split("%")[0].split()[-1] == "80.1"

    dense = next(
        ln for ln in block.splitlines() if ln.strip().startswith("raw_cv_text")
    )
    assert "dolna granica" not in dense, "to jest pomiar kolumny, nie oszacowanie"
