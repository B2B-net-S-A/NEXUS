"""Fragmenty umowy ramowej dla Jarvisa — podział, ranking po słowach, wybór.

Zgłoszenie 09.10.2026: pytanie „ile Bank Pocztowy ma czasu na akceptację Karty
Czasu Pracy”. Umowa nie zna tej nazwy — pisze „Karta Ewidencji Świadczenia
Usług” — więc te testy pilnują zapasu po słowach na takim właśnie przypadku
(treść poniżej jest fikcyjna).
"""

from __future__ import annotations

from app.services import framework_contract_text as fct
from app.services.framework_contract_text import ChunkRef

_FILLER = (
    "Wykonawca zobowiązuje się świadczyć Usługi z należytą starannością, zgodnie "
    "z Umową oraz obowiązującymi przepisami prawa.\n"
)
_CLAUSE = (
    "§ 7 Rozliczenia\n"
    "1. Specjalista sporządza Kartę Ewidencji Świadczenia Usług za każdy miesiąc.\n"
    "2. Zamawiający akceptuje Kartę albo zgłasza uwagi w terminie 5 Dni Roboczych "
    "od dnia jej otrzymania.\n"
)


def _contract_text() -> str:
    return (_FILLER * 30) + _CLAUSE + (_FILLER * 30)


def _refs(text: str, *, contract_id: int = 40, first_id: int = 1) -> list[ChunkRef]:
    return [
        ChunkRef(id=first_id + i, contract_id=contract_id, index=i, text=chunk)
        for i, chunk in enumerate(fct.split_into_chunks(text))
    ]


def test_chunks_are_contiguous_and_bounded():
    text = _contract_text()
    chunks = fct.split_into_chunks(text)

    assert "".join(chunks) == text
    assert len(chunks) > 5
    assert all(chunk.strip() for chunk in chunks)
    assert max(len(chunk) for chunk in chunks) <= fct.MAX_CHUNK_CHARS


def test_paragraph_sign_starts_a_new_chunk():
    before = _FILLER * 3
    assert fct.MIN_SECTION_CHARS <= len(before) < fct.TARGET_CHUNK_CHARS

    chunks = fct.split_into_chunks(before + _CLAUSE + _FILLER)

    assert chunks[0] == before
    assert chunks[1].startswith("§ 7 Rozliczenia")


def test_short_paragraphs_stay_together():
    """Trzy krótkie paragrafy to jeden fragment, nie trzy bez kontekstu."""
    text = "§ 1 Definicje\nA.\n§ 2 Przedmiot\nB.\n§ 3 Czas trwania\nC.\n"

    assert fct.split_into_chunks(text) == [text]


def test_one_long_line_is_cut_on_whitespace():
    """DOCX oddaje akapit jako jedną linię — bez cięcia byłby jednym fragmentem."""
    text = "słowo " * 2000
    chunks = fct.split_into_chunks(text)

    assert "".join(chunks) == text
    assert max(len(chunk) for chunk in chunks) <= fct.MAX_CHUNK_CHARS
    assert all(chunk.endswith(" ") for chunk in chunks)


def test_empty_text_gives_no_chunks():
    assert fct.split_into_chunks("") == []
    assert fct.split_into_chunks("  \n\n ") == []


def test_stems_survive_polish_inflection():
    stems = fct.query_stems("Ile czasu na akceptację Karty Czasu Pracy?")

    # „karty” → „kart” trafia „Kartę”, „akceptację” → „akcep” trafia „akceptuje”.
    assert "kart" in stems and "akcep" in stems
    assert "ile" not in stems and "na" not in stems
    assert len(stems) == len(set(stems))


def test_keyword_ranking_finds_the_clause_under_another_name():
    refs = _refs(_contract_text())
    stems = fct.query_stems(
        "ile bank pocztowy ma czasu na akceptację karty czasu pracy"
    )

    ranked = fct.rank_by_keywords(stems, refs)

    assert ranked, "zapas po słowach musi coś znaleźć"
    best = next(ref for ref in refs if ref.id == ranked[0])
    assert "5 Dni Roboczych" in best.text


def test_keyword_ranking_returns_nothing_without_a_hit():
    refs = _refs(_contract_text())

    assert fct.rank_by_keywords(fct.query_stems("timesheet"), refs) == []
    assert fct.rank_by_keywords([], refs) == []


def test_passages_respect_budget_and_merge_neighbours():
    refs = _refs(_contract_text())
    clause = next(ref for ref in refs if "5 Dni Roboczych" in ref.text)
    neighbour = next(ref for ref in refs if ref.index == clause.index + 1)
    far = refs[0]

    passages = fct.build_passages([clause.id, far.id, neighbour.id], refs, budget=4000)

    assert passages[0].first_chunk == clause.index
    assert passages[0].last_chunk == neighbour.index
    assert passages[0].text == clause.text + neighbour.text
    assert passages[1].first_chunk == passages[1].last_chunk == far.index
    assert sum(len(p.text) for p in passages) <= 4000


def test_passages_never_join_two_contracts():
    first = _refs("Umowa pierwsza. " * 20, contract_id=1, first_id=1)[:1]
    second = _refs("Umowa druga. " * 20, contract_id=2, first_id=100)[:1]

    passages = fct.build_passages(
        [first[0].id, second[0].id], first + second, budget=4000
    )

    assert [p.contract_id for p in passages] == [1, 2]


def test_budget_keeps_the_best_chunk_even_when_it_is_tight():
    refs = _refs(_contract_text())

    passages = fct.build_passages([r.id for r in refs], refs, budget=100)

    assert len(passages) == 1
    assert passages[0].first_chunk == refs[0].index
    assert len(passages[0].text) <= 100


def test_unknown_ids_are_ignored():
    """Punkt Qdranta bez wiersza w bazie (sierota po usuniętej umowie)."""
    refs = _refs(_contract_text())

    passages = fct.build_passages([999_999, refs[2].id], refs, budget=4000)

    assert [p.first_chunk for p in passages] == [refs[2].index]


def test_sequential_read_continues_where_it_stopped():
    refs = _refs(_contract_text())

    first, next_chunk = fct.read_in_order(refs, from_chunk=0, budget=2000)
    assert first is not None and first.first_chunk == 0
    assert next_chunk == first.last_chunk + 1

    second, _ = fct.read_in_order(refs, from_chunk=next_chunk, budget=2000)
    assert second is not None and second.first_chunk == next_chunk

    last, after_last = fct.read_in_order(refs, from_chunk=len(refs) - 1, budget=2000)
    assert last is not None and after_last is None

    assert fct.read_in_order(refs, from_chunk=len(refs), budget=2000) == (None, None)
