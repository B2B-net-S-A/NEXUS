# Audyt narzędzi rekrutera — 2026-09-17

Cel: rekruter ma robić codzienną pracę szybciej i bez irytacji (wygląd, czytelność, ergonomia, drobne poprawki funkcji).
Zakres: lista i profil kandydata · rekrutacje i pipeline (kanban, doki) · wyszukiwarka i Talent Radar · generator CV · kalendarz i feedback po rozmowach · dashboard rekrutera i powiadomienia.

Stan kodu: `07101a0e2` (main z 16.09). Audyt tylko z kodu (FE ↔ BE, ścieżka wywołania → handler → schemat), bez zmian w repo i bez odpalania na prodzie. Każde znalezisko poniżej zostało potwierdzone drugim odczytem kodu po obu stronach; zachowania opisane w `CLAUDE.md` jako zamierzone pominięto.

Skala: **P1** = błędne dane / zablokowany przepływ / crash · **P2** = zepsute lub irytujące UX · **P3** = kosmetyka i drobiazgi.
Baseline: `tsc --noEmit` zielony, `api-error-detail-guard` zielony.

Łącznie: **6 × P1, 31 × P2, ~38 × P3**. Wspólne wzorce: (1) bramki ról na froncie liczone inaczej niż na backendzie — przycisk widoczny, klik = 403; (2) deep-linki z powiadomień do zakładek, których strona nie zna; (3) surowe enumy/ID zamiast etykiet i nazwisk; (4) reguły z jednego widoku nieskopiowane do drugiego (tablica vs warsztat, tabela vs kafelki, lista vs mini-lejek).

---

## 1. Rekrutacje i pipeline (kanban, doki)

### P1
- **Karta „Pending”: tablica pokazuje DL/HoR „Akceptuj/Odrzuć”, backend przyjmuje tylko admina; powiadomienie idzie tylko do adminów, a toast odsyła rekrutera do DL.** FE: `frontend/src/components/v2/pages/KanbanBoardV2.tsx:137` (`APPROVER_ROLES = admin, delivery_lead, head_of_recruitment`), `:844-873`, toast `:1891` („Wysłano do akceptacji delivery_lead”); kopie: `frontend/src/components/v2/jobs/ScreeningWorkbench.tsx:159-164, 528`, `frontend/src/app/pending-verifications/page.tsx:24`. BE: `backend/app/api/pipeline.py:2021, 2108` (`AdminUser`), `:264-284` (odbiorcy = tylko admin). Test BE `test_pending_verification.py::test_accept_verification_forbidden_for_delivery_lead` pinuje 403, test FE `KanbanBoardV2.test.tsx:239` pinuje pokazywanie akcji DL — oba naraz nie mogą być prawdą. *Repro:* DL → karta Pending → „Akceptuj” → 403.
- **Mini-lejek na liście rekrutacji i dok „Gotowość” gubią kandydatów z etapu „Ogłoszenia”.** `frontend/src/lib/job-pipeline-funnel.ts:166-175` mapuje `intake/screening/verification/client/contract`, a `groupKeyForColumn` zwraca też `posting` (`frontend/src/lib/pipeline-flow.ts:454`). Konsumenci: `JobsListV2.tsx:431-467`, `JobReadinessDock.tsx:317-423`. *Repro:* 4 osoby na „Ogłoszenia” + 1 na „Nowi” → lista „1·0·0 / 1”, tablica 5 kart.

