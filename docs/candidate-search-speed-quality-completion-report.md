# Wyszukiwarka kandydatów — szybkość i jakość (25–26.09.2026)

Stan prac i instrukcja dla osoby, która przejmie temat. Raport audytu z pomiarami:
https://claude.ai/artifact/1DKHMLHNc3QKUg4rtf2nei. Reguły, które łatwo cofnąć, są też
w CLAUDE.md w sekcjach „Słowa kluczowe przez korpus złożony + lista „najpierw id””
i „Kolejność „Dopasowanie” i górne pole listy”.

## Punkt wyjścia (pomiary na produkcji, 25.09.2026)

| Wyszukiwanie (strona 50 osób) | Czas serwera |
|---|---:|
| Lista bez filtra | 430 ms |
| „java” | 0,9–1 s |
| „java” + „spring” | 1,2 s |
| 3 wiersze wymagań | 2 s |
| „c#” | 5,9 s |

- **Główny koszt**: 68% czasu „java” (629 z 918 ms) zjadała gałąź regex po
  `candidates.keyword_doc`. Wersja bez polskich znaków rozpakowywała tekst z TOAST dla
  każdego pasującego kandydata, a dokładała tylko 2 osoby z 15 710.
- **Pozostałe koszty**:
  - `count(*) OVER()` na pełnych wierszach (bez filtra 170 MB na dysk tymczasowy);
  - regex po notatkach (≈100 ms);
  - brak indeksu na `created_at`.
- **Jakość kolejności**: przy „najnowsi” pierwsza strona „Szukaj ręcznie” zawierała osobę,
  którą zespół potem zweryfikował, w 33% rekrutacji.
  - Test: 120 rekrutacji z 24 miesięcy, baza cofnięta do dnia otwarcia rekrutacji.
  - Proste sortowania w bazie (ts_rank, słowa w profilu, świeżość CV) NIE pomagały.
- **Notatki z Traffita**: 37 363 notatki zapisano jako cały JSON z `\uXXXX`. Polskie
  słowa były w nich nie do znalezienia.

## Decyzje Artura

- Kroki 1–4 (szybkość i notatki, bez zmiany kolejności) za przełącznikiem. Przed
  włączeniem porównanie starej i nowej ścieżki.
- „Szukaj ręcznie”: domyślnie „Dopasowanie do rekrutacji”, tym samym wektorem co kolumna
  „Dop.”.
- Lista z wierszami wymagań: domyślnie „Dopasowanie do wymagań”.
- Kolejność: „Mile widziane” najpierw, osoby z brakami danych na koniec (jak dotąd).
- „Szukaj ręcznie” bez wymagań w Championie: cała baza według dopasowania. Dotąd tytuł
  szedł jako tekst po znaczeniu z limitem 200 osób.
- Górne pole: jeśli wpisano same nazwy technologii, zamieniają się w wiersze wymagań.
  Przycisk „Szukaj … po znaczeniu” cofa zamianę.
- Notatki: poprawiony import i naprawa istniejących wierszy.
- 26.09: przed włączeniem przełącznika poprawić fazy przy myślniku („CI/CD-driven”).
  Zrobione w #1848.
- 26.09 (po sprawdzeniu każdej utraconej osoby): poprawić litery z osobnym znakiem
  akcentu i `<script>` w CV (wersja 3 składania, 0387). Wyrazów sklejonych kropką
  („scrum.org”, „8.krakow”) NIE rozcinamy — rozcięcie przywróciłoby szum z adresów
  e-mail i linków. Przełącznik włączamy po ponownym porównaniu i zgodzie Artura.

## Co jest zrobione

