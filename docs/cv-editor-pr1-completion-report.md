# Edytor CV 2, PR 1 — edytor na cały ekran bez AI (12.10.2026)

Pomiar na produkcji (30 dni do 12.10.2026, tylko odczyt, same liczby): 686 CV
z generatora, w edytorze poprawiono 17 (2,5%), mediana 2 zapisy i 1,5 minuty.
Poprawki szły w Wordzie poza NEXUSEM. Artur zatwierdził makiety
(https://claude.ai/artifact/N82z8poJ4waexM46zLvMkg, prywatne) i decyzje D1–D6;
to pierwszy z pięciu PR-ów. Reguły po tej zmianie:
`docs/claude/generator-cv/edytor-cv-pelny-ekran.md`.

## Co się zmieniło

| Obszar | Zmiana |
|---|---|
| Okno (D1) | Edytor zajmuje cały ekran. Akcje w górnym pasku: Drukuj / PDF, Pobierz, Zamknij, Zapisz. Od 1180 px źródła stoją obok kartki, węziej jest przełącznik „CV \| Źródła” |
| Kartka | Treść wygląda jak szablon Worda: kolory i układ sekcji, podpowiedzi „Stanowisko:” / „Nazwa firmy:”, pogrubiona etykieta technologii. Dokładny plik pokazuje „Podgląd Word” (DOCX z bieżącej treści, bez pobierania) |
| Pasek narzędzi | Cofnij / Ponów, pogrubienie, lista, „Typ akapitu”, „Dodaj” (stanowisko, punkt, wiersz edukacji, grupa umiejętności, certyfikat, język); dla stanowiska pod kursorem: wyżej, niżej, powiel, usuń z potwierdzeniem |
| Źródła | Oryginalne CV i pliki kandydata, wymagania klienta, „Po ludzku”, notatki z rekrutacji. CV bez rekrutacji mówi, czemu panel jest pusty |
| Klauzula RODO (D3) | Nie da się jej zmienić ani usunąć: w przeglądarce wtyczka przywraca ją po każdej zmianie, na serwerze `keep_rodo_clause` w zapisie i zatwierdzeniu obu edytorów |
| Pola w nawiasach | Nowe bloki mają pola do wypełnienia; „Zapisz” zapisuje szkic, ale nie zatwierdza CV, dopóki zostały |
| Zapis pobrań (D5) | „Pobierz” w sześciu miejscach dokleja intencję; serwer zapisuje `cv_file_downloaded` (format, stan, miejsce, numer wersji — bez nazw plików). Podglądy nie zostawiają wpisu |
| Harness | `/preview/cv-editor?state=draft\|finalized\|conflict\|nosources` |

Bez migracji i bez nowych zmiennych środowiskowych. Sześć miejsc, które
otwierają edytor, i ścieżka modułu zostają.

## Dwa błędy sprzed tej zmiany, naprawione przy okazji

| Błąd | Przyczyna | Dowód |
|---|---|---|
| „Zapisz” na zatwierdzonej wersji bez żadnej zmiany zakładało nowy szkic | `editor.setEditable()` w Tiptapie emituje `update`, okno brało to za zmianę treści | test harnessu „…nie zakłada szkicu”; po cofnięciu poprawki pada |
| „Cofnij” tuż po otwarciu opróżniało CV | `setContent` trafiało do historii cofania | `cv-editor-structure.test.ts`, „Cofnij” wyłączone po wczytaniu |

## Odstępstwa od makiet i planu

- Prawy panel „Do poprawy” dochodzi w PR 2; do tego czasu po prawej jest sama kartka.
- Stanowisko edytuje się w tekście, bez pól formularza — Word powstaje z HTML-a
  edytora i każde opakowanie zmieniłoby kształt, który czyta serwer.
- Kartka nie używa czcionki Montserrat (frontend jej nie ładuje); układ i kolory są z szablonu.
- `@tiptap/core` i `@tiptap/pm` nie są dopisane do `package.json`: są zależnościami
  równorzędnymi `@tiptap/react`, a `main` importuje `@tiptap/core` tak samo od dawna.
- Typ encji wpisu o pobraniu to `candidate_stage_cv` / `cv_generated_document`,
  nie `candidate` — wpis nie trafia na oś kandydata. Widać go w dzienniku
  w Ustawieniach (opis „pobrał(a) plik CV”).
- Doszło szóste miejsce pobrania (`files` — lista plików kandydata), którego plan nie wymieniał.

## Weryfikacja

| Część | Stan | Dowód |
|---|---|---|
| Typy, lint, moduły nieosiągalne | zielone lokalnie | `tsc --noEmit`, `eslint` bez błędów, `check-unreachable-modules`: 0 nowych |
| Testy frontu | zielone lokalnie | 5230 testów w 377 plikach (edytor, okna, rekrutacja, pulpit, generator, pliki, strażnicy harnessów, inwentarz) |
| Cały harness na prawdziwym edytorze | zielone lokalnie | `cv-editor-harness.test.tsx`: zero żądań, blokada „Zapisz”, brak nowego szkicu; test mutacyjny (cofnięcie `setEditable(…, false)`) wywraca 2 z 4 |
| Testy backendu bez bazy | zielone lokalnie | 67 testów: strażnik klauzuli, edytor generatora, generator Worda, wpis pobrania, lustro etykiet, indeks reguł |
| Testy backendu z bazą | w CI | `test_route_logs_a_download_and_only_a_download` (9 tras), `test_refused_download_is_not_logged`, `test_saving_and_approving_keep_the_saved_consent_clause` |
| Parametry tras | potwierdzone lokalnie | `app.openapi()`: `intent`, `surface` jako opcjonalne parametry zapytania na 9 trasach, ciało żądań POST bez zmian |
| Przeglądarka 1280 × 720 | przeklikane lokalnie | harness: kartka i źródła obok siebie, nowe stanowisko po bieżącym, wpisany tytuł zastępuje pole, „Zapisz” wypisuje pozostałe pola i nie zamyka okna, klauzula zostaje ostatnia, konsola bez błędów |
| Przeglądarka 768 i 390 | sprawdzone lokalnie | brak przewijania strony w bok, jedna kolumna z przełącznikami, pasek narzędzi przewija się w swoim wierszu |
| Przegląd kodu | REVIEW_PLACEHOLDER | REVIEW_EVIDENCE |

## Niepotwierdzone

- Edytor na produkcji z prawdziwym CV: po wdrożeniu samo otwarcie i zrzut, bez
  edycji. Harnessy `/preview/*` są publiczne tylko poza produkcją.
- Wpisy `cv_file_downloaded`: odczyt SQL po pierwszych pobraniach.
- Zachowanie blokady klauzuli przy pisaniu z klawiatury ekranowej (IME) — sprawdzone tylko na klawiaturze fizycznej.

## Co dalej

PR 2 — panel „Do poprawy” (QC w trybie doradczym z #2139, uwagi generatora,
kontrola AI) z poprawką jednym kliknięciem; warunek wstępny: `qc/apply`
z `expected_revision`. Potem PR 3 (AI na zaznaczeniu), PR 4 (polecenie
i PL→EN), PR 5 (historia wersji i powrót pliku Word — po odczycie liczb z D5).
