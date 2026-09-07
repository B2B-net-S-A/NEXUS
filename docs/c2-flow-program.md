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
| 2 | 03 Pozyskiwanie — rama źródeł | 4 karty nad C2 (AI Matching · Wyszukaj manualnie · Podobne projekty · Portale) z licznikami; „Podobne projekty" i „Rekomendowani" jako karty, nie bloki nad rankingiem; Historia requestu pod ramą + „N kandydatów → źródło" | **fala 1 — w tym PR** (zebrane z #1391) |
| 3 | 04 Pipeline — dok „Karta w procesie" | dok obok kanbana (etapy, „Przenieś na etap" z bramką wyszarzoną z powodem, notatki, CV, warunki), karta z wiekiem/następną akcją/flagą, filtry lewej kolumny, „Ukryj puste" | **fala 1 — w tym PR** |
| 4 | 01 Lista | lewa kolumna filtrów (typ, szybkie z licznikami: Moje/Niezamknięte/Potrzebny search/Aktywni/Brak ownera/Deadline ≤ 7 d), mini-lejek w wierszu, dok „Gotowość zlecenia" | **fala 1 — w tym PR** |
| 5 | 02 Zlecenie i Champion | Champion na pełną szerokość ze stanem sekcji, dok „Gotowość" (readiness + weryfikacja + briefing + zespół + HM), handoff jako główna akcja | fala 2 (jeden PR z 6 i 7) |
| 6 | 05 Screening + 06 CV do klienta | stanowisko screeningu (kolejka → arkusz → dok „Weryfikacja"); CV do klienta (reguły klienta przed generacją, jedna akcja „Wyślij") | **fala 2 — w tym PR** |
| 7 | 07 Rozmowy i decyzja + 08 Umowa | karta rozmowy z feedbackiem HM (małe rozszerzenie `hiring_manager_verdicts`), karta zamknięcia + „Zamknij rekrutację z powodem" (`POST /jobs/{id}/close`) | fala 2 |

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
