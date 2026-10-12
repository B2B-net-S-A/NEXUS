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
| Klauzula RODO (D3) | Nie da się jej zmienić ani usunąć: w przeglądarce wtyczka przywraca ją po każdej zmianie i odrzuca zmianę, po której jej tekst zostałby w treści; na serwerze `keep_rodo_clause` w zapisie, kontroli AI, podglądzie Word i zatwierdzeniu obu edytorów |
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
| Testy frontu | zielone lokalnie, po scaleniu `main` | 5258 testów w 380 plikach (edytor, okna, rekrutacja, pulpit, generator, pliki, strażnicy harnessów, inwentarz) |
| Cały harness na prawdziwym edytorze | zielone lokalnie | `cv-editor-harness.test.tsx`: zero żądań, blokada „Zapisz”, brak nowego szkicu; test mutacyjny (cofnięcie `setEditable(…, false)`) wywraca 2 z 4 |
| Testy backendu bez bazy | zielone lokalnie, po scaleniu `main` | 132 testy: strażnik klauzuli, kolejka kontroli, edytor generatora, generator Worda, import DOCX, wpis pobrania, lustro etykiet, kontrola po edycji, indeks reguł |
| Testy backendu z bazą | w CI | `test_route_logs_a_download_and_only_a_download` (9 tras), `test_refused_download_is_not_logged`, `test_saving_and_approving_keep_the_saved_consent_clause` |
| Parametry tras | potwierdzone lokalnie | `app.openapi()`: `intent`, `surface` jako opcjonalne parametry zapytania na 9 trasach, ciało żądań POST bez zmian |
| Przeglądarka 1280 × 720 | przeklikane lokalnie | harness: kartka i źródła obok siebie, nowe stanowisko po bieżącym, wpisany tytuł zastępuje pole, „Zapisz” wypisuje pozostałe pola i nie zamyka okna, klauzula zostaje ostatnia; trzy razy Delete na końcu ostatniego bloku nic nie zmienia (jedna klauzula, „Cofnij” nadal wyłączone), pisanie dalej działa |
| Przeglądarka 768 i 390 | sprawdzone lokalnie | brak przewijania strony w bok, jedna kolumna z przełącznikami, pasek narzędzi przewija się w swoim wierszu |
| Przegląd kodu | zrobiony przed PR-em, blokery naprawione | tabela niżej |

## Przegląd kodu przed PR-em

Trzech recenzentów czytało diff niezależnie (TypeScript, Python, bezpieczeństwo).
Każde znalezisko zostało najpierw odtworzone testem, który padał.

| Znalezisko | Waga | Co zrobione | Dowód |
|---|---|---|---|
| Delete na końcu ostatniego akapitu albo punktu doklejał tekst klauzuli do treści CV (wtyczka dokładała klauzulę drugi raz, serwer tego nie widział) | blokuje | Filtr transakcji odrzuca zmianę, po której kawałek klauzuli zostałby poza nią; kopię wklejoną w głąb listy naprawa usuwa | 4 testy w `cv-editor-structure.test.ts`; próba losowa; prawdziwa przeglądarka |
| Wklejenie ze schowka CV kończącego się klauzulą w środek akapitu kasowało resztę tego akapitu; Backspace na początku klauzuli doklejał ją do poprzedniego punktu (znalezione własną próbą po przeglądzie) | blokuje | Naprawa usuwa sam tekst klauzuli z początku albo końca akapitu, z którym się skleiła | 2 testy w `cv-editor-structure.test.ts`; próba losowa 150 × 80 operacji ze wklejaniem ze schowka |
| „Dodaj → Stanowisko” w starym CV bez znaczników odbierało pozostałym stanowiskom „Stanowisko:” i „Nazwa firmy:” w Wordzie | blokuje | `insertRole` najpierw oznacza istniejącą strukturę (`markLegacyStructure`) | test w `cv-editor-blocks.test.ts` |
| Kontrola AI liczyła treść bez przywróconej klauzuli, zatwierdzenie z przywróconą — zatwierdzenie nie znajdowało wyniku kontroli i odpowiadało 409 bez końca | blokuje | Strażnik także w `enqueue_review` i w obu renderach szkicu | `test_ai_review_checks_the_content_that_approval_will_store`, `test_word_preview_renders_the_content_that_approval_will_store` |
| Klauzula przepisana jako `div` omijała strażnika, a Word przypinał ją na dole | średnia | Kandydat na klauzulę to `p` albo `div` bez bloków w środku, jak w generatorze Worda | `test_clause_rewritten_as_a_div_is_replaced_too` |
| Tekst przed pierwszym blokiem wracał z encji jako znaczniki (tylko gdy strażnik przebudowywał treść) | niska | Tekst jest kodowany przed złożeniem, a przebudowana treść przechodzi przez sanitizer | `test_text_before_the_first_block_stays_text_when_the_clause_is_restored` |
SECURITY_ROW

Świadomie zostaje: klauzula zagnieżdżona w `blockquote` albo komórce tabeli jest
przyjmowana bez zmian, a Word jej nie przypina — tak samo było przed tą zmianą
i edytor takiej treści nie tworzy.

## Niepotwierdzone

- Edytor na produkcji z prawdziwym CV: po wdrożeniu samo otwarcie i zrzut, bez
  edycji. Harnessy `/preview/*` są publiczne tylko poza produkcją.
- Wpisy `cv_file_downloaded`: odczyt SQL po pierwszych pobraniach.
- Zachowanie blokady klauzuli przy pisaniu z klawiatury ekranowej (IME) — sprawdzone tylko na klawiaturze fizycznej.
- Tekst klauzuli wklejony w ŚRODEK zdania zostaje w treści — edytor nie odróżni go od tekstu wpisanego ręcznie.

## Co dalej

PR 2 — panel „Do poprawy” (QC w trybie doradczym z #2139, uwagi generatora,
kontrola AI) z poprawką jednym kliknięciem; warunek wstępny: `qc/apply`
z `expected_revision`. Potem PR 3 (AI na zaznaczeniu), PR 4 (polecenie
i PL→EN), PR 5 (historia wersji i powrót pliku Word — po odczycie liczb z D5).
