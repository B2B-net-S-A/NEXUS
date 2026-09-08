# Program „Flow rekrutacyjny w języku C2" — wdrożenie makiet krok po kroku

> Makiety: artefakt „Rekrutacja od zlecenia do umowy" (claude.ai/code, 53c9c6e4…).
> Inwentarz 200 funkcji z kodu (agent, 7.09.2026) — sekcja „Nic nie znika" artefaktu.
> Zasada nadrzędna: **C2 (warsztat AI Matching, `AIMatchingSection` + `JobMatchDock`)
> zostaje bez zmian.** Kroki wchodzą **FALAMI**, nie per krok: fundament (#1388) osobno,
> fala 1 = kroki 01 · 03 · 04 (jeden PR), fala 2 = 02 · 05–08 (jeden PR) — każdy merge na
> `main` to pełny rebuild Coolify, więc trzy PR-y naraz = trzy rebuildy bez powodu. Prod działa
> po każdej fali, żadna funkcja z inwentarza nie znika (tabela w artefakcie mapuje każdą
> jako zostaje / przeniesione / nowe).

## Kolejność PR-ów i status

| # | PR | Zakres | Status |
|---|---|---|---|
| 1 | listwa kroków | `JobDetailCompactHeader`: kroki w kolejności procesu (Zlecenie i Champion · Pozyskiwanie ▾ · Pipeline [N] · Baza pytań ‖ Historia · Chat [N] · Zespół i priorytet). Zdjęte „Narzędzia ▾" i „Pozyskaj ▾" z rzędu 1. Zero zmian w treści zakładek. | **zmergowany #1388 (`aec2f246`), na prodzie** |
| 2 | 03 Pozyskiwanie — rama źródeł | 4 karty nad C2 (AI Matching · Wyszukaj manualnie · Podobne projekty · Portale) z licznikami; „Podobne projekty" i „Rekomendowani" jako karty, nie bloki nad rankingiem; Historia requestu pod ramą + „N kandydatów → źródło" | **na prodzie** — fala 1 #1396 (zebrane z #1391) |
| 3 | 04 Pipeline — dok „Karta w procesie" | dok obok kanbana (etapy, „Przenieś na etap" z bramką wyszarzoną z powodem, notatki, CV, warunki), karta z wiekiem/następną akcją/flagą, filtry lewej kolumny, „Ukryj puste" | **na prodzie** — fala 1 #1396 (+ #1399 kafelki) |
| 4 | 01 Lista | lewa kolumna filtrów (typ, szybkie z licznikami: Moje/Niezamknięte/Potrzebny search/Aktywni/Brak ownera/Deadline ≤ 7 d), mini-lejek w wierszu, dok „Gotowość zlecenia" | **na prodzie** — fala 1 #1396 (+ #1399 kafelki) |
| 5 | 02 Zlecenie i Champion | Champion na pełną szerokość ze stanem sekcji, dok „Gotowość" (readiness + weryfikacja + briefing + zespół + HM), handoff jako główna akcja | **na prodzie** — fala 2 #1403 (zebrane z #1401) |
| 6 | 05 Screening + 06 CV do klienta | stanowisko screeningu (kolejka → arkusz → dok „Weryfikacja"); CV do klienta (reguły klienta przed generacją, jedna akcja „Wyślij") | **na prodzie** — fala 2 #1403 (zebrane z #1400) |
| 7 | 07 Rozmowy i decyzja + 08 Umowa | karta rozmowy z feedbackiem HM (małe rozszerzenie `hiring_manager_verdicts`), karta zamknięcia + „Zamknij rekrutację z powodem" (`POST /jobs/{id}/close`) | **na prodzie** — fala 2 #1403 (zebrane z #1402) |
| 8 | fala 3 — parytet z makietami | po obejrzeniu produ (8.09): układ zgodny z makietami, GĘSTOŚĆ nie — patrz sekcja „Fala 3" niżej; jeden PR zbierający czterech wykonawców | **fala 3 — w tym PR** |

## Fala 3 — parytet z makietami (8.09.2026)