| PR | Zawartość | Stan (26.09 rano) |
|---|---|---|
| [#1845](https://github.com/B2B-net-S-A/NEXUS/pull/1845) | Migracja 0385 (`keyword_fold_fts`, `content_fold_fts`, indeks `created_at`); nowa ścieżka `_whole_word_match` za `KEYWORD_SEARCH_FOLDED_FTS` (OFF); pętla uzupełniania z rozpakowaniem notatek; lista „najpierw id” (okno `count(*)` na samych id); front bez liczby bazy w „Szukaj ręcznie” | Na produkcji (`2a5de38`) |
| [#1846](https://github.com/B2B-net-S-A/NEXUS/pull/1846) | `sort=match` (`services/candidate_match_order.py`, `CANDIDATE_MATCH_SORT`, domyślnie ON); `GET /api/candidates/keywords/classify`; front: domyślna kolejność, etykiety, komunikat, zamiana w górnym polu; `ManualSearchPanel` bez tytułu jako tekstu | W kolejce merge'ów; wdrożenie po 7:00 |
| ten PR | Wersja 2 składania tekstu (myślnik jako spacja, migracja 0386); faza wersji w pętli (przeliczenie wszystkiego przy zmianie `FOLD_VERSION`); ten raport | Otwarty |

### Zmierzone po wdrożeniu #1845

- **Lista bez filtra**: 430 → ~210 ms.
- **Migracja 0385**: 3 indeksy `indisvalid = t`, triggery założone.
- **Uzupełnianie**:
  - 63 369 kandydatów i 71 881 notatek, ok. 1 500 kandydatów na minutę.
  - Paragon `app_settings['0385_traffit_note_content_unwrap']`: `wrapped_before` 37 363,
    `unwrapped` 37 363, `wrapped_left` 0.
  - Po naprawie w notatkach nie ma już `\uXXXX`.
- **Porównanie starej i nowej ścieżki** (`python -m scripts.compare_keyword_fold_fts`,
  50 słów, wersja 1 składania):
  - ubywa razem 43 osoby, przybywa 5 439;
  - przykłady: „krakow” +1 477, „scrum” +848, „lodz” +744;
  - czasy: „java” 1,8 s → 0,1 s, „c#” 8,4 s → 0,03 s, „f#” 9 s → 0,004 s;
  - ubytki to głównie linki w notatkach (`…/j.php?…` przy „php”, dziś szum) i
    „CI/CD-driven” — to poprawia ten PR.
- **Test kolejności** (`python -m scripts.eval_manual_search_order`, 120 rekrutacji):

| kolejność | rekrutacje z ≥1 właściwą osobą na 1. stronie | MRR |
|---|---:|---:|
| najnowsi | 33,3% | 0,047 |
| wektor kolumny „Dop.” | 83,3% | 0,279 |
| cała baza wg „Dop.” (bez wymagań) | 80,0% | 0,216 |

### Sprawdzenie utraconych osób (26.09, produkcja, tylko odczyt)

Wszystkie 43 osoby, które nowa ścieżka traciła w porównaniu wersji 1, sprawdzone
na treści CV, profilu i notatek:

| grupa | osób | przyczyna | co dalej |
|---|---:|---|---|
| „CI/CD-driven”, „biznesowy-systemowy” | 9 | myślnik sklejał frazę | naprawione w #1848 |
| szum | 28 | linki `j.php`/`index.php` w notatkach, miasto w adresie e-mail (`marczak.krakow@gmail.com` to osoba z Łodzi), firma `Devops.ly`, `spark.fi`, `Java.script`, plik `IT Tester.pdf` | dobrze, że znika |
| wyraz sklejony kropką | 5 | „scrum.org” ×3 (certyfikaty PSM/PSPO), „Agile.a”, „8.krakow” — parser traktuje je jak adres strony | świadomie zostaje (decyzja 26.09) |
| `<script>` w CV | 1 | kandydat 34020: składanie zamieniało `</script>` w `< script>`, parser nie znajdował końca „skryptu” i połykał 6 336 znaków CV razem z „Łódź” (tak samo 3 inne CV, razem 11 906 znaków) | naprawia 0387 (`<` i `>` jako spacja) |

Próbka 14 osób dodanych przez nową ścieżkę: wszystkie to prawdziwe trafienia
(„Kraków, woj. małopolskie” w CV, „Agile/Scrum”, „SysOps/Admin/SQL/DevOps”,
„Infosys | Łódź”). Przy okazji: 133 CV i 41 notatek mają polskie litery zapisane
jako litera + osobny akcent — ani stara, ani nowa ścieżka ich nie znajdowała;
0387 to poprawia (sprawdzone na produkcji wyrażeniem: „lodz” 4 → 10 CV,
„zarzadzanie” 57 → 62 wśród CV z takimi znakami). Logi produkcji z 10 godzin po #1845: bez błędów, lista 200.

## Co zostało (w tej kolejności)

1. **Scalić ten PR i poczekać na wdrożenie.**
   - Pętla `keyword_corpus_backfill` zobaczy inną wersję (`app_settings['keyword_fold_fts_version']`
     brak albo 1) i przeliczy wszystkie wiersze. Zajmie to ok. 45 min kandydaci + kilka
     minut notatki.
   - Postęp w logach: `keyword fold corpus v2 recomputed`.
   - Do końca przeliczania nowa ścieżka jest wyłączona niezależnie od przełącznika.
2. **Powtórzyć porównanie** w kontenerze backendu:
   `cd /app && python -m scripts.compare_keyword_fold_fts` (tylko odczyt, ok. 3 min).
   Sprawdzić, że „ci/cd” już nie traci osób. Tabelę pokazać Arturowi.
3. **Po zgodzie Artura włączyć przełącznik.**
   - Workflow „Coolify set env” z `KEYWORD_SEARCH_FOLDED_FTS=true` i `redeploy=false`, a
     potem jedno zwykłe wdrożenie. `redeploy=true` powodowało przerwę (pamięć projektu).
   - Po wdrożeniu zmierzyć „java”, „c#” i „scrum” na `GET /api/candidates`; cel poniżej
     300 ms.
4. **Po wdrożeniu #1846** przeklikać w przeglądarce ze zrzutami:
   - listę z wierszami wymagań (sortowanie „Dopasowanie do wymagań”);
   - górne pole z „java” (komunikat „Czytam jako wymagania” i przycisk „po znaczeniu”);
   - „Szukaj ręcznie” z wymaganiami i bez (kolejność zgodna z kolumną „Dop.”);
   - zmierzyć czas `sort=match` (pierwsza strona i kolejne z pamięci).

## Jak to działa (skrót dla programisty)

- **Korpus złożony**: `app/services/keyword_corpus.py` jest jedynym źródłem DDL.
  - Z niego korzystają migracje 0385/0386 i `entrypoint.sh` przez `schema_ddl()` i
    `schema_index_ddl()`.
  - Funkcja SQL `candidate_keyword_fold` składa tekst i dokumentu, i zapytania
    (`advanced_candidate_search.folded_tsquery`).
  - W siatce `entrypoint.sh` trigger jest podmieniany tylko przy istniejącej kolumnie.
    Inaczej przegrana blokada `ADD COLUMN` wywaliłaby każdy zapis kandydata.
- **Pętla uzupełniania**: `app/tasks/keyword_corpus_backfill.py`, cztery fazy:
  stary korpus → NULL-e kandydatów → NULL-e notatek z rozpakowaniem → wersja.
  - Notatki są aktualizowane bez zmiany `updated_at`, bo od niej zależy odcisk nocnej
    analizy AI.
  - Zakleszczenia z innym zapisem kandydatów (4 razy 25.09 w nocy) są niegroźne: pętla
    ponawia po 60 s, a pozycja przeliczania przeżywa ponowienie.
- **Lista „najpierw id”**: `app/api/candidates.py::_list_page_ids_first`, wyłącznik
  `CANDIDATE_LIST_IDS_FIRST`.
  - Filtr idzie raz, z oknem `count(*)` na samych id.
  - Osobne `count(*)` liczyłoby regex dwa razy. Wyłapał to przegląd kodu.
- **Kolejność „Dopasowanie”**: `app/services/candidate_match_order.py`.
  - Qdrant exact w paczkach po 5 000, ANN top 3 000 powyżej 30 tys. id.
  - Własna pamięć LRU: 32 wpisy, 5 min.
  - NIE używa `app/core/cache.py` — ten nie ma limitu, a lista bywa długa na 60 tys. id.
- **Skrypty** (tylko odczyt, uruchamiane w kontenerze backendu):
  - `scripts/compare_keyword_fold_fts.py` — stara vs nowa ścieżka słów kluczowych;
  - `scripts/eval_manual_search_order.py` — jakość kolejności na historii rekrutacji;
    woła Voyage, nie zapisuje do bazy.

## Ryzyka i rzeczy poza zakresem

- **„c#” i „c++” przy wyłączonym przełączniku**: przez regex trwają nadal 7–9 s.
  Rozwiąże je dopiero włączenie przełącznika.
- **Po każdym wdrożeniu** Postgres restartuje się razem z aplikacją, więc pierwsze
  wyszukiwania trwają ok. 2 s (zimna pamięć). Możliwe `pg_prewarm` — osobna decyzja.
- **Stara wyszukiwarka** `/candidates/search?mode=search&job=` (silnik
  `POST /api/search/candidates`) trwa 2,2 s. Nie jest ruszana; do rozważenia
  przekierowanie na listę.
- **Tabela `candidates`**:
  - zduplikowane indeksy (email ×2, status ×2, id ×2);
  - 7 indeksów GIN;
  - spowalniają zapisy importu Traffita, ale nie wyszukiwanie.
- **Eksport z `sort=match`** idzie od najnowszych (ten sam zbiór, inna kolejność).
