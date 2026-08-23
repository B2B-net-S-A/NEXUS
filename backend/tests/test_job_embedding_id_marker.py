"""``jobs.embedding_id`` — znacznik "ma wektor", który cicho wycinał trzy powierzchnie.

Kolumna jest zapisywana jako ``str(job_id)`` (``embedding_service.embed_job``),
więc jej jedyną treścią jest "NULL czy nie". ``embed_job`` upsertuje wektor do
Qdranta **przed** ``db.commit()`` stempla, a całość jest w ``except Exception:
return False`` — więc padnięty commit zostawia wektor w kolekcji i pustą
kolumnę, a wołający dostaje tylko ``False``, który wszystkie ścieżki zapisu
odrzucają.

To boli inaczej niż u kandydatów, gdzie kolumna jest wyłącznie statystyką:
tutaj trzy miejsca używały jej jako BRAMKI — ``marketplace_service`` oraz oba
tiery ``question_suggestions`` — i oferta z wektorem cicho przestawała
generować propozycje i podpowiedzi pytań. Bez błędu, bez ponowienia: sweeper
marketplace filtruje po ``Job.updated_at``, a nieudany stempel nie bumpuje
``updated_at``, więc po dwóch godzinach oferta wypada z okna na zawsze.

Ten strażnik pilnuje granicy, która została po naprawie: **odczyt wartości
kolumny na INSTANCJI oferty jest predykatem "ma wektor", a ona na to pytanie
nie odpowiada wiarygodnie.** Dozwolony jest dokładnie jeden taki odczyt — ten,
który podaje wartość do ``embedding_service.job_has_vector``, czyli do
WSPÓLNEGO autorytetu. Każdy inny to nowa kopia bramki.

Świadomie NIE jest zabroniony ``Job.embedding_id`` na poziomie KLASY
(``select(...).where(Job.embedding_id.is_(None))``): to nie predykat na jednej
ofercie, tylko wybór wierszy do naprawy — dokładnie do tego ta kolumna służy.
"""

from __future__ import annotations

import ast

import pytest

from tests.test_candidate_embedding_id_marker import BACKEND_ROOT

# Jedyny dozwolony odczyt wartości kolumny na instancji oferty: przekazanie jej
# do wspólnego autorytetu. Lekcja z #1235 (helper skopiowany czterokrotnie):
# strażnik ma wymuszać WSPÓŁDZIELENIE, nie tylko poprawność jednego przebiegu.
_COLUMN = "embedding_id"
_SHARED_AUTHORITY = "job_has_vector"


def _instance_reads(tree: ast.AST, rel: str) -> list[str]:
    """Odczyty ``<cokolwiek>.embedding_id`` poza wywołaniem wspólnego autorytetu.

    Dopasowujemy po NAZWIE ATRYBUTU, a nie po nazwie bazy. Pierwsza wersja tego
    strażnika wymagała bazy nazwanej dosłownie ``job`` i była przez to ŚLEPA na
    dominujący idiom tego repo: czwarta bramka napisana jako
    ``for j in jobs: ... if not j.embedding_id: continue`` przechodziła na
    zielono (sprawdzone mutacją). ``for j in <...>jobs`` występuje w ``app/``
    17 razy wobec 13 dla ``for job in``, a pola Joba czytane jako ``j.<pole>``
    ponad sto razy — w tym w bezpośrednim sąsiedztwie miejsc, gdzie czwarta
    bramka najpewniej powstanie. Strażnik, który przepuszcza najbardziej
    prawdopodobny zapis regresji, jest zielony w dniu, w którym miał zadziałać,
    i jednocześnie produkuje fałszywą pewność.

    Dwa wyłączenia, oba konieczne:

    * baza pisana WIELKĄ literą (``Job.embedding_id``,
      ``CompetenceCategory.embedding_id``) to wybór wierszy w zapytaniu, a nie
      predykat na jednej ofercie — to jedyna sensowna droga do naprawy dryfu
      (``WHERE embedding_id IS NULL``) i zakazywanie jej byłoby zakazem bez
      alternatywy;
    * argumenty wywołania ``job_has_vector`` — w OBU formach, także
      ``getattr``. Pierwsza wersja sprawdzała listę dozwolonych wyłącznie dla
      dostępu przez atrybut, więc sankcjonowane
      ``job_has_vector(job.id, getattr(job, "embedding_id", None))`` zgłaszała
      jako naruszenie: za wąska i za szeroka naraz.
    """
    allowed: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        fn_name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", None)
        if fn_name != _SHARED_AUTHORITY:
            continue
        for arg in node.args:
            allowed.add(id(arg))

    def _is_class_base(base: ast.AST) -> bool:
        """``Job.embedding_id`` — wybór wierszy, nie predykat na instancji."""
        name = None
        if isinstance(base, ast.Name):
            name = base.id
        elif isinstance(base, ast.Attribute):
            name = base.attr
        return bool(name) and name[0].isupper()

    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == _COLUMN:
            if not isinstance(node.ctx, ast.Load):
                continue
            if _is_class_base(node.value):
                continue
            if id(node) not in allowed:
                hits.append(f"{rel}:{node.lineno}")
        elif isinstance(node, ast.Call):
            fn = node.func
            if getattr(fn, "id", None) != "getattr" or len(node.args) < 2:
                continue
            name = node.args[1]
            if not (isinstance(name, ast.Constant) and name.value == _COLUMN):
                continue
            if _is_class_base(node.args[0]):
                continue
            if id(node) not in allowed:
                hits.append(f"{rel}:{node.lineno}")
    return hits


