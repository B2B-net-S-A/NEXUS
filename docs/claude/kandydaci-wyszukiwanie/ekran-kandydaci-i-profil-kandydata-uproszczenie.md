# Ekran „Kandydaci” i profil kandydata — uproszczenie (22.09.2026)

Decyzja Artura 22.09.2026 (makiety: https://claude.ai/artifact/UwUfN2BH4fgGxPWHLD1hfC,
wariant A + „filtry na stałe po lewej” + „wybór źródła na starcie”). Zastępuje
trzy tryby z 21.09 (Baza / Wyszukiwanie / Z treści requestu).

**Lista `/candidates` = JEDEN ekran, jeden silnik (`GET /api/candidates`).**
- Filtry stoją PASKIEM NAD TABELĄ (`components/v2/candidates/CandidateFilterBar.tsx`;
  wariant A z makiet https://claude.ai/artifact/7MJmn8Unqc26J6yHB9ThNG,
  **decyzja Artura 23.09.2026** — do tego dnia była kolumna 224 px po lewej
  i szuflada „Zaawansowane” z prawej; tabela z 8 kolumnami dostaje teraz całą
  szerokość). Priorytet z 22.09 zostaje: „szukamy głównie ręcznie po słowach
  kluczowych i wykluczeniach, stawce, lokalizacji i trybie pracy”. Rząd 1:
  słowa kluczowe jako LISTA WYMAGAŃ (`KeywordFields` w
  `CandidateSearchFields.tsx` → `RequirementRowsField`; od 25.09.2026 zamiast
  trzech woreczków — patrz „Wyszukiwanie ręczne: …”), „Wyklucz” `q_none`,
  „Szukaj w” `q_scope`; zasady dopasowania pod ⓘ; na telefonie za przyciskiem
  „Słowa kluczowe (N)”). Rząd 2: przyciski z okienkami
  (Radix Popover) — Stawka · Lokalizacja (miasto z podpowiedziami, promień w km,
  województwa; tekst wpisany tuż przed zamknięciem okienka zapisuje cleanup
  `LocationFields`) · Tryb pracy | Historia z nami (blok „Rekrutacje”: brał /
  nie brał udziału, bez procesu w toku — osobna reguła „Blok „Rekrutacje”…”;
  etap, wysłany do klienta, pracował u klienta, KONTAKT z kandydatem w okresie
  i przez kogo) · Umiejętności · Dostępność (jedno pytanie „Czy można go teraz
  zaproponować?” — `lib/candidate-availability-choice.ts` ustawia
  `availability` + `employment` naraz) · „Więcej filtrów” (szuflada z prawej:
  Doświadczenie/języki/kategoria, Firma i stanowisko, Kto dodał/pule — w tym
  „Moi kandydaci”, Inne — tagi, status w bazie, otwarty na, ukryj
  bez danych). Ustawiony przycisk niesie wartość („Stawka: do 160 zł/h”) albo
  licznik i ✕ czyszczące grupę — liczniki i podsumowania liczy
  `lib/candidate-filter-groups.ts`. Chipy nad tabelą (`ActiveFilterChips`
  z `omitKey={isChipShownOnFilterBar}`) pokazują TYLKO filtry, których wartości
  nie widać na przycisku — nie dubluj ich. Gotowych skrótów nad listą świadomie
  NIE ma („za bardzo kombinujesz”). Nie dokładaj kolejnych przycisków na pasek —
  rzadkie filtry idą do „Więcej filtrów”. Tabela ma domyślnie kolumny:
  Kandydat (pod nazwiskiem miasto) · Ostatnie stanowisko (+ firma,
  `getCurrentTitle`/`getCurrentCompany`) · Telefon (`tel:` + kopiuj,
  `CandidatePhoneCell`) · Stawka B2B · Dostępność · W procesie (skrót, a po
  najechaniu/kliknięciu lista rekrutacji w toku z klientem i etapem,
  `CandidateProcessCell` — reguła „w toku” jedna: `activeRecruitments`) · CV
  (podgląd, `CandidateCvCell`; przycisk tylko przy `has_cv_document` z listy —
  NIE przy `cv_filename`, bo import Traffita wpisuje nazwę pliku, zanim faza
  plików go pobierze) · Przypisz (widoczny przycisk „Rekrutacja”;
  hurtem przez zaznaczenie i `CandidateBulkBar`). Przycisk „Kolumny” pozwala
  każdemu dołożyć E-mail, Lokalizację, Staż, Ostatni kontakt, Dodano albo
  schować kolumnę (`lib/candidate-table-columns.ts`; wybór w przeglądarce,
  `useUiStore.columnPreferences["candidates-table-v2"]` = lista ukrytych;
  Kandydat i Przypisz zawsze). Bez presetów, kafelków i gęstości
  (`/api/settings/candidates-columns` nie ma konsumenta na tym ekranie).
