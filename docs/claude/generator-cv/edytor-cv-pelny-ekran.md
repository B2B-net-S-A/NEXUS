# Edytor CV na cały ekran — kartka, bloki, źródła, stała klauzula RODO (12.10.2026)

<!-- indeks: kontrakt HTML edytor ↔ Word, bloki i etykiety szablonu, blokada klauzuli (przeglądarka + serwer), pola w nawiasach, wpis `cv_file_downloaded`, panel „Do poprawy” (QC, uwagi generatora, kontrola AI, „Popraw wszystko”, `qc/transform`), harness `/preview/cv-editor` -->

Pomiar na produkcji (30 dni do 12.10.2026, tylko odczyt, same liczby): 686 CV
z generatora, w edytorze poprawiono 17 (2,5%), mediana 2 zapisy i 1,5 minuty.
Poprawki szły w Wordzie poza NEXUSEM, a wersja wysłana klientowi nie wracała.
Decyzje Artura D1–D6 (makiety: https://claude.ai/artifact/N82z8poJ4waexM46zLvMkg,
prywatne): pełny ekran, „Popraw wszystko” tylko z dowodem, klauzula RODO bez
edycji, powrót pliku Word, zapis pobrań, pięć PR-ów po kolei. Ten plik opisuje
PR 1 (edytor bez AI) i PR 2 (panel „Do poprawy”); kolejne PR-y dopisują swoje
sekcje tutaj.

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
  styl zamiast wywracać zapis.
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
- **Zatwierdzona wersja: najpierw szkic, potem poprawka** (`ensureDraft` w
  oknie). Wczytanie nowego szkicu jest poza historią cofania, więc poprawka
  nałożona przed nim nie dałaby się cofnąć.
- **„Popraw wszystko” (decyzja D2)** bierze tylko: pogrubienie wymagań,
  pisownię technologii i zdania AI w brzmieniu z serwera (cytat sprawdzony przy
  pobraniu propozycji). Usunięcie terminu i zdanie AI z własnym tekstem
  zatwierdza się pojedynczo. Listę pilnuje SERWER (`cv_qc.BULK_ACTIONS`, pole
  `bulk`), front tylko jej nie wysyła (`bulkPlan`). Poprawka, której nie da się
  nałożyć, wraca w `skipped` z powodem (200, nie 422) i nie zatrzymuje
  pozostałych. Propozycji AI panel nie pobiera sam — to płatne wywołanie,
  rekruter klika.
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
  zapisuje się raz, przy zamknięciu edytora, i tylko gdy treść się zmieniła.
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
  bez zielonej plakietki. Brak dostępu mówi o dostępie.
- **Panel nie ma obejścia QC ani ruchu karty** — to zostaje w oknie QC. Karty
  są wspólne (`recruitment/cv-qc-cards.tsx`); „Pokaż w CV” i odnośniki
  w nowej karcie włącza kontekst edytora (`locate`, `linksInNewTab`).
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

## Harness

`/preview/cv-editor?state=draft|finalized|conflict|nosources|clean|qcdown` —
prawdziwy edytor na stanie z pamięci (`editorApi`, `issuesApi`, `editorFiles`,
`sourceLoaders` jako propsy okna), źródła z zasiewu, sieć odcięta. Panel
„Do poprawy” dostaje dane z `issues-fixture.ts`: „QC” liczy się tam z ostatnio
zapisanej treści, więc widać obieg poprawka → autozapis → świeża lista. Test
`app/preview/__tests__/cv-editor-harness.test.tsx` montuje całą stronę bez atrapy
Tiptapa; testy okna (`CVBrandedEditModal.test.tsx`) mają atrapę, więc zachowania
zależnego od prawdziwego edytora nie złapią.
