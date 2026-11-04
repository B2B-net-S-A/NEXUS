# Tabele Worda z wgranych plików — komórki przez `app/core/docx_cells.py` (11.10.2026)

`row.cells` z python-docx oddaje komórkę tyle razy, ile wynosi jej `gridSpan`,
a tę liczbę podaje plik — bez górnej granicy. CV z formularza kariery, plik
requestu, wzór Profilu Championa i załącznik zamówienia są niezaufane i czytane
w procesie aplikacji, więc jedna komórka z `gridSpan="5000000"` zajmowała
proces na minuty. #2112 naprawił import do edytora, #2119 odczyt w QC CV,
a 11.10.2026 pozostałe pięć czytników (`champion_document.document_text`
i `table_profile`, `cv_text_extractor._extract_docx`, oba `_extract_docx`
generatora CV).

- **Każdy czytnik wgranego pliku Worda bierze komórki z `app/core/docx_cells.py`:**
  - `row_cells(row)` — komórki z własną treścią, każda raz (dalszy ciąg
    scalenia w pionie pominięty); dla czytników, które i tak odrzucały
    powtórzenia;
  - `row_texts(row)` — teksty z zachowaniem pozycji kolumn (dalszy ciąg
    scalenia w pionie = pusty napis); dla odczytu formularza po numerze kolumny;
  - `grid_cell_texts(tables)` (na `grid_rows(table)`) — teksty w kolejności
    `row.cells`, scalona komórka powtórzona; dla czytników, których tekst ma
    zostać taki sam jak dotąd.
- **Trzy liczby z pliku, które sterowały kosztem** — każda ma teraz granicę
  w `grid_rows` / `grid_cell_texts`:
  - `gridSpan`: sufit `MAX_GRID_SPAN` = 63 (Word nie zapisze szerszej tabeli);
  - długość scalenia w pionie: `row.cells` wspina się do początku scalenia
    osobno z każdego wiersza, więc 600 wierszy scalonych w jedną komórkę
    czytało się 18 s, a 2000 — 2 minuty (plik 40 KB, pomiar 11.10.2026).
    `grid_rows` niesie początek scalenia z wiersza na wiersz: 20 000 wierszy
    = 1,8 s. Nie czytaj tabeli wiersz po wierszu przez `tc._tc_above`;
  - rozmiar tekstu: scalona komórka wraca raz na każdą pozycję siatki, więc
    plik 60 KB dawał ponad 1 GB tekstu. `MAX_TABLE_TEXT_CHARS` = 2 mln znaków
    (ten sam sufit co tekst z PDF-a) kończy odczyt tabel.
- **`cv_text_extractor` i `legacy_v7` zostają przy `grid_cell_texts`**, bo ich
  wynik powtarza tekst scalonej komórki, a na tym tekście stoją odczyt zamówień
  z DOCX-a (polityki per klient) i zamrożona ścieżka generatora `legacy_v7`.
  Zmiana na `row_cells` zmieniłaby treść idącą do modelu — to osobna decyzja
  z pomiarem, nie sprzątanie.
- Dalszy ciąg scalenia w pionie bez początku nad sobą (plik spreparowany albo
  zepsuty; python-docx rzuca `ValueError`) nie wywraca odczytu: `grid_rows`
  czyta go jak zwykłą komórkę, `row_cells` go pomija.
- **Strażnik:** `backend/tests/test_docx_table_cells.py` czyta drzewo składni
  całego `app/` i pada na każdym `.cells` poza listą `TRUSTED_DOCUMENTS`
  (dokumenty zbudowane przez nasz kod: szablony umów, wyrenderowane CV; oraz
  `pko_bp_layout.py`, gdzie `row.cells` to słownik kolumn PDF-a). Nowy plik na
  tej liście wymaga zdania, skąd pochodzi dokument.
- Lokalny Python 3.9 nie importuje pakietu generatora — pełny test biegnie
  w CI; lokalnie da się sprawdzić pomocników i `champion_document`.
