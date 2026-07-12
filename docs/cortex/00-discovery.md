# Cortex 00 — Discovery: warstwa „central intelligence" w NEXUS

> Rozpoznanie pod trzy widoki: (1) mapa technologiczna bazy (skill × seniority × dostępność),
> (2) mapa klient × technologia (kto gdzie siedzi na jakim stacku), (3) luki kompetencyjne
> (czego klienci chcieli, a czego nie dowieźliśmy). Zero kodu — tylko inwentaryzacja, oceny i plan.
>
> **Data:** 2026-07-12 · **Źródła:** kod backendu (modele SQLAlchemy, serwisy, API) + odczyty
> z produkcji przez zalogowaną sesję API (bez bezpośredniego SQL — patrz §5.1).
> **Metodologia liczb:** kandydaci = próbka losowa n=1200 z 53 430 (±3 p.p.) + dokładne totale
> z filtrów API; joby / kontrakty / klienci = **pełne tabele** (4023 / 475 / 157 rekordów).

---

## TL;DR (wersja brutalna)

1. **Paliwo jest w CV, nie w polach.** 93% kandydatów ma plik CV, ale strukturalne `skills` wypełnia **0,3%** bazy. Pełnotekst po CV znajduje 14 387 osób z Pythonem; pole `skills` — 178. Cała dzisiejsza „inteligencja" NEXUS-a działa na regexach po tekście, nie na danych.
2. **Oś „dostępność" nie istnieje.** `availability_status`: 53 430 / 53 430 = `unknown` (dokładnie 0 rekordów w innym stanie). Stawki oczekiwane (`expected_rate_hourly`): 0 rekordów. Macierz skill × seniority × dostępność ma dziś **jedną** działającą oś.
3. **„Czego klienci chcieli" = tytuł stanowiska.** Opisy i wymagania jobów: ~0% (Traffit ich nie oddał). `must_skills` wygląda na wypełnione (89,4%), ale w 100% wygenerowało je AI **z samego tytułu** — to pseudo-dane do zaudytowania, nie fakty.
4. **„Czego nie dowieźliśmy" — liczby są, powody nie.** 3747 zamkniętych rekrutacji, 573 obsadzone (hit-ratio 15,3%), 3174 przegrane — ale `close_reason`: **100% brak**. Analogicznie `termination_reason` kontraktów: 100% NULL. Wiemy ILE przegrywamy, nie wiemy DLACZEGO.
5. **Mapa klient × konsultant jest w zasięgu ręki.** 414 aktywnych kontraktów z FK do klienta i stawkami (89% wypełnień), 754 osoby „u klienta" wg szerszej definicji. Populacja jest mała (20 klientów kontraktowych) — jeden przebieg LLM po ich CV daje mapę stacków w tydzień.
6. **NEXUS ma chroniczny wzorzec: pole jest, procesu nie ma.** availability, close_reason, termination_reason, verified_tech, city, seniority jobów — wszystko istnieje w schemacie i świeci zerami. Kolejna tabela nic nie da bez zmiany workflow.

---

## 1. Inwentaryzacja

### 1.1 Encje i relacje (stan realny, nie teoretyczny)

```
Candidate (53 430) ──< CandidateStage (~175k wierszy, PEŁNA HISTORIA) >── Job (4 023)
     │                          │ rejection_reason_id → RejectionReasons (słownik)      │
     │                          │ screening_answers / scorecard JSONB                   │ client_id (FK, NOT NULL)
     ├──< Contract (475) ── client_id ──> Client (157)                                  │
     │        │ job_id: wypełnione 0,2% (!)                                             ▼
     │        └── stawki: schedule z historią (ContractCandidateRate/ClientRate)     Client
     ├──< Note / Activity / Call / LinkedinSnapshot (historie zdarzeń)
     └── embedding → Qdrant nexus_candidates (payload: tylko id+nazwisko+kategoria)

Skill (~100 kanonicznych) ─< SkillAlias (~280)   ← TAKSONOMIA BEZ ŻADNEGO FK z encji!
DynaReporter (dr_*)  ← RÓWNOLEGŁY świat ręcznych KPI z własną tabelą klientów (bez FK do core)
```

