"""Komórki tabel Worda czytane wprost z XML-a wiersza.

``row.cells`` z python-docx oddaje komórkę tyle razy, ile wynosi jej
``gridSpan`` — a tę liczbę podaje plik, bez górnej granicy. CV z formularza
kariery, plik requestu i wzór Profilu Championa są niezaufane i czytane
w procesie aplikacji, więc jedna komórka z ``gridSpan="5000000"`` zajmowała
proces na minuty (#2112, #2119). Każdy czytnik wgranego pliku bierze komórki
stąd; pilnuje tego ``tests/test_docx_table_cells.py``.

Trzy kształty, bo czytniki różnie traktują scalenia:

- ``row_cells`` — komórki z własną treścią, każda raz;
- ``row_texts`` — teksty z zachowaniem pozycji kolumn (dalszy ciąg scalenia
  w pionie to pusty napis);
- ``grid_rows`` / ``grid_cell_texts`` — jak ``row.cells`` (komórka na każdą
  pozycję siatki, scalona powtórzona), ale z sufitem na ``gridSpan``, jednym
  przejściem po tabeli i limitem znaków; dla czytników, których wynik ma
  zostać bajt w bajt taki sam jak dotąd.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any

# Word nie pozwala na więcej niż 63 kolumny w tabeli — większy gridSpan nie
# pochodzi z prawdziwego dokumentu.
MAX_GRID_SPAN = 63

# Scalona komórka wraca w ``grid_cell_texts`` raz na każdą pozycję siatki, więc
# plik 60 KB potrafił dać setki MB tekstu. 2 mln znaków to ten sam sufit, który
# ma tekst z PDF-a (``cv_text_extractor._PDF_WORKER_MAX_CHARS``).
MAX_TABLE_TEXT_CHARS = 2_000_000

_CONTINUED = "continue"


def _cell(tc: Any, row: Any) -> Any:
    from docx.table import _Cell

    return _Cell(tc, row.table)


def row_cells(row: Any) -> list[Any]:
    """Komórki wiersza z własną treścią — każda raz, bez względu na ``gridSpan``.

    Komórka będąca dalszym ciągiem scalenia w pionie nie ma własnej treści
    (leży w komórce nad nią), więc jest pomijana.
    """
    return [_cell(tc, row) for tc in row._tr.tc_lst if tc.vMerge != _CONTINUED]


def row_texts(row: Any) -> list[str]:
    """Teksty komórek wiersza, po jednym na ``w:tc``.

    Dalszy ciąg scalenia w pionie daje pusty napis, żeby kolejne kolumny
    zostały na swoich pozycjach (odczyt formularza po numerze kolumny).
    """
    return [
        "" if tc.vMerge == _CONTINUED else _cell(tc, row).text.strip()
        for tc in row._tr.tc_lst
    ]


def grid_rows(table: Any) -> Iterator[list[Any]]:
    """Wiersze tabeli jako komórki na każdą pozycję siatki — jak ``row.cells``.

    Dla dokumentu, który da się zapisać w Wordzie, wynik jest identyczny
    z ``row.cells``: scalenie w poziomie powtarza komórkę, a dalszy ciąg
    scalenia w pionie oddaje komórkę, od której scalenie się zaczyna. Różnice
    dotyczą tylko pliku spreparowanego:

    - ``gridSpan`` ma sufit ``MAX_GRID_SPAN``;
    - początek scalenia w pionie jest niesiony z wiersza na wiersz. python-docx
      wspina się po niego osobno z każdego wiersza, więc tabela o tysiącach
      wierszy scalonych w jedną komórkę kosztowała kwadratowo (2000 wierszy
      = 2 minuty);
    - dalszy ciąg scalenia bez początku nad sobą (python-docx rzuca wtedy
      ``ValueError``) jest czytany jak zwykła komórka.
    """
    from docx.table import _Cell

    above: dict[int, Any] = {}
    for tr in table._tbl.tr_lst:
        roots: dict[int, Any] = {}
        cells: list[Any] = []
        offset = tr.grid_before
        for tc in tr.tc_lst:
            root = above.get(offset, tc) if tc.vMerge == _CONTINUED else tc
            roots[offset] = root
            # Pozycje liczy się własnym gridSpan komórki (tak jak python-docx),
            # powtórzeń jest tyle, ile wynosi gridSpan początku scalenia.
            offset += tc.grid_span
            cells.extend([_Cell(root, table)] * min(root.grid_span, MAX_GRID_SPAN))
        above = roots
        yield cells


def grid_cell_texts(tables: Iterable[Any]) -> list[str]:
    """Niepuste teksty komórek tabel w kolejności ``row.cells``, do limitu znaków."""
    texts: list[str] = []
    total = 0
    for table in tables:
        for cells in grid_rows(table):
            for cell in cells:
                text = cell.text
                if not text:
                    continue
                texts.append(text)
                total += len(text)
                if total >= MAX_TABLE_TEXT_CHARS:
                    return texts
    return texts
