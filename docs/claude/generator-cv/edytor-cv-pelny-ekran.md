# Edytor CV na cały ekran — kartka, bloki, źródła, stała klauzula RODO (12.10.2026)

<!-- indeks: kontrakt HTML edytor ↔ Word, bloki i etykiety szablonu, blokada klauzuli (przeglądarka + serwer), pola w nawiasach, wpis `cv_file_downloaded`, panel „Do poprawy” (QC, uwagi generatora, kontrola AI, „Popraw wszystko”, `qc/transform`), AI na zaznaczeniu (`cv-ai/selection`, kontrola „bez nowych faktów”, klucz `cv_selection_edit`), polecenie dla całego CV (`cv-ai/command`, plan zmian sprawdzany przez kod, klucz `cv_editor_command`), historia wersji i powrót pliku Word (`…/versions`, `…/import-preview` bez zapisu, treść nakłada edytor), harness `/preview/cv-editor` -->

Pomiar na produkcji (30 dni do 12.10.2026, tylko odczyt, same liczby): 686 CV
z generatora, w edytorze poprawiono 17 (2,5%), mediana 2 zapisy i 1,5 minuty.
Poprawki szły w Wordzie poza NEXUSEM, a wersja wysłana klientowi nie wracała.
Decyzje Artura D1–D6 (makiety: https://claude.ai/artifact/N82z8poJ4waexM46zLvMkg,
prywatne): pełny ekran, „Popraw wszystko” tylko z dowodem, klauzula RODO bez
edycji, powrót pliku Word, zapis pobrań, pięć PR-ów po kolei. Ten plik opisuje
PR 1 (edytor bez AI), PR 2 (panel „Do poprawy”) i PR 3 (AI na zaznaczeniu);
kolejne PR-y dopisują swoje sekcje tutaj.

## Kontrakt HTML — edytor pisze to, z czego serwer składa Word

- Dokument w Tiptapie jest płaski: `h1 | p | hr | h2[sekcja] | ul | p[role] |
  p[employer] | p[duties_label] | ul | p[technologies] | … | p[rodo]`. Nie ma
  opakowania stanowiska — rola to zakres od `p[role]` do następnej roli,
  nagłówka h1/h2, klauzuli albo końca. Każda operacja na „bloku” (przenieś,
  powiel, usuń) liczy ten zakres w `lib/cv-editor-blocks.ts` (`cvOutline`),
  nie w komponencie.
- Stanowisko edytuje się w tekście, bez pól formularza, bo
  `services/cv_approved_docx.py` czyta HTML: rola dostaje „Stanowisko:” tylko
  z pogrubionym początkiem, firma „Nazwa firmy:” tylko tuż po roli. Podpowiedzi
  tych etykiet na kartce to CSS (`::before`), nie treść.
- Etykiety „Zakres zadań:” / „Tasks:”, „Technologie:” / „Technologies:” i tytuły
  sekcji muszą mieć dokładny tekst szablonu. `CV_TEMPLATE_LABELS` w
  `cv-editor-blocks.ts` jest lustrem `docx_renderer.TRANSLATIONS`; pilnuje
  `backend/tests/test_cv_editor_template_labels.py` (także podpowiedzi CSS
  i początek klauzuli).
- Znaczniki `data-cv-section` żyją tylko na akapitach poziomu dokumentu
  (serwer zachowuje je na `p` i `h2`). Wtyczka zdejmuje znacznik z akapitu,
  który trafił do listy, a przycisk listy jest wyłączony na oznaczonym akapicie.
- Jeden znacznik `role` przełącza serwer z rozpoznawania po kształcie na same
  znaczniki. Dlatego w starym CV bez znaczników pierwsze „Typ akapitu →
  Stanowisko” oznacza od razu wszystko, co serwer rozpoznałby sam
  (`markLegacyStructure`). To samo robi „Dodaj → Stanowisko” — nowy blok
  niesie znacznik `role`, więc bez tego stare stanowiska traciły w Wordzie
  „Stanowisko:” i „Nazwa firmy:”.

## Wczytanie i stan edytora

- Treść wczytuje `loadCvHtml` (`lib/cv-editor-structure.ts`), nie gołe
  `setContent`: wczytanie poza historią cofania i bez zdarzenia `update`.
  Inaczej „Cofnij” po otwarciu opróżnia CV.
- `editor.setEditable(value, false)` — drugi argument jest konieczny. Bez niego
  Tiptap emituje `update`, okno uznaje treść za zmienioną i „Zapisz” na
  zatwierdzonej wersji bez zmian zakłada nowy szkic (błąd sprzed tej zmiany).
- Pełny ekran to `DialogContent` z klasami nadpisującymi bazę okna;
  `max-h-dvh`, nie `max-h-none` (tailwind-merge nie uznaje `none` za wysokość
  i zostawia `max-h-[90dvh]`). Kontrakt klas ma test okna.
- Od 1180 px szerokości panel stoi obok kartki, węziej jest jedna kolumna
  z przełącznikiem „CV | Źródła | Do poprawy (N)”. Układ paneli: sekcja
  „Panel »Do poprawy«” niżej.

## Klauzula zgody RODO jest stała (D3)

- Przeglądarka: wtyczka `CvEditorStructure` po każdej transakcji przywraca
  jedną klauzulę na końcu (zrzut z wczytania) — transakcją dołączaną
  (`appendTransaction`). Filtr odrzucający każdą zmianę blokowałby „zaznacz
  wszystko i usuń” i mógłby odrzucić wczytanie nowszej wersji.
- Filtr (`filterTransaction` → `clauseLeaks`) odrzuca tylko zmianę, po której
  kawałek klauzuli zostałby poza nią: Delete na końcu ostatniego akapitu albo
  punktu (klawisz obsługuje model ProseMirrora, więc `contenteditable=false`
  go nie zatrzyma), usunięcie zaznaczenia sięgającego w głąb klauzuli, tekst
  wpisany w nią. Naprawa dołożyłaby wtedy klauzulę drugi raz, a doklejony
  tekst poszedłby do klienta jako treść CV.
- Naprawa usuwa też kopie klauzuli (`clauseCopy`): cały akapit, także w głębi
  listy, albo sam jej tekst z początku lub końca akapitu, z którym się skleiła.
  Tak kończy się wklejenie ze schowka CV z klauzulą w środek akapitu
  i Backspace na początku klauzuli — w liście Tiptap przenosi treść przez
  „usuń i wstaw”, czego filtr po mapowaniu pozycji nie widzi. Usuwanie całego
  sklejonego akapitu kasowało resztę akapitu użytkownika.
- Serwer: `cv_rodo_clause.keep_rodo_clause(zapisane, przysłane)` wszędzie,
  gdzie treść z edytora jest zapisywana, sprawdzana albo składana w Word:
  `update_branded_cv`, `finalize_stage_cv`, `cv_generated_editor.save` /
  `finalize`, `cv_approval_queue.enqueue_review` oraz oba rendery szkicu
  (`render_stage_editor_docx`, `cv_generated_editor.render`). Kontrola AI
  i zatwierdzenie muszą dostać tę samą treść: zatwierdzenie szuka wyniku
  kontroli po skrócie treści, więc kontrola policzona bez klauzuli kończyła się
  409 „Uruchom kontrolę” bez końca.
- Strażnik liczy to samo, co przypnie generator Worda (`_pinned_by_word` =
  lustro `cv_approved_docx.flatten` i `paragraph_block`): akapit `p` albo `div`
  bez bloków w środku, na poziomie dokumentu, bez obrazka. Treść wraca bajt
  w bajt tylko wtedy, gdy jest w niej dokładnie jeden akapit udający klauzulę
  i to on jest zapisaną klauzulą na przypinanym miejscu. W każdym innym
  układzie zapisana klauzula wraca na koniec, kopie i przeróbki znikają (także
  schowane w cytacie, komórce tabeli, jako luźny tekst między blokami), a inny
  tekst ze znacznikiem klauzuli zostaje w treści bez znacznika. Bez tego
  prawdziwa klauzula schowana w cytacie przepuszczała cudzą, którą Word
  przypinał na dole; pusty blok z klasą klauzuli zostawiał stronę bez niej.
- Naprawa idzie do skutku na świeżo sparsowanej treści (kilka przebiegów),
  bo lxml i sanitizer budują z niedomkniętych znaczników różne drzewa.
  Przebudowana treść przechodzi przez sanitizer, klauzula jest doklejana jako
  osobny, domknięty fragment. Pusta treść zostaje pusta, żeby wołający dał
  swoje 422.
- `sanitize_cv_html` usuwa znaki, których lxml nie przyjmuje (form feed i inne
  sterujące, także jako odwołania `&#12;`). Przechodziły przez bleach, a lxml
  w strażniku i w generatorze Worda rzucał wyjątkiem: zapis kończył się 500,
  a zapisana z nimi treść blokowała każdy następny zapis. Zapisanego CV,
  którego nie da się odczytać, strażnik nie chroni (ostrzeżenie w logu) —
  stara treść nie może zablokować zapisu.
