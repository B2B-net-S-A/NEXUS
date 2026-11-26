# Lista kandydatów: wyszukiwanie zwija się po „Szukaj”, fragmenty CV za przełącznikiem (26.11.2026)
<!-- indeks: `CollapsedSearchSummary`, `useUiStore.candidatesSearchCollapsed` / `candidatesSnippetsVisible`, bez kryteriów zawsze rozwinięte, okno „Szukaj ręcznie” bez zmian, „Kolumny” → „Fragmenty CV pod osobą”, przewodnik `candidates.list`, lekcja `lekcja-zwijane-wyszukiwanie` -->

Decyzja Artura z 26.11.2026 po prośbie rekrutera („kafelek z wyszukiwaniem
zajmuje prawie połowę okna, po ustaleniu filtrów chcę widzieć więcej
kandydatów”). Makiety ze stagingu: https://claude.ai/artifact/EevocZtyQjuBTfnBR9B1TZ
(wybrany wariant C zwijania i W2 przy wierszach). Na stagingu, konto rekrutera,
1280 × 720, wyszukiwanie z 4 wymaganiami po 5–11 wariantów: pole wymagań
i pigułki kończyły się na ok. 700 px, a tabela zaczynała się pod krawędzią
okna. Wiersz z fragmentami CV miał 175 px (64 dane + 28 „Ostatnio z osobą”
+ do 83 fragmentów), więc nawet bez filtrów mieściły się 2–3 osoby.

- **„Szukaj” zwija wyszukiwanie do jednej linii** (`CollapsedSearchSummary`
  w `CandidateFilterBar`): zdanie `describeKeywordSearch`, plakietki stawki,
  miasta i trybu pracy (te trzy nie mają chipów pod paskiem —
  `isChipShownOnFilterBar`), „+N filtrów” dla reszty, „Pokaż filtry”
  i „Szukaj”. Klik w zdanie też rozwija. „Zwiń wyszukiwanie” stoi w nagłówku
  „Słowa kluczowe”, bo na końcu rzędu pigułek spadał przy 1280 do drugiego
  rzędu pod dymek Jarvisa. Tabela zaczyna się wtedy ok. 255 px od góry.
- **Stan pamięta przeglądarka** (`useUiStore.candidatesSearchCollapsed`).
  Bez żadnych kryteriów (`totalActiveFilters === 0`) pasek jest zawsze
  rozwinięty — zwinięty nie miałby czego streszczać.
- **Fragmenty CV pod osobą są domyślnie schowane**; włącza je „Kolumny” →
  „Fragmenty CV pod osobą” (`useUiStore.candidatesSnippetsVisible`). Wyłączone
  = wiersz 92 px, 4–5 osób na ekranie. Linia „Ostatnio z osobą” zostaje
  zawsze (osobna decyzja z 18.11). Wysokość w `estimateSize` liczy fragmenty
  tylko przy włączonym przełączniku — inaczej wirtualizacja zostawia dziury.
- **Okno „Szukaj ręcznie” (`embed`) bez zmian:** nie zwija się, nie ma
  „Zwiń wyszukiwanie” i zawsze pokazuje fragmenty CV — tam rekruter porównuje
  osoby z wymaganiami Championa, a prośba dotyczyła listy.
- Testy listy zerują oba pola store w `beforeEach`; helper `bar()` rozwija
  zwinięty pasek przed szukaniem w nim przycisków.