Porównanie krok po kroku, prod vs makieta, na rekrutacji z makiet (`/jobs/552495`,
„Programista Python (ZOB-2947)", 26 w procesie · 6 w screeningu · 3 zweryfikowanych).
Układ trzech kolumn i listwa kroków zgadzają się; różni się to, **co niesie każdy element**.
Zasada fali: żadna z różnic nie dokłada nowej domeny — to te same dane w gęstości makiety.

| Krok | Prod (przed falą 3) | Makieta → co wchodzi |
|---|---|---|
| jobbar (02–08) | tytuł + badge'e; klienta w nagłówku nie ma; panel „Zespół i priorytet" ROZWINIĘTY domyślnie na każdej zakładce (~40 % ekranu); listwa obcina „Baza pytań" | `tytuł · klient` + subtytuł (lokalizacja/tryb · budżet PLN/h · deadline · właściciel) + **3 KPI per krok** z tego samego kanbana (`lib/job-header-kpis.ts`); panel domyślnie zwinięty (preferencja użytkownika wygrywa); listwa mieści wszystkie etykiety |
| 01 Lista | liczniki tylko przy „Brak ownera requestu" (z bieżącej strony); Status jako select; osobna kolumna Klient; dok bez zakładek i nawigacji | `GET /api/jobs/quick-counts` (te same predykaty co filtry listy) + `owner_missing` w `list_jobs`; Status jako pigułki (`draft/published/closed` — tylko istniejące statusy); klient pod tytułem, mini-lejek z liczbami `13·2·0 / 15`, deadline `30.09 · 23 d`; dok: `‹ 1 z 12 ›`, zakładki Gotowość · Pipeline · Zespół · Historia, stopka „Ostatnia zmiana" |
| 02 Champion | dok: 5 warunków + osobna lista weryfikacji, zakładki zawijają się; wszystkie 6 sekcji rozwinięte z chipem „Pusta" | dok: JEDNA lista 7 warunków (rozmowa z klientem · z konsultantem · briefing · stack · budżet · właściciel · HM) z akcjami Oznacz/Podepnij/Claim/Przypisz, gauge „N / 7 · zlecenie gotowe w X %", bramka jako jedna linia z rozwinięciem, box „Rekomendowane wyszukiwania (AI)" inline; edytor: Zlecenie (z widełkami klienta) → 1 → 3 (stack `Musi mieć · N`) → 2·4·5 zwinięte, gdy puste → 6 z kartą klienta |
| 04 Pipeline | rail = 15 etapów; karta = wynik + nazwisko + „R: Imię"; puste kolumny stoją; dok bez osi czasu | rail = 6 grup (`groupKanbanColumns`) + „Bez następnej akcji" + SLA klienta z karty klienta; puste grupy „U klienta" / „Umowa → zatrudnieni" zwinięte do jednej kolumny-placeholdera (nie jest celem drop); karta = nazwisko + awatar rekrutera + wiek (bad ≥ 7 d) + **następna akcja** (`lib/pipeline-next-action.ts`, deterministycznie z kategorii etapu); nagłówek kolumny z linią SLA/„najstarszy N d"; dok: `‹ N z M ›`, oś czasu etapu, „Przenieś na etap: <następny>", Poprzedni/Następny |
| 05–08 warsztaty | struktura trzech kolumn jest, brakuje nagłówków, pigułek stanu, zakładek doku, osi podpisu | nagłówki `Krok · Nazwisko` + subtytuł + pigułki; dok z zakładkami (Stawka i decyzja · Dopasowanie / Wyślij · Linki / Decyzja · Oferta / Po podpisie · Zamówienie · Alerty DL); reguły CV klienta jako lista warunków; marża (podgląd) przy stawce do klienta; oś czasu podpisu z `statusHistory`; „Odrzuć z powodem" przez tę samą ścieżkę `requestMove` |

Poza falą 3 (świadomie): „Źródło" na tablicy (`KanbanItem` nie niesie źródła — backend),
„Wiadomość" zbiorcza z tablicy (brak bulk e-maila), „Pliki" w doku pipeline'u, ocena ryzyka
kandydata („Niskie ryzyko" — brak źródła), „Ostatnia aktywność: kto zmienił etap" (brak
taniego feedu).

## Kontrakt wspólny (obowiązuje każdy PR)

- **Nawigacja:** `JobDetailTab` bez zmian (`pipeline | history | ai-matching | manual-search |
  portals | champion | questions | chat`). Listwa kroków w `JobDetailCompactHeader`; nowe
  powierzchnie (CV do klienta, Rozmowy, Umowa) dochodzą jako NOWE wartości `JobDetailTab`
  w swoich PR-ach — nie przepinaj istniejących.
- **Layout kroku (jak C2):** `grid grid-cols-1 gap-4 lg:grid-cols-[230px_minmax(0,1fr)]
  xl:grid-cols-[230px_minmax(0,1fr)_360px]` — lewa kolumna filtrów/wymagań, środek, dok
  (`xl:sticky xl:top-4 xl:self-start`; poniżej `xl` dok spływa pod listę). Bez poziomego
  scrolla strony (`overflow-x-auto` tylko na własnych kontenerach).
- **Tokeny, nigdy hardcody:** `success*`, `warning*`, `destructive*`, `primary`, `muted*`
  z `globals.css`. Zero `emerald-*`/`amber-*`/`green-*`.
- **Stany widoku:** ładowanie / brak uprawnień (403 ≠ pusto) / nie znaleziono / awaria /
  pusto — pusty stan wyłącznie pod `isSuccess`; awaria z przyciskiem „Ponów".
- **RBAC:** `readOnly` (`canWritePipeline`) wyłącza mutacje, nie odczyt; akcje admin-only
  (np. `JobAIActions`) zostają admin-only.
- **Bramka dopuszczalności:** akcja zablokowana = widoczna, wyszarzona, `title` = polski
  powód (jak w C2), nie 409 po kliknięciu. Terminalne (`rejected`/`withdrawn`) zawsze
  przechodzą. `hired` nigdy zbiorczo. `withdrawn` zawsze z powodem ze słownika.
- **Ukrywanie nigdy nie jest ciche:** każdy filtr dealbreakera ma licznik „ukryto N".
- **Kubełek „Poza szablonem"** nie jest celem drop; 15 kolumn kanbana to sufit układu.
- **Weryfikacja przed PR:** `tsc --noEmit` (bez `| tail`!), `eslint` 0 błędów, vitest dla
  dotkniętych testów (`--no-file-parallelism`), zrzut z produkcji przez Chrome po deployu.
  Testy jednostkowe dla nowych helperów/komponentów z logiką (filtry, liczniki, stany).
- **Merge FALAMI, nie per krok:** agent kończy PR-em bez merge'a; koordynator zbiera commity
  agentów cherry-pickiem na gałąź integracyjną fali (od `origin/main` — gałęzie agentów
  bazowały na listwie kroków sprzed squasha, więc `merge` zdublowałby ją), robi przegląd
  i poprawki, weryfikuje raz centralnie i otwiera JEDEN PR fali; PR-y agentów zamyka
  z odnośnikiem „zebrane w #X". Potem `scripts/merge-train.sh <pr>` (main rusza co ~20 min;
  `strict=true`).

## Briefy per krok (dla agentów)

### PR 2 · 03 Pozyskiwanie — rama źródeł (`frontend/src/app/jobs/[id]/page.tsx`, zakładka `ai-matching`)
Dziś zakładka renderuje kolejno `HistoricalCandidatesSection` → `SuggestedCandidatesWidget` →
`AIMatchingSection` (C2). Cel (makieta krok 03): nad C2 rama czterech kart-źródeł:
1. **AI Matching · C2** (domyślna, aktywna) — liczniki: w rankingu (`ai-matches` `matches.length`),
   ukryto (`meta.hidden`), shortlista (`GET /api/jobs/{id}/shortlist`).
2. **Wyszukaj manualnie** — klik = `onTabChange("manual-search")` (osadzony `CandidateSearchView`
   zostaje w swojej zakładce); licznik: liczba zapisanych strategii (`ChampionRecommendedSearches`
   → zatwierdzone) jeśli tanio dostępne, inaczej bez licznika.
3. **Podobne projekty** — to dzisiejszy `HistoricalCandidatesSection` renderowany jako karta
   (klik rozwija go POD ramą, zamiast bloku NAD rankingiem); licznik z jego odpowiedzi
   (`candidates-from-similar` total).
4. **Portale** — klik = `onTabChange("portals")`; licznik publikacji (`GET /api/jobs/{id}/postings`
   length) + banner „symulowane" zostaje w widoku portali.
`SuggestedCandidatesWidget` („Rekomendowani"): jego kontrolki (lokalizacja + źródło, „Poza
budżetem", „Tylko-zdalni", „Odśwież propozycje"/„Zasugeruj") czytają te same parametry co C2 —
**przenieś je jako drugorzędne akcje do karty AI Matching** (przycisk „Odśwież propozycje" →
`POST …/proposals/regenerate` + invalidate `["ai-matches", jobId]`), a sam widget usuń z zakładki
TYLKO jeśli każda jego funkcja z inwentarza (poz. 87–95) ma nowe miejsce; w razie wątpliwości
zostaw go zwinięty pod ramą z nagłówkiem „Rekomendowani (tryb snapshot)". Historia requestu:
skrót w listwie zostaje (`history`), a pod ramą renderuj kompaktowy `RequestHistorySection`
(ten sam komponent, prop `compact` jeśli dodasz) — bez duplikowania logiki.
Nie dotykaj `AIMatchingSection`/`JobMatchDock`.

### PR 3 · 04 Pipeline — dok „Karta w procesie" (`KanbanBoardV2.tsx`, nowy `PipelineCandidateDock.tsx`)
- Nowy dok po prawej (grid jak w C2, `xl` 3 kolumny; poniżej dok pod tablicą). Otwiera go klik
  w kartę (nie checkbox, nie link do profilu). Treść: nagłówek (avatar, nazwisko, rola·firma·miasto,
  `ScoreRing`/wynik z `pipelineScores`), zakładki: **W procesie** (oś etapów z `CandidateStage`
  historii: kto/kiedy, „Dodano przez"), **Screening** (`ScreeningSheet` inline lub przycisk
  otwierający — nie duplikuj formularza), **CV** (snapshot oryginalne/brandowane — linki do
  istniejących modali), **Dopasowanie** (leniwy `DopasowanieTab`), **Notatki** (`NotatkiTab`
  albo lista + `noteadd`). Sekcja „Przenieś na etap": pills kolumn szablonu; etap zablokowany
  bramką (`assert_candidate_move_eligible` → użyj istniejącego endpointu podglądu, jeśli jest;
  inaczej wyszarz po `hm_veto`/`verification_status=pending` z danych karty) wyszarzony z powodem;
  ruch przez ISTNIEJĄCY `sendMove` (modale stawek/odrzucenia zostają). Akcje: Otwórz CV · Wyślij
  wiadomość · Pełny profil · Odrzuć z powodem (`RejectionV2`).
- Karta: dodaj „wiek na etapie" (już jest: dni w etapie) + **następna akcja** (jeśli brak danych —
  nie wymyślaj; pokaż „brak następnej akcji" z opcją dodania notatki) + flaga bramki (`hm_veto`,
  `verification_status`).