- `sanitize_cv_html` ma ograniczony koszt (12.10.2026). html5lib w bleach
  płacił czasem kwadratowym w trzech miejscach, a handlery wołają sanitizer
  w pętli zdarzeń — 500 KB (tyle mieści `content_html`) potrafiło trwać minuty:
  - **głębokie drzewo:** limit `MAX_TREE_DEPTH = 80` liczy sam parser
    (`_OpenElements` podmienia jego stos otwartych elementów). Licznik
    w pre-parserze nie wystarcza: `<li><h1>` albo `<b><div></b>` powtarzane
    w kółko budują drzewo na tysiące poziomów, choć w tekście nic nie wygląda na
    zagnieżdżone. Po przekroczeniu treść jest składana drugi raz ze spłaszczonego
    zapisu (`flatten`: najwyżej `MAX_NESTING = 32` otwartych znaczników, reszta
    pominięta, tekst zostaje),
  - **szerokie drzewo:** `_IndexedTreeWalker` pamięta pozycję rodzica zamiast
    szukać jej wśród rodzeństwa (tysiące akapitów z pogrubieniem w środku),
  - **treść wprost w `<table>`:** ponad `MAX_MISNESTED_IN_TABLE = 1000` takich
    elementów tabele są rozbierane na tekst (`plain_tables`),
  - **tysiące atrybutów w jednym znaczniku:** do parsera trafia pierwsze
    `MAX_ATTRIBUTES = 64` (tokenizer porównuje każdy atrybut z poprzednimi),
  - **tysiące ukrytych znaczników** (`<head>`, `<template>`…): pre-parser
    trzyma licznik i pierwsze otwarcie każdego rodzaju zamiast listy, którą
    przeszukiwał przy każdym znaczniku zamykającym.
  Treść, która nie przekracza limitów, wychodzi bajt w bajt jak z `bleach.clean`
  (wynik jest porównywany przy ponownym zatwierdzeniu i w skrótach kontroli AI).
  Zaczepy siedzą we wnętrzu bleach 6.4.0 — przy podbiciu wersji pierwszy pada
  `test_parser_hooks_are_alive` w `tests/test_html_sanitizer_limits.py`.
- Nieprawidłowa deklaracja w `style` (urwane `font-size`, zbłąkany nawias)
  znika, reszta stylu zostaje. Do 12.10.2026 token błędu z tinycss2 trafiał do
  serializacji i każdy taki `style` kończył zapis CV błędem 500. Wartość
  z setkami zagnieżdżonych nawiasów (`RecursionError` w tinycss2) usuwa cały
  styl zamiast wywracać zapis. Od 14.10.2026 znika też deklaracja z błędem
  W WARTOŚCI (`_broken`: urwany napis `font-size: 'abc`, `f('abc`): tinycss2
  oddawał ją bez zamykającego cudzysłowu i każdy zapis dokładał średniki
  (`"abc;;` → `"abc;;;;`), więc ta sama treść dawała inny wynik sanitizera —
  a ten jest porównywany przy ponownym zatwierdzeniu i w skrótach kontroli AI
  (audyt 13.10.2026). Sanitizer ma być idempotentny; pilnuje
  `tests/test_fix48_ws06_sanitizer_style.py`.
- CV zapisane bez klauzuli nie ma czego chronić: pierwszy akapit klauzuli,
  który ktoś do niego dopisze, staje się chroniony przy następnym zapisie.
- Strażnika nie ma w `_write_stage_draft`: nowy szkic z generatora albo
  z innego CV może przynieść inną klauzulę i to jest poprawne.
- Rozpoznanie klauzuli jest jedno: `is_rodo_node` (znacznik edytora, klasa
  generatora albo pierwsze słowa szablonu) — używa go też generator Worda.

## Pola w nawiasach

Nowe bloki wstawiają pola do wypełnienia w nawiasach kwadratowych
(`[Stanowisko]`, `[MM.RRRR – MM.RRRR]`). „Zapisz” zapisuje szkic, ale nie
zatwierdza CV i nie zamyka okna, dopóki zostały (`cvPlaceholders`). Autozapis
działa dalej.

## Wpis o pobraniu pliku CV (D5)

- Podgląd i pobranie idą tą samą trasą, więc przycisk „Pobierz” dokleja
  `intent=download&surface=…` (`lib/cv-download-intent.ts`). Podglądy —
  „Podgląd Word”, podgląd etapu, okno wyniku — nie doklejają niczego.
- Serwer zapisuje `Activity(action="cv_file_downloaded")` w
  `services/cv_download_log.py`, tuż przed oddaniem pliku (odmowa zgody nie jest
  pobraniem), w SAVEPOINT-cie: błąd zapisu kończy się ostrzeżeniem w logu, plik
  wychodzi. Typ encji to istniejące `candidate_stage_cv` i
  `cv_generated_document`, nie `candidate` — wpis z `candidate` trafiłby na oś
  kandydata, do „ostatniej aktywności” w dodatku Outlooka i do podglądu
  scalania.
- W `details` są tylko `format`, `state`, `surface`, `version`. Bez nazw plików
  (niosą nazwisko, a wpisy przeżywają usunięcie kandydata). Nieznane miejsce
  zapisuje się jako `other`; `SURFACES` jest lustrem `CvDownloadSurface`.
- Odczyt do decyzji przed PR 5 (same liczby):
  `SELECT details->>'surface', details->>'state', count(*) FROM activities
  WHERE action = 'cv_file_downloaded' GROUP BY 1, 2`.

## Panel „Do poprawy” (PR 2, 12.10.2026)

Jedno miejsce na to, co system już wie o CV: QC CV pary, uwagi generatora
i kontrola AI ostatniej zatwierdzonej wersji. Komponent
`components/v2/cv-editor/CvEditorIssues.tsx`, logika w
`lib/cv-editor-issues.ts`, znaczniki w `lib/cv-editor-issue-marks.ts`.

- **Poprawkę liczy serwer na treści Z EDYTORA, a zapisuje autozapis.**
  `POST /api/pipeline/stages/{id}/qc/transform` dostaje HTML z ekranu i listę
  poprawek, zwraca nową treść i NIE zapisuje szkicu. Panel nakłada wynik
  transakcją Tiptapa, a utrwala go zwykły autozapis. Jedna droga zapisu = panel
  i pisanie nie ścigają się o `edit_revision`. Nie wołaj z edytora `qc/apply`:
  zapisuje szkic po stronie serwera i edytor otwarty obok dostaje 409 przy
  następnym autozapisie (okno QC dalej używa `qc/apply`, teraz
  z `expected_revision` → 409 `CV_CHANGED`).
- **Jedno „Cofnij” = jedna poprawka.** `fixStep` zamienia tylko bloki, którymi
  nowa treść różni się od bieżącej (kilka małych zamian w jednej transakcji),
  i zaczyna nowy krok historii (`closeHistory`). Bez tego „Cofnij” zabierało
  razem z poprawką tekst wpisany pół sekundy wcześniej, a jedna zamiana całego
  różniącego się zakresu wyróżniała pół dokumentu. Wynik, który przyszedł po
  tym, jak rekruter coś dopisał, nie jest nakładany (porównanie dokumentu
  sprzed żądania).
  Od 13.10.2026 krok jest sprawdzany w obie strony (`acceptedBothWays`
  w `docStep`): przy klauzuli zgody bez znacznika (starsze CV) poprawka
  dopisująca albo usuwająca akapit tuż przed klauzulą była odrzucana po cichu
  (panel i tak ogłaszał sukces) albo nie dawała się cofnąć. Gdy najmniejsze
  zamiany nie przechodzą, `docStep` zamienia całe bloki, a w ostateczności całą
  treść; `null` znaczy też „edytor tego nie przyjmie”.
- **Zatwierdzona wersja: najpierw szkic, potem poprawka** (`ensureDraft` w
  oknie). Wczytanie nowego szkicu jest poza historią cofania, więc poprawka
  nałożona przed nim nie dałaby się cofnąć. Szkic powstaje dopiero PO tym, jak
  serwer potwierdzi, że poprawka coś zmienia: nowy szkic zdejmuje z CV stan
  „zatwierdzone” (linki, wysyłka), więc poprawka, której nie da się nałożyć,
  nie może kosztować ponownego zatwierdzania.
- **„Popraw wszystko” (decyzja D2)** bierze tylko: pogrubienie wymagań,
  pisownię technologii i zdania AI w brzmieniu z serwera (cytat sprawdzony przy
  pobraniu propozycji). Usunięcie terminu i zdanie AI z własnym tekstem
  zatwierdza się pojedynczo. Listę pilnuje SERWER (`cv_qc.BULK_ACTIONS`, pole
  `bulk`), front tylko jej nie wysyła (`bulkPlan`). Poprawka, której nie da się
  nałożyć, wraca w `skipped` z powodem (200, nie 422) i nie zatrzymuje
  pozostałych. Od 14.10.2026 (D5) propozycje AI ładują się same, gdy QC ma
  pozycję z poprawką AI (`fix: "ai"`) — serwer liczy je zaraz po automacie
  i pamięta per treść, więc zwykle to odczyt z pamięci. Przycisku „Zaproponuj
  poprawki (AI)” nie ma (w oknie QC też); zostaje „Przygotowuję poprawki AI…”
  i „Ponów” po awarii, a „Popraw wszystko” bierze zdania AI od razu. Bez
  pozycji z poprawką AI panel o propozycje nie pyta. Zdania AI serwer nakłada PIERWSZE, niezależnie od kolejności
  w żądaniu: szukają swojej linii po tekście, a pisownia ten tekst zmienia
  (poprawka AI wracała jako „punkt się zmienił”).
- **„Tytuł” nie wchodzi do „Popraw wszystko”,** choć był na makiecie:
  sprawdzenie `title_matches_role` nie ma poprawki w kodzie.
- **Miejsce uwagi szuka się po tym, co widać, nie po indeksie bloku.** QC
  opisuje ZAPISANĄ treść blokami tekstu, edytor trzyma dokument, który rekruter
  zmienia. `locateTarget`: numer stanowiska w sekcji doświadczenia (lustro
  `cv_qc.cv_roles`), etykieta roli, termin w tekście (najpierw w tej roli),
  treść całej linii. Klauzula zgody nie jest miejscem żadnej uwagi. Uwaga,
  której miejsca już nie ma, traci znacznik, a „Pokaż w CV” mówi o tym wprost.
- **Znaczniki przy tekście to dekoracje widoku** (`cv-issue-*`): nie trafiają
  do `getHTML()`, zapisu, Worda ani historii cofania. Czerwony = zatrzymuje
  wysyłkę. Sprawdzenia pogrubień zaznaczają tylko wystąpienia bez pogrubienia.
