# „Moi ludzie" — lista rekrutera, dzwonek przy nowej rekrutacji, postać w rogu (21.09.2026)

Rekruter wysyła tych samych ludzi do klientów raz za razem, aż któryś projekt
się zamknie. „Moi ludzie" to ta lista: buduje się sama, jest pod ręką z każdego
ekranu (przycisk w topbarze, skrót `m`, postać w rogu), a publikacja rekrutacji
od razu mówi, kto z listy pasuje. Migracja `0334_my_people` (+ lustro
w `entrypoint.sh`, sondy w `/api/health/deep`). Raport:
`docs/my-people-completion-report.md`.

- **Właściciel osoby = PIERWSZY weryfikator** pary (kandydat, rekrutacja), która
  potem doszła do `cv_sent` — ktokolwiek wysłał CV (decyzja Artura 21.09).
  Para bez żadnej weryfikacji (import Traffita pomija etap) → autor pierwszego
  `cv_sent`. Para bez `cv_sent` nie tworzy listy. **Bez limitu czasu** —
  porządek robi ręczne „Uśpij". Liczone WPROST z `candidate_stages`
  (`services/my_people.py`, indeks `ix_candidate_stages_moved_by_stage`),
  **nie** przez `VERIFIER_ANCHORED_CTE` — tamto płaci nagrody i nie wolno go
  ruszać przy okazji.
- **Nazwa w UI to „Moi ludzie", nie „ławka"** — `EmploymentState.on_bench`
  znaczy już „konsultant bez projektu", a „shortlista" to `JobShortlist`.
- **Grupy:** aktywni po primary CC (`candidate_competence_categories`, fallback
  `competence_category_id`, reszta „Pozostałe"); **„Pracują"** = żywa umowa
  (`current_employment`) — osoba nie znika, ale nie ma przycisku „Dodaj";
  **„Uśpieni"** (`my_people_overrides.kind='snoozed'`, powód obowiązkowy —
  CHECK). „Przypnij" (`kind='pinned'`) dokłada osobę spoza wyliczenia; jeden
  wiersz na (użytkownik, kandydat), nowsza decyzja nadpisuje. Globalna
  blacklista wyklucza zawsze.
- **Dzwonek `my_people_match`** (`services/my_people_matching.run_for_job`)
  jedzie na kolejce auto-matcha: `tasks/candidate_auto_match._run_my_people`
  po `run_job_event`, w savepoincie — zwykły błąd nie cofa auto-matcha,
  `AutoMatchUnavailable` (Qdrant) PRZECHODZI dalej, żeby zdarzenie się
  powtórzyło. Działa niezależnie od `AUTO_MATCH_DRY_RUN` (niczego nie dodaje),
  ale przy `AUTO_MATCH_ENABLED=false` stoi (nie ma zdarzeń). Wyłącznik
  `MY_PEOPLE_MATCH_ENABLED`; próg `MY_PEOPLE_MATCH_MIN_SCORE` (70), sufit
  `MY_PEOPLE_MATCH_MAX_PER_USER` (10), pula `MY_PEOPLE_MATCH_POOL` (200).
  Jeden dzwonek na (odbiorca, rekrutacja), link `/jobs/{id}?people=1`, i tylko
  przy NOWYCH wierszach `my_people_job_matches` (UNIQUE na trójce) — istotna
  zmiana rekrutacji nie budzi drugi raz tymi samymi nazwiskami.
- **Liczba to kanoniczny fit** (`canonical_fit.score_candidates`), ta sama co
  na ekranach C2 — NIE `rank_candidates_for_job`. Niezmierzony = `None`, nigdy
  0 i nigdy w dzwonku. `hidden` (blacklista, duplikat) odpada, ostrzeżenia
  (konflikt klienta, weto HM) jadą jako plakietka; weto HM blokuje „Dodaj".
  Dzwonek liczy profilem wag klienta (`user_id=None`), zakładka panelu
  profilem patrzącego — przy profilach per użytkownik liczby mogą się różnić.
- **Zakładka „Do tej rekrutacji"** (`GET /api/my-people/for-job/{id}`, bramka
  `_authorized_job` jak `/scores`, limit 20/min) liczy na żądanie do
  `MY_PEOPLE_PANEL_POOL` (60) najbliższych wektorowo; awaria Qdranta =
  `degraded: true` i komunikat „nie znaczy, że nikt nie pasuje", nigdy pusta
  lista. Obejrzenie zakładki zeruje dopasowania tej rekrutacji w liczniku
  (`POST /matches/seen` — GET zostaje tylko do odczytu).
- **Front:** panel to NIEMODALNY `<aside>` z-40 (`components/v2/my-people/`),
  kontekst z `usePathname()`; widoki prezentacyjne w `MyPeopleViews.tsx`
  (harness `/preview/my-people`, zero zapytań). Capability `nav.my_people` =
  lustro `nav.candidates` (`CandidateSearchAccess`). Dodanie idzie przez
  `proposals/bulk` ze źródłem **`my_people`** (lustra: `BulkAddSource`
  w `proposals_bulk.py` i `candidate-search-api.ts`, `PIPELINE_ADD_SOURCES`
  w telemetrii). WS `pipeline_changed` unieważnia listę i zakładkę rekrutacji,
  ale NIE podsumowanie (liczy całą listę); WS `notification` typu
  `my_people_match` unieważnia wszystko.
- **Postać w rogu** mówi wyłącznie zdaniami z szablonów
  (`lib/my-people-summary.summarySentences`, zero AI), raz na sesję dla tej
  samej treści (`sessionStorage`), pulsuje tylko licznik. **Ustępuje maskotce
  Jarvisa** (ten sam róg; `useJarvisOwnsCorner` = lustro `showMascot`
  z `JarvisRoot`, te same klucze zapytań — także w trybie Kids), chowa się na
  `/jobs/{id}` (róg zajmuje dok kanbanu),
  przy otwartym panelu i po „Ukryj postać" (`useUiStore.hideMyPeopleBuddy`,
  przywracane checkboxem w stopce panelu). Główne, dostępne wejście to
  przycisk w topbarze.
- **Jarvis przypomina o przepinaniu** (21.09.2026): narzędzia odczytu
  `my_people` i `my_people_for_job` (tylko osoby do przepięcia; brak wyniku =
  `"niepoliczony"`, weto HM = `nie_mozna_dodac`), sekcja „PRZEPINANIE" w
  prompcie, poranny skrót dnia dostaje `briefFragments` (nowe dopasowania,
  czekający > 30 dni), a dzwonek `my_people_match` → zdarzenie okna
  `nexus:my-people-match` (z `useNotifications`) → dymek Jarvisa, którego
  kliknięcie wysyła `reassignPrompt(jobId)` i kończy się kartą
  `add_candidates_to_job` do potwierdzenia. Świadomie tylko DWA momenty
  (poranek + nowa rekrutacja) — częstsze przypomnienia uczą ignorowania.
  Działa dopiero przy `JARVIS_ENABLED=true`.
- **Poza zakresem świadomie:** widok HoR „czyja lista leży", zmiana atrybucji
  wyścigów.