- **Słowa kluczowe v2 = CAŁE SŁOWA (porównanie z Traffitem, 22.09.2026).**
  „java” nie znajduje „JavaScript” (przed zmianą: 22 384 osoby, w Traffit
  15 916; po zmianie 14 071 w 0,7 s). `java*` = początek słowa, `*script` =
  koniec, fraza = słowa obok siebie, `c++`/`.net` z granicą słowa tylko po
  stronie litery. Reguła ma trzy lustra: `services/keyword_terms.py` (regex
  Postgresa + Pythona i `to_tsquery`), `advanced_candidate_search._whole_word_match`
  (FTS dla słów i fraz, regex z jawną klasą liter — ctype produkcji to `C`,
  więc `[[:alnum:]]` zna tylko ASCII) i wycinki `candidate_snippets.extract_field_snippets`.
  **v1 (alerty starych zapisów) zostaje przy podłańcuchu.** Zakres `q_scope`
  (`all|cv|title|skills|notes`, „Stanowisko” = `experience[*].role`) działa
  tylko w v2 i dotyczy wszystkich trzech pól słów. Odpowiedź v2 niesie
  `match_snippets` — każde pole z trafieniem (do 5, po 2 okna) z zakresami
  pogrubień liczonymi na serwerze; front (`FieldSnippets`) nie powtarza reguły.
- **Słowa kluczowe v2 szukają w KORPUSIE, nie w `search_fts`/`search_doc`**
  (migracja 0350, `services/keyword_corpus.py` = jedno źródło listy pól dla
  SQL-a triggera i wycinków). Porównanie z Traffitem na próbce 3 250 osób ×
  18 zapytań (22.09.2026): NEXUS znajdował ~84% osób z Traffita, a różnica
  siedziała w polach, nie w dopasowaniu. Korpus: CV + profil + pola Traffita
  (`cv_extracted_data.traffit_Position/technologie/certificates/
  previous_employers/education/nationality`) + „Kandydat o sobie”
  (`profile_about`); z JSON-ów WYŁĄCZNIE wartości treści (rola, firma, opis,
  technologie; nazwa umiejętności; szkoła/kierunek/stopień; nazwa języka;
  tagi-napisy). **Nie dokładaj `ai_summary`** („bankowość” z AI dawała 9 794
  osoby przy 810 w Traffit) **ani surowego `::text` JSON-ów** (poziom
  umiejętności „junior” miało 26 609 osób, więc „java NIE junior” wycinało
  seniorów). „Stanowisko” = role + `traffit_Position`, „Umiejętności” = nazwy
  + `traffit_technologie`. Kolumny `keyword_doc` (profil bez CV, bez polskich
  znaków, trigram) i `keyword_fts` (profil + CV, GIN) liczy TRIGGER; istniejące
  wiersze uzupełnia pętla `keyword_corpus_backfill` po starcie (backfill
  w migracji = 6 min 502, jak przy 0143), a do jej końca
  `keyword_corpus.ready()` dokłada gałąź po starych kolumnach dla wierszy
  z `keyword_doc IS NULL`. v1 dalej czyta `search_fts`/`search_doc`.
  `.net` (kropka na początku) ma granicę słowa po lewej, poza `ASP/ADO/VB`
  (`keyword_terms.DOT_PREFIXES`) — klauzula „zgoda … B2B.net S.A.” jest w
  prawie każdym CV. Czego NIE da się dogonić: Traffit szuka też we własnym
  parserze CV i w tagach, których publiczne API nie wystawia.