- **Lista QC dotyczy ostatnio zapisanej treści.** Panel odświeża ją 1,5 s po
  autozapisie przez `GET …/qc?transient=true` (bez zapisu przebiegu — inaczej
  każda pauza w pisaniu dopisywała wiersz `cv_qc_runs`). Przebieg dla Tablicy
  zapisuje się raz, przy zamknięciu edytora, i tylko gdy treść się zmieniła —
  przez `queryClient.fetchQuery`, żeby awaria trafiła do zgłaszania błędów
  zapytań (panelu już wtedy nie ma). Każde otwarcie edytora liczy QC od nowa
  (`refetchOnMount: "always"`, `gcTime: 0`): wynik trzymany w pamięci po
  zamknięciu pokazywał przy ponownym otwarciu listę sprzed poprawek.
- **QC bierze zatwierdzone CV pary, a para może mieć CV na kilku wierszach
  etapu.** Gdy `cv.stage_id` z QC nie jest etapem otwartym w edytorze, panel
  pokazuje komunikat zamiast listy, która nie dotyczy tej treści.
- **Uwagi generatora i kontroli AI:** `GET …/cv/branded/issues`
  (`services/cv_editor_issues.py`). Kontrola AI zapisuje tylko wskaźniki linii;
  tekst linii jest odtwarzany z zatwierdzonej treści wyłącznie przy zgodnym
  skrócie i tej samej wersji podziału na linie. Panel pokazuje te uwagi,
  których linia nadal stoi w CV. Nie ma „Sprawdź teraz” — kontrola biegnie po
  „Zapisz”.
- **Awaria QC nie wygląda jak CV bez uwag:** osobny komunikat z „Ponów”,
  bez zielonej plakietki. Brak dostępu mówi o dostępie. Licznik w pasku niesie
  stan (`CvIssueCount.state`): „Do poprawy” bez liczby, dopóki QC się liczy,
  „Do poprawy (?)” po awarii (panel otwiera się wtedy sam) — zero znaczy zero.
- **Jedna lista od 13.10.2026 (PR 4, „CV w procesie”):** `buildIssueList`
  w `lib/cv-editor-issues.ts` scala zadania QC, uwagi generatora i kontroli AI,
  grupuje je po sekcjach CV (`cvOutline`: „Całe CV”, „Nagłówek”, sekcje
  w kolejności CV, „Pozostałe sekcje”) z etykietą źródła (QC / generator /
  kontrola AI), a uwaga generatora „MUST-HAVE: X” znika, gdy QC mówi o X
  (zadanie, informacja albo pominięcie). Kolejność: „Popraw wszystko”, grupy
  sekcji, propozycje AI, „Zapytaj kandydata”, „Pominięte”, „Informacje”,
  „W porządku”. Edytor bez etapu ma dalej osobny blok uwag generatora.
- **Panel nie ma obejścia QC ani ruchu karty** — przekazanie Delivery
  Leadowi (z obejściem „Przekaż mimo uwag…”) stoi w stopce edytora, sekcja
  „Przekazanie Delivery Leadowi ze stopki” niżej (D6, 14.10.2026); panel
  podaje stopce wynik QC przez `onCount` (`CvIssueCount.qc`). Karty są wspólne
  (`recruitment/cv-qc-cards.tsx`); „Pokaż w CV” i odnośniki w nowej karcie
  włącza kontekst edytora (`locate`, `linksInNewTab`).
- **Układ:** 1180–1539 px (laptop 1280) — obok kartki JEDEN panel: źródła
  (440 px, lewa) albo „Do poprawy” (360 px, prawa); od 1540 px oba; węziej
  przełącznik kolumny. Gdy są uwagi, „Do poprawy” otwiera się samo, raz. Panel
  jest zamontowany także ukryty (`hidden`), bo liczy znaczniki i licznik
  w pasku — nie zamieniaj tego na warunkowe renderowanie.
- **Edytor wyniku generatora** (bez etapu) ma w panelu tylko uwagi generatora
  podane z listy (`generatorWarnings`); QC nie widzi jego edycji. Otwarty bez
  nich (z okna QC) nie ma panelu.
- **Ślad użycia:** `Activity(action="cv_qc_fix_applied", details.via="editor")`
  — ten sam wpis co poprawki z okna QC, z polem `bulk`.
- **Koszt `qc/transform` jest ograniczony** (przegląd bezpieczeństwa
  13.10.2026). Trasa bierze do 500 KB treści od klienta i każda poprawka czyta
  ją od nowa, więc: liczenie idzie w wątku (`run_in_threadpool`), żądanie
  niesie najwyżej 20 poprawek, powtórzona wraca jako `duplicate`, a po
  `TRANSFORM_BUDGET_S` (4 s procesora wątku; pierwsza poprawka idzie zawsze)
  pozostałe wracają jako `budget` z prośbą o nałożenie osobno. Limit 20/min.
  Budżet działa MIĘDZY poprawkami, więc każda musi być liniowa sama z siebie:
  `EditableCv` nie szuka bloków liniowo (`_block_at`, `_starts`), separator
  listy przed terminem ma kotwicę na początku ciągu odstępów (`_SEP_LEAD` — bez
  niej 40 KB spacji liczyło się 12 s), `_wrap_matches` sprawdza kolizję trafień
  po dwóch sąsiadach, a lista technologii jest rozpoznawana raz na blok. Wątek
  nie ratuje przed jednym długim wywołaniem `re` (trzyma GIL). Nowa operacja na
  treści z edytora ma być liniowa — pilnują testy z limitem czasu procesora
  w `tests/test_cv_qc.py` (`TRANSFORM_CPU_LIMIT`, kształty z przeglądu).

## AI na zaznaczeniu (PR 3, 13.10.2026)

> Interfejs (dymek, menu „AI”, karta „było / będzie”) zastąpił 14.10.2026
> asystent w kolumnie — sekcja „Asystent w kolumnie” niżej. Reguły
> sprawdzania faktów (`cv_selection_ai.check`) obowiązują dalej, bo woła je
> asystent; trasa `cv-ai/selection` stoi bez ekranu.

Rekruter zaznacza fragment CV i wybiera: **Skróć · Rozwiń z oryginału ·
Przeredaguj · Popraw język · Na angielski** (dymek nad zaznaczeniem albo menu
„AI” w pasku). Wynik to zawsze PROPOZYCJA na karcie „było / będzie” — do CV
trafia dopiero po „Przyjmij”.

- **Model proponuje, kod sprawdza** (`services/cv_selection_ai.check`).
  Skrócenie, redakcja, korekta i tłumaczenie nie mogą dodać faktu spoza
  zaznaczonego tekstu: liczby, daty, nazwy własnej, technologii
  (`unsupported_facts` z „Ułóż w zdanie”) ani wymagania rekrutacji zapisanego
  małą literą (`dz._found`). Rozwinięcie wolno oprzeć tylko na cytacie, który
  serwer znalazł w oryginalnym CV albo w notatkach (reguły `cv_qc.parse_fixes`:
  co najmniej 4 słowa, nie lista technologii, nie z innego stanowiska, bez
  stawki), a tekst propozycji musi wynikać z fragmentu i cytatu. Sam istniejący
  cytat nie wystarcza — model mógłby zacytować cztery słowa i dopisać cokolwiek.
  Propozycja, która nie przeszła, nie wraca do edytora: wraca powód i zapis,
  o który poszło (`status: "rejected"`).
- **Czego kontrola pilnuje poza nazwami i liczbami** (przeglądy 13.10.2026):
  odnośnika, adresu e-mail i domeny spoza źródeł (`_new_address` — pisane małą
  literą przechodziły kontrolę nazw); znaków niewidocznych i sterujących, które
  `clean_markup` wycina, zanim cokolwiek sprawdzimy (znak zerowej szerokości
  w środku słowa chował wymaganie, NUL odrzucał autozapis, połówka pary
  zastępczej dawała 500); słowa z literą innego alfabetu albo znakiem łączącym
  spoza źródeł (`_odd_character` — cyrylickie „е” wygląda jak łacińskie).
  Liczby porównujemy też po sklejeniu separatora tysięcy („500 000” =
  „500,000”), a miesiąc w propozycji poznajemy po dokładnych formach
  (`_MONTHS`), nie po rdzeniu — rdzeń łapał „mają”, „czerwone” i „major”.