def _job_embedding_id_instance_reads() -> list[str]:
    hits: list[str] = []
    for root in ("app", "scripts"):
        for path in sorted((BACKEND_ROOT / root).rglob("*.py")):
            rel = path.relative_to(BACKEND_ROOT).as_posix()
            tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
            hits.extend(_instance_reads(tree, rel))
    return hits


def test_no_surface_reads_the_job_column_as_a_gate():
    """Lista dozwolonych jest PUSTA — poza przekazaniem do wspólnego autorytetu.

    Trzy bramki (#403) były trzema kopiami tego samego predykatu. Jeśli ten test
    zaczyna padać, ktoś dopisał czwartą: albo przepuść wartość przez
    ``job_has_vector``, albo — gdy ta powierzchnia wektora oferty w ogóle nie
    używa (jak skan marketplace) — nie pytaj o niego wcale.
    """
    assert _job_embedding_id_instance_reads() == []


def test_the_guard_actually_sees_a_gate_and_lets_the_authority_through():
    """Enumerujący strażnik potrzebuje dowodu, że w ogóle coś widzi.

    Strażnik, który nic nie łapie, jest zielony także wtedy, gdy literówka w
    nazwie atrybutu wyłączyła mu dopasowanie — a właśnie tak wygląda cicha
    śmierć strażnika (patrz komentarz w bliźniaczym teście kandydackim).
    """
    gate = ast.parse("if not job.embedding_id:\n    pass\n")
    assert _instance_reads(gate, "x.py") == ["x.py:1"]

    getattr_gate = ast.parse('if not getattr(job, "embedding_id", None):\n    pass\n')
    assert _instance_reads(getattr_gate, "x.py") == ["x.py:1"]

    # Mutacja, która POKONAŁA pierwszą wersję strażnika: baza nazwana `j`,
    # czyli dominujący idiom tego repo. Wcześniej: 10 passed, zero czerwieni.
    dominant_idiom = ast.parse(
        "for j in jobs:\n    if not j.embedding_id:\n        continue\n"
    )
    assert _instance_reads(dominant_idiom, "x.py") == ["x.py:2"], (
        "strażnik ślepy na `j.embedding_id` przepuszcza najbardziej "
        "prawdopodobny zapis czwartej bramki"
    )

    # Inne bazy, których pierwsza wersja też nie widziała.
    for src, label in (
        ("if not row.embedding_id:\n    pass\n", "row"),
        ("if not self.job.embedding_id:\n    pass\n", "self.job"),
        ("if not the_job.embedding_id:\n    pass\n", "the_job"),
    ):
        assert _instance_reads(ast.parse(src), "x.py") == ["x.py:1"], (
            f"baza `{label}` nierozpoznana"
        )

    through_authority = ast.parse("await job_has_vector(job.id, job.embedding_id)\n")
    assert _instance_reads(through_authority, "x.py") == []

    # Sankcjonowane wywołanie w formie `getattr` — pierwsza wersja sprawdzała
    # listę dozwolonych WYŁĄCZNIE dla dostępu przez atrybut, więc to zgłaszała
    # jako naruszenie: strażnik był za wąski i za szeroki naraz.
    through_authority_getattr = ast.parse(
        'await job_has_vector(job.id, getattr(job, "embedding_id", None))\n'
    )
    assert _instance_reads(through_authority_getattr, "x.py") == []

    # Odczyt na KLASIE to wybór wierszy (jedyna droga naprawy dryfu:
    # WHERE embedding_id IS NULL) — musi przechodzić.
    for src in (
        "select(Job.id).where(Job.embedding_id.is_(None))\n",
        "where(CompetenceCategory.embedding_id.is_(None))\n",
    ):
        assert _instance_reads(ast.parse(src), "x.py") == []

    class_level = ast.parse("select(Job.id).where(Job.embedding_id.is_(None))\n")
    assert _instance_reads(class_level, "x.py") == []