- **Tekst CV czyta faza `candidates_cv_text` nocnego syncu** (budżet
  `TRAFFIT_SYNC_CV_TEXT_LIMIT`, `cv_text_backfill.run_backfill`). Do 22.09
  pliki pobierane przez sync nie dostawały tekstu (jednorazowy skrypt
  z 10.08), a ekstraktor wybierał parser po NAZWIE: 3 320 PDF-ów zapisanych
  jako `*.docx` dostało terminalny znacznik `empty`. Format rozpoznaje
  `cv_text_extractor.sniff_extension` (pierwsze bajty); znaczniki
  `empty/unsupported_format/legacy_doc` bez flagi `sniffed` dostają jedną
  ponowną próbę. **Tekst SKLEJONY** (średnia „słowa” > 12 znaków,
  `cv_text_extractor.looks_glued`; 1 581 CV 23.09.2026, prawie same PDF-y
  z ciasnym kerningiem) PDF czyta drugi raz z `x_tolerance=1` — tylko jako
  ścieżka zapasowa, bo niższy próg dla wszystkich rozcinałby rozstrzelone
  nagłówki. Te same CV czyta ponownie drugi przebieg fazy
  (`run_backfill(glued=True)`, CLI `--glued`); gorszy odczyt nie nadpisuje
  tekstu i dostaje znacznik `still_glued`, błąd pobrania — nie.
- **Lokalizacja z promieniem i województwo** (`services/pl_places.py`, dane
  `app/data/pl_places.json` z GeoNames, CC BY 4.0, 3 331 miejscowości,
  pokrycie 95% kandydatów z miastem). Kandydaci NIE mają współrzędnych, więc
  filtr wylicza w Pythonie nazwy miejscowości w promieniu i porównuje je
  z kluczem nazwy `city`/pierwszego członu `location` (`place_key_sql` —
  lustro `place_key`). Kraj inny niż PL odpada (zagraniczna nazwa bywa równa
  polskiej wsi). Nieznane miasto z promieniem = 422 po polsku. Podpowiedzi:
  `GET /api/candidates/places/suggest` (bez bazy).
- **Kontakt z kandydatem** (`contacted=yes|no`, `contacted_from/to`,
  `contacted_by`): notatka, rozmowa (`calls`) albo aktywność Traffita
  `Email`/`Reply`/`Rozmowa telefoniczna`/`Spotkanie`. Historia z Traffita ma
  datę importu (5.05.2026) — okres wcześniejszy nic nie znaczy.
- **Zapisane wyszukiwania: dzwonek domyślnie WŁĄCZONY przy zapisie**
  (22.09.2026 na produkcji: 3 zapisy, 0 z dzwonkiem, skaner nie sprawdził
  nikogo). Skaner pyta listę o `changed_after` (zmiana wiersza ALBO nowa/
  zmieniona notatka ALBO nowy dokument — notatka dodana w NEXUSIE nie rusza
  `candidates.updated_at`). `POST /saved-searches/{id}/viewed` zwraca
  `new_candidate_ids` z logu alertów, a lista oznacza „Nowy” tych ludzi (plus
  nowo dodanych); samo `updated_at` odpadło, bo nocny import podświetlał tysiące.
- **Jedno pole wyszukiwania szuka też „po znaczeniu”.** Lista wysyła
  `text_mode` (URL `tm`, domyślnie `auto`) przy niepustym `q` i v2; backend
  (`_resolve_semantic_text` w `api/candidates.py`) idzie wtedy pulą
  `candidate_text_retrieval.semantic_pool` — tą samą co wyszukiwarka — chyba że
  tekst wygląda na osobę (nazwisko / e-mail / telefon → dosłownie). Pula ZAWĘŻA
  (pusta pula = 0 wyników, nigdy cała baza), pozostałe filtry działają, a bez
  jawnego `sort` kolejność = ranking puli. Odpowiedź niesie
  `text_mode_applied`, `search_degraded`, `result_cap_reached`.
  **v1 i żądania BEZ `text_mode` zostają dosłowne** — na tym stoją alerty
  zapisanych wyszukiwań, które skaner (i porównanie migracji) odtwarza zawsze
  dosłownie (`with_literal_text()`); semantyczne alerty gubiłyby nowych
  kandydatów spoza puli i płaciły za embedding przy każdym przebiegu.
