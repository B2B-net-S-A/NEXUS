# Wyszukiwarka kandydatów — szybkość i jakość (25–26.09.2026)

## Przekazanie (26.09.2026, ok. 08:00 UTC) — przeczytaj najpierw

Praca przechodzi na inną maszynę. Stan w jednym miejscu:

| Co | Stan |
|---|---|
| #1845 (korpus złożony, lista „najpierw id”, notatki) | na produkcji |
| #1846 (kolejność „Dopasowanie”, górne pole) | na produkcji (`e80bdb0`, 26.09 07:27 UTC), **nieprzeklikane** |
| #1848 (składanie v2: myślnik) | na produkcji; pętla przelicza kolumny v2 (o 07:55 UTC w toku) |
| #1852 (składanie v3: `<`/`>` i znaki łączące, ten raport) | w kolejce merge'ów; po wdrożeniu pętla przeliczy wszystko jeszcze raz (v3) |
| Przełącznik `KEYWORD_SEARCH_FOLDED_FTS` | **OFF** — czeka na porównanie po v3 i zgodę Artura |
| Nic do cofnięcia | przy OFF wyniki wyszukiwania są jak przed zmianami; logi bez błędów |

**Czeka na Artura:** zgoda na włączenie przełącznika — po tabeli z kroku 2 niżej.
**Zrobić dalej (kolejność):** sekcja „Co zostało”. Dostęp do produkcji: sekcja
„Dostęp do produkcji (tylko odczyt)”.

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

