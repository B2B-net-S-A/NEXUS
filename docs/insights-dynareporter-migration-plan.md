# Insights ← DynaReporter: raport z rozpoznania i plan wykonawczy

Repo robocze: `/Users/arturtwardowski/NEXUS/.claude/worktrees/insights-rekrutacja-nexus-data-dc14e9`
Źródło oryginału: `/Users/arturtwardowski/InfraReporter` (`client/src/pages/*.tsx`, `server/src/routes/*.ts`)
Wchłonięty port: `backend/app/api/dynareporter_*.py` (21 routerów), `backend/app/models/dr_*.py`, migracja `0113`
Stan mierzony na produkcji (`api.nexus.dynaminds.pl`, sesja admina) — traktuję jako fakt, nie hipotezę.

---

---

## 0. Decyzje Artura (2026-08-31) — ROZSTRZYGNIĘTE, wiążą cały dokument

| # | Pytanie | Decyzja | Skutek dla planu |
|---|---|---|---|
| **D1** | Czy zespół zacznie klikać w NEXUSIE? | **TAK, wchodzimy w NEXUS** | Etapy 2 i 3 są **odblokowane** (tabela imienna, Liga, wyścigi, Hall of Fame). Atrybucja imienna wchodzi do zakresu. Kolumna `unattributed` musi być renderowana od pierwszego dnia — dziś większość dorobku pochodzi z importu i to musi być widoczne, a nie zamiecione. |
| **D2** | Kanoniczna definicja placementu | **Pierwsze `hired` per para kandydat×oferta** (`analytics_first_milestones`) | Jedna definicja na **całej** stronie /insights, także w Zarządzie i w Lidze. Wpisać do CLAUDE.md. Wycofać z /insights liczenie „każdy wiersz `hired`" (`reports.py:1532`, `reports.py:1080-1098`) i „pierwsze `hired` per próba procesu" (`kpi_panel.py:155-166`). |
| **D3** | Liga Mistrzów i nagrody | **Naprawić formułę, BEZ retroaktywności** | Składnik interview przestawiony z `client_interview` (martwy) na `interview`; próg progresywny 1/2/3 wg miesiąca kwartału; niezakwalifikowani widoczni z „(brakuje placementu)" zamiast znikać; **wagi konfigurowalne przez admina → migracja `insights_scoring_config` WCHODZI do zakresu**. Obowiązuje od najbliższego niezamkniętego kwartału. Zamrożonych podiów (`competition_winners`) **nie ruszamy**. |
| **D4** | Premie (`/kpi/sales/bonuses`) | **POZA ZAKRESEM**, razem z Sales | Nie odtwarzamy. Gamifikacja rekrutacyjna zostaje — żyje na stronie Rekrutacja, nie na Premiach. |
| **D5** | Dni robocze / urlopy | **Z COMPASSA** (`public.leave_requests` + `profiles.leave_entitlement_days`) | Odblokowuje Power Calling, „CV/MD target 5" i każdy wskaźnik „na dzień". Naprawia `reports.py:1854-1855`, gdzie dziś dzieli się przez **sztywne 5 dni** — przez co osoba na urlopie ląduje na liście „poniżej progu" z imienia i nazwiska. **NEXUS przechowuje wyłącznie LICZBĘ DNI, nigdy typu nieobecności** (`sick_leave`/`maternity` to dane o zdrowiu). Warunek: pokrycie zespołu rekrutacyjnego w COMPASSIE — do zmierzenia przed budową. |
| **D6** | Seniority | **Z liczby placementów w oknie czasowym**, nie z tabeli kadrowej | Zastępuje `dr_user_seniority` (jedyne miejsce, gdzie `seniority_level` w ogóle istnieje). Placement wg **D2**. Odblokowuje Acceleration Path bez integracji kadrowej. |
| **D7** | Kto co widzi | **WSZYSCY widzą wszystko** na /insights | Zgłosiłem konsekwencję (kwoty — przychody, marże, stawki — oraz dane imienne stają się widoczne dla każdej roli), Artur potwierdził. Znika redakcja `VIEW_FINANCE` **na /insights**. Sweep musi objąć wszystkie lustra list ról (zakładki, middleware, sidebar, macierz capability, in-page `RequireRole`) **oraz** guardy backendu. Poszerzamy **tylko /insights** — jeśli endpoint jest współdzielony z powierzchnią, która ma zostać wąska, robimy osobny `/api/insights/*`. |

**Zakres docelowy Insights po tych decyzjach:** Rekrutacja · Liga Mistrzów / wyścigi · Delivery Lead (Body Leasing) · Klienci / MRR · Zarząd.
**Poza zakresem:** Sales · AI Analytics · Przetargi · Premie.

**Wszystkie pytania z §6 są rozstrzygnięte (D1-D7).** §6 zostaje wyłącznie jako uzasadnienie decyzji.

## 1. Co pokazuje DynaReporter (inwentarz)

### 1.0 Poza zakresem — decyzja Artura, nie mapuję i nie planuję

| Obszar | Status |
|---|---|
| **Sales** (`Sales.tsx`, `dr_sales`, `dynareporter_sales_mgmt.py`) | POZA ZAKRESEM. Do skasowania z /insights razem z `SalesOverview.tsx`. |
| **AI Analytics** (`AIAnalytics.tsx`, `dynareporter_mindy.py`, `dr_mindy`) | POZA ZAKRESEM. |
| **Przetargi** (`Przetargi.tsx`, `dr_przetargi`, `dynareporter_przetargi.py`) | POZA ZAKRESEM. Dzisiejszy `TendersSection.tsx` w zakładce Zarząd — do skasowania bez następcy. |

**Uwaga do zakresu, którą musisz rozstrzygnąć (patrz §6 Q4):** zakładka **Premie** w DynaReporterze **NIE jest premią rekrutacyjną**. `client/src/pages/Premie.tsx:241,244` woła `/kpi/sales/bonuses` (`server/src/routes/kpi.ts:3978-4235`), a role to `hod | bdm | sdr` (Head of Technology / BDM / SDR), pozycje to `projectId/projectName/netValue/projectCosts/margin` oraz `leadId/companyName/weekStart`. To jest moduł **sprzedażowy**. Rekrutacyjna gamifikacja (Liga Mistrzów, wyścigi, Hall of Fame) żyje na stronie **Rekrutacja**, nie na Premiach. Poniżej inwentaryzuję ją jako §1.2, ale samo Premie traktuję jako kandydata do wypadnięcia razem z Sales.

---

### 1.1 Rekrutacja (`Rekrutacja.tsx`, `server/src/routes/kpi.ts`)

Wszystko stoi na JEDNEJ tabeli `kpi_body_leasing` (`InfraReporter/server/src/db/schema.sql:36-49`: `user_id, report_date, week_number, verifications, recommendations, interviews, placements, requests, days_worked, linkedin_*`) zasilanej **cotygodniowym uploadem XLSX + ręcznym formularzem**.

| Widget | Definicja DR | Stan danych dr_* w NEXUSIE |
|---|---|---|
| Filtr okresu (Tydzień/Miesiąc/Rok + dropdown tygodnia) | `buildKpiDateFilter` (kpi.ts:9-43); anchor przez `weekNumber+year` / `date`. Default tygodnia = **poprzedni, zamknięty** tydzień (kpi.ts:38-42) | **ZAMROŻONE** — `/rekrutacja/available-weeks` czyta `dr_kpi_body_leasing`, ostatni wpis: **tydzień 21/2026** |
| Przełącznik Overall / Miesiąc + plakietka roku | Gałąź `year` czyta wyłącznie `date` → **plakietka roku nic nie robi** (kpi.ts:29-36) | udokumentowany bug |
| Kafel Weryfikacje | `SUM(k.verifications)`, bez joina do users, bez filtra roli (kpi.ts:170-182) | ZAMROŻONE |
| Kafel Rekomendacje | `SUM(k.recommendations)` (kpi.ts:168-178) | ZAMROŻONE |
| Kafel Interviews | `SUM(k.interviews)` | ZAMROŻONE |
| Kafel Placements | `SUM(k.placements)` + filtr `is_draft` | ZAMROŻONE |
| Kafel Requests (zapotrzebowania) | `SUM(k.requests)` | ZAMROŻONE, **bez mapowania w NEXUSIE** |
| Kafel Dni robocze | `SUM(k.days_worked)` | ZAMROŻONE, **brak odpowiednika** |
| Konwersje Wer→Rek, Rek→Int, Int→Plac, Overall | `/monthly-trends` (kpi.ts:534-618) — **inna populacja niż kafle** (bez `is_draft`) | ZAMROŻONE |
| Tabela „Performance per osoba" (Osoba/Rola/Wer/Rek/Int/Plac, medale, chip „były pracownik") | `users LEFT JOIN kpi_body_leasing`, `department='body_leasing'`, `roles && [sourcer,tac,recruiter]` (kpi.ts:62-88) | ZAMROŻONE |
| Plakietki ostrzeżeń „Słabe wyniki" / „Procedury" | `users.warning_banner*` — ręczna flaga admina (`client/src/components/warningBanner.ts:36-57`) | **NIGDY NIE ZAIMPORTOWANE** — `grep warning_banner backend/` = 0 trafień |
| Eksport CSV / XLS / Drukuj + kolumna „Punkty" | Czysto kliencki blob (`ExportButton.tsx:14-90`) | n/d |
| Drag&drop kolejności 11 sekcji (`localStorage bodyLeasing-sectionOrder-v8`) | Rekrutacja.tsx:58-70 | n/d |
| Wykres „Progress Zespołu" (4 serie, dwie osie) | 4 zapytania all-time po tygodniach, klient filtruje bieżący rok (`TeamProgressChart.tsx:46-129`) — **ignoruje filtr strony** | ZAMROŻONE (tydzień 21/2026) |
| Wykres „Efektywność Lejka" (4 konwersje po miesiącach, oś 0-100%) | `ConversionBars.tsx:39-77`, twardo bieżący rok, oś przycięta → **ciche obcinanie >100%** | ZAMROŻONE |
| LinkedIn: 4 kafle (CV dodane / CV per MD, target 5 / Wiadomości / Response Rate) | `kpi.ts:921-987`, populacja `roles && [tac,recruiter]` — **sourcerzy wykluczeni, jedyne takie miejsce**; CV/MD = **nieważona** średnia per-user | ZAMROŻONE |
| LinkedIn: tabela 7 kolumn z paskiem % wobec `CV_TARGET_PER_MD=5` | `LinkedInPerformancePanel.tsx:37-245` | ZAMROŻONE |
| Power Calling — lista poniżej progu | `competitions.ts:765-865`: `latest_work_week` (ostatni tydzień z `days_worked>0`), `verificationsPerDay = SUM(verifications)/SUM(COALESCE(days_worked,5))`, próg z `system_config` (default 3) | ZAMROŻONE |
| Power Calling — wiersze „Brak danych" | drugie zapytanie: aktywni bez ANI JEDNEGO wpisu KPI, szary chip, liczeni jako niespełniający progu (competitions.ts:815-854) | ZAMROŻONE |
| Analiza Placementów — donut per osoba (+ All-time) | `placements.ts:315-372`, `HAVING > 0` | **ZAMROŻONE** — `/placements/all` = 390 wierszy, najnowszy `placement_date` **2026-05-11**; `/placements/stats/by-user` = `[]` |
| Analiza Placementów — donut per klient | `COUNT(placement_details) JOIN clients` (placements.ts:233-245) — **INNA tabela niż donut obok** | ZAMROŻONE / chronicznie niekompletne |
| Plakietka rozjazdu „Przypisano X z Y" | `hasGap = COUNT(placement_details) < SUM(kpi.placements)` (placements.ts:247-266) — istniała **wyłącznie** po to, żeby ujawnić dług ręcznej atrybucji | n/d |
| 3 kafle placementów (osoby / suma / klienci + nazwa top) | `PlacementRankingSection.tsx:156-162,319-352` | ZAMROŻONE |
| Zespół Rekrutacji — Sourcerzy wg Kategorii Kompetencji (1st/2nd Priority) | `competence_categories × sourcer_category_assignments` (recruitmentTeam.ts:507-549) | dane w `dr_sourcer_category_assignments`, konsumowane przez `dynareporter_rekrutacja.py:1393+` |
| Zespół Rekrutacji — TAC × Delivery Lead + LinkedIn Farming | `tac_delivery_lead_assignments` + `tac_linkedin_farming` (recruitmentTeam.ts:551-600) | jw. |
| Acceleration Path — Junior→Senior i Senior→Expert (Start/Mscy/2 paski/Status) | `users.seniority_level + acceleration_start_date + senior_since/expert_since`; progi 6/6 lub 12/12 i 12/6 lub 24/12; awans od 1. dnia kolejnego miesiąca; okno resetuje się po 12 mc | `dr_user_seniority` + `dr_placement_details` (`dynareporter_rekrutacja.py:1161-1310`). **Silnik awansów w oryginale MUTOWAŁ dane przy GET** (kpi.ts:4730-4998) |
| Acceleration Path — badge statusu + liczniki nagłówka | priorytet: pending → window_expired → behind → on_track (kpi.ts:4703-4724) | jw. |