Kluczowe własności strukturalne:

- **Historia jest.** `candidate_stages` to append-owy audit trail (każdy ruch = nowy wiersz; ~175k wierszy: new 78 993, screening 34 127, cv_sent 19 656, rejected 24 919, **hired 965**). Do tego `activities`, `user_activities`, `rate_history`, snapshoty LinkedIn, schedule stawek kontraktowych z datami. Trend/retrospekcja są policzalne.
- **Taksonomia skilli istnieje, ale wisi w próżni.** Tabele `skills` + `skill_aliases` (~100 kanonicznych nazw z kategoriami: backend/cloud/…) służą wyłącznie scoringowi do normalizacji aliasów in-memory. Żadna encja nie ma FK do skilla.
- **Klient to porządny FK** (kontrakty i joby wiszą na `client_id`, od migracji 0120 NOT NULL na jobach). Nazwy klientów bywają zdublowane wariantami z Traffita (mechanizm `display_name`/`hidden` istnieje, wypełnienie ~0).

### 1.2 Kandydat — 53 430 rekordów (próbka n=1200, ±3 p.p.)

| Pole | Typ | Wypełnienie | Komentarz |
|---|---|---|---|
| email / phone | wolny tekst | **97,8% / 91,3%** | tożsamość OK; unique na email |
| **plik CV** (`cv_filename`/storage) | binarka w object storage | **93,4%** | główne aktywo bazy |
| `raw_cv_text` (`cv_parsed_at`) | tekst | **52,6%** | ekstrakcja tekstu przeszła przez ~połowę; OCR fallback od PR #661 |
| `cv_extracted_data.traffit_technologie` | free-text CSV | **~55%** (n=300) | np. „Tenable, Nessus, SIEM, WiZ…" — **gotowy półprodukt skilli, bez LLM** |
| `cv_extracted_data.traffit_experience/education` | free-text | ~86% | bufor z Traffita, nieznormalizowany |
| `experience` JSONB | JSONB lista | 48,3% | firmy/role — jakość różna (import) |
| `languages` JSONB | JSONB lista | 47,5% | sensowne pokrycie |
| **`skills` JSONB** `[{name,level,years}]` | JSONB lista | **0,3%** | martwe; poziomy są (100%), lata rzadko (11%) |
| `verified_tech` (ze screeningu) | JSONB lista | **0,0%** | proces screeningu tego nie zapisuje |
| `tags` | JSONB | 45,4% | **UWAGA: to NIE skille** — eventy źródeł Traffit (`traffit_source`) |
| `competence_category` (słownik CC) | FK + legacy string | 20,8% | jedyna „kategoria" jaką mamy; multi-CC z confidence istnieje |
| `years_it_experience` | int | 6,3% kolumna | ale **76,3% ma jakikolwiek sygnał doświadczenia** (buckety Traffita `Poniżej 2`/`2-5`/`5+` honorowane przez filtr) |
| seniority kandydata | — | **BRAK KOLUMNY** | wyprowadzane heurystyką ≥7 lat=senior, ≥3=mid (konwencja scoringu) |
| `availability_status` | enum (4 stany) | **100% `unknown`** | dokładnie: 0 rekordów actively_looking/open/not_looking |
| `availability_date` / `notice_period` | date / int | 1,7% | śladowe |
| `expected_rate_hourly` | int (PLN/h) | **0,0% (0 rekordów)** | pole z migracji 0138 — nikt nie wpisał ani jednego |
| `salary_expectation` | int (PLN/mies.) | 1,7% | śladowe |
| `city`/`country`/`region` (strukturalne) | string | **0,0%** | tylko legacy `location` free-text 16,5% |
| `linkedin` URL | string | 25,7% | sync LinkedIn: `linkedin_current_company` 4,8% |
| `ai_summary` | tekst | 28,3% | generowane historycznie |
| `status` | enum | 99,8% `active` | **zero sygnału** (blacklisted: 0) |
| `employment` (wyliczane) | derived | at_client **754** / available 52 676 | z kontraktów + hired-stage + conflictów |
| imię = „?" | — | 0,3% | resztka po backfillu nazwisk |