| PR | Zawartość | Stan (26.09, 08:00 UTC) |
|---|---|---|
| [#1845](https://github.com/B2B-net-S-A/NEXUS/pull/1845) | Migracja 0385 (`keyword_fold_fts`, `content_fold_fts`, indeks `created_at`); nowa ścieżka `_whole_word_match` za `KEYWORD_SEARCH_FOLDED_FTS` (OFF); pętla uzupełniania z rozpakowaniem notatek; lista „najpierw id” (okno `count(*)` na samych id); front bez liczby bazy w „Szukaj ręcznie” | Na produkcji |
| [#1846](https://github.com/B2B-net-S-A/NEXUS/pull/1846) | `sort=match` (`services/candidate_match_order.py`, `CANDIDATE_MATCH_SORT`, domyślnie ON); `GET /api/candidates/keywords/classify`; front: domyślna kolejność, etykiety, komunikat, zamiana w górnym polu; `ManualSearchPanel` bez tytułu jako tekstu | Na produkcji (`e80bdb0`), nieprzeklikane |
| [#1848](https://github.com/B2B-net-S-A/NEXUS/pull/1848) | Składanie v2 (myślnik jako spacja, migracja 0386); faza wersji w pętli (przeliczenie wszystkiego przy zmianie `FOLD_VERSION`) | Na produkcji; przeliczanie v2 w toku |
| [#1852](https://github.com/B2B-net-S-A/NEXUS/pull/1852) | Składanie v3 (`<`/`>` jako spacja, NFC + usunięcie znaków łączących, migracja 0387); rozbiór 43 utraconych osób; ten raport | W kolejce merge'ów |

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

1. **Poczekać na scalenie i wdrożenie #1852.**
   - Deploy po merge'u czeka na ciszę na mainie (~5 min), w nocy 0–7 (Warszawa)
     wcale — nocne merge'e wdraża poranny bieg. Sprawdź: `curl -fsS
     https://api.nexus.dynaminds.pl/api/health | jq .version` = SHA z maina
     zawierający #1852 (`git log origin/main`).
   - Pętla `keyword_corpus_backfill` zobaczy `FOLD_VERSION = 3` i przeliczy obie
     kolumny (~45 min kandydaci + kilka minut notatki). Koniec = log
     `keyword fold corpus v3 recomputed` i `app_settings['keyword_fold_fts_version'] = 3`.
     Do końca nowa ścieżka jest wyłączona niezależnie od przełącznika.
   - **26.09, 08:10 UTC:** przeliczenie v2 nie skończyło się ani razu (brak
     `keyword_fold_fts_version` w `app_settings`) — pozycja żyła tylko w pamięci
     procesu, a od #1850 każdy merge restartuje kontener (07:27, 07:52, 08:06).
     Poprawka: pozycja w `app_settings['keyword_fold_fts_recompute']` (wersja +
     ostatnie id kandydatów i notatek), kasowana po końcu. Wznowienie widać
     w logu `keyword fold corpus v3 recompute resumed at …`.
   - Jeśli #1852 wypadnie z kolejki: przyczyna w logach biegu `merge_group`
     (komentarz robota pod PR-em), potem `gh pr merge 1852 --squash --auto`.
2. **Powtórzyć porównanie** w kontenerze backendu (tylko odczyt, ~3 min):
   `docker exec -i -w /app -e PYTHONPATH=/app <backend> python -m scripts.compare_keyword_fold_fts`.
   Oczekiwane względem wersji 1 (tabela niżej): „ci/cd” i „analityk biznesowy” bez
   ubytków; ubytki tylko z grup „szum” i „wyraz sklejony kropką” (~5 prawdziwych:
   „scrum.org” ×3, „Agile.a”, „8.krakow”). Kandydat 34020 wraca w „łódź”.
   Każdy NOWY ubytek sprawdź na treści (zapytanie jak w „Dostęp do produkcji”),
   zanim pokażesz tabelę. Tabelę pokazać Arturowi i poprosić o zgodę.
3. **Po zgodzie Artura włączyć przełącznik.**
   - Workflow „Coolify set env” z `KEYWORD_SEARCH_FOLDED_FTS=true` i `redeploy=false`,
     a potem jedno zwykłe wdrożenie (ręczny „Run workflow” na Deploy).
     `redeploy=true` powodowało przerwę.
   - Po wdrożeniu zmierzyć „java”, „c#” i „scrum” na `GET /api/candidates`
     (token zmintowany w kontenerze); cel poniżej 300 ms.
4. **Przeklikać #1846 w przeglądarce** (jest już na produkcji; zalogowanej sesji nie
   da się wstrzyknąć — użyj harnessu `/preview/candidates-list` albo zalogowanej
   przeglądarki Artura):
   - listę z wierszami wymagań (sortowanie „Dopasowanie do wymagań”);
   - górne pole z „java” (komunikat „Czytam jako wymagania” i przycisk „po znaczeniu”);
   - „Szukaj ręcznie” z wymaganiami i bez (kolejność zgodna z kolumną „Dop.”);
   - zmierzyć czas `sort=match` (pierwsza strona i kolejne z pamięci).
5. Na koniec raport w formacie Czeka na mnie / Zmienione / Znalezione i dopisek
   w tym pliku.

## Dostęp do produkcji (tylko odczyt)

- SSH na serwer NEXUSA (adres w CLAUDE.md, sekcja Deploy) kluczem root z maszyny
  Artura. Nazwy kontenerów zmieniają się po każdym wdrożeniu:
  `docker ps --format '{{.Names}}' | grep '^postgres-ocgkw'` / `'^backend-ocgkw'`.
- SQL zawsze w trybie tylko do odczytu:
  `docker exec -i <postgres> psql -U nexus -d nexus` i jako pierwsza instrukcja
  `SET default_transaction_read_only = on;`.
- Gdzie pasowało słowo u konkretnej osoby (użyte przy rozbiorze 43 osób):
  `substring(raw_cv_text from '(?i).{0,45}SLOWO.{0,45}')`, to samo na `keyword_doc`
  i `notes.content`.
- Czy parser coś połyka: `ts_debug('simple', candidate_keyword_fold(raw_cv_text))`
  i tokeny `blank`/`tag` dłuższe niż 200 znaków (po v3 zostają tylko 2 CV ze
  śmieciowymi symbolami z uszkodzonego PDF-a — tam nic nie ginie).
- Tokeny do GET-ów mintuj w kontenerze backendu i kasuj po użyciu; nie wstrzykuj
  ich do przeglądarki.

## Jak to działa (skrót dla programisty)

- **Korpus złożony**: `app/services/keyword_corpus.py` jest jedynym źródłem DDL.
  - Z niego korzystają migracje 0385/0386/0387 i `entrypoint.sh` przez `schema_ddl()` i
    `schema_index_ddl()`.
  - Funkcja SQL `candidate_keyword_fold` składa tekst i dokumentu, i zapytania
    (`advanced_candidate_search.folded_tsquery`). Zmiana funkcji = podbij
    `FOLD_VERSION` (historia w komentarzu przy stałej) i nowa migracja z samym DDL.
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
- **Wyrazy sklejone kropką** („scrum.org”, „8.krakow”) nowa ścieżka świadomie gubi
  (~5 osób na 50 słów) — decyzja Artura 26.09, bo rozcięcie przywraca szum z e-maili
  i linków. Jeśli wróci temat: rozcinanie tylko po cyfrze („8.krakow”) nie rusza
  e-maili.
- **Zakleszczenia pętli uzupełniania z innym zapisem kandydatów** (25.09 w nocy, 4×):
  ponawia sama; przyczyny drugiej strony nie ustalono.