### 1.2 Gamifikacja rekrutacyjna (strona Rekrutacja, `competitions.ts`)

| Widget | Definicja DR | Stan |
|---|---|---|
| Liga Mistrzów — podium top-3 (punkty + rozbicie P/I/R) | `SUM(placements/interviews/recommendations/verifications) × system_config['champions_league_scoring']` (default **120/12/1/0**), populacja `roles && [sourcer,tac,recruiter] AND is_active AND department != 'rekrutacja_viewer'` (competitions.ts:110-156) | **ZAMROŻONE** — `/competitions/winners` i `/rekrutacja/hall-of-fame` = podium Q1 2026, `points 0`, `metric_value 0`, `prize null` |
| Liga Mistrzów — pełny ranking (4+) | `standings.slice(3)`, **LEFT JOIN → wszyscy, także z zerami**; niezakwalifikowani na pomarańczowo „(brakuje placementu)" (competitions.ts:107-137, `QuarterlyLeague.tsx:347`) | ZAMROŻONE |
| Liga Mistrzów — countdown dni + pasek postępu kwartału | `getQuarterInfo` (competitions.ts:9-49) z gałęziami `isCompleted` / `isUpcoming`; `totalDays` liczone realnie (90/91/92) | czysta arytmetyka |
| Liga Mistrzów — nagrody 5000/3000/2000 PLN | hardcode (competitions.ts:175-179), osobny panel „Nagrody" | n/d |
| Liga Mistrzów — panel „System punktowy" + edycja przez admina | `system_config['champions_league_scoring']`, `PUT /api/config/scoring`, walidacja 0..1000, cache 5 min | `dr_system_config` (`dynareporter_admin_config.py:44-46,64-138`) — **write dead**, `DYNAREPORTER_MODE=read_only` → 409 |
| Liga Mistrzów — „Warunek udziału" (progresywnie 1/2/3 wg miesiąca kwartału) | `requiredPlacements = monthInQuarter`; dla zamkniętego kwartału wymuszone 3; **flaga, nie filtr** | n/d |
| Wyścig Rekomendacji — ranking miesięczny | `SUM(k.recommendations)` za miesiąc kalendarzowy, LEFT JOIN → cała załoga z zerami (competitions.ts:238-249) | ZAMROŻONE |
| Wyścig Rekomendacji — plakietka „X.X/dzień" (wymóg 4 wer./dzień roboczy) | `SUM(verifications)/SUM(COALESCE(days_worked,5))` — **rate per-osoba** | ZAMROŻONE |
| Wyścig Rekomendacji — plakietka precision ≥75% | `recommendations/verifications`, aktywna **tylko od `2026-04`** (`PRECISION_RATE_ACTIVE_FROM`), wcześniej chip ukryty (competitions.ts:220-221,279,318) | ZAMROŻONE |
| Wyścig Placementów — ranking miesięczny | `SUM(k.placements)` | ZAMROŻONE |
| Wykluczenie lidera kwartalnego z wyścigów | **tylko w ostatnim miesiącu kwartału** (`if (quarterInfo.isLastMonthOfQuarter)`, competitions.ts:251) | n/d |
| Hall of Fame | tabela `competition_winners`, **w 100% ręczna** | ZAMROŻONE, Q1 2026 |

### 1.3 Body Leasing / Delivery Lead (`DeliveryLead.tsx`, `deliveryLead.ts`)

Etykiety realne: Ranking Delivery Leadów, Zapytania, Wakaty, Zamknięte zapytania, Hit Ratio %, Fill Rate %, Placements, Historia zespołu, Średni Hit Ratio, Średnia 6 mies., wykres „Hit Ratio i Placements", sortowanie po nagłówku.

| Widget | Stan dr_* |
|---|---|
| Ranking DL: requests / placements / vacancies / hit_ratio / fill_rate | **ŻYWE DANE** w `/api/dynareporter/delivery-lead-dashboard/dashboard` — ale **userzy DL mają `is_active = false`** |
| Trend 6-mies. per DL | jw. |
| Historia zespołu | jw. |
| Kafle body-leasing (summary/ranking) | **PUSTE** — `/api/dynareporter/kpi/body-leasing/summary` = same zera, `/ranking` = `[]` |

### 1.4 Klienci / MRR (`clients-mrr`, `dr_client_mrr`)

Widgety: „Suma MRR (12 mc)", „Aktywnych klientów", tabela MRR per klient × miesiąc.

**CAŁKOWICIE PUSTE.** `/api/dynareporter/clients-mrr/mrr` = `[]`; `/summary` = `total_mrr 0`, `distinct_clients 0`. Modele: `backend/app/models/dr_clients_mrr.py` (`dr_clients`, `dr_client_mrr`, `dr_finances`).

### 1.5 Zarząd / Rada (`Board.tsx`, `boardMonthly.ts`, `dr_board_monthly_report`)

Sekcje realne: **Finanse**, **Wskaźniki operacyjne**, **Rozbicie placementów na klientów**, **Dywersyfikacja placementów**, kolumna **Ocena** (Lepiej/Gorzej), **Marża**, **Suma/rok**, **Suma/Średnia**.

| Pole (`backend/app/models/dr_board.py:24-43`) | Stan |
|---|---|
| `revenue` | **NIGDY NIE WYPEŁNIONE** — 0.0 w każdym z 36 miesięcy |
| `consultant_costs`, `other_costs` | **NIGDY NIE WYPEŁNIONE** |
| `avg_margin_per_hour` | **NIGDY NIE WYPEŁNIONE** |
| `hit_ratio` | **NIGDY NIE WYPEŁNIONE** |
| `active_consultants` | **REALNE** |
| `departures` | **REALNE** |
| `placements` | **REALNE** |
| `dr_board_placement_clients` (breakdown per klient × miesiąc) | **REALNE** |
| `/api/dynareporter/board/latest` | `report_month 2026-10`, **wszystkie pola zerowe** (pusty wiersz z przyszłości) |