### P2
- **„CV Wysłane” z tablicy pyta każdą rolę o stawkę do klienta, którą zapisać może tylko admin.** `KanbanBoardV2.tsx:1778-1783`, `:2339-2353` (toast „uzupełnij ją z profilu kandydata” — tam ta sama bramka odmówi). BE: `backend/app/api/candidates.py:3716`, `backend/app/api/candidate_access.py:95` (`CANDIDATE_FINANCE_ROLES = (admin,)`). `CvHandoffWorkbench.tsx:208-213` zna problem i chowa pole — tablica nie.
- **DL/TCM przy ruchu na „Zweryfikowany” widzi „brak budżetu — ruch bez akceptacji”, a serwer i tak stawia Pending.** `backend/app/api/jobs.py:209-218` zeruje `salary_max` dla DL/TCM; `frontend/src/lib/verified-rate-gate.ts:116-125` czyta `null` jako „no_budget”; `backend/app/api/pipeline.py:713-728` porównuje z prawdziwym budżetem. Trzy sprzeczne komunikaty w jednym kliknięciu.
- **Ruch na „Zweryfikowany” połyka powód odmowy serwera.** `KanbanBoardV2.tsx:1895-1907` — stałe „Nie udało się przesunąć kandydata.”; BE zwraca po polsku 403 (sourcer) i 409 (blacklista/NDA/konkurent) `pipeline.py:565-595`. `sendMove` (`:1712`) używa `assignErrorMessage` — tu nie.
- **Ruchy zbiorcze omijają bramkę `moveBlockedReason`; zablokowana karta wraca po cichu.** `KanbanBoardV2.tsx:2380-2474` (`bulkMove` bez bramki; jedyne wywołania `:1746, 2113, 2127`), `:2354-2356` (`!ok && isBulk` → tylko refresh, zero toastu).
- **Head of Recruitment ma edytowalną tablicę i doki, a każdy `/move` kończy się 403.** `backend/app/services/section_permissions.py:65-69` (HoR `pipeline=write`) → `frontend/src/app/jobs/[id]/page.tsx:1998` (`canWritePipeline`); `backend/app/api/deps.py:434-446` (`RecruiterPlus` bez HoR), `pipeline.py:403`.
- **Wyszukiwarka listy rekrutacji obiecuje „Tytuł, klient, technologia…”, backend filtruje tylko po tytule** (bez escapowania `%`/`_`). `JobsListV2.tsx:1236` vs `backend/app/api/jobs.py:728`.
- **Deep-linki z powiadomień lądują po cichu na Pipeline; zakładka nie żyje w URL.** `page.tsx:2030-2047` zna `chat|similar|champion|screening|cv|interviews|contract`; BE wysyła `?tab=champion-profile` (`jobs.py:2143`) i `?tab=notes&note=` (`backend/app/services/mention_dispatch.py:80`). `activeTab` = `useState` (`page.tsx:2014`) — F5 i „Wstecz” wracają na Pipeline; lista zapisuje 5 z 14 filtrów (`JobsListV2.tsx:717-732`).

### P3
- Karty na „Ogłoszenia” bez wiersza „co dalej” (`frontend/src/lib/pipeline-next-action.ts:75` deklaruje, `switch` nie ma `case "posting"`).
- Zaznaczenie zbiorcze trzyma martwe id po ruchu — „Zaznaczono N” kłamie (`KanbanBoardV2.tsx:1225`, id podmieniane `:1620-1643`, licznik `:2612`).
- „Wszystkie aktywne” w lewej szynie liczy zatrudnionych, „W procesie” w nawigatorze nie (`PipelineFiltersRail.tsx:183-185` vs `KanbanBoardV2.tsx:254-257`).
- Tabela listy rekrutacji nie honoruje `can_open` (kafelki tak): `JobsListV2.tsx:476-489` vs `:1411`.
- `POST/GET /api/pipeline/stages/{id}/screening` bez sprawdzenia członkostwa (`pipeline.py:1561-1651`).
- Natywne `confirm()`/`alert()` w regułach powiadomień etapu (`frontend/src/components/StageNotificationRulesModal.tsx:64,70`).
- Badge czatu rekrutacji odpytuje co 30 s + na focus (`page.tsx:2054`), choć WS niesie `chat:message:new` — handler nie unieważnia `["job-chat-unread"]` poza zamontowanym `JobChatTab`.

## 2. Lista i profil kandydata

