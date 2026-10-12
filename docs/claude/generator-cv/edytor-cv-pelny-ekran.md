# Edytor CV na cały ekran — kartka, bloki, źródła, stała klauzula RODO (12.10.2026)

<!-- indeks: kontrakt HTML edytor ↔ Word, bloki i etykiety szablonu, blokada klauzuli (przeglądarka + serwer), pola w nawiasach, wpis `cv_file_downloaded`, harness `/preview/cv-editor` -->

Pomiar na produkcji (30 dni do 12.10.2026, tylko odczyt, same liczby): 686 CV
z generatora, w edytorze poprawiono 17 (2,5%), mediana 2 zapisy i 1,5 minuty.
Poprawki szły w Wordzie poza NEXUSEM, a wersja wysłana klientowi nie wracała.
Decyzje Artura D1–D6 (makiety: https://claude.ai/artifact/N82z8poJ4waexM46zLvMkg,
prywatne): pełny ekran, „Popraw wszystko” tylko z dowodem, klauzula RODO bez
edycji, powrót pliku Word, zapis pobrań, pięć PR-ów po kolei. Ten plik opisuje
PR 1 (edytor bez AI); kolejne PR-y dopisują swoje sekcje tutaj.

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
- Od 1180 px szerokości źródła stoją obok kartki (440 px, zwijane), węziej jest
  jedna kolumna z przełącznikiem „CV | Źródła”.

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
  tekst poszedłby do klienta jako treść CV. Kopię klauzuli wklejoną w głąb
  listy naprawa usuwa.
- Serwer: `cv_rodo_clause.keep_rodo_clause(zapisane, przysłane)` wszędzie,
  gdzie treść z edytora jest zapisywana, sprawdzana albo składana w Word:
  `update_branded_cv`, `finalize_stage_cv`, `cv_generated_editor.save` /
  `finalize`, `cv_approval_queue.enqueue_review` oraz oba rendery szkicu
  (`render_stage_editor_docx`, `cv_generated_editor.render`). Kontrola AI
  i zatwierdzenie muszą dostać tę samą treść: zatwierdzenie szuka wyniku
  kontroli po skrócie treści, więc kontrola policzona bez klauzuli kończyła się
  409 „Uruchom kontrolę” bez końca.
- Nietknięta klauzula = treść wraca bajt w bajt; usunięta albo zmieniona wraca
  z zapisanego CV; inny tekst ze znacznikiem klauzuli zostaje w treści bez
  znacznika. Kandydat na klauzulę to `p` albo `div` bez bloków w środku, tak
  jak w generatorze Worda. Przebudowana treść przechodzi jeszcze raz przez
  sanitizer. Pusta treść zostaje pusta, żeby wołający dał swoje 422.
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

## Harness

`/preview/cv-editor?state=draft|finalized|conflict|nosources` — prawdziwy
edytor na stanie z pamięci (`editorApi`, `editorFiles`, `sourceLoaders` jako
propsy okna), źródła z zasiewu, sieć odcięta. Test
`app/preview/__tests__/cv-editor-harness.test.tsx` montuje całą stronę bez atrapy
Tiptapa; testy okna (`CVBrandedEditModal.test.tsx`) mają atrapę, więc zachowania
zależnego od prawdziwego edytora nie złapią.