**Wniosek ramowy dla całej §1: odbudowa czegokolwiek przez czytanie `dr_*` jest bezcelowa.** `dr_kpi_body_leasing` nie ma ani jednego writera — `POST /api/dynareporter/upload/excel` zwraca **410 Gone** (`backend/app/api/dynareporter_upload.py:65-70`: „parsowanie XLSX nigdy nie powstało"), a trasy zapisu KPI zdjęto 2026-07-20 (`backend/app/api/dynareporter_kpi_body_leasing.py:6-8`). W całym backendzie zostały wyłącznie SELECT-y.

---

## 2. Skąd wziąć te dane z NEXUSA

Legenda wykonalności: **direct** = endpoint istnieje i zwraca to pole · **derivable** = liczone na froncie/SQL z tego, co już wraca · **needs_code** = trzeba dopisać zapytanie/parametr · **impossible** = brak modelu danych.
Wierność: **identical** / **approximate** / **PROXY** (inna wielkość pod tą samą nazwą — nie wolno rysować na jednej osi z historią DR).

### 2.1 Rekrutacja — lejek

| Widget DR | Źródło NEXUS | Wykon. | Wierność | Nakład |
|---|---|---|---|---|
| Filtr okresu | `backend/app/analytics/periods.py:77-155` + `backend/app/api/dashboard_v2.py:113-129` | **needs_code** ⬇️ *zdegradowane z „direct"* | approximate | S/M |
| Dropdown „dostępne tygodnie" | **BRAK** — `/rekrutacja/available-weeks` czyta martwą `dr_kpi_body_leasing`. Trzeba nowego zapytania po `candidate_stages.moved_at` | needs_code | approximate | S |
| Overall / plakietka roku | **nie odtwarzać** — to udokumentowany bug DR | impossible | — | — |
| Kafel Weryfikacje | ⚠️ **NIE** `data.kpis.verifications`. Kanoniczna liczba org-level: `analytics_first_milestones WHERE stage='verified'` — wzorzec z `backend/app/api/reports.py:239-247` | direct (nowe zapytanie) | **PROXY** | S |
| Kafel Rekomendacje | `analytics_first_milestones stage='cv_sent'` / `data.kpis.recommendations` | direct | approximate | S |
| Kafel Interviews | `stage IN ('interview','client_interview')`. ⚠️ `interview` to **zlepek**: Traffit `technical_verification` → `interview` (`backend/app/services/traffit/mappers.py:415-419`) razem z `interview`. `client_interview` **nie ma żadnego mapowania Traffita** | direct | **PROXY** | S |
| Kafel Placements | `analytics_first_milestones stage='hired'`. ⚠️ **NIE** `data.kpis.placements` (liczy per PRÓBA procesu, `kpi_panel.py:155-166` → sierpień 20 vs 12 raw) | direct | approximate | S |
| Kafel Requests | `jobs` utworzone w oknie **albo** `client_orders` — **nikt tego nie zdefiniował** | needs_code | PROXY | S |
| Kafel Dni robocze | **BRAK** (§3a) | impossible | — | — |
| 4 konwersje lejka | liczone z tych samych liczników co kafle, funkcją `backend/app/services/recruitment_trend.py:168`. ⚠️ **NIE** `data.conversions.*` — tamto stoi na `team.totals`, czyli na podzbiorze przypisanym | derivable | **PROXY** | S |
| Tabela per osoba | `GET /api/dashboard/v2/recruitment-stats → data.team_table` (`backend/app/services/dashboard_v2.py:1780-1813`, `backend/app/services/kpi_team.py:137-350`). Komponent gotowy: `frontend/src/components/v2/dashboard/RecruitmentTeamTable.tsx` | direct | approximate | S |
| Kolumna „Rola" | `team_table.rows[].role` z `User.role`. ⚠️ pojedyncze pole, nie `roles[]` — `competitions.py:253-256` czyta OBA | direct | approximate | S |
| Plakietki ostrzeżeń | **BRAK KOLUMNY** (§3a) | impossible | — | M |
| Eksport CSV/XLS | z tego, co już wisi w stanie komponentu | derivable | identical | S |
| Drag&drop sekcji | czysto przeglądarkowe | derivable | identical | M |
| Wykres „Progress Zespołu" | `data.trend.months[]` (`backend/app/services/recruitment_trend.py:107-160`), komponent `RecruitmentTrendChart.tsx`. ⚠️ okno to **12 miesięcy kroczących**, nie rok kalendarzowy | direct | approximate | S |
| Wykres „Efektywność Lejka" | arytmetyka na `trend.months[]`. **Nie przycinać osi** — `None` renderować jako lukę, nie zero | derivable | approximate | S |
| Time-to-hire per rekruter (**nowe, DR tego nie miał**) | `candidate_stages.moved_at` per para. ⚠️ **NIE UŻYWAĆ** `/api/reports/time-to-hire` — `backend/app/api/phase3.py:428` bierze `start = items[0].moved_at`, a `items` filtruje `moved_at >= since` (phase3.py:407-419) → **każdy proces zaczęty przed oknem ma ucięty i zaniżony czas** | needs_code | approximate | M |
| Kolumna „akceptacje" + konwersje interview→acceptance→placement | **pole wraca, ale będzie ~0** — żaden stan Traffita nie mapuje się na `acceptance`, `client_interview`, `negotiation`, `onboarding`, `prep_call` (`mappers.py:405-449`) | **impossible (de facto)** | different | S |

### 2.2 Rekrutacja — LinkedIn i Power Calling

| Widget DR | Źródło NEXUS | Wykon. | Wierność | Nakład |
|---|---|---|---|---|
| LinkedIn 4 kafle | `data.linkedin` (`dashboard_v2.py:1894-1917`) ← `backend/app/api/linkedin_metrics.py:217-278` nad `linkedin_daily_metrics`. **Natywne, nie dr_***, ale dalej RĘCZNIE WPISYWANE | needs_process_change | approximate | M |
| LinkedIn tabela 7 kolumn | `data.linkedin.per_user[]` (`linkedin_metrics.py:250-263`) — 6 z 7 kolumn wprost; brak mianownika MD | needs_process_change | approximate | M |
| „CV/MD" target 5 | `days_reported = COUNT(wierszy)` (`linkedin_metrics.py:222`), **nie dni robocze** → nagradza NIEwpisywanie. Target konfigurowalny przez `kpi_role_defaults`/`user_kpi_targets` (`backend/app/models/kpi_target.py:32,55`) | needs_process_change | **PROXY** | M |
| Power Calling — lista poniżej progu | `GET /api/reports/power-calling` (`backend/app/api/reports.py:1875-2005`) — istnieje, ale mierzy co innego: definicja weryfikacji = `new+screening+prep_call` (reports.py:1901), atrybucja po **surowym `moved_by`**, mianownik **`POWER_CALLING_WORKDAYS=5` na sztywno** (reports.py:1854-1855) | direct | **PROXY** | M |
| Power Calling — wiersze „Brak danych" | brak: zapytanie robi JOIN do `candidate_stages` (reports.py:1907-1918), więc osoba bez ruchów **nie ma wiersza** — czyli najważniejszy wiersz raportu jest niewidoczny. Fix: LEFT JOIN od `users`, wzorzec `kpi_team.py:220-232` | derivable | approximate | S |

### 2.3 Gamifikacja

| Widget DR | Źródło NEXUS | Wykon. | Wierność | Nakład |
|---|---|---|---|---|
| Liga — podium top-3 | `GET /api/competitions/current?type=quarterly_champions_recruiter` (`backend/app/api/competitions.py:36-138` → `backend/app/services/competitions.py:449,223`); też jako `data.quarterly_league`. Renderer: `frontend/src/components/v2/dashboard/RecruitmentCompetitions.tsx` | **needs_code** ⬇️ *zdegradowane* | **PROXY** | M |
| Liga — pełny ranking 4+ | ⚠️ `full_ranking` **NIE JEST pełny**: `limit=10` (`competitions.py:461`, cięcie `:316`) + **twardy filtr** `if placements < min_placements: continue` (`competitions.py:292`, `QUARTERLY_MIN_PLACEMENTS=3` `:48`). DR nigdy nie filtrował — miał flagę `isQualified`. Pole `qualified` istnieje w schemacie (`backend/app/schemas/dashboard_v2.py:392`) i **nigdy nie jest zapisywane** (`competitions.py:300-312`) | **needs_code** | **PROXY** | M |
| Liga — countdown + pasek | `days_left_in_quarter` (`competitions.py:323-332`) — ale **nieparametryzowane okresem**; `/current` przyjmuje `period` dla rankingu i **ignoruje go** dla countdownu (`api/competitions.py:93`). Drugie, **niezgodne o 1 dzień** wyliczenie: `dynareporter_rekrutacja.py:158-173` | needs_code | approximate | S |
| Liga — nagrody 5000/3000/2000 | `QUARTERLY_PRIZES_PLN` (`competitions.py:50`), pole `prize_pln` w payloadzie | direct | identical | S |
| Liga — panel „System punktowy" + edycja | `POINTS_FORMULA` = **stałe w kodzie 150/15/5** (`competitions.py:56-63`), **bez składnika za weryfikacje**. Brak jakiegokolwiek natywnego store'u konfiguracji | **impossible bez nowej tabeli** | different | M |
| Liga — warunek udziału (ramp 1/2/3) | do dopisania w `_rank_recruiters_by_points`; wzorzec obok: `monthly_most_recommendations` liczy `qualified` jako KOLUMNĘ, nie filtr (`competitions.py:498-520`) | needs_code | approximate | S |
| Wyścig Rekomendacji | `GET /api/competitions/monthly-races` → `monthly_most_recommendations` (`competitions.py:465`) | **needs_code** | **PROXY** | M |
| Wyścig — „X.X/dzień" | **niewykonalne jako rate** — brak `days_worked`. Wykonalne jako progres bezwzględny: `extras.verifications / extras.required_verifications` gdzie `required = 4 × business_days_elapsed_in_month` (`competitions.py:470-472,583-615`) | partial | **PROXY** | S |
| Wyścig — precision ≥75% | `extras.precision_pct` (`competitions.py:495-505,552-580`). ⚠️ **brak bramki `2026-04`** — NEXUS stosuje regułę do KAŻDEGO miesiąca wstecz; port DR ją zachował (`dynareporter_rekrutacja.py:853-856,916,971-973`). ⚠️ przy `verified=0` warunek `100*cv_sent >= 75*0` → **PRZECHODZI**, a wyświetla się „0%" | needs_code | different | S |
| Wykluczenie lidera kwartalnego | ⚠️ `compose_monthly_races` wyklucza go **w KAŻDYM miesiącu** (`competitions.py:686`), DR tylko w ostatnim | needs_code | different | S |
| Wyścig Placementów | `monthly_most_placements` (`competitions.py:621` → `:160`, `min_value=2`, `limit=10`) | needs_code | PROXY | S |
| Hall of Fame | `competition_winners` + `data.hall_of_fame` (`dashboard_v2.py:1833-1893`), autofreeze `backend/app/tasks/competition_autofreeze.py` | direct | identical | S |

### 2.4 Delivery Lead / Body Leasing

| Widget DR | Źródło NEXUS | Wykon. | Wierność | Nakład |
|---|---|---|---|---|
| Ranking DL (requests/vacancies/placements/hit/fill) | `GET /api/reports/delivery-leads` (`backend/app/api/reports.py:870-892` → `_compute_dl_metrics`). Wakaty = `Job.headcount − hired` dla jobów `draft|published` typu `body_leasing` | direct | approximate | S |
| Trend 6 mies. per DL | ⚠️ `GET /api/reports/delivery-leads/{id}/trend` (`reports.py:895-945`) — **ZEPSUTY**. Woła `_compute_dl_metrics(period_start=month_start)` **bez górnej granicy**; kod liczący `month_end` jest napisany i **wyrzucony** (`reports.py:911-915` — dwa `datetime(...)` bez przypisania). Każdy „miesiąc" to skumulowany ogon do dziś → wykres z definicji malejący | **needs_code (naprawa)** | **BROKEN** | M |
| Historia zespołu | agregat po `_compute_dl_metrics` per miesiąc — po naprawie wyżej | derivable | approximate | S |
| Widok DL „mój portfel" | ⚠️ `GET /api/reports/my-delivery-lead` zwraca **410 Gone** (`reports.py:947-970`) → następca: `GET /api/dashboard/v2/delivery-lead` (`backend/app/api/dashboard_v2.py:141`) | direct | approximate | S |
| Przypisanie DL ↔ klient | `DeliveryLeadClientAssignment` (`backend/app/models/team_structure.py:102-122`, `is_head`) — natywne, nie dr_* | direct | identical | S |
| Liga DL | `?type=quarterly_champions_dl` — **nie ma jej w composicie** `recruitment-stats`, trzeba osobnego wywołania | direct | PROXY | S |
| Kafle body-leasing summary | zero odpowiednika w dr_*; do policzenia z `analytics_first_milestones` + `jobs.recruitment_type='body_leasing'` | needs_code | PROXY | M |

### 2.5 Klienci / MRR

| Widget DR | Źródło NEXUS | Wykon. | Wierność | Nakład |
|---|---|---|---|---|
| Tabela MRR per klient × miesiąc | `GET /api/admin/clients-overview` (`backend/app/api/admin_clients_overview.py`, `frontend/src/lib/api/dlPortal.ts:508`) — **to jest jedyny działający zamiennik i on już działa** (158 klientów, revenue lifetime, active PLN, marża/mc, MSA) | direct | approximate | S |
| „Suma MRR (12 mc)" / „Aktywnych klientów" | agregat z powyższego | derivable | approximate | S |
| Hit ratio per klient | `GET /api/reports/clients` + `/clients/at-risk` + `/clients/{id}/trend` (`reports.py:1252,1302,1369`) — mianownik `Job.status=closed` po `closed_at` | direct | approximate | S |
| Placementy per klient (donut) | **NEXUS jest tu STRUKTURALNIE LEPSZY** niż DR: `credited hired JOIN jobs j ON j.id = c.job_id GROUP BY j.client_id`; `jobs.client_id` jest NOT NULL od migracji 0120 (`backend/app/models/job.py:190-194`). Ręczna atrybucja `placement_details` i plakietka rozjazdu przestają być potrzebne. Wzorzec JOIN-a: `reports.py:275-291` | needs_code | **identical** | M |
| MRR/marża per DL | `GET /api/admin/clients-overview/by-dl` (`dlPortal.ts:509`) | direct | approximate | S |

### 2.6 Zarząd / Rada

| Pole DR (`dr_board_monthly_report`) | Źródło NEXUS | Wykon. | Wierność | Nakład |
|---|---|---|---|---|
| `placements` | `analytics_first_milestones stage='hired'`. ⚠️ **NIE** dzisiejsze `/api/reports/board` — `reports.py:1531-1539` liczy KAŻDY wiersz `candidate_stages.hired` (trzecia definicja placementu w aplikacji) | needs_code | approximate | S |
| `active_consultants` | `summarize_active_contracts(...)` na `contracts` (`reports.py:1580,1691`) | direct | approximate | S |
| `departures` | **BRAK DEFINICJI** — kandydaci: `contracts.end_date` minęło / `terminated_at` / przejście statusu na `ended`. Do rozstrzygnięcia jedną regułą | needs_code | PROXY | M |
| `revenue`, `consultant_costs`, `other_costs`, `margin`, `avg_margin_per_hour` | ⚠️ Dzisiejsze `/api/reports/board` liczy je z **KOLUMN CACHE'U** `Contract.rate_client`/`rate_candidate` (`reports.py:103,113` w `_fold_finance_pln`). CLAUDE.md mówi wprost: prawdziwa stawka idzie z **harmonogramów** (`candidate_rate_schedule` / `client_rate_schedule` / `framework_rate_schedule`) przez `app.api.contracts._effective_rate_fields`. Drugie, niezależne źródło realnych pieniędzy: `finance_monthly_results` (`backend/app/models/finance.py:172-212`: `cost_rate_md, md_count, compensation, revenue_rate_md, invoice_amount, margin_pln`) + `finance_import_runs` z `status='current'` per miesiąc | **needs_code** | **BROKEN dziś** | L |
| `hit_ratio` | ⚠️ Dzisiejsze `avg_hit_ratio = placements_ytd / COUNT(jobs utworzonych YTD)` (`reports.py:1607`) — mianownik to WSZYSTKIE joby, nie zapytania body-leasingowe. Poprawnie: `overall.avg_hit_ratio` z `_compute_dl_metrics` | needs_code | BROKEN dziś | S |
| Rozbicie placementów per klient × miesiąc (`dr_board_placement_clients`) | jak §2.5 (`credited hired JOIN jobs.client_id`) | needs_code | identical | M |
| Dywersyfikacja placementów | agregat z powyższego (HHI / udział top-klienta) | derivable | approximate | S |
| Kolumna „Ocena" (Lepiej/Gorzej) | delta MoM na powyższych | derivable | identical | S |
| „top_dl" | ⚠️ dziś `User z największą liczbą hired po moved_by` (`reports.py:1587-1602`) — **to nie jest Delivery Lead, tylko ktokolwiek kliknął**. Poprawnie: `_compute_dl_metrics` | needs_code | BROKEN dziś | S |
| Ostrzeżenie „Brak kursu NBP dla EUR" | `rates_to_pln` + `_fold_finance_pln` (`reports.py:84-123`) — brak kursu ⇒ **kwota WYPADA z sumy**, nie zeruje się. Banner: `reports.py:1704-1714`. Naprawa: `POST /api/fx/refresh` | direct | identical | S |

### 2.7 Instrument uczciwości (bez odpowiednika w DR — konieczny)

`GET /api/admin/process-adoption` (`backend/app/api/admin_process_adoption.py:88-190`, zamontowany `backend/app/main.py:857`) — ruchy per etap × `external_source`, miesięcznie, oraz kaskada `credited → credited_with_user → credited_active_user` liczona **tym samym CTE co kafle**. Jedyne narzędzie, które mierzy różnicę „lejek firmy" vs „lejek przypisany". Dziś schowane za guardem admina i nikt na nie nie patrzy.

---

## 3. Czego NEXUS nie ma

### (a) Nie ma modelu danych w ogóle

| Rzecz | Dowód | Co musiałoby się zmienić | Co zależy |
|---|---|---|---|
| **Dni robocze / nieobecności per osoba** | `days_worked` istnieje wyłącznie w `backend/app/models/dr_kpi_body_leasing.py:61` i `dr_kpi_sales`. `User` nie ma dat zatrudnienia, nie ma tabeli urlopów | nowa tabela + wejście danych z HR, albo integracja z systemem kadrowym | Power Calling („X wer./dzień"), plakietka „4/dzień" w wyścigu, kafel i pasek „CV/MD target 5" — **trzy raporty** |
| **Plakietki ostrzeżeń** (`warning_banner`, `warning_banners[]`, `warning_banner_note`) | `grep -rn warning_banner backend/` = **0 trafień** | nowa tabela + panel admina + polityka kto kogo oznacza + ocena RODO/prawa pracy (sekcja jest org-wide, `dashboard_v2.py:177-186`) | plakietki w tabeli performance i w wyścigach |
| **Seniority / ścieżka awansu** (`seniority_level`, `acceleration_start_date`, `senior_since`, `expert_since`) | `grep -rn seniority_level backend/` trafia **wyłącznie** w `backend/app/models/dr_user_seniority.py:27` i w zapytania `dynareporter_rekrutacja.py` | nowa natywna tabela kadrowa + panel admina, albo świadome zachowanie `dr_user_seniority` jako jedynego wyjątku | cała sekcja Acceleration Path (2 tabele + badge + liczniki) |
| **Konfiguracja punktacji Ligi** | `POINTS_FORMULA` = stałe 150/15/5 w `backend/app/services/competitions.py:56-63`; brak `system_config` w natywnym kodzie | nowa tabela klucz-wartość (albo reużycie `app_setting`) + wpięcie w `_rank_recruiters_by_points` | panel „System punktowy" + zmiana wag bez deployu |
| **`departures` (odejścia konsultantów)** | pola nie ma nigdzie; `dr_board_monthly_report.departures` to import | rozstrzygnięcie definicji (`end_date` minęło / `terminated_at` / przejście statusu) | kafel Zarządu |
| **„Requests" jako pojęcie** | `kpi_body_leasing.requests` był liczbą wpisaną w Excelu; w NEXUSIE nie ma bytu „zapotrzebowanie" | decyzja: `jobs` czy `client_orders` czy nowy model | kafel Rekrutacji |

### (b) Model istnieje, ale jest pusty, bo nikt nie pracuje w NEXUSIE

| Rzecz | Dowód | Konsekwencja |
|---|---|---|
| **Etapy `acceptance`, `client_interview`, `negotiation`, `onboarding`, `prep_call`** | `backend/app/services/traffit/mappers.py:405-449` — **żaden** stan Traffita nie mapuje się na te 5 etapów. ~cała historia to import | kolumna „akceptacje" i konwersje `interview→acceptance→placement` wyrenderują się jako 0-kilka i **przeczytają się jako „klienci nas nie akceptują"**, a znaczą „nie odnotowujemy akceptacji". W Lidze Mistrzów `competitions.py:283-284` punktuje `client_interview` → **składnik „interview" w punktacji jest w praktyce ZAWSZE ZERO**, a ranking sprowadza się do `150×placementy + 5×rekomendacje` |
| **`candidate_source_events`** | `SourcesFunnelSection` woła `GET /api/reports/sources` (`backend/app/api/candidate_sources.py:131`) i na prodzie renderuje „Brak danych dla wybranego okresu" | zakładka „Źródła kandydatów" jest pusta z powodu braku danych, nie awarii |
| **SLA na etapach** | `SLAAlertsSection` → `/api/phase3/pipeline/overview-sla` (`backend/app/api/phase3.py:116`) — na prodzie „Alerty SLA (0)" z komunikatem, że żaden etap nie ma skonfigurowanego SLA | funkcja martwa: albo skonfigurować progi, albo skasować sekcję |
| **`linkedin_daily_metrics`** | model natywny (`backend/app/models/linkedin_metric.py:32-66`), wejście ręczne (`POST /api/linkedin-metrics/batch`, `linkedin_metrics.py:151`) | jeśli nikt nie wpisuje, kafle pokażą **zera, nie „brak danych"** |
| **`Contract.job_id`** | pusty w całej bazie (memory `consultants-table-job-id-empty-on-prod`) | placementów **nie da się** wiązać z rekrutacją przez kontrakty — tylko przez `candidate_stages.job_id` |
| **Linki aplikacyjne** | prod: 1 link, 0 aplikacji | `InviteLinksSection` nie ma czego pokazać |

### (c) Model i dane są, ale atrybucja jest zepsuta → liczby będą ułamkiem prawdy

| Rzecz | Dowód | Co musi się zmienić |
|---|---|---|
| **`credit_user_id = NULL` i `kpi_eligible = FALSE` na praktycznie wszystkich `recruitment_processes`** (`origin_kind='external_observed'`) | zmierzone na prodzie w oknie 14 miesięcy | Częściowo już naprawione: `backend/app/services/kpi_panel.py:209,224` od 2026-08-13 (#1153) czyta `(cp.kpi_eligible IS TRUE OR cp.origin_kind::text = 'external_observed')`, a gałąź `classified_fallback` (`:212-226`) kredytuje `candidate_stages.moved_by`. **Ale nikt tego nie przemierzył po zmianie** — poprzedni pomiar (4-92%, zjazd do ~4%) jest sprzed poprawki |
| **`moved_by = NULL` dla nieodwzorowanych operatorów Traffita** | `backend/app/services/traffit/importer.py:1389-1418` — mapowanie po e-mailu, „Brakujące (no email match) są pomijane"; `mappers.py:844-855` zostawia `moved_by: None` | każdy taki kamień milowy wypada z kolumny per osoba do skalara `totals.unattributed` (`kpi_team.py:200-203`), a `unattributed` jest **jedną liczbą na wszystkie etapy** — nie da się odzyskać per etap |
| **Suma wierszy tabeli < kafel** | `kpi_team.py:194-204` vs `dashboard_v2.py:1747` | trzeba **wyrenderować `totals.unattributed`** (dziś tylko stopka pod tabelą, `RecruitmentTeamTable.tsx:314-317`), inaczej tabela wygląda na zepsutą |
| **`is_active` w konkursach vs tabela zespołu** | `competitions.py:255-256` wymaga `u.is_active IS TRUE`; importer zakłada konta operatorów Traffita jako `is_active=false` (`importer.py:1425-1431`); `kpi_team.py:243-263` **świadomie wraca** nieaktywnych z aktywnością | podium i tabela na tym samym ekranie **nie sumują się do siebie** |
| **Role zdryfowane przez AAD** | `backend/app/api/dynareporter_rekrutacja.py:80-89` — komentarz mówi wprost, że AAD nadał role dziesiątkom kont ATS, a część realnych rekruterek trzyma dorobek na koncie z rolą `user` | pula bazowa `u.role IN (sourcer,tac,recruiter)` (`kpi_panel.py:44-49`, `competitions.py:180-186`) wpuszcza widma z zerami i wycina realne osoby |
| **0,5% ruchów natywnych** (144 z 31 572 w 90 dni) | pomiar prod | **NIE oznacza**, że liczby lejka będą zerowe — `moved_at` i `moved_by` importowanych wierszy są wierne. **Oznacza**, że każde „kto to zrobił" to naprawdę „kto to zrobił w Traffcie" |

---

## 4. Ryzyka i pułapki

**R1. Sklejenie historii DR z nową podstawą na jednym wykresie.** `dr_kpi_body_leasing` nie ma writera (`dynareporter_upload.py:65-70` → 410; `dynareporter_kpi_body_leasing.py:6-8`), ostatni tydzień to 21/2026. Nowa podstawa to `candidate_stages`. **Koszt zignorowania:** uskok w danych zostanie odczytany jako załamanie wyników zespołu, a będzie zmianą definicji. → Dwa osobne wykresy z jawną datą cięcia albo wyłącznie nowa podstawa + archiwum DR jako oznaczony widok read-only.

**R2. Trzy definicje „weryfikacji" i trzy „placementu" w jednej aplikacji.**
- weryfikacja: `verified` (credited CTE) / `new+screening` (`reports.py:1531-1539`, board) / `new+screening+prep_call` (`reports.py:1901`, power-calling)
- placement: pierwsze `hired` per proces (`kpi_panel.py:155-166`) / pierwsze `hired` per para kandydat×oferta (`analytics_first_milestones`) / **każdy wiersz** `hired` (`reports.py:1532`, `reports.py:1080-1098`)
**Koszt:** ten sam ekran pokaże trzy różne prawdy i nikt nie będzie umiał powiedzieć, która jest firmowa. → Jedna definicja na całą stronę, wpisana do CLAUDE.md.

**R3. `/api/reports/recruitment` ma klucz cache'u bez okna.** `cache_key = f"reports:recruitment:{period}:{recruitment_type}"` (`reports.py:211`; ten sam kształt `reports.py:883`). Dodanie `date_from/date_to` bez zmiany klucza **poda liczby jednego okna pod etykietą drugiego**. Do tego jego okres to kroczące `_period_start` w **UTC bez górnej granicy** (`reports.py:138-149,244,281`), a `dashboard_v2` używa półotwartego `[start,end)` w Warsaw. **Koszt:** pod jedną etykietą „Miesiąc" na jednym ekranie stoją dwa różne okna.

**R4. Trend DL jest zepsuty i wygląda wiarygodnie.** `reports.py:895-945` liczy każdy „miesiąc" jako skumulowany ogon do dziś (górna granica policzona i wyrzucona, `reports.py:911-915`). **Koszt:** monotonicznie malejący wykres, który zostanie odczytany jako spadek wydajności DL.

**R5. Board liczy pieniądze ze STALE kolumn.** `_fold_finance_pln` (`reports.py:84-123`) czyta `c.rate_client` / `c.rate_candidate` — wartość zapisaną przy ostatnim ZAPISIE kontraktu. Stawka progresywna i aneks z datą, która już nadeszła, dają starą kwotę. Profil klienta liczy poprawnie, z harmonogramów. **Koszt:** dwie różne liczby dla tych samych pieniędzy w tej samej aplikacji, przy czym ta na dashboardzie zarządu jest zła.

**R6. Brak kursu NBP kasuje pieniądze po cichu.** `_fold_finance_pln` przy braku kursu robi `continue` — kwota **wypada z sumy** (`reports.py:105-120`). Banner jest (`reports.py:1704-1714`), ale kafel obok pokazuje pewną liczbę. **Koszt:** MRR zaniżony o nieznaną kwotę, bez oznaczenia na samym kaflu. → `POST /api/fx/refresh` + degradacja kafla, nie tylko baner.

**R7. Fałszywe metryki Zarządu.** `tender_win_rate` = tender-joby zamknięte z `priority IN (high, urgent)` (`reports.py:1621-1626`) — to nie jest wygrany przetarg, to proxy, stąd 0%. `avg_hit_ratio` = `placements_ytd / COUNT(wszystkich jobów YTD)` (`reports.py:1607`) — stąd 5,2%. `top_dl` = ktokolwiek najczęściej klikał `hired` (`reports.py:1587-1602`). **Koszt:** trzy liczby na dashboardzie rady, które nie znaczą tego, co mówi ich etykieta.

**R8. Strukturalnie nieobecne etapy renderują się jako pewne zera.** `acceptance`, `client_interview`, `negotiation`, `onboarding`, `prep_call` — zero mapowań z Traffita. Do tego mapper **cicho degraduje** nieznane typy stanów do `screening` (`mappers.py:454-458`) — te ruchy znikają z lejka bez śladu. **Koszt:** „klienci nas nie akceptują" zamiast „nie odnotowujemy akceptacji"; martwy składnik punktacji w Lidze przy nagrodach 5000/3000/2000 PLN.

**R9. `ANALYTICS_V1_MODE=off`.** `/api/analytics/v1/*` → 503 (`backend/app/api/analytics_v1.py:72-75`, `backend/app/core/config.py:523`). **Nie dotyczy** `/api/dashboard/v2/*` ani `/api/competitions/*` — te są zamontowane bezwarunkowo (`main.py:1153`, `main.py:1190-1192`, a `main.py:339` jawnie wyłącza `/api/competitions` ze ścieżki deprecacji). **Koszt zignorowania:** planowanie na `analytics_v1` = planowanie na 503.

**R10. `DYNAREPORTER_MODE=read_only`.** `backend/app/core/config.py:528` + middleware `backend/app/main.py:418-440` → 409 `DYNAREPORTER_READ_ONLY` na każdej mutacji dr_*. **Koszt:** panel „System punktowy" i edycja nagród w dr_ to eksponaty muzealne — zmiana tam nic nie robi w natywnym silniku, który i tak ich nie czyta (**split-brain: dwie strony pokazują różne punkty za ten sam kwartał**).

**R11. Awaria renderowana jako pustka.** Reguła repo (memory `failure-must-not-render-as-empty`, `empty-state-must-hang-on-issuccess`): kolejność gałęzi to `isError → !isSuccess → puste`. W przerwie między ponowieniami react-query ma `isLoading=false, isError=false, data=[]`. **Koszt:** „brak danych" tam, gdzie backend padł. Dotyczy KAŻDEGO widgetu tej strony.

**R12. RBAC i 403 czytane jako utrata danych.** `GET /api/dashboard/v2/recruitment-stats` ma guard `OperationalUser` (`dashboard_v2.py:174`) — legacy `user` dostaje **403**, a DR używał `authenticateAny`. `finance` **PRZECHODZI** (decyzja 19.08, docstring `dashboard_v2.py:186-192` ostrzega wprost, żeby nie robić bramki węższej na froncie niż w API). `/api/reports/board` = `FinanceReadUser`. `/api/reports/delivery-leads` = **tylko admin + head_of_recruitment** — sam DL tego nie dostaje. **Koszt:** albo pusty ekran zamiast komunikatu „brak dostępu", albo split-brain front/backend.

**R13. Brak client-scope'u dla DL.** Źródła rekrutacyjne są org-wide **z założenia** (`backend/app/services/dashboard_v2_sources.py:474-489`: „Dane są org-wide by design … adaptery nie przyjmują scope'u"). Delivery Lead otwierający /insights zobaczy całą firmę. **Koszt:** albo świadoma decyzja, albo wyciek portfela poza opiekuna.

**R14. Redakcja finansowa.** Przychód/marża Zarządu, MRR klientów, kwoty nagród, stawki konsultantów i stawki MD — wszystko na zakładkach widocznych szerzej niż finance/admin. Konwencja repo: renderować `—` (`formatPLN(null)`), nie **ukrywać kolumny** (znikająca kolumna czyta się jak brak danych). **Koszt:** albo wyciek kwot, albo trzy puste kolumny bez wyjaśnienia.

**R15. Wydajność `VERIFIER_ANCHORED_CTE`.** `backend/app/services/kpi_panel.py:123-285` to najwolniejsze zapytanie w `/api/admin/process-adoption`, a composite `recruitment-stats` odpala je **wielokrotnie** (panel zespołu, liga, wyścigi) nad ~49k kandydatów i ~53k procesów — przy każdym wejściu i każdej zmianie okresu. „All-time" jest niedostępne jednym żądaniem: `MAX_CUSTOM_PERIOD_DAYS = 366` (`backend/app/analytics/periods.py:25,105-120`) — to **guardrail, nie bug**.

**R16. Kafle ligi i wyścigów IGNORUJĄ filtr okresu strony.** `load_quarterly_league` jest przypięta do bieżącego kwartału **z założenia** (`dashboard_v2_sources.py:491-499`: „ZAWSZE bieżący kwartał (reguła konkursu)"), `load_monthly_races` do bieżącego miesiąca (`:514-518`). **Koszt:** filtr obiecuje, że steruje stroną, a nie dociera do połowy kafli.

**R17. Zamrożone podium jest nieodwracalne.** Autofreeze (`backend/app/tasks/competition_autofreeze.py`, `main.py:605`) zapisuje zwycięzców write-once (`competitions.py:826-843` loguje no-op przy ponownym freeze). **Koszt:** jeśli kwartał zamknie się na zepsutej atrybucji, złe podium z kwotą nagrody zostaje w `competition_winners` **na stałe** i nie da się go naprawić ponownym freeze'em.

**R18. `slowapi` + `from __future__ import annotations`.** Moduł z `@limiter.limit` nie może mieć tego importu (PEP 563 + slowapi #579 → body ląduje jako parametr Query, 422 na poprawnym żądaniu). Dotyczy każdego nowego routera z limiterem.

---

## 5. Plan działania

### 5.0 Co ginie z dzisiejszego /insights — plik po pliku

| Plik | Źródło danych dziś | Decyzja |
|---|---|---|
| `frontend/src/components/insights/InsightsView.tsx` | — | **PRZEPISAĆ** — nowe zakładki + slugi; zachować mechanikę `?tab=` z toastem 403 (jest poprawna) |
| `.../RekrutacjaPanel.tsx` | — | **PRZEPISAĆ** |
| `.../KlienciPanel.tsx` | — | **PRZEPISAĆ** (rozbić na Klienci/MRR + Delivery Lead) |
| `.../ZarzadPanel.tsx` | — | **PRZEPISAĆ** |
| `sections/_shared.tsx` | — | **PODNIEŚĆ** — helpery Card/Skeleton/error; dołożyć obowiązkową gałąź `isError` i stan „brak dostępu" |
| `sections/PeriodSelector.tsx` | — | **PRZEPISAĆ** — dziś zna tylko `today\|week\|month\|quarter` (`RekrutacjaPanel.tsx:20-24`), brakuje kotwicy historycznej i `custom` |
| `sections/ActivityHeatmap.tsx` | `/api/activities/leaderboard` | **SKASOWAĆ** — na prodzie 2 rekruterów po 1-2 akcje; zastępuje ją `team_table` |
| `sections/FunnelSection.tsx` | `/api/phase3/reports/funnel` | **SKASOWAĆ** — czwarta definicja lejka |
| `sections/TimeToHireSection.tsx` | `/api/phase3/reports/time-to-hire` | **PODNIEŚĆ SKORUPĘ, PRZEPISAĆ BACKEND** (`phase3.py:428` zaniża) |
| `sections/SLAAlertsSection.tsx` | `/api/phase3/pipeline/overview-sla` | **SKASOWAĆ** — 0 alertów, żaden etap nie ma SLA (chyba że Q: konfigurujemy SLA) |
| `sections/SourcesFunnelSection.tsx` | `/api/reports/sources` | **SKASOWAĆ z Rekrutacji** — „Brak danych"; endpoint zostaje |
| `sections/ClientsRanking.tsx` | `/api/admin/clients-overview` | **PODNIEŚĆ 1:1** — to jedyny działający zamiennik `dr_client_mrr` |
| `sections/DLRevenueLeaderboard.tsx` | `/api/admin/clients-overview/by-dl` | **PODNIEŚĆ 1:1** → zakładka Delivery Lead |
| `sections/ClientsHitRatio.tsx` | `/api/reports/clients` + `/clients/at-risk` | **PODNIEŚĆ 1:1** |
| `sections/HiringManagersSection.tsx` | `/api/reports/hiring-managers` | **PODNIEŚĆ** (nie ma odpowiednika w DR — czysty zysk) |
| `sections/ChampionsSection.tsx` | `/api/competitions/current?type=…_dl` i `…_recruiter` | **PODNIEŚĆ** — już pokazuje realne nazwiska, punkty i kwoty; wzbogacić o `qualified` i pełny ranking |
| `sections/BoardKPI.tsx` | `/api/reports/board` | **PRZEPISAĆ** — podnieść wyłącznie wzorzec bannera FX; liczby przeliczyć (R5/R7) |
| `sections/InviteLinksSection.tsx` | `/api/reports/invite-links` | **PODNIEŚĆ do Rekrutacji** jako kanał źródeł (1 link / 0 aplikacji — musi mieć uczciwy pusty stan) |
| `sections/TendersSection.tsx` | `/api/reports/tenders` | **SKASOWAĆ, bez następcy** (Przetargi poza zakresem) |
| `sections/SalesOverview.tsx` | `/api/reports/sales` | **SKASOWAĆ, bez następcy** (Sales poza zakresem) |
| `sections/__tests__/` | — | przepisać razem z komponentami |

Endpointy, które po tych kasacjach zostają bez konsumenta w /insights (nie kasować backendu w tym samym PR): `/api/reports/tenders`, `/api/reports/sales`, `/api/phase3/reports/funnel`, `/api/phase3/pipeline/overview-sla`, `/api/activities/leaderboard`.

---

### Etap 0 — Fundament (przed jakimkolwiek widgetem)

**Cel:** jeden kontrakt okresu, jeden kontrakt pustki/awarii, jedna macierz RBAC, jeden świeży pomiar atrybucji. Bez tego każdy kolejny etap zbuduje własną, niezgodną wersję.

**Backend:**
- `backend/app/analytics/periods.py` — dodać kotwicę do `resolve_period(kind, anchor=…)`, żeby `week|month|quarter|year` adresowały **przeszły** okres bez objazdu przez `custom` (dziś `:120-150` zwraca wyłącznie bieżący). Zachować `MAX_CUSTOM_PERIOD_DAYS=366`.
- `backend/app/api/dashboard_v2.py:113-129` — `parse_dashboard_period` przyjmuje kotwicę.
- `backend/app/api/reports.py:138-149` — zdjąć `_period_start` (kroczące UTC, bez górnej granicy) i przestawić `/recruitment`, `/delivery-leads`, `/clients` na wspólny `Period`. **Klucz cache'u musi zawierać okno** (`reports.py:211` i `:883`).
- Wycofać z użycia `backend/app/api/dynareporter_rekrutacja.py:219-262` `_resolve_period_bounds` (inclusive end vs half-open → off-by-one-day).
- Nowy endpoint „tygodnie z danymi": `SELECT DISTINCT` po `analytics_first_milestones.first_reached_at` (NIE `dr_kpi_body_leasing`).
- **Decyzja do zapisania w kodzie:** „Tydzień" = poprzedni zamknięty (jak DR, `kpi.ts:38-42`) czy bieżący do dziś (jak `periods.py:126-129`). Rekomendacja: **poprzedni zamknięty** — w poniedziałek okno „bieżące" jest prawie puste.

**Frontend:**
- `frontend/src/lib/dashboard-presets.ts:9` — dodać `"custom"` do `DashboardPeriod`.
- `frontend/src/lib/dashboard-v2-api.ts:367-376` — `getRecruitmentStats` przekazuje `date_from`/`date_to` (dziś wysyła tylko `period`).
- Nowy `frontend/src/components/insights/PeriodPicker.tsx` — granularność + kotwica + etykieta okna („1–31.07.2026, Europe/Warsaw").
- `_shared.tsx`: wymuszony kontrakt `isError → !isSuccess → empty`, komponent `<NoAccess/>` dla 403, komponent `<Degraded/>` dla `quality != "complete"`.

**Migracje:** brak.

**Weryfikacja:**
```sql
-- 1) Świeży pomiar atrybucji PO poprawce #1153 (poprzedni jest nieaktualny):
SELECT date_trunc('month', first_reached_at) AS m, stage, count(*)
FROM analytics_first_milestones
WHERE first_reached_at >= now() - interval '12 months'
GROUP BY 1,2 ORDER BY 1,2;

-- 2) Ile ruchów jest natywnych, a ile z importu, per etap:
SELECT external_source, stage, count(*)
FROM candidate_stages
WHERE moved_at >= now() - interval '90 days'
GROUP BY 1,2 ORDER BY 2,1;

-- 3) Ile kamieni nie ma autora (to jest liczba, która zniknie z tabeli per osoba):
SELECT count(*) FROM candidate_stages
WHERE moved_at >= now() - interval '90 days' AND moved_by IS NULL;

-- 4) Czy import nie degradował stanów do 'screening' (podejrzenie z fazy `workflows`):
SELECT stage, count(*) FROM candidate_stages WHERE external_source='traffit' GROUP BY 1 ORDER BY 2 DESC;
```
Plus w przeglądarce: `GET /api/admin/process-adoption` (kaskada `credited → credited_with_user → credited_active_user`) — to jest liczba, którą trzeba znać, ZANIM ktokolwiek zobaczy nowy kafel.

**Rozmiar:** M.

---

### Etap 1 — Rekrutacja, warstwa org-level (pierwsza rzecz do wypuszczenia)

**Cel:** uczciwy lejek firmy, bez atrybucji imiennej. Działa niezależnie od odpowiedzi na §6 Q1.

**Backend:** nowy `backend/app/api/insights_recruitment.py` (bez `from __future__ import annotations`, jeśli dołożysz limiter — R18):
- `GET /api/insights/recruitment/funnel` — `analytics_first_milestones` per etap w oknie, **bez żadnego predykatu atrybucji** (wzorzec `reports.py:239-247`, ale **bez** `JOIN jobs`, który gubi kamienie na skasowanych ofertach).
- Zwraca też `conversions` liczone z tych samych liczników (`recruitment_trend.funnel_conversions`, `backend/app/services/recruitment_trend.py:168`) i `trend.months[]` (`recruitment_trend.py:107-160`).
- W kopercie: `coverage` = udział `external_source='manual'` + `unattributed`.

**Frontend:** `frontend/src/components/insights/sections/RecruitmentFunnel.tsx`, `RecruitmentTrend.tsx` (podnieść wykres z `frontend/src/components/v2/dashboard/RecruitmentTrendChart.tsx`), `FunnelConversions.tsx`.
- Etapy strukturalnie nieobecne (`acceptance`, `client_interview`, `negotiation`, `onboarding`, `prep_call`) **ukryte albo z etykietą „tylko ruchy wykonane w NEXUSIE" + licznik pokrycia** — nigdy jako gołe zero (R8).
- Oś konwersji **nie przycięta do 100%**; `None` = luka, nie zero.
- Stopka sekcji: „X% ruchów w tym oknie pochodzi z importu Traffit" z `/api/admin/process-adoption`.

**Migracje:** brak.

**Weryfikacja:** Chrome MCP na `/insights?tab=rekrutacja` — porównać kafle z surowym SQL-em z Etapu 0 pkt 1; ręcznie wywołać 500 (np. przez zły parametr) i sprawdzić, że renderuje się „Nie udało się wczytać" + „Ponów", **nie** „Brak danych".

**Rozmiar:** M. **To jest MVP — od tego momentu /insights ma wartość.**

---

### Etap 2 — Rekrutacja, warstwa imienna (tabela zespołu + LinkedIn)

**Status: ODBLOKOWANY decyzją D1** („wchodzimy w NEXUS"). Uwaga: dorobek historyczny nadal pochodzi z importu, więc `totals.unattributed` musi być renderowane obok sumy każdej kolumny od pierwszego dnia — inaczej tabela wygląda na zepsutą, a rosnąca adopcja będzie nie do odróżnienia od regresji.

**Backend:**
- Reużyć `GET /api/dashboard/v2/recruitment-stats → data.team_table` (`backend/app/services/dashboard_v2.py:1780-1813`, `backend/app/services/kpi_team.py:137-350`) — **bez przepisywania**.
- `backend/app/services/kpi_team.py` — rozbić `TeamTotals.unattributed` (dziś **jeden skalar na wszystkie etapy**, `:96-99,:200-208`) na słownik per etap. Bez tego nie da się ani opisać, ani skorygować kolumny.
- `backend/app/services/kpi_panel.py:44-49` — rozstrzygnąć raz `User.role` vs `User.roles[]` dla całej strony (wzorzec: `competitions.py:253-256` czyta oba).
- Time-to-hire: nowe zapytanie w `insights_recruitment.py`, start pary **bez ograniczenia oknem** (naprawia `phase3.py:428`), mediana + p90 + `n`; przy `n < 5` **nie renderować liczby**.

**Frontend:** podnieść `frontend/src/components/v2/dashboard/RecruitmentTeamTable.tsx`; **obowiązkowo wyrenderować `unattributed`** obok sumy kolumny (inaczej tabela wygląda na zepsutą, R z §3c). Eksport CSV/XLS z tego, co już jest w stanie komponentu; kolumnę „Punkty" liczyć **na froncie z kolumn tabeli**, nie zszywać z ligi po `user_id` (dwa różne rankingi, różne filtry `is_active`).

**Migracje:** brak.

**Weryfikacja:** suma kolumny + `unattributed` musi = liczba z Etapu 1 dla tego samego etapu i okna. Jeśli się nie zgadza — nie wypuszczać.

**Rozmiar:** M.

---

### Etap 3 — Gamifikacja (Liga, wyścigi, Hall of Fame)

**Status: ODBLOKOWANY decyzją D3** (naprawa formuły, bez retroaktywności). Migracja `insights_scoring_config` **jest w zakresie**. Nowa formuła obowiązuje od najbliższego niezamkniętego kwartału; `competition_winners` z zamkniętych kwartałów **nietykalne** (autofreeze jest write-once, `competitions.py:826-843`). Przed merge'em wypisać podium stare i nowe obok siebie.

**Backend — `backend/app/services/competitions.py`:**
1. `:292` — zamienić twardy `continue` na flagę `extras["qualified"]`; zdjąć `limit=10` (`:316,:461`) dla `full_ranking`, **zostawić** dla podium/freeze.
2. `:246-247` — `FROM credited JOIN users` → `FROM users LEFT JOIN credited`, żeby cała załoga była w rankingu z zerami (jak DR, `competitions.ts:107-129`).
3. `:48` — próg progresywny `monthInQuarter` (1/2/3) zamiast płaskiego 3.
4. `:686` — wykluczenie lidera kwartalnego **tylko w ostatnim miesiącu kwartału**.
5. `:499-502` i `:562` — naprawić inwersję precision przy `verified = 0` (dziś `100*cv_sent >= 75*0` → przechodzi, a wyświetla „0%”).
6. Dodać bramkę `PRECISION_RATE_ACTIVE_FROM = '2026-04'` (port z `dynareporter_rekrutacja.py:853-856,916,971-973`).
7. `:283-284` — **ROZSTRZYGNIĘTE (D3)**: przestawić na `interview`. `client_interview` nie ma żadnego mapowania z Traffita (`mappers.py:404-449`), więc dziś ten składnik jest zawsze zerowy.
8. `:323-332` — sparametryzować `days_left_in_quarter` wybranym kwartałem + `business_today()` zamiast `date.today()`; dodać `is_completed`/`is_upcoming` (port `competitions.ts:9-49`).
9. `:255-256` — uzgodnić `is_active` z `kpi_team.py:243-263` (albo obie strony pokazują byłych, albo żadna).
10. Jeśli wagi mają być konfigurowalne → **nowa tabela** (patrz Migracje).

**Frontend:** `ChampionsSection.tsx` → nowy `sections/League.tsx`; przepuścić `qualified` przez `RecruitmentCompetitions.tsx:22-34` i wyrenderować pomarańczowe „(brakuje placementu)".

**Migracje (tylko przy decyzji „wagi konfigurowalne"):** `insights_scoring_config` (klucz, wartość int 0..1000, `updated_by`, `updated_at`) **albo** reużycie `app_setting`. **Obowiązkowo lustro DDL w `backend/entrypoint.sh`** (prod alembic bywa orphaned) + wpis do `core_checks` w `/api/health/deep`.

**Weryfikacja:** `GET /api/competitions/current?type=quarterly_champions_recruiter&period=2026-Q1` musi zwrócić countdown = 0 dni / 100% (kwartał zamknięty) i ranking Q1, **nie** countdown bieżącego kwartału. Podium przed i po zmianie formuły — wypisać obok siebie i pokazać Arturowi PRZED merge'em.

**Rozmiar:** L.

---

### Etap 4 — Delivery Lead / Body Leasing

**Cel:** ranking DL i trend, które nie kłamią.

**Backend — `backend/app/api/reports.py`:**
- `:895-945` — **naprawić trend**: przywrócić `month_end` (kod jest napisany i wyrzucony w `:911-915`) i przekazać go do `_compute_dl_metrics` jako górną granicę. To jest bug jednoliniowy w skutkach i wielomiesięczny w konsekwencjach.
- `:870-892` — rozszerzyć guard o `delivery_lead` **ze scope'em na własny portfel** (`DeliveryLeadClientAssignment`, `backend/app/models/team_structure.py:102-122`), albo świadomie zostawić admin+HoR i dać DL osobne `GET /api/dashboard/v2/delivery-lead`. **Nie zostawiać `/api/reports/my-delivery-lead`** — zwraca 410 (`reports.py:947-970`).
- Nowe: placementy per klient — `credited hired JOIN jobs j ON j.id = c.job_id GROUP BY j.client_id` (wzorzec JOIN-a `reports.py:275-291`). **Nie używać** `/api/reports/clients` do donuta — tam placement = każdy wiersz `hired` i tylko dla jobów zamkniętych (`reports.py:1080-1098`).

**Frontend:** `sections/DLRanking.tsx` (nowy), `DLTrend.tsx` (nowy), podnieść `DLRevenueLeaderboard.tsx` 1:1. Tabela sortowana po nagłówku (jak DR). Kolumna akcji sticky (memory `clipped-actions-read-as-missing-feature`).

**Migracje:** brak.

**Weryfikacja:** trend 6-mies. dla jednego DL — suma miesięcy musi ≈ wartość za pół roku, a wykres **nie może** być monotonicznie malejący. SQL kontrolny:
```sql
SELECT date_trunc('month', cs.moved_at) m, count(*)
FROM candidate_stages cs JOIN jobs j ON j.id = cs.job_id
WHERE cs.stage='hired' AND j.recruitment_type='body_leasing'
  AND cs.moved_at >= now() - interval '6 months'
GROUP BY 1 ORDER BY 1;
```

**Rozmiar:** M.

---

### Etap 5 — Klienci / MRR

**Cel:** zastąpić pustą `dr_client_mrr` tym, co już działa.

**Backend:** nic nowego dla rdzenia — `/api/admin/clients-overview` i `/by-dl` (`backend/app/api/admin_clients_overview.py`) wystarczą. Dołożyć wyłącznie serię miesięczną MRR (12 mc), jeśli ma być wykres.
⚠️ **Stawki muszą iść z harmonogramów**, nie z `contracts.rate_*` — reużyć `app.api.contracts._effective_rate_fields` i **`selectinload` trzech harmonogramów**, inaczej `MissingGreenlet` → 500 bez CORS (CLAUDE.md §Klienci).

**Frontend:** podnieść `ClientsRanking.tsx` i `ClientsHitRatio.tsx` 1:1; dodać kafle „Suma MRR (12 mc)" / „Aktywnych klientów" jako agregat z tej samej listy (kafel będący sumą innych liczb niż widoczne pod nim nie daje się zweryfikować wzrokiem).

**Migracje:** brak. **Weryfikacja:** suma kolumny „Marża/mc" = kafel MRR. **Rozmiar:** S.

---

### Etap 6 — Zarząd / Rada

**Cel:** dashboard rady na prawdziwych pieniądzach.

**Backend — nowy `backend/app/api/insights_board.py`** (nie rozbudowywać `reports.py:1512`):
- `placements` = `analytics_first_milestones stage='hired'` (jedna definicja, ta sama co Etap 1).
- `revenue`/`consultant_costs`/`margin`: **DWA źródła, jawnie rozdzielone** — (a) MRR bieżący z kontraktów **liczony z harmonogramów** przez `_effective_rate_fields` (naprawa R5), (b) zrealizowane z `finance_monthly_results` (`backend/app/models/finance.py:172-212`) dla runów `status='current'` (`finance_import_runs`). Nie mieszać w jednej kolumnie.
  ⚠️ `finance_monthly_results.consultant_name`/`client_name` to **wolny tekst bez FK** (`finance.py:192-194`) — dopasowanie po nazwie, z jawnym wierszem „niedopasowane".
- `hit_ratio` = `overall.avg_hit_ratio` z `_compute_dl_metrics`, **nie** `placements/COUNT(jobs)`.
- `top_dl` z `_compute_dl_metrics`, nie z `moved_by`.
- `departures` — po decyzji definicji.
- **Usunąć** blok tenders (poza zakresem).
- FX: zachować `rates_to_pln`/`_fold_finance_pln`, ale **zdegradować sam kafel** przy `board_fx_missing`, nie tylko pokazać baner (R6).
- Rozbicie placementów per klient × miesiąc + wskaźnik dywersyfikacji.

**Frontend:** `sections/BoardKPI.tsx` przepisany; `BoardTrends.tsx`; `BoardPlacementsByClient.tsx`; kolumna „Ocena" (delta MoM). Redakcja `VIEW_FINANCE` → `—`, nie ukrywanie kolumn (R14).

**Migracje:** brak (jeśli `departures` liczone, nie przechowywane).

**Weryfikacja:**
```sql
-- MRR z harmonogramów vs z kolumn cache'u — jeśli się różnią, board dziś kłamie:
SELECT count(*) FROM contracts c
WHERE c.status='active' AND c.start_date <= current_date
  AND (c.end_date IS NULL OR c.end_date >= current_date);
-- + porównać sumę z /api/admin/clients-overview (harmonogramy) z /api/reports/board (kolumny)
SELECT period_year, period_month, status, count(*) FROM finance_import_runs GROUP BY 1,2,3 ORDER BY 1,2;
```
`curl -fsSL https://api.nexus.dynaminds.pl/api/fx/... ` → jeśli banner EUR nadal jest: `POST /api/fx/refresh`.

**Rozmiar:** L.

---

### Etap 7 — Sprzątanie

- Skasować z frontendu: `TendersSection.tsx`, `SalesOverview.tsx`, `ActivityHeatmap.tsx`, `FunnelSection.tsx`, `SLAAlertsSection.tsx`, `SourcesFunnelSection.tsx` + ich testy.
- **NIE robić `DROP` na 58 tabelach `dr_*`** — memory `dr-tables-drop-classification` odradza wprost. Zostawić read-only (`DYNAREPORTER_MODE=read_only` już to wymusza) jako oznaczone archiwum z jawną datą cięcia (R1).
- Zaktualizować CLAUDE.md: jedna kanoniczna definicja placementu/weryfikacji/interview + data cutoveru serii.
- Rozważyć wycofanie routerów `dynareporter_*` bez następcy — osobny PR, po tym jak /insights zastąpi je w praktyce.

---

### Konwencje wdrożeniowe (obowiązują w każdym etapie ze zmianą schematu)

1. **Lustro DDL w `backend/entrypoint.sh`** (6068 linii) — prod alembic bywa orphaned; `CREATE TABLE` idzie do listy DDL, **nie** przez `Base.metadata.create_all` (tamten blok to jedna transakcja i potrafi paść w całości).
2. Nowa tabela **musi** trafić do `core_checks` w `/api/health/deep` — to jedyny dowód, że schemat jest na prodzie (`/alembic` nie wystarcza).
3. Głowa alembica **jedna**; przy równoległych PR-ach sprawdzić `alembic heads`.
4. Deploy: `git push origin main` → GH Actions → Coolify webhook → smoke test `/api/health` z `version` matchującym short SHA. Prod nadchodzi ~6 min po merge'u.
5. Zmienne środowiskowe na prodzie: **wyłącznie** workflow „Coolify set env" (`.github/workflows/coolify-set-env.yml`), `workflow_dispatch`. **Nie** `redeploy=true` przy zmiennych runtime (28 min przerwy 25.08).
6. Weryfikacja UI: Chrome MCP, realne klikanie + screenshot. Ekrany za loginem → harness `/preview/*` z **zasianym** cache react-query (niezasiany klucz → 401 → `/login`).
7. Wiele PR-ów naraz: `scripts/merge-train.sh`, nie ręczne klikanie.

---

## 6. Pytania do Artura

> **WSZYSTKIE ROZSTRZYGNIĘTE 2026-08-31 — patrz §0** (Q1-Q4 → D1-D4, Q5 → D5+D6, Q6 → D7). Poniżej zostawione wyłącznie jako uzasadnienie decyzji.

**Q1. Czy zespół zacznie przesuwać kandydatów w NEXUSIE?**
Dziś 0,5% ruchów jest natywnych (144 z 31 572 w 90 dni) — reszta to import z Traffita. `moved_at`/`moved_by` importu są wierne, więc lejek org-level będzie prawdziwy niezależnie od odpowiedzi. Ale **każde „kto to zrobił" znaczy „kto to zrobił w Traffcie"**, a operatorzy bez dopasowania po e-mailu wypadają całkowicie (`importer.py:1389-1418`).
- **A)** Tak, wchodzimy w NEXUS → budujemy Etapy 2 i 3 (tabela per osoba, ligi, wyścigi).
- **B)** Nie / nie wiem → **budujemy tylko Etap 1** (org-level), a atrybucję imienną, ligi i premie odkładamy.
- **Rekomendacja: B na teraz, A jako warunek odblokowania Etapów 2-3.** Ranking imienny na atrybucji Traffita będzie kwestionowany przy pierwszej wypłacie.

**Q2. Która definicja „placementu" jest firmowa?**
Trzy żyją w kodzie: pierwsze `hired` per **para kandydat×oferta** (`analytics_first_milestones`) / pierwsze `hired` per **próba procesu** (`kpi_panel.py:155-166`, sierpień 20 vs 12) / **każdy wiersz** `hired` (`reports.py:1532`). To samo dotyczy „weryfikacji" (3 definicje) i „interview" (zlepek weryfikacji technicznej z rozmową u klienta, `mappers.py:415-419`; `client_interview` bez żadnego mapowania).
- **Rekomendacja: pierwsze `hired` per para kandydat×oferta** — jedna liczba, zgadza się z rzędem wielkości (315/rok), nie liczy dwa razy przy ponownym otwarciu. „Interview" opisać w UI jako „rozmowy (weryfikacja techniczna + rozmowa u klienta)", bo rozdzielić się już nie da — informacja przepadła w mapperze.

**Q3. Liga Mistrzów i nagrody 5000/3000/2000 PLN — przeliczamy na nowej podstawie?**
Dziś: składnik „interview" punktuje `client_interview` (`competitions.py:283-284`), którego w historii importowanej **nie ma wcale** → ranking to `150×placementy + 5×rekomendacje`. Wagi są stałymi w kodzie (DR miał konfigurowalne 120/12/1/0). Próg to płaskie 3 od pierwszego dnia kwartału (DR: 1/2/3 wg miesiąca), a niezakwalifikowani **wypadają z listy** zamiast być oznaczeni. Zamrożeni zwycięzcy są nieodwracalni.
- **A)** Formuła bez zmian, tylko naprawiamy ranking (ramp, pełna lista, `qualified`).
- **B)** Formuła + składnik interview do rozstrzygnięcia + wagi konfigurowalne przez admina (nowa tabela).
- **Rekomendacja: B, ale bez retroaktywności** — nowa formuła obowiązuje od najbliższego niezamkniętego kwartału; zamrożonych podiów nie ruszamy.

**Q4. Premie — w zakresie czy wypadają z Salesem?**
`Premie.tsx:241,244` woła `/kpi/sales/bonuses`; role to `hod/bdm/sdr`, pozycje to projekty i leady z marżą. To jest moduł **sprzedażowy**, a nie premie rekrutacyjne.
- **A)** Poza zakresem razem z Sales (spójne z Twoją instrukcją).
- **B)** W zakresie → to jest zmiana **płacowa**, nie raportowa: liczby, na których wypłacamy premie, zmieniają podstawę.
- **Rekomendacja: A.**

**Q5. Czy NEXUS dostaje dane kadrowe?**
Bez nich wypadają **trzy raporty naraz**: Power Calling („X wer./dzień" — dziś dzieli przez sztywne 5 dni, więc **osoba na urlopie trafia na listę poniżej progu**, `reports.py:1854-1855`), plakietka „4/dzień" w wyścigu, kafel i pasek „CV/MD target 5". Osobno: Acceleration Path wymaga `seniority_level`/`acceleration_start_date`/`senior_since` (istnieją **tylko** w `dr_user_seniority`), a plakietki ostrzeżeń wymagają kolumny, której nigdzie nie ma (+ ocena RODO — to zapis o ocenie pracownika widoczny całemu zespołowi).
- **A)** HR karmi NEXUS dniami pracy/urlopami → wszystkie trzy wracają.
- **B)** Nie → **Power Calling nie wypuszczamy w ogóle** (nazywa ludzi po nazwisku na mianowniku, którego nie umiemy policzyć), wskaźniki „na dzień" pokazujemy jako liczby bezwzględne, Acceleration Path i plakietki ostrzeżeń wypadają.
- **Rekomendacja: B teraz.** Fałszywy alarm w raporcie, który wskazuje ludzi palcem, ma koszt osobowy, nie analityczny.

**Q6. Kto co widzi?**
Trzy niezależne rozstrzygnięcia: (a) **finance** przechodzi przez `OperationalUser` od 19.08, więc dziś ma dostęp do tabeli per osoba, podium i nazwisk — front węższy niż API odtwarza split-brain (`dashboard_v2.py:186-192` ostrzega wprost). (b) **Delivery Lead** — źródła rekrutacyjne są org-wide *z założenia* (`dashboard_v2_sources.py:474-489`), więc DL zobaczy całą firmę, chyba że dołożymy scope, którego dziś nie ma. (c) **Pieniądze** poniżej admina — `/api/reports/board` to `FinanceReadUser`, `/api/reports/delivery-leads` to admin+HoR (sam DL **nie dostaje** własnego rankingu).
- **Rekomendacja:** finance = jak recruiter (spójnie z decyzją 19.08, nie robić wyjątku dla /insights) · DL = **własny portfel** na zakładce Delivery, org-wide tylko na Rekrutacji z jawną etykietą „dane całej firmy" · kwoty = admin + finance, dla reszty `—` (nigdy ukryta kolumna) · każda zakładka bez uprawnień renderuje komunikat „brak dostępu", **nigdy pusty wykres**.