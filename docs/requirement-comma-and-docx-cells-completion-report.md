# Lista kandydatów: przecinek = kolejne wymaganie; tabele Worda bez `row.cells` — raport

Data: 11.10.2026. Polecenie Artura („to napraw to też”) do dwóch pozycji
zostawionych poza zakresem B2B-net-S-A/NEXUS#2120.

## Problem

| Co | Przed zmianą |
|---|---|
| Słowa kluczowe na liście kandydatów i w „Szukaj ręcznie” | przecinek i Enter dopisywały WARIANT do tego samego wiersza: „Java, Spring” dawało jedno wymaganie „Java lub Spring” (znajduje osoby z samą Javą), inaczej niż na `/jobs/new` po D1 |
| Pięć czytników wgranych plików Worda | brały komórki tabeli z `row.cells`, które powtarza komórkę `gridSpan` razy — liczba z pliku, bez górnej granicy. Jedna komórka z `gridSpan="5000000"` zajmowała proces aplikacji na minuty (ta sama klasa co #2112 i #2119) |

## Co zrobiono

**Lista kandydatów** (`RequirementRowsField` — lista `/candidates`, okno „Szukaj
ręcznie” rekrutacji, „Wymagania do wyszukiwania” w Profilu Championa)

- W pustym wierszu Enter, przecinek, średnik i wklejona lista to osobne
  wymagania; „Kafka / RabbitMQ”, „a lub b”, „a or b” to warianty jednego.
  Reguły: `parseRequirementEntry(text, keywordLongEnough)` i nowe
  `enterKeywordRows` (`lib/keyword-requirements.ts`).
- Wypełniony wiersz pokazuje słowa i przycisk „+ lub”; pole wariantu otwiera
  dopiero on. Pusty Enter w polu wariantu zamyka je i szuka, Esc zamyka bez
  szukania, kursor wraca na „+ lub”.
- Po wpisie zostaje pusty wiersz roboczy z kursorem — Enter w nim to nadal
  „Szukaj”. Takie samo wymaganie drugi raz i nadmiar ponad 10 wierszy dają
  notkę pod listą.
- Pusty wiersz roboczy nie idzie do zapisu Championa (`champion-save.ts`).
- Podpowiedź pod ⓘ i odpowiedź przewodnika Jarvisa (`candidates.list`) mówią
  o nowym wpisywaniu; stempel przewodnika odświeżony.

**Tabele Worda** (`backend/app/core/docx_cells.py`)

- `row_cells` (komórka raz), `row_texts` (teksty z pozycjami kolumn),
  `grid_cell_texts` (teksty w kolejności `row.cells`, z trzema granicami:
  `gridSpan` najwyżej 63 — tyle kolumn ma tabela Worda; scalenie w pionie
  czytane jednym przejściem po tabeli; najwyżej 2 mln znaków z tabel).
- Przepięte: `champion_document.document_text` i `table_profile`,
  `cv_text_extractor._extract_docx`, `_extract_docx` generatora CV i jego
  zamrożonej ścieżki `legacy_v7`. `cv_docx_import` i `dz_review` (naprawione
  wcześniej) biorą komórki z tego samego modułu.
- Tekst z prawdziwych dokumentów się nie zmienia: `cv_text_extractor`
  i `legacy_v7` dalej powtarzają tekst scalonej komórki (na tym tekście stoi
  odczyt zamówień z DOCX-a i ścieżka `legacy_v7`), pozostałe czytniki już
  wcześniej odrzucały powtórzenia.
- Strażnik w `tests/test_docx_table_cells.py`: każde `.cells` w `backend/app`
  poza czterema plikami pracującymi na dokumentach zbudowanych przez nasz kod
  wywraca test.

Bez migracji. Reguły: nowy `docs/claude/podstawy/tabele-worda-z-wgranych-plikow.md`,
poprawione `kandydaci-wyszukiwanie/wyszukiwanie-reczne-…`, `rekrutacja-tworzenie/umiejetnosci-krytyczne-…`,
`screening-notatki/screening-wybor-gotowego-cv-…`.

## Stan i dowody

| Część | Stan | Dowód |
|---|---|---|
| Wpisywanie wierszy | zrobione | Playwright na lokalnym podglądzie `/preview/candidates-list` (11.10), 1280×720, tryb `?embed=1` i telefon 390 px: „Java, Spring” + Enter → 2 wiersze i pusty wiersz z kursorem; „+ lub” + „JDK” → „Java lub JDK”; „Kafka / RabbitMQ” → 1 wiersz; zdanie „Szukamy osób, które mają (Java lub JDK) i Spring i (Kafka lub RabbitMQ)”; Enter w pustym wierszu stosuje wyszukiwanie; Esc zamyka pole wariantu, fokus na „+ lub”; 0 px poziomego scrolla |
| Testy frontu | zielone | `vitest --changed origin/main` po poprawkach z przeglądu: 71 plików, 1180 testów; `npm run type-check` i ESLint zmienionych plików czyste; e2e `responsive-preview -g candidates` 4/4 na lokalnym serwerze |
| Czytniki Worda | zrobione, pełny test tylko w CI | lokalnie (Python 3.9, kopia testu ładująca moduły po ścieżce) 24 testy: plik z `gridSpan="5000000"` i tabela 6000 wierszy scalonych w pionie czytają się w ułamku sekundy we wszystkich czytnikach przy `row.cells` podmienionym na wyjątek; tekst dokumentu ze scaleniami równy dawnej regule. `grid_rows` daje te same komórki co `row.cells` na 596 losowych tabelach ze scaleniami i na 49 tabelach z 27 plików `.docx` w repo. Strażnik AST wymaga Pythona 3.12 — biegnie w CI; `git grep "\.cells\b" backend/app` pokazuje tylko cztery pliki z listy zaufanych |
| Długie scalenie w pionie | znalezione w przeglądzie, naprawione | pierwsza wersja (`grid_cells`, wspinanie przez `_tc_above`) czytała 600 wierszy 18,5 s i zdejmowała przypadkowy bezpiecznik `main` (`RecursionError` około 1000 wierszy). Po zmianie: 600 wierszy 0,05 s, 5000 — 0,39 s, 20 000 — 1,78 s |
| Stemple i indeks | zrobione | `check_stamps.py` 0, `build_claude_index.py --check` 0, `CLAUDE.md` 28 891 B (limit 40 000), `test_claude_md_index.py` 4/4 |
| Wąski ekran, klik myszą | sprawdzone | niezatwierdzony wpis „Java, Spring” i prawdziwy klik w „Szukaj” przy 390, 800 i 1280 px: wpis daje dwa wiersze, przycisk nie ucieka spod kursora (przesunięcie 1 px), wyszukiwanie rusza |
| Przegląd kodu | zrobiony, uwagi naprawione | python-reviewer: jeden bloker — długie scalenie w pionie (wiersz wyżej). typescript-reviewer: bez blokerów, trzy regresje naprawione z testami — fokus ginął po usunięciu wiersza nad otwartym polem wariantu; edytor Championa zostawał „z niezapisaną zmianą” po dopisaniu i usunięciu wymagania (`comparableSection`); wiersze z górnego pola listy dochodziły pod pustym wierszem roboczym (`cleanRows` w `runSearch`) |

## Niepotwierdzone i poza zakresem

- Testy backendu (`tests/test_docx_table_cells.py` w całości) — dopiero w CI.
- Czytniki nie były mierzone na plikach z produkcji: zmiana nie rusza tekstu
  prawdziwych dokumentów (test równoważności na dokumencie ze scaleniami),
  a pomiar wymagałby czytania CV kandydatów.
- `company_variant.py`, `cv_approved_docx.py`, `docx_renderer.py` zostają przy
  `row.cells` — chodzą po dokumentach zbudowanych przez nasz kod.
- Pole wariantu zostaje otwarte po dodaniu słowa (można dopisać kolejne);
  zamyka je pusty Enter albo Esc — tak samo jak na `/jobs/new`.