**Wniosek:** baza kandydatów to w praktyce **indeks kontaktowy + archiwum CV + historia procesów**. Warstwa „kompetencyjna" (skills/seniority/availability/stawki) jest pusta lub wyprowadzana ad-hoc z tekstu w momencie zapytania.

### 1.3 Job / zapytanie — 4 023 rekordy (pełna tabela)

| Wymiar | Stan | Komentarz |
|---|---|---|
| status | **14 published / 262 draft / 3 747 closed** | baza jobów = w 93% archiwum |
| `title` | 100% | **jedyny wiarygodny nośnik „czego chciał klient"** (tytuły Traffita niosą rolę+seniority+klienta, np. „PL_KYC_NFT Performance Tester-Senior-TP") |
| `description` / `requirements` | **~0%** | Traffit nie oddał treści zapytań; nowe joby też ich nie mają |
| `must_skills` JSONB | 89,4% niepuste | **ale 3 596 = dokładnie liczba `criteria_generated_at`** → 100% wygenerowane przez AI z tytułu; jakość niezaudytowana |
| `nice_skills` | 9,8% | j.w. |
| `seniority` (enum jobowy) | **3 rekordy / 4 023** | praktycznie brak |
| `industry` / `subcategory` | ~0% | puste |
| `close_reason` (enum: budget/competitor/filled_by_us/…) | **0% — wszystkie 3 747 zamkniętych = „unknown"** | enum z migracji 0048 nigdy nie użyty w praktyce |
| `salary_min/max` (budżet) | ~0,1% | brak widełek |
| `client_id` | 100% (NOT NULL) | 92 klientów z historią zapytań |
| `champion_profile` | ~0,1% | wypełniany tylko przy świadomym prowadzeniu roli |
| pochodzenie | Traffit (import+sync) + ręczne | sync działa codziennie (status „errors/degraded" — patrz §3.9) |

### 1.4 Klient — 157 rekordów

- `status`: 154 active / 2 inactive / 1 prospect (czyli status nie różnicuje niczego).
- `industry`: **5,1%** wypełnień. Brak pola „stack technologiczny klienta", brak struktury (programy/ART-y są tylko free-text `train_name` na jobach).
- 92 klientów ma historię zapytań; **20 klientów ma kontrakty**; koncentracja ogromna: Nordea ≈ 60% aktywnych kontraktów.
- Dublety nazw z Traffita — mechanizm kuracji (`display_name`, `hidden`) istnieje, nieużywany w API listy.

### 1.5 Kontrakt — 475 rekordów (pełna tabela) — najzdrowsza encja

| Wymiar | Stan |
|---|---|
| status | **414 active / 20 ending / 28 ended / 13 draft** |
| `candidate_id`, `client_id` | 100% (FK) |
| stawki `rate_candidate` / `rate_client` | **89,5% / 88,8%** + marża liczona automatycznie + **schedule z historią zmian** (aneksy, stawki progresywne) |
| `end_date` | 96,4% |
| **`job_id`** (most do „czego dotyczyło") | **0,2%** — praktycznie brak |
| kontekst delivery: `team_name`/`project_name`/`work_mode`/`office_location` | **0% / 3,8% / 0% / 0%** |
| `termination_reason` + `termination_lessons` | **100% NULL** (enum 10 powodów odejść — nieużyty) |
| unikalni konsultanci | 422 | 20 klientów |

**Wniosek:** wymiar finansowo-relacyjny (kto, u kogo, za ile, od–do) jest dobry. Wymiar merytoryczny (na jakim stacku, w jakim zespole, czemu odszedł) — pusty.

### 1.6 Infrastruktura matchingu (istnieje i działa)

- **Qdrant**: 2 kolekcje (`nexus_candidates`, `nexus_jobs`, 1024-dim, Voyage `voyage-3-large` + cache embeddingów). **Payload ubogi**: kandydat = `{candidate_id, name, competence_category}` — nie da się filtrować semantyki po skill/seniority/availability bez reindeksu.
- **Scoring hybrydowy** (`scoring_service`): semantic 0-35 + skills 0-30 + salary 0-12 + location 0-8 + availability 0-5 + champion_fit 0-10; wyjaśnialny breakdown; cache per (kandydat, job, profil wag). Skoro `skills`/`salary`/`availability` kandydatów są puste — te komponenty w praktyce działają na regexach z CV i neutralnych frakcjach.
- **Harness ewaluacji**: `scripts/eval_matching.py` (Precision@5, Recall@20, MRR, nDCG).
- **Gotowe endpointy analityczne**: `/api/reports/clients` (hit-ratio per klient + rozkład close_reasons — dziś „unknown"), `/api/contract-analytics/role-client-mix` (mapa rola×klient — dziś ~wszystko „Unknown"), `/termination-analysis`, `/margin-by-client`, `/utilization`, `/api/dashboard/pipeline-funnel`.
- **DynaReporter** (`dr_*`): równoległy, ręcznie karmiony świat KPI (MRR per klient, placementy per miesiąc, liczby konsultantów) z WŁASNĄ listą klientów bez FK do core. To drugie źródło prawdy o „ilu mamy u klienta".

---

## 2. Trzy kubełki

### 2a. Do zrobienia JUŻ TERAZ (dane są, brak tylko widoku)

| Co | Na czym stoi |
|---|---|
| **Mapa klient × konsultant × stawki × od–do** | kontrakty: FK 100%, stawki 89%, daty 96% — brakuje tylko UI agregującego (role-client-mix istnieje, ale oś „rola" jest pusta — patrz 2b) |
| **Hit-ratio / luki ilościowe per klient** | `/api/reports/clients` już liczy: 3 747 closed → 573 filled → 15,3%; per-klient, z trendem |
| **Funnel i konwersje per etap / per klient** | ~175k wierszy historii stage'ów; policzalne przejścia, czasy, drop-off |
| **Full-text „kto zna X"** | `q_all` po search_doc (CV włączone): python 14 387, java 17 323, react 6 773 — działa dziś, tylko nikt tego nie agreguje |
| **Koncentracja przychodu / ryzyko klienta** | margin-by-client + kontrakty + `client_order_end_date` |
| **Attrition ilościowe** | 48 ended/ending z datami (bez powodów) |

### 2b. Wymaga TYLKO przetworzenia (surowiec jest, trzeba go zmielić)

| Co | Surowiec | Przetworzenie |
|---|---|---|
| **Skill-store kandydatów** | `traffit_technologie` (~55% bazy, CSV free-text) → **bez LLM**, split + normalizacja aliasami; CV (93% plików, 53% już ztekstowanych) → **LLM** | batch: najpierw 754 at_client, potem aktywni w pipeline, potem reszta |
| **Seniority kandydata (derived)** | buckety doświadczenia Traffita (76% ma sygnał) + role z `experience` + tytuły z CV | heurystyka jak w scoringu + LLM przy parsie CV; oznaczać jako „derived, confidence X" |
| **Stack per kontrakt (kto na czym siedzi u klienta)** | CV konsultanta + tytuł joba źródłowego (po nazwie), historia stage'ów | LLM po CV 754 osób + dopięcie `job_id`↔kontrakt tam, gdzie da się zrekonstruować po (kandydat, klient, data hired) |
| **Rola znormalizowana z tytułów jobów** | 4 023 tytuły (100%) | słownik ról + LLM-klasyfikacja tytułu → (rola, seniority, technologia wiodąca); to naprawia i role-client-mix, i gap-analizę |
| **Luki per rola × klient** | j.w. + hit-ratio | po normalizacji tytułów: „u Nordei przegrywamy 80% zapytań o QA-automation" staje się policzalne |
| **Certyfikaty / języki** | `traffit_certificates` 28%, `languages` 47% | normalizacja słownikowa |
| **Rozszerzenie payloadów Qdrant** | wynik skill-store | reindeks z payloadem {skills[], seniority, availability?, city} → filtrowany semantic search |

### 2c. NIE MAMY — trzeba zacząć zbierać od zera (żaden backfill tego nie wyczaruje)

| Co | Stan | Jak zacząć zbierać |
|---|---|---|
| **Dostępność kandydata** | 100% unknown; pole+enum+TTL-e gotowe | proces: obowiązkowe przy screeningu/rozmowie + kwartalny nudge; inaczej wyciąć tę oś z projektu |
| **Powód przegranej rekrutacji** (`close_reason`) | 0% | wymusić przy zamykaniu joba (UI ma endpoint POST /close z polem — nikt nie wypełnia); historii nie odtworzymy |
| **Powód zakończenia kontraktu** | 0% | wymusić przy akcji „Zakończ"; 48 historycznych można spróbować uzupełnić ręcznie (mała liczba) |
| **Treść zapytania klienta** (wymagania) | ~0% opisów | import z maili/dokumentów przy tworzeniu joba (dziś Traffit tego nie niesie); od nowych zapytań |
| **Stawki oczekiwane kandydatów** | 0% | zapisywać przy screeningu (snapshot `expected_rate_value` na stage'u ISTNIEJE — sprawdzić czemu pusty / nieużywany) |
| **`verified_tech` ze screeningu** | 0% | screening ma pytania championowe — dodać krok „potwierdź technologie" |
| **Stack/kontekst po stronie klienta** (zespół, projekt, program) | ~0% | uzupełniać przy starcie kontraktu (pola są) |

---

## 3. Największe pułapki (bez znieczulenia)

1. **Zbudujesz agregację pustki.** Każdy widok „skill × cokolwiek" na dzisiejszych polach strukturalnych pokaże 0,3% bazy. Najpierw skill-store z backfillem, potem dashboard — odwrotna kolejność = strata miesiąca i zaufania zespołu do narzędzia.
2. **`must_skills` to nie są dane, to halucynacja niskiej gęstości.** 100% wygenerowane z SAMEGO tytułu (opisów nie ma). Gap-analiza „jakich skilli klienci chcieli" na tym zbiorze będzie brzmiała wiarygodnie i będzie zmyślona. Przed użyciem: audyt próbki ~100 jobów ręcznie.
3. **Wzorzec organizacyjny „pole jest, procesu nie ma".** availability (enum, 0 użyć), close_reason (enum, 0), termination_reason (enum 10 wartości, 0), verified_tech (0), city (0), expected_rate_hourly (0), seniority jobów (3/4023). To nie jest problem schematu — to problem workflow. Każda nowa kolumna bez wymuszenia w UI i bez właściciela procesu skończy tak samo.
4. **Świeżość faktów.** CV bywają sprzed lat; skill wyciągnięty z CV z 2019 ≠ kompetencja 2026; dostępność psuje się w tygodnie. Skill-store bez pól `source`, `observed_at`, `confidence` stanie się drugim śmietnikiem. Fakty kompetencyjne muszą mieć metrykę pochodzenia i decay.
5. **Wiele prawd o tym samym.** „Kto u klienta": kontrakty (414) vs derived at_client (754 — kontrakt LUB hired-stage LUB flaga konfliktu) vs DynaReporter (ręczne MRR/liczby). „Placementy": filled_jobs 573 vs placements 737 vs hired-stage'y 965. Bez uzgodnienia definicji każda mapa będzie kwestionowana na pierwszym spotkaniu.
6. **Tożsamość i dublety.** 53k rekordów z importów; dedup jest (linkedin_slug, telefon), ale nie był przegonony pod kątem „jedna osoba = jeden wiersz" na całej bazie. Mapa podaży skilli na dubletach zawyży stan.
7. **RODO.** Agregaty (heatmapy) są bezpieczne; ale „lista nazwisk z Javą u klienta X" + eksporty do sprzedaży to profilowanie danych osobowych. Trzymać widoki nazwiskowe za RBAC, eksporty przemyśleć z DPO.
8. **Qdrant do reindeksu.** Wzbogacenie payloadów = re-upsert 53k punktów; koszt Voyage ograniczony (jest `embedding_cache`), ale to operacja do zaplanowania, nie „przy okazji".
9. **Fundament się rusza.** Traffit sync działa, ale ostatnie runy kończą się `errors` / health `degraded` (+ `candidates_added_this_month: 0` w KPI). Zanim Cortex, warto domknąć błędy synca — inaczej intelligence liczy się na danych, które cicho przestały płynąć.
10. **To będzie intelligence retrospektywno-sprzedażowe, nie operacyjne.** 14 otwartych jobów vs 3 747 zamkniętych: wartość map jest w sprzedaży (cross-sell, dossier klienta, „kogo mamy pod nowe zapytanie") i strategii kompetencji — nie w codziennym matchingu do wakatów, bo wakatów prawie nie ma w systemie.

---

## 4. Co bym zbudował i w jakiej kolejności (wartość / nakład)

**Zasada nadrzędna: najpierw warstwa faktów, potem widoki.** Proponuję jeden nowy byt danych zamiast trzech dashboardów: **skill-fact store** — `(candidate_id, skill_id → taksonomia, poziom?, lata?, source [traffit|cv_llm|screening|contract], observed_at, confidence)`. Wszystkie trzy Twoje widoki to potem zapytania po tym jednym magazynie + istniejących kontraktach/jobach.

| # | Co | Wartość | Nakład | Uzasadnienie |
|---|---|---|---|---|
| 0 | **Audyt jakości `must_skills`** (próbka 100 jobów, ręcznie) + **uzgodnienie definicji** (konsultant-u-klienta, placement) | odblokowuje resztę | 0,5 dnia | bez tego każda liczba niżej jest podważalna |
| 1 | **Mapa aktywnych konsultantów: klient × stack × stawki** — LLM po CV 754 osób at_client → skill-store → widok na bazie role-client-mix | **najwyższa** (sprzedaż: cross-sell, dossier na spotkanie, następca „Unknown×Nordea") | ~1 tydzień; koszt LLM pomijalny (setki CV) | mała populacja, kompletne kontrakty, natychmiastowy efekt „wow" |
| 2 | **Backfill skill-store dla całej bazy**: najpierw `traffit_technologie` (~29k osób, **bez LLM** — split+aliasy), potem LLM po CV dla reszty; rozszerzenie taksonomii ~100→~300 haseł | wysoka (fundament) | parsowanie darmowe + batch LLM (rząd wielkości: dziesiątki–niskie setki $ na Haiku/Sonnet za ~25-50k CV — do decyzji budżetowej) | odblokowuje mapę technologiczną bazy i filtrowany semantic search |
| 3 | **Normalizacja tytułów jobów → (rola, seniority, tech wiodąca)** dla 4 023 jobów + podpięcie pod hit-ratio | wysoka (jedyna droga do „luk" na historii) | 2-3 dni + tani batch LLM | tytuły są jedynym prawdziwym sygnałem popytu; naprawia role-client-mix i gap-analizę jednocześnie |
| 4 | **Widok „Luki": rola × klient × hit-ratio × trend** + od dziś **wymuszone `close_reason`** przy zamykaniu joba | średnio-wysoka | 3-4 dni (endpoint hit-ratio już jest) | ilościowe luki od razu; jakościowe (powody) zaczną się kumulować od włączenia wymuszenia |
| 5 | **Tech-mapa bazy (skill × derived-seniority)** z jawnym fill-rate i freshness na UI | średnia | 3-4 dni po (2) | dopiero po backfillu; pokazywać „na ilu % bazy stoi ta liczba", żeby nie kłamać samym sobie |
| 6 | **Procesy zbierania**: availability przy screeningu + kwartalny nudge (infra TTL już jest), verified_tech w screeningu, stawka oczekiwana na stage'u | średnia, rośnie w czasie | głównie decyzja + drobny UI | bez tego osie „dostępność" i „zweryfikowane skille" nigdy nie powstaną |
| 7 | Reindeks Qdrant z payloadem skills/seniority (filtered semantic search) | średnia | 1-2 dni po (2) | ulepsza matching, ale to deser, nie danie główne |

**Gdzie Twoje myślenie bym skorygował:**

- **„skill × seniority × dostępność" jako jedna macierz** — dziś to macierz 3D, w której dwie osie są puste. Buduj skill-store z metryką pochodzenia; „dostępność" traktuj jako **atrybut świeżości/confidence** (ostatni kontakt, koniec kontraktu, deklaracja), nie jako równorzędną oś. Oś stanie się osią, gdy proces z p. 6 pożyje kwartał.
- **„czego klienci chcieli" na poziomie skilli** — na historii masz TYLKO tytuły. Realny poziom granulacji luk to **rola × seniority × klient**, nie „brakowało nam Kafki". Poziom skilli zacznie być prawdziwy dopiero dla nowych zapytań, jeśli zaczniecie importować ich treść.
- **przestrzelenie zakresu**: „jeden widok na wszystko" na starcie = dashboard, któremu nikt nie ufa. Odwróć: dwa konkretne pytania sprzedażowe (1: „kogo mamy u klienta X / na stacku Y", 4: „gdzie przegrywamy najwięcej") dowiezione end-to-end zbudują zaufanie i sfinansują resztę.
- **czego w Twoim myśleniu BRAKUJE**: wymiar **czasu/świeżości** (decay faktów) oraz **właściciela procesu** dla każdego zbieranego pola. To one decydują, czy Cortex za rok będzie żywy, czy będzie kolejnym `availability_status`.

---

## 5. Czego potrzebuję od Ciebie

### 5.1 Dostępy
1. **Read-only dostęp do prod DB.** Mój klucz SSH (`claude-nexus-dbaccess-20260623`) przestał być honorowany przez serwer 91.99.199.112 (Permission denied — root i typowe loginy), a lokalnie nie ma hasła do panelu Coolify. Docelowo: MCP `postgres-nexus` z rolą `claude_ro` (plan „Phase 4" ze skilla ops-db-query). Do tego czasu ten raport stoi na API produkcyjnym — kilka liczb wymaga weryfikacji SQL: pokrycie `embedding_id`, dokładny fill `raw_cv_text`, skala dubletów, rozkład dat `updated_at` (żywość bazy).
2. Potwierdzenie, że mogę odpalić **testowy batch LLM** (np. 200 CV) na kluczu produkcyjnym Anthropic do wyceny jakości/kosztu ekstrakcji.

### 5.2 Decyzje
3. **Budżet na backfill LLM** (rząd wielkości: dziesiątki–niskie setki $ za całość bazy; populacja at_client — pomijalne grosze). Mogę zacząć od 754 + aktywnych w pipeline bez osobnej zgody budżetowej, jeśli potwierdzisz.
4. **Definicja „konsultant u klienta"**: aktywny kontrakt (414)? czy szersza derived (754, z hired-stage'ów i flag)? Rekomendacja: kontrakt = prawda twarda, reszta = „prawdopodobnie u klienta (źródło: pipeline)" z oznaczeniem.
5. **Wymuszenie `close_reason`** przy zamykaniu joba (pole obowiązkowe) — tak/nie + od kiedy. Analogicznie `termination_reason` przy kończeniu kontraktu.
6. **Proces availability**: czy zespół będzie utrzymywał status dostępności (screening + nudge)? Jeśli nie — świadomie wycinamy tę oś i mówimy to wprost.
7. **Kurator taksonomii skilli** (rozszerzenie ~100→~300 i utrzymanie aliasów): kto po stronie zespołu zatwierdza słownik.

### 5.3 Materiały
8. **2-3 surowe zapytania klientów** (mail/RFP/dokument, w oryginale) — ocenię, czy da się je automatycznie strukturyzować przy tworzeniu joba (to jedyna droga, by „czego chcieli" zeszło z poziomu tytułu na poziom wymagań).
9. Jeśli istnieją **poza-systemowe listy** „kto u jakiego klienta na jakim stacku" (Excel u delivery leadów, dane z DynaReporter) — chętnie użyję ich jako ground truth do walidacji mapy z p. 1 rankingu.

---

*Raport wygenerowany w ramach rozpoznania Cortex (zero zmian w kodzie). Liczby produkcyjne z 2026-07-12; kandydaci — próbka n=1200 (±3 p.p.) + dokładne totale filtrów; joby/kontrakty/klienci — pełne tabele.*