- **Eksport „z filtra” używa TEJ SAMEJ decyzji** (`_resolve_semantic_text`) —
  plik zawiera dokładnie to, co widać na ekranie (test w
  `test_list_semantic_text_and_languages.py`).
- **Filtr języków na liście** (`languages=kod[:POZIOM]`, URL `lang`) — ta sama
  reguła co wyszukiwarka (`candidate_search_predicates.language_clause`);
  w zapisanych wyszukiwaniach to pole WSPÓLNE (`[{code, min_level}]`).
- **„Z requestu”** otwiera okno z wyborem źródła (wklej tekst / plik Championa /
  rekrutacja z NEXUSA) + klient, budżet, dni w biurze
  (`RequestSearchDialog.tsx`). „Dalej” prowadzi do `?mode=request`
  (`TalentRadarWorkspace` z propem `initial`, od razu na sprawdzeniu wymagań);
  dane idą STANEM `CandidatesWorkspace`, nigdy adresem (treść requestu jest
  poufna).
- **Stare adresy:** `?mode=search` bez `job` jest przepisywane na adres listy
  (`lib/candidates-search-redirect.ts`); `?mode=search&job=` (ręczne szukanie
  z rekrutacji) nadal renderuje `CandidateSearchView`; `/talent-radar` bez zmian.
- **„Szukaj ręcznie” w oknie rekrutacji = ta lista w trybie osadzonym**
  (`CandidatesListV2 embed`, decyzja Artura 25.09.2026 — wcześniej stary
  formularz `CandidateSearchView`). Stan startuje z filtrów rekrutacji
  (`ManualSearchPanel.jobListFilters`: tytuł po znaczeniu, must-have jako
  „Mile widziane”, pierwsze miasto, kategoria, status bez czarnej listy),
  NIGDY z adresu strony rekrutacji. Osoby już w rekrutacji ukrywa zapytanie
  (`recruitment_match=not_assigned`, `candidatesListFiltersForQuery`) — poza
  chipami i „Wyczyść”; te same filtry idą do podglądu i linku profilu, a
  wybór rekrutacji w bloku „Rekrutacje” jest tu zablokowany zdaniem
  (`recruitmentFilterLocked`), bo zapytanie i tak by go nadpisało — same opcje
  („Bez procesu w toku” itd.) zostają. Dochodzi kolumna „Dop.” (`jobOnly`, osobny klucz
  kolumn `candidates-table-job-search`, telefon domyślnie schowany, żeby
  „Dodaj” mieściło się w oknie), a „Dodaj” / „Dodaj N do Nowych” woła
  `proposals/bulk` ze źródłem `manual_search`. Świadomie odpadły: przypięte
  zapisane wyszukiwania, diagnostyka pustego wyniku, shortlista, opcje etapu,
  notatki i tagów przy dodawaniu. Harness `/preview/candidates-list?embed=1`.
- **Podgląd kandydata** (`CandidateQuickView`) jest odchudzony: fakty
  (dostępność, stawka z `quick-view` — `expected_rate_hourly`, lokalizacja),
  kontakt, „W procesie”, ostatnia notatka, „Przypisz” i „Otwórz profil”.
  „Oznacz jako zatrudnionego” żyje wyłącznie w jego menu „⋯”.