@pytest.mark.asyncio
async def test_column_narrows_for_free_and_qdrant_decides_only_on_the_negative():
    """Kolumna niepusta = odpowiedź bez ruchu sieciowego."""
    from app.services import embedding_service as es

    called: list[list[int]] = []

    async def _never(ids):  # pragma: no cover — ma się nie wykonać
        called.append(ids)
        raise AssertionError("Qdrant pytany mimo niepustej kolumny")

    orig = es.indexed_job_ids
    es.indexed_job_ids = _never
    try:
        assert await es.job_has_vector(7, "7") is True
    finally:
        es.indexed_job_ids = orig
    assert called == []


@pytest.mark.asyncio
async def test_outage_answers_unknown_not_absent(monkeypatch):
    """``None`` to "nie wiem" — awaria nie może udawać "nie ma wektora"."""
    from app.services import embedding_service as es

    async def _down(ids):
        return None

    monkeypatch.setattr(es, "indexed_job_ids", _down)
    assert await es.job_has_vector(7, None) is None


@pytest.mark.asyncio
async def test_vector_present_heals_the_column_in_place(monkeypatch):
    """Gdy Qdrant mówi TAK, kolumna jest naprawiana — następne pytanie jest darmowe.

    Bez tego każde kolejne wywołanie dla tej samej oferty znowu płaciłoby
    round-tripem, a ``POST /api/phase3/jobs/embed-all`` (``WHERE embedding_id IS
    NULL``) w kółko re-embedowałby wektor, który już jest w kolekcji.

    Qdrant jest tu podmieniony celowo: sprawdzamy naprawę stempla, a nie
    łączność — test nie ma prawa wymagać żywej kolekcji.
    """
    from sqlalchemy import text

    from app.core.database import AsyncSessionLocal
    from app.models.job import Job, JobStatus
    from app.services import embedding_service as es

    async with AsyncSessionLocal() as db:
        client_id = (
            await db.execute(text("SELECT id FROM clients LIMIT 1"))
        ).scalar_one_or_none()
        if client_id is None:
            pytest.skip("brak klienta w bazie testowej")
        job = Job(client_id=client_id, title="DRYF 403", status=JobStatus.draft)
        db.add(job)
        await db.commit()
        await db.refresh(job)
        job_id = job.id

    assert job.embedding_id is None

    async def _qdrant_says_yes(ids):
        return set(ids)

    monkeypatch.setattr(es, "indexed_job_ids", _qdrant_says_yes)
    assert await es.job_has_vector(job_id, None) is True

    async with AsyncSessionLocal() as db:
        healed = (
            await db.execute(
                text("SELECT embedding_id FROM jobs WHERE id = :i"), {"i": job_id}
            )
        ).scalar_one()
        await db.execute(text("DELETE FROM jobs WHERE id = :i"), {"i": job_id})
        await db.commit()

    assert healed == str(job_id)
