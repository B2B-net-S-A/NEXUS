"""Chunker CV — własności, na których opiera się rozmiar kolekcji.

Rozmiar indeksu pasaży jest twardo ograniczony: kontener Qdranta ma 2 GB RAM.
Liczba pasaży na CV przekłada się wprost na zużycie pamięci, więc reguły cięcia
nie są kosmetyką.
"""

from app.services.cv_passages import (
    MAX_CHARS,
    MIN_CHARS,
    Passage,
    estimate_passage_count,
    split_cv_into_passages,
)

CV = """Jan Kowalski
Senior Python Developer

DOŚWIADCZENIE

2019-2024 Acme Corp — Senior Backend Developer
Projektowanie i rozwój usług w Pythonie (FastAPI, SQLAlchemy). Migracja
monolitu do architektury usługowej. Optymalizacja zapytań PostgreSQL,
wprowadzenie indeksów pokrywających i partycjonowania tabel zdarzeń.

2015-2019 Beta Sp. z o.o. — Backend Developer
Utrzymanie i rozwój API w Django. Integracje z systemami płatności.
Wdrożenie kolejek zadań opartych o Celery i Redis.

WYKSZTAŁCENIE
Politechnika Warszawska, Informatyka, magister inżynier
"""


def test_empty_input_yields_nothing():
    assert split_cv_into_passages(None) == []
    assert split_cv_into_passages("") == []
    assert split_cv_into_passages("   \n\n  ") == []


def test_passages_are_deterministic():
    """Nadpisywanie punktów w Qdrancie opiera się na stabilnych indeksach.

    Gdyby ten sam tekst dawał różne cięcia, ponowny przebieg dopisywałby
    duplikaty zamiast zastępować — indeks rósłby przy każdym imporcie.
    """

    first = split_cv_into_passages(CV)
    second = split_cv_into_passages(CV)
    assert [(p.index, p.text) for p in first] == [(p.index, p.text) for p in second]


def test_indexes_are_dense_and_start_at_zero():
    passages = split_cv_into_passages(CV)
    assert [p.index for p in passages] == list(range(len(passages)))


def test_no_passage_exceeds_the_hard_ceiling():
    """Pasaż wielkości całego CV to powrót do uśredniania, przed którym uciekamy."""

    long_cv = "Zdanie o pracy w Pythonie. " * 400  # ~10 800 znaków, bez akapitów
    for passage in split_cv_into_passages(long_cv):
        # Zakładka doklejana z poprzednika może przekroczyć MAX o jej długość.
        assert len(passage.text) <= MAX_CHARS + 200, len(passage.text)


def test_single_block_without_punctuation_is_still_split():
    """CV po OCR bywa jednym blokiem bez kropek — twarde cięcie musi zadziałać."""

    blob = "a" * 9000
    passages = split_cv_into_passages(blob)
    assert len(passages) > 1, "blok bez interpunkcji musi zostać pocięty"


def test_tiny_tail_is_merged_not_indexed_separately():
    """Pasaż złożony z nagłówka dopasowałby się do wszystkiego.

    Krótki ogon dokleja się do poprzednika zamiast zostać osobnym punktem.
    """

    cv = "A" * 900 + "\n\n" + "B" * 20
    passages = split_cv_into_passages(cv)
    assert all(len(p.text) >= MIN_CHARS for p in passages)
    assert passages[-1].text.endswith("B" * 20)


def test_overlap_carries_the_boundary_forward():
    """Zdanie przecięte na granicy musi zostać w całości u sąsiada."""

    cv = "X" * 990 + "\n\n" + "Y" * 990
    passages = split_cv_into_passages(cv)
    assert len(passages) >= 2
    assert "X" in passages[1].text, "drugi pasaż musi nieść zakładkę z pierwszego"


def test_estimate_matches_actual_split():
    """Szacowanie rozmiaru kolekcji NIE może rozjeżdżać się z tym, co zapiszemy."""

    assert estimate_passage_count(CV) == len(split_cv_into_passages(CV))


def test_realistic_cv_stays_in_the_budgeted_range():
    """Mediana CV (3 556 znaków) ma dać kilka pasaży, nie kilkadziesiąt.

    Przy ~50 tys. kandydatów każdy dodatkowy pasaż na osobę to ~200 MB wektorów
    f32 — czyli różnica między zmieszczeniem się w 2 GB a niezmieszczeniem.
    """

    median_like = (CV + "\n\n") * 3  # ~2,7 tys. znaków, kształt realnego CV
    count = estimate_passage_count(median_like)
    assert 1 <= count <= 8, f"nietypowa liczba pasaży: {count}"


def test_passage_is_frozen():
    """Pasaż jest tożsamością punktu w indeksie — nie wolno go mutować w locie."""

    import dataclasses

    assert dataclasses.fields(Passage)
    passage = split_cv_into_passages(CV)[0]
    try:
        passage.text = "zmiana"  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        return
    raise AssertionError("Passage musi być frozen")