**Profil `/candidates/[id]` — pasek osoby, „Do propozycji” po lewej, 6 zakładek
(E1–E6 i D1–D8, decyzje Artura 13.10.2026; makiety
https://claude.ai/artifact/LPzm9GQGPQCrnWjdtg2WG9 i
https://claude.ai/artifact/K45m9WCNz9ypfKBE87B9dv). Zastępuje wariant B z 04.10.2026.**
`?tab=summary|recruitments|screening|activity|cv|documents` = Przegląd · Rekrutacje
· Screening · Notatki · CV · Dokumenty. Treść w `components/v2/candidate-profile/*`;
`CandidateDetailV2.tsx` jest orkiestratorem. Zasady, których łatwo nie zauważyć:
- **Układ (E1):** nad siatką pasek osoby na całą szerokość (`ProfilePersonBar`
  w `candidate-profile/ProfileHeader.tsx`): awatar (inicjały tylko z liter —
  `getCandidateInitials`), imię, nagłówek, pigułki, kontakt, obecni na profilu
  i akcje w jednym rzędzie „Przypisz do rekrutacji” · „Dodaj notatkę” · „Nie
  odebrał” · „⋯”. Menu „⋯”: Kontakt (Napisz maila, Zaplanuj rozmowę, Zaproś na
  prep, follow-up) · Dane (Edytuj dane, Tagi i pule, Konflikty i weta, Scal z…)
  · Usuń profil. Adres e-mail w pasku otwiera okno M365 (`SendEmailV2`), obok
  kopiowanie adresu i numeru. Aktywny konflikt z klientem to czerwony chip
  otwierający „Konflikty i weta”. Od 1100 px lewa kolumna (przyklejona) =
  „Do propozycji” (`CandidateProfileFactsBar layout="proposal"`): na górze
  ramka zatrudnienia (`AtOurClientBanner compact`), fakt w jednej linii,
  źródło wartości jako kropka-przycisk z okienkiem (działa też na dotyk), bez
  edycji „Praca” = tryb + miasto w jednym wierszu. Pod kartą linia „N rzeczy
  do sprawdzenia z rozmowy · Sprawdź” — liczba pozycji `can_apply`
  z `GET /notes-facts`, tylko z `candidate.profile_fact.manage`.
- **Pigułka dostępności zamiast „Aktywny/Pasywny” (D4):** `ds/AvailabilityPill`
  („Szuka aktywnie” / „Otwarty na oferty” / „Nie szuka”; `unknown` = brak
  pigułki), etykiety z `lib/candidate-availability-label.ts`. Ta sama pigułka
  (`appearance="text"`) stoi w drugiej linii wiersza listy. Czarna lista
  zostaje jedynym ostrzeżeniem statusu. Szybki podgląd jeszcze pokazuje
  „Aktywny/Pasywny” (poza zakresem 13.10).
- **Martwe funkcje zdjęte z profilu (D1–D3, liczby z produkcji 13.10.2026):**
  „Obserwuj” i pasek przypiętych na liście, „Wrzuć na targ”, „Korekta imienia
  i nazwiska” (czyszczenie e-maila i telefonu oraz przycinanie imienia przejęło
  „Edytuj dane”), „Generuj CV” z menu (zostaje w CV i w karcie rekrutacji),
  przycisk CloudTalk, status kontaktu i „Zaloguj wynik”, pasek „Ocena ryzyka
  chwilowo niedostępna”, „Zaangażowanie”, synchronizacja z LinkedIn, filtr
  „Telefony”. Trasy backendu tych funkcji zostały — powrót na profil tylko
  decyzją Artura.
- **Każdy fakt pokazany RAZ:** stan dostępności żyje w pigułce paska osoby,
  a w „Do propozycji” tylko termin („od 10.09”, „za 1 mies.”, „nie ustalono”);
  stawka, praca, języki i narodowość wyłącznie w „Do propozycji”. Ołówki
  pokazuje dopiero „Edytuj” (`candidate.profile_fact.manage`). Dostępność
  zapisuje PATCH kandydata tylko ze zmienionymi polami
  (`lib/candidate-availability-edit.ts`), lokalizacja też (z regionem i hubem).
  Kontrakt źródła `CandidateDetailRecruiterUx.test.ts` pilnuje, że
  `availability_status` w orkiestratorze trafia tylko do pigułki.
- **Przegląd (E2):** „W skrócie” (`CandidateActivitySummaryCard
  variant="compact"`, jedyna karta AI) obok „Ostatnio” (trzy ostatnie
  stanowiska) → 8 umiejętności z „+N w zakładce CV” → „Do zrobienia” (zaległy
  telefon po ciszy klienta i procesy z ruchem po naszej stronie —
  `next_action_owner` ∈ rekruter / do przejrzenia / Delivery,
  `recruitmentsAwaitingUs`, najwyżej 3) → pasek „Z nami” (w toku, zakończone,
  ostatnia rozmowa, próby kontaktu, w bazie od) → „Ostatnia rozmowa”. Bez
  procesu w toku: „Nie jest teraz w żadnej rekrutacji. Ostatnio: …”. Kto ma
  ruch liczy SERWER (`/history` → `next_action_owner`, reguła karty na
  Tablicy, `null` dla zakończonych; zatrudnienie też kończy proces).
- **Rekrutacje (E3, D5):** „W toku · N” jako tabela (`ActiveRecruitmentsTable`:
  rekrutacja z klientem, etap, ruch, dni, stawka, do klienta przy prawie
  wglądu), od najdłużej bez ruchu. Klik rozwija wiersz: `RecruitmentCard`
  (stawki, CV, akcje), feedback po rozmowach tej rekrutacji i „Ocena
  dopasowania · Pokaż” (`DopasowanieTab jobId`, bez wyboru rekrutacji). Menu
  wiersza: Tablica, Usuń z rekrutacji. Wiersz z fokusem (wejście z rekrutacji,
  `?recruitments=matching`) rozwinięty od pierwszego renderu. „Zakończone”
  otwarte, 5 ostatnich + „Pokaż wszystkie”. „Pasujące rekrutacje” zwinięte
  na dole — `SuggestedJobsWidget` montuje się i pyta serwer dopiero po
  „Pokaż”. Licznik zakładki = procesy w toku (`splitRecruitments`).
- **Screening** (`CandidateScreeningAnswersCard variant="tab"`, aliasy
  `?tab=odpowiedzi|screeningi`): jedna rozmowa na rekrutację z pytaniami
  i odpowiedziami arkusza Championa (`GET /api/candidates/{id}/screening-answers`,
  tylko rekrutacje widoczne dla patrzącego), pod nimi odpowiedzi z kart
  rekomendacji. Odpowiedzi renderuje JEDEN komponent
  `screening/ScreeningAnswersList` (profil, dok osoby, panel osoby).
- **Notatki (E4):** filtry w dwóch grupach (Rozmowy · Delivery Lead · Próby
  kontaktu · Automat, gdy są | Maile · Czat), przełącznik „Zmiany etapów
  i automaty” = oś czasu (pobrania plików z jednego dnia zwinięte do „Pobrano
  pliki · N”), „CV obok”. Lista z nagłówkami miesięcy, przypięte na górze,
  10 najnowszych + „Pokaż starsze (N)” po stronie przeglądarki (`?note=`
  starszej notatki rozwija listę). Ikony akcji notatki po najechaniu i fokusie,
  na dotyku zawsze. `NotesList` jest wspólny z notatkami rekrutacji — grupy
  miesięczne i stronicowanie to opcje (`groupByMonth`, `initialVisible`).
- **CV (E5):** `CvSkillsSection` — umiejętności (warianty nazw łączone
  WYŁĄCZNIE w widoku przez słownik `GET /api/skills`, `lib/skill-display.ts`),
  doświadczenie jako oś „daty · stanowisko · firma” (4 pierwsze + „N
  wcześniejsze”), wykształcenie.
- **Dokumenty (E5, D7):** umowy, pliki, zwinięte „Dane do umowy (JDG / firma)”.
  Pliki w grupach (`groupCandidateFiles`, `lib/candidate-files.ts`): „CV
  kandydata” · „CV wysłane klientom” (nazwa z „B2B” albo z kodem rekrutacji
  osoby — „ZOB-2962”, numer Traffita „(42700)” — z tytułów `/history`, plus CV
  z generatora) · „Załączniki i formularze”; „Dodaj plik” rozwija formularz
  (pusty profil — formularz od razu). Umowy: `GET /api/contracts` tylko
  z `delivery_view`; bez niego klient, daty i status z `contracts[]` w `/history`
  (front kopiuje jawnie pola bez kwot) i zdanie „Umowy prowadzi Delivery”
  z Delivery Leadem ze znacznika zatrudnienia. Załączniki umowy, Autenti
  i szkic za `contractAccess()` (jak karta kontraktu, 403 chowa sekcję),
  kafle stawek tylko z wglądem w finanse.
- **Imię bez dopisków (D6):** osobna reguła `imie-bez-dopiskow.md`.
- **Mail = jedno okno** (`SendEmailV2`): bez podłączonej skrzynki M365 okno
  mówi to i prowadzi do Ustawień zamiast kończyć się 412.
- **Nic nie znika:** `lib/candidate-profile-feature-inventory.json` + test
  `candidate-profile-feature-parity.test.ts` (plik + marker każdej funkcji;
  zdjęte mają `removed_reason`).
- **Stare klucze `?tab=` i podparametry żyją jako aliasy**
  (`candidate-profile-navigation.ts`): `matching` → Rekrutacje z otwartą oceną
  dopasowania, `emails`/`notes`/`calls`/`chat` → Notatki z filtrem
  (`activity=calls` → oś czasu; wartość zostaje dozwolona w adresie, bo niosą
  ją linki — `test_client_tab_links.py`), `documents=files|contracts` →
  Dokumenty. Linki zapisane w powiadomieniach prowadzą w te miejsca — nie
  usuwaj aliasów.
- Harnessy wizualne (publiczne, zero zapytań): `/preview/candidates-list`
  (`?dialog=1` otwiera okno requestu) i `/preview/candidate-profile` (`?tab=`,
  `?employed=1`, `?role=recruiter` — konto bez `delivery_view` i `amounts_view`).

**Pliki, języki i „Dodaj kandydata” od CV (0400, 29.09.2026):**
- **„Nieaktualne” to tylko plakietka** (`candidate_documents.outdated_at/
  outdated_by`, `PATCH …/documents/{id}` z `outdated`). Plik zostaje, wyszukiwanie,
  `raw_cv_text` i wektory bez zmian. Głównego CV nie da się oznaczyć (409 „Najpierw
  ustaw inne CV jako główne.”), nieaktualnego nie da się ustawić jako głównego
  (409), chyba że w tym samym żądaniu `outdated: false`. Lista plików: główne CV,
  potem najnowsze (`uploaded_at ?? created_at`), podpis „dodano DD.MM.RRRR · osoba”
  z `uploaded_by` (wiersze sprzed 0400 i importy — sama data albo „z Traffita”).
- **Języki: jedna lista** `LANGUAGE_OPTIONS` (`lib/candidate-languages.ts`, filtr
  listy i okno „Języki kandydata”) ↔ `candidate_language_writer._LANGUAGE_CODES`
  (`test_candidate_language_options_mirror.py`). `PUT /languages` odrzuca 422 kod
  spoza listy bez `other: true` — chyba że kandydat już ma taki język zapisany
  (stare dane z CV zostają zapisywalne). Pola „Kod” w oknie nie ma.
- **„Dodaj kandydata” zaczyna się od CV (opcjonalnie):** `POST /api/candidates/cv/preview`
  czyta plik BEZ zapisu; odczyt żyje w OGRANICZONEJ pamięci
  `services/cv_preview_cache.py` (64 wpisy, 30 min, tekst > 200 tys. znaków nie jest
  trzymany; nie `app/core/cache.py` — ten nie ma limitu ani sprzątania). `/from-cv`
  z tym samym plikiem bierze odczyt (jeden płatny), a przy trafieniu bez `force`
  i tak puszcza darmowe sito. Pola formularza (`name`, `lastname`, `email`,
  `phone`, `city`, `linkedin`) wygrywają z odczytem, `""` = pole wyczyszczone
  (wartość z CV nie wraca, także do skanu duplikatów). Reszta formularza jedzie
  w tym samym żądaniu (`candidate`, JSON, walidacja `CandidateCreate` PRZED
  odczytem) — jedna transakcja, bez PATCH-a. E-mail innego kandydata = 409
  „Kandydat z tym adresem e-mail już istnieje.” także przy `force` (jak
  `POST /api/candidates`); front pokazuje go przy polu (`emailFieldError`).
  `/from-cv` tylko CZYTA z pamięci — masowy import jej nie zapełni. Osobne
  „Dodaj z CV” zdjęte z listy kandydatów (`AddCandidateFromCVModal` zostaje
  w rekrutacji).
- **Od 12.10.2026 okno sprawdza tylko e-mail** i zamiast listy „podobnych”
  pokazuje jedną ramkę „Ten kandydat już jest w bazie” z „Dodaj to CV do
  profilu”; „Zapisz mimo to” nie ma. Pełna reguła:
  `ta-sama-osoba-ten-sam-e-mail.md`.