- **Nazwa na początku zdania (14.10.2026).** `unsupported_facts` z „Ułóż
  w zdanie” pomija słowo z wielkiej litery na początku zdania i po
  „( : ; „ " '”, więc przechodziły „Klient: Microsoft — …”, „(Allegro)”
  i dopisane „Microsoft jako główny klient.” (audyt 13.10.2026). Tego pliku nie
  zmieniamy (wspólny z kartą rekomendacji) — `cv_selection_ai._hidden_names`
  sprawdza te słowa wobec fragmentu (przy „Rozwiń” także cytatów):
  - po „( : ; „ " '”, po skrócie („np.”, „m.in.”) i z wielką literą w środku
    słowa („AWS”, „GitHub”) to nazwa — odmowa `new_fact` (w tłumaczeniu
    uwaga, jak inne wielkie litery),
  - zwykły zapis z wielkiej litery na początku zdania („Microsoft”, ale też
    „Tworzenie”) kod nie odróżni od zwykłego słowa: w „Skróć” i „Popraw
    język” to odmowa (nie mają czego dodawać), w „Przeredaguj” i „Rozwiń”
    uwaga na karcie (`cautions`). Pierwsze słowo propozycji, które zastąpiło
    pierwsze słowo fragmentu („rozwój …” → „Tworzenie …”), to redakcja — bez
    uwagi. Tłumaczenie początków zdań nie ocenia (angielski).
- **Plakietka „Zgodne ze źródłem” (14.10.2026)** wymaga, żeby każde słowo
  rozwinięcia stało we fragmencie albo w cytacie (`new_words`, ta sama funkcja
  co przy poleceniu — mieszka teraz w `cv_selection_ai`). Sam istniejący cytat
  dawał plakietkę także „…; kierował zespołem i zarządzał budżetem projektu”.
  Bez plakietki propozycja wraca jako `ok` z `message`, które wymienia słowa
  do sprawdzenia.
- **Rozwinięcie nie przenosi pieniędzy do CV.** Notatki idą do modelu bez pól
  handlowych karty rekomendacji (`CV_HIDDEN_FIELDS`: stawka, red flags,
  motywacja — jak w generatorze CV). Cytat z kwotą nie jest źródłem; o tym, czy
  zdanie mówi o pieniądzach, decyduje całe zdanie źródła, nie wycięty z niego
  kawałek (`_about_pay`, także „150 netto” bez waluty); propozycja nie może
  dodać kwoty, której nie było w zaznaczeniu (`reason: "amount"`).
- **Rozwinięcie a stanowisko.** `resolve_role` wskazuje rolę oryginału tylko
  jednoznacznie: firma, przy dwóch stanowiskach u jednego pracodawcy nazwa,
  przy dwóch o tej samej nazwie (CV „blind”) lata z nagłówka. Cytat sięgający
  w nagłówek innego pracodawcy to inna rola. Gdy fragment stoi w stanowisku,
  a roli nie da się wskazać, propozycja z cytatem z oryginalnego CV wraca BEZ
  plakietki „Zgodne ze źródłem”, z uwagą na karcie (`message` przy
  `status: "ok"`); cytat z notatek nie jest przypisany do roli.
- **Tłumaczenie:** liczby, tokeny z cyfrą i miesiące (tabela PL→EN) muszą się
  zgadzać; nowe wyrazy z wielkiej litery to `cautions` na karcie, nie odmowa —
  angielski pisze wielką literą więcej („Project Manager”). Wymaganie
  rekrutacji zapisane w tłumaczeniu zwykłym słowem („mikroserwisów” →
  „microservices”) też jest uwagą, bo to przekład; zapisane jak nazwa, której
  nie było w zaznaczeniu („…and Kafka”), jest dopisaną technologią i odmową.
  „Na angielski” w polskim CV zostawia polskie etykiety szablonu i klauzulę;
  karta to mówi. Przeniesienie całego CV PL→EN to PR 4.
- **Trasa jest bezstanowa:** `POST /api/pipeline/stages/{id}/cv-ai/selection`
  (`api/cv_editor_ai.py`, bez `from __future__`). Klient wysyła TEKST — fragment
  (`**pogrubienie**`), jego akapit i opis stanowiska z `cvOutline` — nigdy HTML
  ani pozycji w dokumencie; serwer niczego nie zapisuje w szkicu. Nazwy roli od
  klienta służą tylko do WYBORU roli z odczytu oryginału (`resolve_role`).
  Wynik biznesowy to zawsze 200 ze statusem (`ok`, `rejected`, `no_source`,
  `not_supported`, `unavailable`); awaria modelu nigdy nie jest 5xx. Tokeny
  integracji dostają 403 (płatne wywołanie zamawia osoba). Limit 20/min.
  Moduł jest w `_SCOPED_MODULES` kontraktu `tests/test_job_scope_contract.py`
  (od 14.10.2026): każda jego trasa musi wołać `ensure_job_membership`, zanim
  dotknie modelu. Bramka przepuszcza role operacyjne bez przypisania do
  zespołu (reguła 23.09.2026), 403 dostaje dawny podgląd `user`.
- **Przeglądarka czeka 120 s** (`SLOW_ENDPOINT_TIMEOUT_MS` w
  `lib/api/cvEditorAi.ts` i `cvEditorCommand.ts`, od 14.10.2026). Na domyślnych
  30 s instancji `api` przeglądarka zrywała żądanie, zanim serwer skończył
  (polecenie czeka na model do 60 s), rekruter widział błąd, a model i tak
  liczył — „Jeszcze raz” płaciło drugi raz.
- **AI:** klucz `cv_selection_edit` (F30, migracja 0433 + lustro w
  `entrypoint.sh`), Sonnet 5 z zapasem Haiku — recenzent przy „Zapisz” to Luna,
  autor ma być innym modelem. Wywołanie w `ai_feature()` z commitem PRZED
  modelem, limit czasu 30 s łącznie, prompt przez `prompt_fencing` (znaczniki
  `cv_*`, `original_*`, `recruiter_hint`, `previous_proposals` w `_TAG_RE`).
  „Doprecyzuj” to wskazówka stylu — idzie w osobnym znaczniku i nie jest
  źródłem faktów. Wyłącznik: `CV_SELECTION_AI_ENABLED`.
- **Gdzie AI działa:** w obrębie jednego akapitu albo punktu ze zwykłą treścią
  (`selectionTarget`). Nagłówek, stanowisko, firma, etykieta obowiązków
  i lista technologii mają gramatykę, z której serwer składa Word — przyciski
  AI są tam wyłączone z powodem. Klauzula zgody i edytor wyniku generatora
  (bez etapu) nie mają dymka wcale.
- **Zakres czekający na propozycję** (`CvEditorAiPending`) to dekoracja widoku:
  jedzie z tekstem, gdy rekruter pisze gdzie indziej, przeżywa ponowne
  wczytanie tej samej treści (nowy szkic) i gaśnie, gdy zmieni się sam fragment
  — wtedy karta mówi, że tekst się zmienił, i niczego nie nakłada.
- **„Przyjmij” = jedna cofalna zmiana** dokładnie na tym zakresie (`acceptStep`,
  `closeHistory`); pogrubienie z zapisu `**x**`, inne znaczniki obejmujące cały
  fragment zostają. Szkic na zatwierdzonej wersji powstaje dopiero przy
  „Przyjmij” — zamówienie i odrzucenie propozycji niczego w CV nie zmieniają.
  Kontroler nie zeruje się w trakcie przyjmowania (`busy`): założenie szkicu
  przeładowuje treść, a bez tego propozycja znikała, zanim została nałożona.
- **Escape w karcie odrzuca propozycję, nie zamyka edytora.** Radix słucha
  Escape na `document`, więc `stopPropagation` w karcie nie wystarcza — okno
  poznaje kartę po znaczniku `data-cv-ai-card` (`CV_AI_CARD_ATTR`).
- **Dymek i karta stoją w kolumnie kartki** (`createPortal` do `.cv-paper`,
  pozycja z `coordsAtPos`), nie w `body`: okno edytora jest modalne, więc
  element poza nim byłby nieklikalny. Stąd własny dymek zamiast `BubbleMenu`
  Tiptapa — bez nowych zależności. Przycisk dymka robi `preventDefault` na
  `mousedown`, żeby nie zabrać edytorowi zaznaczenia. Karta przewija się do
  widoku przy każdej zmianie swojego rozmiaru (`ResizeObserver`): montuje się
  mała, a rośnie z propozycją i z polem „Doprecyzuj” — na telefonie przyciski
  zostawały pod krawędzią okna.
- **„Pokaż w oryginale”** przy cytacie z oryginalnego CV otwiera źródła i zleca
  „Szukaj w CV” (`CandidatePreviewPane.searchRequest` z zewnątrz) — szuka
  początku cytatu, bo wyszukiwarka PDF-a gubi się na łamaniu wierszy. Karta
  zawsze pokazuje pełny cytat. Numer strony i podświetlenie w „Notatkach” —
  odłożone.
- **Ślad użycia:** `Activity(action="cv_selection_ai")` z akcją, statusem
  i powodem odmowy — bez tekstu CV i propozycji.

## Polecenie dla całego CV (PR 4, 13.10.2026)

> Pole „Polecenie”, panel planu i „Zastosuj zaznaczone” zastąpił 14.10.2026
> asystent w kolumnie (sekcja niżej). Obowiązuje dalej: model zwraca plan na
> numerach wierszy, kod sprawdza każdą operację (`verify_plan`), struktura
> Worda i klauzula są poza zasięgiem modelu.

Przycisk „Polecenie” w pasku otwiera pole: własne słowa („skróć do dwóch stron,
zostaw wszystko o Kafce”) albo gotowe polecenie. Wynik to **plan zmian** —
lista operacji z polami wyboru w panelu obok i podgląd na kartce. Do CV trafia
dopiero to, co rekruter zostawi zaznaczone i zatwierdzi „Zastosuj zaznaczone”.

- **Model zwraca plan, nie tekst CV.** Edytor wysyła CV wiersz po wierszu
  (`lib/cv-editor-command.cvLines`: każdy blok dokumentu i każdy punkt listy,
  tekst z `**pogrubieniem**`, rodzaj, sekcja, numer stanowiska; klauzuli zgody
  nie wysyła wcale). Model odpowiada operacjami na numerach wierszy: `remove`,
  `replace`, `merge`, `reorder`, `remove_role`, `remove_section`.
- **Kod sprawdza każdą operację osobno** (`services/cv_command_ai.verify_plan`)
  i wypuszcza tylko te, które przeszły; odrzucone wracają z powodem (panel mówi
  ile). Reguły, których nie wolno poluzować „przy okazji”:
  - pojedynczo wolno ruszać tylko wiersze `bullet` i `text`; tytuł, nagłówki,
    stanowisko, firma, etykieta obowiązków i lista technologii mają zapis,
    z którego serwer składa Word — znikają wyłącznie z całą rolą albo sekcją;
  - sekcja doświadczenia i ostatnie stanowisko nie znikają; `remove` nie
    zostawia roli ani sekcji bez treści (od tego jest `remove_role` /
    `remove_section`);
  - nowy tekst (`replace`, `merge`) przechodzi tę samą kontrolę „bez nowych
    faktów” co AI na zaznaczeniu (`cv_selection_ai.check`), a ta łapie liczby,
    daty, nazwy własne i wymagania — NIE zwykłe słowa pisane małą literą
    („prowadził zespół”, „magister informatyki”). Dlatego operacja niesie
    `new_words`: słowa nowej treści, których nie było w zastępowanych wierszach
    (z tolerancją odmiany). Taka operacja przychodzi NIEZAZNACZONA, a panel
    pokazuje te słowa. Panel nie może obiecywać więcej, niż kontrola sprawdza
    — zdanie „żadna zmiana nie dopisuje faktów” było nieprawdą;
  - CV bez znaczników stanowisk (starsze, wklejone): wiersz sekcji
    doświadczenia bez numeru stanowiska nie jest ruszany wcale — stanowisko,
    firma i etykieta wyglądają tam jak zwykły tekst;
  - pusty punkt nie jest treścią (nie „trzyma” roli przy życiu); klauzula zgody
    nie jest ruszana ani wpisywana, nawet gdyby edytor ją przysłał; CV bez
    stanowisk zachowuje co najmniej jedną sekcję;
  - jeden wiersz należy do jednej operacji — dlatego rekruter może odznaczyć
    dowolną bez psucia pozostałych;
  - `reorder` to permutacja WSZYSTKICH punktów jednego stanowiska albo sekcji.
- **Wymaganie klienta, które by zniknęło.** Przy operacji stoi lista wymagań
  rekrutacji, które po niej nie występują już nigdzie w CV (`loses`). Taka
  operacja przychodzi NIEZAZNACZONA i z ostrzeżeniem — usunięcie jedynego
  miejsca z wymaganiem ma być świadomą decyzją. `loses` liczy się NARASTAJĄCO
  w kolejności planu (wymaganie w dwóch miejscach, usuwane dwiema operacjami,
  gubi ta druga) i bez znaczników `**` („Spring **Boot**” to „Spring Boot”).
- **Gotowe polecenia** (`PRESETS`) mają treść w kodzie serwera i idą do promptu
  bez ogrodzenia; własne słowa rekrutera to dane w znaczniku
  `recruiter_command`. Polecenie mówi, CO zmienić, i nie jest źródłem faktów.
  „Wersja anonimowa” z makiety nie weszła: zamiana nazwy firmy na opis branży
  dopisuje treść, a generator ma do tego tryb „blind”.
- **Kartka czeka na decyzję.** Od zamówienia planu do „Zastosuj” / „Odrzuć”
  edytor jest tylko do odczytu (`command.locked` → `setEditable(false)`): plan
  odnosi się do wierszy z chwili zamówienia. `applyPlan` i tak sprawdza, że
  wiersze się nie zmieniły, i wtedy niczego nie nakłada.
- **Edytor nie pomija operacji po cichu.** Zmiany kolejności punktów, które
  stoją w dwóch listach, edytor nie umie nałożyć (`canApply`) — taka operacja
  nie trafia do planu i liczy się do odrzuconych. Escape w trakcie liczenia
  planu nie zamyka edytora (pole jest wtedy wyłączone, klawisz trafia w `body`).
- **„Zastosuj zaznaczone” = jedna transakcja** (`applyPlan`: poprawki od końca
  dokumentu, lista bez punktów znika cała), jeden krok „Cofnij”. Szkic na
  zatwierdzonej wersji powstaje dopiero wtedy — zamówienie i odrzucenie planu
  niczego w CV nie zmieniają. Utrwala zwykły autozapis.
- **Podgląd to dekoracje widoku** (`CvEditorPlanPreview`): przekreślone wiersze,
  nowa treść pod zmienianym wierszem, numer nowego miejsca przy przestawianych.
  Nie trafiają do `getHTML()`. Panel „Plan zmian” zajmuje miejsce „Do poprawy”
  (przy jednym panelu naraz także źródeł); na wąskim ekranie to osobna kolumna.
- **Trasa** `POST /api/pipeline/stages/{id}/cv-ai/command` (`api/cv_editor_ai.py`):
  bezstanowa, te same bramki co `cv-ai/selection`, 6/min, limit 400 wierszy
  i 60 tys. znaków, zawsze 200 ze statusem (`ok`, `empty`, `unavailable`).
  Model ma do 60 s (`timeout=45`, `total_timeout=60`), przeglądarka czeka
  `SLOW_ENDPOINT_TIMEOUT_MS` (120 s).
  Klucz AI `cv_editor_command` (F31, migracja 0434 + lustro w `entrypoint.sh`),
  wyłącznik `CV_EDITOR_COMMAND_ENABLED`. Ślad: `Activity(action="cv_command_ai")`
  z nazwą gotowego polecenia i liczbami — bez treści CV i bez własnych słów.
- **Edytor wyniku generatora** (bez etapu) nie ma polecenia: nie ma rekrutacji,
  czyli wymagań do sprawdzenia `loses`, ani uprawnień etapu.
- **Bez miniatur stron z makiety** („Teraz · 3 strony”): edytor nie zna podziału
  na strony. Panel podaje, o ile procent krótsza będzie treść.
- **PL→EN nie weszło** — patrz raport `docs/cv-editor-pr4-completion-report.md`:
  etap trzyma jedno CV w jednym języku, a druga wersja to osobny dokument
  generatora (ok. 3% CV etapów). Do decyzji Artura.

## Historia wersji i powrót pliku Word (PR 5, 13.10.2026)

Przycisk „Historia” w pasku otwiera panel: zatwierdzone wersje CV etapu
(„Porównaj”, „Pobierz DOCX”) i „Wgraj poprawiony plik Word”. Obie funkcje
najpierw pokazują **różnice** wobec bieżącej treści, a dopiero potem —
jednym przyciskiem — wstawiają treść do edytora.

- **Jedna ścieżka zapisu.** Przywrócenie wersji i przyjęcie treści z Worda
  nakłada EDYTOR jedną cofalną zmianą (`lib/cv-editor-diff.replaceContentStep`),
  a utrwala je zwykły autozapis. Serwer nie dostał żadnej nowej trasy
  zapisującej. Dzięki temu CV zostaje podpięte do generatora, zachowuje zrzut
  zgody, szablon, znacznik „blind” i metadane — inaczej niż „Użyj innego CV”
  (`…/cv/branded/upload`), które zapisuje od razu i odłącza CV.
- **Trasy są tylko do odczytu:**
  - `GET …/cv/branded/versions` — zatwierdzone wersje od najnowszej (numer,
    data, IMIĘ zatwierdzającego — nie e-mail, język, czy jest plik Word,
    `is_current`). „Bieżąca” = etap zatwierdzony i ten numer; przy otwartym
    szkicu żadna. CV zatwierdzone przed migracją 0287 nie ma wiersza wersji —
    lista bierze je z wiersza etapu, niczego nie zapisując.
  - `GET …/cv/branded/versions/{n}` — treść wersji (HTML przez sanitizer).
    Bez bramki zgody, jak `GET …/cv/branded`: bramka pilnuje plików, które
    wychodzą do klienta, a pobranie Worda wersji idzie przez bramkowane `/docx`.
  - `POST …/cv/branded/import-preview` — plik Word → HTML edytora, **bez
    zapisu** (szkic, rewizja, wersje i historia zdarzeń nietknięte). Osobny
    moduł `api/cv_editor_import.py`, bo trasa ma limit żądań (10/min),
    a `candidate_stage_cv.py` ma `from __future__ import annotations`. Bramka
    jak przy `…/upload` (zapis w kandydatach + zespół rekrutacji). Odczyt
    pliku i konwersja są wspólne z `…/upload` (`read_word_upload`,
    `word_to_editor_html`); wynik dłuższy niż `CV_CONTENT_HTML_MAX` to 422,
    bo takiej treści nie dałoby się potem zapisać.
- **Historia to zatwierdzone wersje.** Migawek szkicu nie ma w danych (PATCH
  nadpisuje, `edit_revision` to licznik) — panel ich nie udaje.
- **Klauzula zgody zostaje z bieżącego CV** (D3). Treść przychodząca traci
  swoją klauzulę (inną, taką samą, w środku tekstu), a bieżąca wraca na koniec;
  CV bez klauzuli zostaje bez niej. Krok buduje wspólne `docStep`
  (`lib/cv-editor-issues.ts` — to samo, co nakłada poprawki z panelu „Do
  poprawy”): każda próba musi przejść przez wtyczkę struktury razem ze swoim
  cofnięciem (`acceptedBothWays`: historia cofa, odwracając kroki, a przy
  klauzuli BEZ znacznika najmniejsza zamiana sąsiedniego akapitu na tę samą
  literę wchodziła w środek klauzuli — dopisany akapit wtyczka odrzucała po
  cichu, usunięty wchodził, ale „Cofnij” nic nie robiło i blokowało stos).
  Kolejność prób: najmniejsze zamiany → całe różniące się bloki → cała treść
  jednym krokiem; gdy żadna nie przechodzi, `docStep` zwraca `null` i niczego
  nie wstawiamy (`contentDiffers` odróżnia „nie ma czego zmieniać” od odmowy).
  Sterownik ogłasza sukces dopiero, gdy dokument naprawdę się zmienił.
- **Różnice liczymy po wierszach** (`contentLines` + `diffLines`, własny LCS,
  bez zależności), nie po HTML-u: treść z importu ma inny kształt niż treść
  edytora (`<article>`, `li` bez `p`, tylko pogrubienie). Ponad 600 wierszy
  po którejś stronie = komunikat i brak przycisku wstawienia (bez listy różnic
  niczego nie wstawiamy). Plik z samą klauzulą nie czyści CV. Zmiany samej
  struktury (znaczniki, kursywa) nie są na liście — przy równych tekstach
  panel mówi „Treść jest taka sama.” i niczego nie proponuje.
- **Lista różnic dotyczy treści z edytora teraz** — przelicza się 200 ms po
  zmianie. Nasłuch zmian w `useCvHistory` stoi w `useLayoutEffect`, nie
  w `useEffect`: zmiana treści między narysowaniem porównania a zwykłym
  efektem przepadała i licznik zostawał stary (13.10.2026 test wypadł przez to
  z kolejki merge'ów — na wolniejszej maszynie edycja zdążyła przed efektem).
- **Wszystko albo nic.** Makieta miała wybór per różnica i ocenę zgodności ze
  źródłami; weszła lista różnic + jedno wstawienie. Po wstawieniu treść ocenia
  panel „Do poprawy” (QC, w tym twierdzenia bez pokrycia w oryginale).
- **Szkic dopiero przy wstawieniu.** Otwarcie panelu, porównanie i wgranie
  pliku niczego w CV nie zmieniają; na zatwierdzonej wersji nowy szkic powstaje
  przy „Przywróć…” / „Wstaw…” (`ensureDraft`).
- **Wgranie pliku idzie jako `multipart/form-data` jawnie** — instancja `api`
  ma domyślne `application/json` i axios zserializowałby `FormData` do JSON-a
  (strażnik `lib/__tests__/formdata-multipart.test.ts`).
- **Język CV się nie zmienia.** Podgląd importu nie zwraca języka pliku:
  funkcja jest dla TEGO SAMEGO CV poprawionego w Wordzie. Angielski plik
  wstawiony do polskiego CV zostaje „pl” (etykiety przy składaniu Worda).
- **Historia i plan zmian wykluczają się** (jedno miejsce po prawej; przy
  otwartym planie „Historia” jest wyłączona). „Do poprawy” w pasku jest
  włączone tylko, gdy panel faktycznie widać.
- **Konwerter Worda ma limit kosztu** (`cv_docx_import`): akapity i wiersze
  tabel w całym pliku, także puste (`MAX_BLOCKS`), liczba stylów (`MAX_STYLES`),
  styl akapitu czytany raz na styl. Bez tego plik z dziesiątkami tysięcy
  pustych akapitów zajmował konwersję na wiele sekund — a podgląd importu
  dodał do konwertera drugie wejście.
- **Edytor wyniku generatora** (bez etapu) nie ma historii.

## Przekazanie Delivery Leadowi ze stopki (D6, 14.10.2026)

Decyzja Artura D6 z „Drogi rekrutera do DL”
(`rekrutacja-tablica/droga-rekrutera-do-dl.md`): rekruter sprawdza i poprawia
CV w jednym miejscu i przekazuje osobę Delivery Leadowi jednym kliknięciem.

- **Prop `handoff` (`CvEditorHandoff`, reguła w `lib/cv-editor-handoff.ts`).**
  Podaje go `jobs/CvHandoffWorkbench` przez kartę „CV do klienta” do każdego
  otwarcia edytora z karty — tylko gdy karta stoi na „Zweryfikowany”
  (`placeStage(...).column === "verified"`), nie jest tylko do odczytu, a
  szablon ma etap „QC CV”. Bez propa okno wygląda jak dotąd; wynik generatora
  (bez etapu) stopki nie ma nigdy. Działa dla każdego źródła CV (generator,
  kopia z innej rekrutacji, plik Word z profilu albo z dysku).
- **Stopka** (`cv-editor/CvEditorHandoffBar.tsx`): pole „Uwaga dla Delivery
  Leada (opcjonalnie)” (2000 znaków = `StageMove.recruiter_remark`, żyje do
  zamknięcia okna), linia stanu („N rzeczy do decyzji · nic nie blokuje
  wysyłki” / „… · 1 blokuje wysyłkę”), „Zapisz” (z paska przechodzi do
  stopki) i „Zapisz i przekaż do DL →”.
- **Kolejność: zapis jak „Zapisz” (szkic, pola w nawiasach) → ruch →
  zamknięcie → zatwierdzenie w tle.** Zatwierdzenie rusza dopiero po udanym
  ruchu: przy odmowie edytor zostaje otwarty, a zatwierdzenie pod otwartym
  oknem zmieniłoby wersję szkicu i następny autozapis dostałby 409. Odmowa =
  komunikat rdzenia ruchu i zdanie w stopce „CV jest zapisane”.
- **Ruch** idzie `usePipelineMoveCore` (bez własnego `POST /api/pipeline/move`)
  na `stage_def_id` kolumny `cv_qc` bez znacznika Cpro — u Nordei ten sam
  etap, bo tam „QC CV” to przegląd DL przed kolejką Cpro — z
  `expected_state_version` karty i `recruiter_remark` (pustej uwagi nie
  wysyłamy). Konflikt wersji odświeża Tablicę, edytor zostaje.
- **Blokady QC.** Wejście do „QC CV” nie ma bramki QC na serwerze, więc
  obejście jest decyzją produktu: gdy QC tej treści ma blokady i nie jest
  przepuszczone, przycisk to „Przekaż mimo uwag…” → `QcOverrideDialog` (powód;
  Delivery Lead dostaje dzwonek obejścia) → zapis i ruch. Kto może przepuścić,
  mówi serwer (`can_override`, `advisory`); bez tego prawa (poza trybem
  doradczym) przycisk jest wyłączony z powodem. Pola w nawiasach sprawdzamy
  przed oknem obejścia, żeby nie zapisać obejścia bez ruchu. Gdy QC się
  liczy, przycisk czeka; awaria QC nie blokuje (DL widzi wynik w przeglądzie).
- Stan QC stopka bierze z panelu „Do poprawy” (`CvIssueCount.qc` — wynik tej
  treści, `null` przy QC innego CV pary). Lista dotyczy ostatnio zapisanej
  treści, więc poprawka sprzed sekundy liczy się dopiero po autozapisie.
- Toast po sukcesie: „<Imię> — przekazano Delivery Leadowi. Sprawdzamy treść
  CV w tle.” — bez odmiany po rodzaju („przekazana/przekazany”).

## Harness

`/preview/cv-editor?state=draft|finalized|conflict|nosources|clean|qcdown|aidown|handoff|handoff-blocking` —
prawdziwy edytor na stanie z pamięci (`editorApi`, `issuesApi`, `aiApi`, `commandApi`, `historyApi`,
`editorFiles`, `sourceLoaders` jako propsy okna), źródła z zasiewu, sieć odcięta.
„AI na zaznaczeniu” dostaje propozycje z `ai-fixture.ts` (proste przekształcenia
tekstu, bez modelu), a „Polecenie” plan z `command-fixture.ts` (`commandApi`). „Historia”
ma dwie wersje i plik Word z `history-fixture.ts` (`uszkodzony.docx` = odmowa serwera).
`handoff` ma stopkę przekazania na treści bez blokad (ruch w pamięci, strona
pisze, z jaką uwagą), `handoff-blocking` — „Przekaż mimo uwag…” i okno obejścia
(jego zapis idzie przez API, więc w harnessie kończy się komunikatem). Panel
„Do poprawy” dostaje dane z `issues-fixture.ts`: „QC” liczy się tam z ostatnio
zapisanej treści, więc widać obieg poprawka → autozapis → świeża lista. Test
`app/preview/__tests__/cv-editor-harness.test.tsx` montuje całą stronę bez atrapy
Tiptapa; testy okna (`CVBrandedEditModal.test.tsx`) mają atrapę, więc zachowania
zależnego od prawdziwego edytora nie złapią.

## Strażnik klauzuli: koszt liniowy i odmowa pustego zapisu (14.10.2026)

Audyt 13.10.2026 (punkty 1–2): `keep_rodo_clause` przy każdym akapicie
wyglądającym na klauzulę sklejał od nowa cały tekst opakowania — tysiące
akapitów w jednym `<div>` (500 KB mieści się w `CV_CONTENT_HTML_MAX`) to
minuty CPU synchronicznie w trasie `async` jedynego procesu uvicorna, czyli
stojący NEXUS. Teraz `is_rodo_node` czyta tylko początek tekstu
(`_leading_text`, `_PROBE_CHARS`), a wyniki dla elementów jednego drzewa są
zapamiętywane w obrębie przebiegu (`seen`) — 500 KB w ~0,9 s, rośnie liniowo
(`tests/test_rodo_clause_cost.py`). Drugi punkt: `PATCH …/cv/branded`
z treścią, z której po sanitizerze nic nie zostaje (`""`, `<style>…</style>`),
zapisywał pusty szkic, a pusty szkic zdejmował ochronę klauzuli przy
następnym zapisie. Teraz 422 „CV nie może być puste.” — jak zatwierdzenie
i edytor generatora. Pusty dokument z edytora (`<p></p>`) przechodzi jak dotąd.


## Podgląd = plik dla klienta i justowanie (Edytor CV 3, PR 1, 14.10.2026)

Zespół: „podgląd wygląda okropnie, a po pobraniu normalnie” i „brakuje
justowania”. Sprawdzone 14.10.2026 na fikcyjnym CV złożonym kodem z produkcji
(makiety i zrzuty: https://claude.ai/artifact/1g1FJJ2TtojTJSFjmZQj5Z, decyzje
J1–J3 Artura). Obowiązuje:

- **„Podgląd” w karcie „CV do klienta” i w „Użyj innego CV” pokazuje PLIK**
  (`components/v2/cv/CvFilePreviewDialog.tsx` + `CvEditorWordPreview`),
  ładowany `fetchStageCvFile` BEZ intencji pobrania. Wcześniej
  `CvHtmlPreviewDialog` wstawiał surowy HTML w `prose` — nie przypominał pliku
  (usunięty). Gdy pliku nie da się pokazać (409 bez zgody RODO, 403 przy prawie
  tylko do odczytu — `preview-docx` wymaga zapisu), pod komunikatem stoi treść
  w układzie kartki edytora (`CvPaperHtml`, prop `fallback`). Podgląd bez zgody
  RODO musi działać dalej — nie zamieniaj zapasu na sam komunikat.
- **Czcionka Montserrat jest w aplikacji** (`globals.css`, `@font-face` pod
  nazwami z pliku: „Montserrat”, „Montserrat Medium”, „Montserrat SemiBold”,
  „Montserrat ExtraLight”; pliki i licencja w `app/fonts/`). docx-preview
  wstawia te nazwy dosłownie, bez zapasu — bez nich CV rysowało się w Times New
  Roman (Word bierze zapisany w pliku zamiennik Calibri, przeglądarka nie).
  Nie przenoś tego do `next/font` — zmienia nazwę rodziny.
- **CV jest domyślnie wyjustowane (J1).** Reguła klienta
  `client_cv_rules.cv_text_align` (`justify` | `left`, migracja 0441 + lustro
  w `entrypoint.sh`) jest zamrażana w `client_rule_snapshot` przy generacji
  i czytana przez `services/cv_text_align.cv_text_align` w obu rendererach:
  `cv_approved_docx` (styl „Approved CV Body”; nagłówki jawnie do lewej, komórki
  tabel do lewej, klauzula RODO bez zmian) i `docx_renderer.render_cv_to_bytes`
  (punkty, umiejętności, technologie). Brak klucza (stare CV, kopie z Worda)
  = `justify`. Stan CV (`GET …/cv/branded`, edytor generatora) zwraca
  `text_align`, kartka ma `data-cv-align`.
- **Jawne wyrównanie akapitu wygrywa** w każdym bloku treści. Edytor ma
  rozszerzenie TextAlign tylko dla akapitów (`lib/cv-editor-structure.ts`,
  bez skrótów klawiszowych), przyciski „Do lewej” / „Wyjustuj” w pasku
  (`lib/cv-editor-align.ts`: działają na zaznaczeniu, omijają klauzulę zgody).
  Renderer czyta `style` węzła także w punktach (styl `li > p` czytany ZANIM
  powstanie akapit), stanowisku, firmie, etykiecie obowiązków, technologiach,
  umiejętnościach i językach — do 14.10.2026 gubił go wszędzie poza zwykłymi
  akapitami (test: `tests/test_cv_approved_docx_align.py`). `setBlockKind`
  przenosi `textAlign` przy zmianie typu akapitu.
- Harnessy `/preview/cv-to-client` i `/preview/cv-editor` pokazują fikcyjne CV
  w szablonie firmowym (`public/preview/cv-to-client/cv-firmowe-przyklad.docx`,
  wygenerowany `render_approved_docx`); karta przyjmuje `loadStageCvFile`.

## Strony jak u klienta: PDF z pliku Word (Edytor CV 3, PR 2, 14.10.2026)

Decyzja J2 Artura: podgląd CV ma pokazywać prawdziwe strony A4, tak samo na
każdym komputerze. docx-preview nie dzieli dokumentu na strony i nie przypina
klauzuli zgody do dołu ostatniej strony. Obowiązuje:

- **Strony = PDF z TEGO SAMEGO pliku Word** co „Pobierz Word”
  (`services/cv_pdf_preview.docx_to_pdf`, LibreOffice headless w kontenerze
  backendu). Plik Word zostaje jedynym źródłem; nie składaj PDF-a inną drogą
  (HTML → PDF, przeglądarka), bo znów rozjedzie się z plikiem klienta.
- **Trasy** (`api/cv_pdf_preview.py`, osobny moduł bez
  `from __future__ import annotations`, limit `20/minute`) mają te same bramki
  co ich odpowiedniki DOCX: `POST …/stages/{id}/cv/branded/preview-pdf` (szkic,
  prawo zapisu, bez blokady wiersza, żeby nie wstrzymać autozapisu),
  `GET …/versions/{n}/pdf` (wersja zatwierdzona, prawo do dokumentów),
  `POST /api/cv-generator/generated/{id}/editor/preview-pdf`. Zgoda RODO
  (`cv_consent_gate`) jak przy DOCX; `intent=download` zapisuje wpis
  `cv_file_downloaded` z formatem `pdf`, podgląd nie zapisuje nic. Moduł jest
  w `_SCOPED_MODULES` kontraktu zakresu, wzorzec bramek:
  `tests/data/authz_golden/cv_pdf_preview.json` (te same litery co DOCX).
- **Awaria = 503 z polskim komunikatem, a przeglądarka pokazuje plik Word**
  (`components/v2/cv/CvPagesPreview.tsx` → `CvEditorWordPreview` → treść
  w układzie kartki). Brak LibreOffice (lokalnie, w CI), limit czasu (45 s),
  zajęte miejsce (czeka 30 s), wynik, który nie jest PDF-em, i PDF bez
  Montserrat przy CV pisanym Montserrat to ta sama ścieżka zapasu — PDF
  w zastępczej czcionce nie może udawać pliku klienta.
- **Jedna zamiana naraz, kolejka w pętli zdarzeń** (`pdf_from_docx`):
  czekający nie trzymają wątków wspólnej puli (40 na proces — zajęte blokują
  każdą trasę synchroniczną), czeka najwyżej `MAX_WAITING` (4), następny od
  razu dostaje 503 i zapas. Wątek tylko na samą zamianę. Nie wołaj
  `docx_to_pdf` z trasy przez `run_in_threadpool` — to wraca problem.
- **Przed zamianą trasa kończy transakcję** (`_pdf` → `db.commit()`): edytor
  wyniku generatora czyta szkic z `FOR UPDATE`, a blokada trzymana przez
  zamianę wstrzymałaby autozapis; połączenie z bazą też wraca do puli. Wpis
  pobrania idzie po zamianie w nowej transakcji.
- Własny profil LibreOffice na zamianę (`-env:UserInstallation`), osobna grupa
  procesów zabijana w całości, środowisko procesu tylko z `PATH`, `LANG`,
  `LC_*`, `FONTCONFIG_*` (bez sekretów aplikacji), `OSError` przy starcie = 503.
  Pamięć procesu po SHA-256 CZĘŚCI pliku Word (nie bajtów ZIP-a — szkic
  składany od nowa z tej samej treści różni się tylko czasem zapisu), 32 pozycje,
  30 min.
- **Czcionki w obrazie**: `backend/app/assets/fonts/montserrat/` (statyczne
  wagi z nazwami rodzin jak w pliku: „Montserrat”, „Montserrat Medium”,
  „Montserrat SemiBold”, „Montserrat ExtraLight”; licencja OFL) kopiowane
  w `Dockerfile` do `/usr/share/fonts/truetype/montserrat/` + `fc-cache`.
  Czcionki są w repo, a nie z pakietu systemu, bo szablon potrzebuje rodzin
  o dokładnie tych nazwach. Sprawdzenie na serwerze: `fc-list | grep Montserrat`.
- **Front**: `CvPagesPreview` w oknie stron karty (od PR 3: klik w miniaturę) i „Użyj innego CV”
  (`fetchStageCvPdf`, potem `fetchStageCvFile` jako zapas — oba bez intencji
  pobrania) oraz w edytorze: przełącznik „Edycja | Jak u klienta”
  (`CvEditorFiles.draftPdf` / `previewApprovedPdf`; edytor wyniku generatora
  nie ma PDF-u wersji — pokazuje plik Word). W kartce edytora pudełko stron
  dostaje `absolute inset-0` — kartka jest blokiem z przewijaniem, więc
  `flex-1` dałby 0 px.
- **Poza zakresem świadomie**: panel osoby i przegląd DL (`StageCvPreview`)
  zostają na docx-preview — otwierają się przy każdej osobie, a zamiana
  kosztuje ok. 2 s procesora serwera. Szkice nie są zapamiętywane między
  zmianami treści.
- Harnessy pokazują strony z `public/preview/cv-to-client/cv-firmowe-przyklad.pdf`
  (fikcyjne CV z pliku Word harnessu, LibreOffice z Montserrat, metadane bez
  autora). Po zmianie tego pliku Word wygeneruj PDF ponownie.

## Prosty ekran edytora (Edytor CV 3, PR 3, 14.10.2026)

Zespół mówił, że w edytorze „jest chaos” i woli ChatGPT. Artur: „bardzo,
bardzo prosto” (makiety „Ekran 1” i „Ekran 5”). Siedem zasad z makiet, którymi
mierzymy każdą zmianę edytora i karty:

1. Jedno miejsce do AI — kolumna asystenta (PR 4).
2. Problem = jeden przycisk przy pozycji.
3. AI zmienia od razu, z „Cofnij” (PR 4).
4. Nic nie ginie — poprzednia wersja jedno kliknięcie wstecz.
5. Ustawienia schowane: domyślne z reguły klienta, jedna linia i „Zmień”.
6. Pytamy tylko, gdy musimy (fakt bez źródła, usunięcie jedynego wymagania).
7. Podgląd to plik — te same litery, układ i strony co u klienta.

Obowiązuje:

- **Nagłówek w jednym rzędzie** (przy 1280 px): „Zamknij” (ikona), osoba,
  „Szkic vN”, pasek (`CvEditorToolbar`: cofnij, ponów, pogrubienie, lista,
  „Do lewej” / „Wyjustuj”, „Pogrub wymagania (N)”, „Więcej”), „Edycja | Jak
  u klienta”, stan zapisu z godziną („Zapisano 14:01”), „Oryginał”, „Pobierz
  Word”. Nie dokładaj przycisków do paska — nowe polecenie idzie do „Więcej”.
- **„Więcej”**: Dodaj, Typ akapitu, Stanowisko pod kursorem (wyżej, niżej,
  powiel, usuń), „Wyjustuj całe CV” / „Całe CV do lewej”
  (`setCvAlignEverywhere`, jeden krok cofania, bez klauzuli), „Historia
  wersji”, „Pobierz PDF”, „Drukuj”. AI i polecenia nie ma w „Więcej” — od PR 4
  jest w kolumnie asystenta. Menu działa także w „Jak
  u klienta” (pliki, historia); polecenia treści są wtedy wyłączone.
- **„Pogrub wymagania (N)”**: N z wyniku QC (`boldRequirements` w
  `lib/cv-editor-issues.ts`: niepogrubione must i — przy polityce must + nice —
  mile widziane), klik woła przez `ref` panel „Do poprawy”
  (`CvEditorIssuesHandle.boldRequirements`) — ta sama droga co „Pogrub
  wszystkie”: `qc/transform` na treści z edytora, jeden cofalny krok,
  autozapis. Bez wyniku QC przycisk bez liczby i wyłączony; edytor wyniku
  generatora (bez etapu) go nie ma.
- **Jedna kolumna obok kartki**: „Do poprawy” (domyślnie, także bez uwag
  i przy awarii QC) albo oryginał po „Oryginał” (440 px); historia i plan
  zmian zajmują ją na czas decyzji, „Oryginał” zamyka historię. Edytor wyniku
  generatora bez uwag pokazuje w kolumnie oryginał. Układ dwóch paneli od
  1540 px zniknął. Wąski ekran (< 1180 px) — przełącznik kolumny jak dotąd.
- **„Gotowe” w stopce** zamiast „Zapisz” w nagłówku (ta sama ścieżka:
  szkic → pola w nawiasach → zamknięcie → zatwierdzenie w tle). Z przekazaniem:
  „Gotowe” i „Gotowe, przekaż do DL →”. „Zamknij” zamyka bez zatwierdzenia.
  Bez CV stopki nie ma.
- **„Pobierz PDF”**: `CvEditorFiles.draftPdf(payload, purpose)` /
  `approvedPdf(version, purpose)` — `download` niesie intencję (wpis z
  formatem `pdf`), `preview` nie. Edytor wyniku generatora nie ma PDF-u wersji
  — bierze PDF z treści.
- **Kartka jak plik** (`globals.css`, `.cv-paper`): czerwone kwadratowe
  punkty, czerwona linia nad każdą sekcją poza pierwszą i między
  stanowiskami, edukacja w ramce tabeli z szarym nagłówkiem „Daty / Nazwa
  uczelni/kierunek” (sama dekoracja — treść zostaje akapitami). Papieru
  firmowego na kartce świadomie nie ma: szablon bywa różny, a prawdziwy
  papier jest jedno kliknięcie dalej w „Jak u klienta”.
- `initialPanel: "history"` (menu „⋯” karty) otwiera edytor od razu na
  historii; `"issues"` („Sprawdź i popraw”) — na „Do poprawy”.

## Asystent w kolumnie (Edytor CV 3, PR 4, 14.10.2026)

Jedno miejsce do AI (zasada 1): kolumna asystenta pod „Do poprawy” zastępuje
dymek AI nad zaznaczeniem, menu „AI” w pasku i pole „Polecenie” z panelem
planu. Rekruter pisze jak do czatu („rolę w Logistyce skróć do 3 punktów”,
„pogrub Kafkę”, „stanowisko: Senior Java Engineer”) albo klika podpowiedź:
„Skróć do 2 stron”, „Więcej o wymaganiach klienta”, „Popraw język i styl”,
„Usuń najstarsze role”. Front: `cv-editor/useCvAssistant.ts`,
`CvEditorAssistant.tsx`; serwer: `services/cv_command_ai.py`,
`POST /stages/{id}/cv-ai/command` i `…/cv-ai/confirm-fact`.

- **Zmiana od razu, z „Cofnij”** (zasada 3). Operacje, które przeszły
  `verify_plan`, edytor nakłada od razu jedną transakcją
  (`lib/cv-editor-command.applyChanges`) — jeden krok Ctrl+Z i jedno
  „Cofnij” przy odpowiedzi. „Cofnij” działa, dopóki nikt nie zmienił CV po tej
  zmianie (`editor.state.doc === after`); potem jest wyłączony z podpowiedzią
  o Ctrl+Z. Zmienioną treść podświetla dekoracja widoku `CvAssistantHighlight`
  (`.cv-assistant-new`, zielone tło) — nie trafia do HTML ani do Worda.
  Podświetlenie gaśnie przy następnej wiadomości i przy cofnięciu.
- **Kartka czeka na odpowiedź** (`locked`): plan odnosi się do numerów wierszy
  z chwili wysłania, więc do odpowiedzi kartka, „Do poprawy”, historia
  i pliki są wyłączone. Szkic na zatwierdzonej wersji (`ensureDraft`) powstaje
  dopiero przy pierwszej nakładanej zmianie — pytanie bez odpowiedzi szkicu
  nie zakłada.
- **Nowe operacje** (obok `remove`, `replace`, `merge`, `reorder`,
  `remove_role`, `remove_section`): `add` (nowy punkt albo akapit po
  wskazanym wierszu tej samej części CV), `bold` / `unbold` (lista słów;
  nagłówki pomijane), `considered_for` (wiersz „Rozważany na stanowisko:”,
  etykieta zostaje, kwoty odrzucane). Struktura Worda i klauzula RODO dalej
  poza zasięgiem modelu.
- **Pytamy tylko, gdy musimy** (zasada 6), z „Tak” i „Nie” w odpowiedzi:
  - `ask: "source"` — nowa treść ma fakt, którego nie ma w wierszach CV,
    oryginale ani notatkach pary (`_sources`: źródła QC + notatki bez pól
    ukrytych przed CV). „Nie widzę „Terraform” w CV ani w notatkach. Kandydat
    mówił o tym na rozmowie?”. „Tak, dopisz” najpierw zapisuje notatkę
    (`confirm_fact`), potem nakłada zmianę.
  - `ask: "loses"` — po zmianie w CV nie byłoby wymagania klienta, które
    stało tylko w tym miejscu. „Tak, zmień” nakłada zmianę.
  Wiersze operacji z pytaniem odnajdujemy przy odpowiedzi po treści, rodzaju
  i sekcji (`remap`) — wcześniejsze zmiany z tej samej wiadomości przesuwają
  numery. Gdy wiersza już nie ma, odpowiedź mówi to wprost.
- **Fakt z rozmowy = notatka QC.** `confirm_fact` zapisuje notatkę pary
  „Potwierdzone z kandydatem: X — treść” z `external_source` jak „Potwierdzone
  z kandydatem” w QC (`note_kinds.QC_CONFIRM_SOURCE`), więc QC przyjmuje fakt
  jako źródło, a autor i data są w notatkach rekrutacji. Kwot nie zapisujemy
  nigdy (`_MONEY` → 422); pusta treść → 422. Trasa: 20/min, bramka jak
  `cv-ai/command` (członkostwo w rekrutacji, klucz integracji → 403).
- **Rozmowa jako kontekst.** Przeglądarka wysyła do 6 ostatnich wiadomości
  (po 500 znaków) i numery wierszy zaznaczenia (do 60); prompt
  `CV_EDITOR_COMMAND` v2 grodzi je w `<conversation>` i `<selected_lines>`
  jako dane, nie polecenia. Zaznaczony tekst to kontekst wiadomości („Dotyczy
  zaznaczenia: …” nad polem). Ślad użycia (`_log`): rodzaje operacji, pytania,
  liczba wiadomości i zaznaczonych wierszy — bez treści.
- **Kolumna przy 1280 × 720**: „Do poprawy” zwijane nagłówkiem panelu
  (`heading` + `collapsed` w `CvEditorIssues` — jeden nagłówek, nie dwa),
  rozwinięte domyślnie przy blokadach wysyłki, awarii QC i z „Sprawdź
  i popraw”; zwinięte panel dalej liczy znaczniki i liczbę w pasku. Asystent
  ma co najmniej 18rem (nagłówek, dwa rzędy podpowiedzi, pole i kilka linii
  rozmowy), rozwinięta lista 2 : 3 z asystentem; rozmowa przewija się do
  najnowszej odpowiedzi. Edytor wyniku generatora (bez etapu) asystenta nie
  ma — kolumna jak w PR 3.
- **Kwoty** (przegląd PR 4): jeden detektor `cv_command_ai.has_amount` —
  wspólny `money_text` (`MONEY_RE`, `is_rate_text`) plus kod waluty przed
  liczbą („PLN 15000”), „brutto/netto”, „per hour”, „za dzień”. Stawka nie
  wchodzi do CV nigdy; inna kwota (budżet projektu) tylko ta sama, która stała
  w zastępowanym tekście — liczba gdzie indziej w stanowisku niczego nie
  odblokowuje. Notatka z `confirm-fact` z kwotą → 422. „Rate limiting”,
  „50k użytkowników”, „10 tys. żądań” to fakty, nie pieniądze.
- **Dopisanie nie zajmuje wiersza**, za którym staje: dwa punkty za tym samym
  wierszem i nowa treść tego wiersza w jednym planie są w porządku. Wiersz-
  kotwica nie może za to zniknąć (`remove`, `merge`, `remove_role`,
  `remove_section`) ani dostać nowej kolejności swojej listy (`reorder`) —
  `overlap`. Edytor nakłada zmiany od końca dokumentu, w tym samym miejscu
  najpierw dłuższą, a wstawienia w kolejności planu.
- **Odpowiedź na pytanie po innych zmianach** szuka wiersza po treści; ten sam
  tekst w kilku miejscach = po kolejności wystąpienia, a gdy liczba wystąpień
  się zmieniła — „CV zmieniło się…”, bez zgadywania.
- **Zapis czeka na asystenta**: „Gotowe” i „Gotowe, przekaż do DL” są
  wyłączone, dopóki asystent liczy albo nakłada odpowiedź na pytanie.
  Odpowiedź, która przyjdzie po zablokowaniu edytora, nie wchodzi
  („Odpowiedź przyszła, gdy CV się zapisywało…”).
- **Escape** w kolumnie (`data-cv-panel`, `Marked.tsx`) nie zamyka edytora.
- Harness `/preview/cv-editor`: `command-fixture.ts` odpowiada bez sieci
  (skrócenie, „terraform” z pytaniem o źródło, „stanowisko: …”, pogrubienie,
  „Usuń najstarsze role” z pytaniem o wymaganie).