- Lewa kolumna: lista etapów z licznikami (klik = `StageFocusNavigator` fokus), filtry: utknęli
  > 7 d (`days_in_stage`), bez następnej akcji, zablokowani bramką, rekruter (`added_to_job_by`),
  „Poza szablonem" (fokus kubełka), przełącznik „Ukryj puste kolumny" (`useUiStore`).
- Nie zmieniaj DnD, `bulkMove`, modali, `onDragEnd`. Testy: `KanbanBoardV2` ma testy? sprawdź
  `__tests__`; dołóż test doku (render + „Przenieś na etap" wyszarzone z powodem).

### PR 4 · 01 Lista (`JobsListV2.tsx`)
- Grid jak C2: lewa kolumna filtrów (Typ pills; „Szybkie" z licznikami: Moje projekty,
  Niezamknięte, Potrzebny search, Aktywni w searchu, **Brak ownera requestu** (`tac_id IS NULL` —
  jeśli API nie ma filtra, policz z bieżącej strony i oznacz „na tej stronie"), **Deadline ≤ 7 dni**
  (`deadline_*` istniejące opcje); Status, Klient, Kategoria, Osoba, Priority Work, Termin, sort).
  Wszystkie dzisiejsze parametry (`?recruitment_type&status[]&priority_work&client_id[]&
  competence_category_id[]&responsible_id[]&deadline_*&sort&open_only&needs_sourcing&
  active_in_search&mine`) zostają 1:1; deep-linki `?mine=`/`?status=` zostają.
- Wiersz: tytuł+ref, klient, **mini-lejek** (6 grup etapów; dane: `filled/target` + jeśli lista ma
  liczniki etapów — użyj; jeśli nie — pokaż `filled/target` jako pasek i NIE dorabiaj zapytania per
  wiersz), właściciel (`OwnerBadge`), status + „Brak ownera", deadline z kolorem (≤ 7 d warning,
  po terminie destructive), „Wygeneruj link" ikona, klik = dok.
- Dok „Gotowość zlecenia": `GET /api/jobs/{id}/readiness` (blockers) + owner/HM/Champion
  z `GET /api/jobs/{id}`; akcje: Otwórz warsztat (`/jobs/{id}?tab=similar`), Dodaj kandydata,
  Edytuj (istniejące modale). Widok kafelków zostaje jako przełącznik.

### PR 5 · 02 Zlecenie i Champion (`ChampionProfileEditor.tsx`, `page.tsx` zakładka `champion`)
- Edytor na pełną szerokość (zdjąć `max-w`), sekcje z chipem stanu (wypełnione / puste / z AI).
- Dok „Gotowość" (nowy `JobReadinessDock.tsx`): `GET …/readiness` + `ChampionVerificationChecklist`
  + briefing + `ChampionRecommendedSearches` (zakładka „Wyszukiwania (AI)") + **Zespół i priorytet**
  (przenieś `JobOwnershipPanel`, `HiringManagerPicker`, `JobPriorityContext` z rozwijanego panelu
  nagłówka do zakładki doku — panel w nagłówku zostaje dla innych kroków) + `JobHandoffButton`
  jako główna akcja.
- Sekcja „Zlecenie" (pola z `EditJobModal`) — NIE dubluj formularza: karta read-only z przyciskiem
  „Edytuj" (modal zostaje źródłem prawdy).

### PR 6 · 05 Screening + 06 CV do klienta
- Nowa zakładka `screening`: lewa kolumna = kolejka (kandydaci na `screening` + pending
  weryfikacji), środek = `ScreeningSheet` inline dla wybranego (pytania Championa + przypięte
  z `QuestionBankTab` + prep-kit link), dok = stawka (`VerifiedRateModal` jako sekcja) + wynik +
  „Zweryfikowany" (ten sam `POST /api/pipeline/move` z `expected_rate_*`).
- Nowa zakładka `cv`: lewa = zweryfikowani + `ClientCvRuleBanner` jako lista warunków, środek =
  `CVGeneratorStandaloneV2` w trybie osadzonym (prefill kandydat+rekrutacja) + snapshoty
  (`cv/original`, `cv/branded`), dok = stawka do klienta (`client-rate`) + link (`share-token`) +
  „Wyślij klientowi i przenieś na CV Wysłane" (sekwencja: client-rate → share-token → move).

### PR 7 · 07 Rozmowy i decyzja + 08 Umowa
- Zakładka `interviews`: kandydaci na etapach zewnętrznych, karta rozmowy (prep-kit, Screening
  Championa dla klienta + link, feedback HM — wymaga `POST /api/jobs/{id}/hiring-manager-feedback`
  zapisującego werdykt do `hiring_manager_verdicts` z flagą `disqualifies_person`), dok „Decyzja"
  (Przenieś na etap, oferta/reakcja `candidate_offer_response`, `RejectionV2`).
- Zakładka `contract`: status podpisu (`b2bGeneratorApi.statusHistory`), hook `hired` wyjaśniony,
  braki do aktywacji (`ACTIVATION_REQUIRED_FIELDS`), dok: kontrakt/zamówienie/powiadomienia,
  **„Zamknij rekrutację z powodem"** → `POST /api/jobs/{id}/close` (7 powodów `JobCloseReason`).