### P1
- **Porównanie kandydatów wywraca się dla osób z tagiem-obiektem z Traffita (React #31).** `frontend/src/app/candidates/compare/page.tsx:73` rzutuje `tags` na `string[]`, `:109-111` renderuje `{t}`; kolumna niesie obiekty `{type:"traffit_source",…}` (`frontend/src/lib/candidate-tags.ts`). Profil robi to poprawnie przez `getTagName`. Test porównania nie rozwiązuje profili. *Repro:* zaznacz 2 kandydatów z importu → „Porównaj” → „Coś poszło nie tak”.

### P2
- **HoR widzi na profilu akcje zapisu, które backend odrzuca 403** (Edytuj kontakt, Przypisz do rekrutacji, Edytuj, notatki, Usuń z rekrutacji). FE bramkuje sekcją (`CandidateDetailV2.tsx:571-575`, `frontend/src/lib/section-access.ts:147-154` — HoR `sourcing: write`), BE rolą bez HoR (`candidate_access.py:73-83`, `candidates.py:4469`, `notes.py:147`, `recommendations.py:1246`). Szybki podgląd robi to dobrze (`capabilities.can_assign` z BE).
- **Eksport CSV/XLSX ukryty przed HoR i TCM, choć backend im go daje.** `CandidatesListV2.tsx:2270, 3487` (`RequireRole admin/DL/tac/finance`) vs `candidate_access.py:85-92` (`CANDIDATE_EXPORT_ROLES` + HoR + TCM).
- **Filtr etapu „Ogłoszenia” znika po F5, chip pokazuje surowe `posting`.** Inicjalizator stanu `CandidatesListV2.tsx:1434-1453` ma listę etapów bez `posting` (panel go oferuje: `filter-options.ts:70`); `ActiveFilterChips.tsx` bez etykiety.
- **Panele „Zaangażowanie” i „Lokalizacja” kasują wpisywany tekst przy każdym przerysowaniu profilu** (`initial` = literał obiektu z rodzica `CandidateDetailV2.tsx:2854-2879`; `useEffect(..., [initial])` w `CandidateEngagementPanel.tsx:101-111`, `CandidateLocationPanel.tsx:46-53`); brak `onError` — nieudany zapis jest niemy.
- **Przy każdym powrocie do karty historia rekrutacji znika, zakładka pokazuje „Kandydat nie ma aktywnych rekrutacji”.** `candidate-history-query.ts:43-53` (`refetchOnWindowFocus: "always"`, `visibleData = isFetching ? undefined : data`), konsument sprawdza tylko `isPending` (`CandidateDetailV2.tsx:1406-1416`, pusty stan `:3508`); karty podsumowania renderują „Ładowanie…” przy każdym `isFetching`.

### P3
- Strona spoza zakresu = „0 wyników”, pusty stan, brak paginacji do powrotu (`candidates.py:1786-1798` — `count() OVER()` z pustej strony; FE `page` z URL).
- Kafelki pokazują surowy slug etapu („cv_sent”) — `CandidatesTiles.tsx:277`.
- Zapis stawki profilu nie unieważnia listy (`CandidateProfileFactsBar.tsx:716-724`; helper `candidate-cache.ts` kind `"rate"` nieużyty) — kolumna „Stawka” stara przez 30 s.
- Przycisk „CV” na liście: surowy `fetch` + cichy `catch` (`CandidatesListV2.tsx:657-679`) — bez ponowień interceptora, bez komunikatu.
- Przypięty kandydat spoza strony → „0 z N”, „Następny” skacze na pozycję 1 (`CandidatesListV2.tsx:3149-3159`).
- Zakładka Notatki: surowy `note_type` (`CandidateDetailV2.tsx:4362`; oś czasu tłumaczy).
- „Stawka do klienta”: sortowanie po `job_status === "open"` nigdy nie działa (`JobStatus` = draft/published/closed) + surowy `latest_stage` (`CandidateDetailV2.tsx:2379-2408`).
- Z modala „Edytuj” nie da się wyczyścić „Dostępny od” ani okresu wypowiedzenia (`frontend/src/components/AppShell.tsx:518-520` — puste → `undefined`, nie `null`).

## 3. Wyszukiwarka i Talent Radar

### P1
- **Tryb semantyczny (domyślny, gdy jest fraza) ignoruje sortowanie ORAZ chipy skilli „podbijające ranking”.** `backend/app/api/search.py:455` (`use_hybrid = hybrid && q`), `:538-568` — strona wycinana z surowej kolejności RRF; `sort` i soft-ranki tylko w gałęzi `else` (`:569-592`). FE pokazuje przyciski sortowania (`CandidateSearchView.tsx:865-887`) i copy „podbijają ranking” (`FiltersPanel.tsx:291-295`). *Repro:* wpisz „java”, dodaj chip Kubernetes, kliknij „Alfabetycznie” — kolejność bez zmian.

### P2
- **Brak limitów FE lustrzanych do backendu → 422 „Request failed with status code 422” nad starymi wynikami.** `q` bez `maxLength` (BE 500: `schemas/candidate_search.py:64`), listy bez sufitu (20/10), lata (`le=60`); obsługa błędu `err.message` zamiast `apiErrorMessage`, `data` nie czyszczone (`CandidateSearchView.tsx:462-477`). *Repro:* wklej 600 znaków JD.
- **„Porównaj” porównuje tylko zaznaczonych z bieżącej strony i po cichu ucina do 5** (`CandidateSearchView.tsx:547-554`), choć zaznaczenie przeżywa zmianę strony.
- **Po dodaniu do rekrutacji z ostatniej strony ekran zostaje na nieistniejącej stronie: „Brak wyników. Zmień filtry”** (`:415` zachowuje `page`; paginacja ukryta).
- **Talent Radar: zmiana budżetu/dni/miasta/treści nie unieważnia wyświetlonych wyników** (`TalentRadarWorkspace.tsx:374-483` — tylko zmiana klienta `:399-412` czyści); wyniki nie pokazują kryteriów biegu.

### P3
- „Wyczyść” gubi `search_mode` (`FiltersPanel.tsx:165-172`) — kolejne zapytanie idzie FTS, po F5 wraca hybryda; drafty chipów niewyczyszczone.
- Profil otwarty z wyszukiwarki w rekrutacji — „Wróć do kandydatów” prowadzi na globalną listę (`CandidateSearchView.tsx:1297`, brak `encodeJobBackRef`).
- Brak `AbortController`, każda pauza w pisaniu = pełny retrieval + wodospad diagnostyczny przy 0 wyników (`:448-510`; BE `search.py:364-381`).
- Chipy: tekst bez Enter ginie, 1-znakowa umiejętność („C”) odrzucana po cichu (`FiltersPanel.tsx:98-107, 131-146`).
- Radar: toast przy każdym pollu w czasie blipu + zniknięcie paska postępu (`TalentRadarWorkspace.tsx:78`, `FullCandidateSearchResults.tsx:28-35`).
- Radar: liczby poza limitami BE → 422 po angielsku (`:417, 445` vs `talent_radar.py:68, 74`).
- `start()` kasuje zapisany bieg przed `202` — 409 „dwa wyszukiwania trwają” zabiera wyniki z ekranu (`useFullCandidateSearch.ts:92-115`).
- ⌘K / unified search: `%` i `_` nieescapowane w `ILIKE` (`search.py:655-845`).
- `/candidates/compare`: nieudany odczyt jednego kandydata po cichu usuwa jego kartę (`compare/page.tsx:218-269`).
- Wiersz wyniku pokazuje surowy enum dostępności („open to offers”) — `CandidateSearchView.tsx:1341`.
- Wygląd: `CandidateSearchView.tsx` ma ~150 hardcoded klas kolorów z ręcznymi `dark:` zamiast tokenów DS (reszta audytowanych widoków 0–25).

## 4. Generator CV

### P2
- **Wyczerpana kwota AI / AI wyłączone / 422 pokazują się jako „Nie udało się uruchomić generacji.”** `frontend/src/lib/cv-generator.ts:201-222` (`extractErrorDetail` zwraca `detail` tylko, gdy string); BE 503 z `detail = {feature, reason, …}` (`backend/app/api/cv_generator_b2b.py:486-503`, `reason` po polsku). Użycia: `CVGeneratorStandaloneV2.tsx:535, 599`, `modals/CVGeneratorV2.tsx:177`.
- **Upload z klientem z rekrutacji (każdy upload w kroku 06): „Generuj” wyłączony bez komunikatu.** `CVGeneratorStandaloneV2.tsx:485-487` pokazuje Alert tylko przy `uploadClient`, a klient idzie z `uploadRecruitment` (`:415-416`); `canSubmit` (`:495-497`) i tak blokuje.
- **Edytora CV nie da się zamknąć po trwałym błędzie zapisu (409 rewizja, 422 puste CV).** `modals/CVBrandedEditModal.tsx:183-193` — zamknięcie = udany `save()`; brak „Wczytaj aktualną wersję”.
- **Modal „Generator CV” z profilu ignoruje reguły klienta poza zrzutem zgody** (brak `project_ref`, blokady trybu, wymuszonego języka) — `modals/CVGeneratorV2.tsx:135-165`; przy `require_project_ref` 422 o polu, którego w modalu nie ma.
- **Rekruter/sourcer bez przypisania do Joba klienta dostaje 403 na regułę CV, a serwer i tak ją stosuje** — `backend/app/api/client_cv_rules.py:897-916` (`_require_client_rule_access`), `client_access.py:145-169, 308`; FE traci wiedzę o języku/zrzucie/numerze projektu → 422 o niewidocznych polach.

### P3
- Baner reguł mówi „uzupełnij dokument po pobraniu”, pole niżej: „trafi automatycznie na koniec CV” (`ClientCvRuleBanner.tsx:135-140`).
- Zablokowany tryb / wymuszony język da się zmienić klawiaturą (`pointer-events-none` bez `disabled`, `CVGeneratorStandaloneV2.tsx:993, 1006`).
- Kopiowanie linku dla klienta: `clipboard.writeText` bez `try/catch` (`modals/CvGeneratedShareModal.tsx:137-142`) — wbrew regule `lib/clipboard.ts`.
- Błędy pobierania szkicu/DOCX pokazują surowy JSON albo „HTTP 409” (`frontend/src/lib/authenticated-files.ts:33, 60`).
- Po deployu wiersz „Generuję…” kręci się do 3 min, potem „Przerwano” bez „ponów” (`job_leases.py:13`, `durable_jobs.py:243-283`).
- Udana (opłacona) generacja PKO BP przepada, gdy magazyn nie odda zrzutu zgody przy zapisie — `_finalize_success` rzuca poza `try/except` workera (wbrew opisowi fail-soft w CLAUDE.md).

## 5. Kalendarz i feedback po rozmowach

### P1
- **Żadne wydarzenie tworzone z UI nie niesie rekrutacji (`job_id`).** `frontend/src/lib/api.ts:4792-4806` (`createInvite` bez `job_id`), `ScheduleInterviewModal.tsx` (brak pickera), `frontend/src/app/calendar/page.tsx:956, 1014` (stan `job_id: ""`, zero pola w JSX); BE przyjmuje (`calendar.py:917`). Skutki: feedback zapisany z `job_id: null` (`InterviewFeedbackModal.tsx:206`), eskalacja T+2h do DL nigdy nie wychodzi (`notification_triggers.py:663-728` — `latest.get((cid, None))`), zakładka rozmów rekrutacji nie ma jak powiązać wydarzeń.
- **Feedbacku nie da się dodać na żądanie ani poprawić.** Modal montowany tylko z linku powiadomienia (`calendar/page.tsx:521`, `NotificationsDropdown.tsx:442`); okno szczegółów wydarzenia nie ma „Feedback”; przy istniejącym wpisie modal pisze „Po submit dostaniesz błąd 409 — użyj PATCH” (`InterviewFeedbackModal.tsx:302-308`), a `PATCH` istnieje w BE i nie jest wołany nigdzie.
- **Zapisany feedback nie jest nigdzie wyświetlany; karta rekrutacji nadal mówi „do uzupełnienia”.** Jedyny konsument `interviewFeedbackApi` to sam modal; `backend/app/api/hiring_manager_feedback.py:515-519` czyta tylko `calendar_event_id IS NULL`, więc werdykt klienta z modala jest niewidoczny i DL wpisuje go drugi raz.
- **„Usuń” na wydarzeniu z Outlooka nie odwołuje spotkania i wpis wraca przy następnej synchronizacji; błędy „Usuń/Zakończ” nieme.** `calendar.py:626-658` kasuje tylko wiersz (brak `DELETE`/`cancel` w `services/m365/*`); `sync.py:920-990` tworzy wiersz na nowo; `calendar/page.tsx:1295-1306` mutacje bez `onError` (uczestnik cudzego spotkania → 403 bez słowa).

### P2
- **Wybór „Przypomnienie: 5/10/30/60 min” jest martwy** — `reminder_minutes` zapisywane, nikt nie czyta; pętla ma sztywne 16 min (`calendar.py:1146-1160`, test `test_calendar_reminder_window.py:50` pinuje `minutes=16`); link `/calendar` bez `?event=` (`:1083, 1095`), tylko do właściciela.
- **Całodniowe wpisy z Outlooka (urlop, OOO) stają się 24-godzinnymi blokami**: `services/m365/sync.py:69-71` (`EVENT_SELECT` bez `isAllDay`), `:983` (`all_day=False`); siatka rysuje blok na cały dzień, zwęża rozmowy, generuje fałszywe konflikty i przypomnienie o 01:45; to samo w iCal (`ical_import.py:174, 294`). Skutek zależy od włączonego syncu (`M365_SYNC_LOOP_ENABLED` domyślnie off, ale jest ręczny trigger).
- **Wydarzenia nie da się edytować** (jedyne `updateEvent` to `status: completed`, `page.tsx:1301`); każde spotkanie z Outlooka ma `event_type=meeting` (`sync.py:980`), więc interview umówione w Outlooku nie wchodzi w przepływ feedbacku i nie da się tego naprawić z UI.
- **Link Teams z Outlooka nie jest pokazywany** — sync zapisuje `online_meeting_url` (`services/m365/calendar.py:171`), okno szczegółów renderuje tylko `teams_link` (`page.tsx:1412-1425`).
- **Formularz „Zaplanuj spotkanie” nie resetuje się między otwarciami**: `defaultStart = useMemo(nextHourIso, [])` (`ScheduleInterviewModal.tsx:96`) przy stale zamontowanym modalu (`CandidateDetailV2.tsx:1688`) proponuje godzinę z przeszłości; „Dodatkowi uczestnicy” zostają z poprzedniej rozmowy; brak walidacji pustej/przeszłej daty.

### P3
- Modal feedbacku podpisuje kandydata „#196867” (czyta `first_name/last_name`, API daje `name/lastname`) — `InterviewFeedbackModal.tsx:40-46, 99-103`; treści powiadomień też „kandydatem #123”.
- Anulowane spotkania z Outlooka zabierają pas w kolumnie dnia (`page.tsx:575-598` bez filtra `cancelled`).
- Brak walidacji „koniec przed początkiem” w formularzu i w `POST /calendar/events` (`page.tsx:994-1019`, `calendar.py:132-146, 321-367`).
- Uczestnicy w „Nowe wydarzenie” dzieleni tylko po przecinku (`page.tsx:1001-1004`; modal używa `/[,;]/`).
- `needs_attention` i `candidate_confirmed_at` zapisywane, nigdy nie pokazywane (`CalendarEventResponse` ich nie niesie).
- „Najbliższe” i mini-kalendarz opisują tylko załadowany tydzień; wynik importu iCal w języku programisty (`page.tsx:794-799, 881-933, 1588-1590`).
- Do sprawdzenia jednym zaproszeniem testowym: `services/m365/calendar.py:95-96` wysyła do Graph `dateTime` z offsetem `+00:00` razem z `timeZone: "Europe/Warsaw"` — jeśli Graph ignoruje offset, zaproszenie w Outlooku ląduje 2 h za wcześnie.

## 6. Dashboard rekrutera i powiadomienia

### P2
- **`stage_stuck_7d`: codzienna lawina powiadomień bez pułapu wieku i bez filtra otwartych rekrutacji, z surowymi ID.** `backend/app/services/notification_triggers.py:527-573` (bez `floor`, bez `Job.is_open`, dedup dobowy per etap → nowy wiersz każdego dnia roboczego per zaległy kandydat; treść „Kandydat #12345 … 'cv_sent' … w ofercie”); sąsiedni `check_dl_stage_stale_6h` (`:250-262`) ma `floor` po incydencie 2026-05-22. Pętla co 300 s bez wyłącznika (`main.py:757`). To zapewne źródło „ponad tysiąca nieprzeczytanych”.
- **Powiadomienia z czatu nie trafiają do dzwonka na żywo** — WS wysyła `chat:*`, `useNotifications.ts:174-180` unieważnia `["notifications"]` tylko dla `notification`/`kpi_nudge`; wzmianka `@Ty` widoczna dopiero po 5-minutowym pollu.
- **„Moje zadania → Powiadomienia” nie oznacza kliknięcia jako przeczytane** (`MyTasksDashboard.tsx:157-204` — zwykły `<Link>`, brak `markRead`).
- **Wzmianka w notatce prowadzi do złej zakładki** (`?tab=notes&note=`; `candidate-profile-navigation.ts` nie zna `notes`, strona rekrutacji też nie).
- **„Profil Championa zaktualizowany” → `?tab=champion-profile`** nieobsługiwane (patrz pipeline).
- **„Email odrzucenia niewysłany” linkuje do `/settings/integrations` — 404** (`rejection_email_scheduler.py:356`; właściwe `/settings?tab=integracje`).
- **`create_notification(dedupe_resurface=True)` porównuje dobę UTC, indeks unikalny liczy dobę Warsaw** (`notifications.py:311-335` vs `entrypoint.sh:170-174`) → `IntegrityError` bez savepointu, m.in. przy zapisie profilu Championa (`jobs.py:2145`) po 00:00 Warsaw/przed 00:00 UTC. Pewność średnia (zależy od strefy sesji PG; kontener nie ustawia `PGTZ`).

### P3
- Przypomnienie kalendarza linkuje do gołego `/calendar` (`calendar.py:1083, 1095`), tylko do twórcy.
- `&msg=` w linkach czatu nieobsługiwane (`job_chat.py:262`, `candidate_chat.py:281`).
- Badge dzwonka `Math.max(server, wsDelta)` zostawia widmowy licznik po przeczytaniu w innej karcie (`NotificationsDropdown.tsx:252-254`).
- „Aktywność rekrutacyjna” zamraża dzień z chwili montowania (`RecruitmentActivityDashboard.tsx:414-416`).
- 32 z 53 typów powiadomień z ikoną „nowy kandydat” (`NotificationsDropdown.tsx:60-172, 353`).
- „Pokaż więcej” znika w trakcie ładowania (`keepPreviousData`: 20 < 50, `:404-415`); pozycje `<li onClick>` bez klawiatury; tooltip KPI tylko hover; jeden slot toasta z timerem z pierwszego zdarzenia.
- PowerCalling: raport HoR linkuje do `/reports` (brak trasy, `notification_triggers.py:462`); alert 11:45 „N/15 rozmów” dla rekruterów przy wyłączonym CloudTalku.
- Zastępstwo: przypomnienia nieobecnego kolegi bez oznaczenia, „Oznacz wszystko” zamyka je też jemu (`notifications.py:100-112, 230-271`).
- Martwy kod na dashboardzie: `RecruitmentStatsSection`, `RecruitmentCompetitions`, `RecruitmentTeamTable`, `RecruitmentTrendChart`, `RecruitmentLinkedInPanel`, `CallStatsWidget` nigdzie nie montowane.

---

## Sprawdzone i poprawne (wybór)
- `moveBlockedReason` jest jedyną bramką ruchów pojedynczych (drag, doki, warsztaty); weto HM = lustro `VETO_ENFORCED_STAGES`; `primaryForwardMove` zatrzymuje się na wecie; `expected_state_version` tylko przy pojedynczych, oba klucze kanbanu unieważniane; kubełek „Poza szablonem” nie gubi kart; `get_kanban` i `list_candidates` bez N+1.
- Przekazanie CV (`cv-handoff.ts`): kolejność ruch → link → stawka, `isDefiniteRefusal` = 4xx; porównanie stawki w doku po normalizacji miesięcznej; `effective_budget_hourly` spójne (B62/B72).
- Kontrakt FE↔BE listy kandydatów (parametry, enumy, `indexes: null`), `?s=` wyszukiwarki, `/candidate-search/runs`, `/talent-radar/*`; paginacja hybrydowa zgodna z `total`; logika `q_all/q_any/q_none`; ocena dopasowania w wierszach (cache per `profile_key`, 403 → kłódka, 429 → jedna runda).
- Generator CV: cykl zadań (202 + polling do stanu terminalnego, `Idempotency-Key`), limity plików FE = BE, token zgody podpisany, autoryzacja `list_generated_cvs` = `_load_generated_document`, maskowanie blind, escapowanie HTML.
- Kalendarz: `attendeeLabel` wszędzie, `calendar-overlap.ts` bez off-by-one, tydzień od poniedziałku, `?event=&action=feedback` przypięte testami, `_bind_feedback_to_event`, `can_record/can_edit` werdyktu HM, skala 1–5 FE = BE = CHECK.
- Powiadomienia: `unread_count` i lista z tym samym `exclude_section`, „Pokaż więcej” przez `limit`, WS reconnect z odświeżeniem powiadomień i KPI, interwały z `lib/polling.ts`, widżety montowane po sekcji.
- Nazewnictwo „Rekrutacja”: na audytowanych powierzchniach „Oferta” występuje tylko tam, gdzie znaczy ofertę dla kandydata (etap/reakcja/status) — z wyjątkiem treści powiadomienia `stage_stuck_7d`.
- 422 z tablicą `detail`: wszędzie przez `apiErrorMessage`/`extractErrorMsg` (guard testowy zielony) — poza `CandidateSearchView` (`err.message`) i `cv-generator.ts` (`extractErrorDetail` tylko string).
