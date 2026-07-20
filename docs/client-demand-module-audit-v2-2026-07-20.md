# Moduł 1 — Klient, relacje i zapotrzebowanie — Audyt v2 (uzupełniający)

## Nowe ustalenia poza planem Codexa (M1-*) i poza PR #770

**Data audytu:** 2026-07-20
**Repozytorium:** NEXUS
**Zakres źródłowy:** `origin/main` na commicie `bdf5a75a564c08f1c224835cd21807fef966087a` (zawiera scalone PR #770 = containment RBAC modułu klienta)
**Charakter dokumentu:** raport audytowy uzupełniający; nie zmienia działania systemu
**Metodyka:** audyt wieloagentowy (8 finderów per wymiar) → adwersaryjna weryfikacja kodu per finding (domyślnie obalająca, sprawdza duplikaty M1-*) → krytyk kompletności → **niezależna re-weryfikacja headline’ów przez prowadzącego na kanonicznym drzewie**.

---

## 1. Po co ten dokument

Plan Codexa (`docs/client-demand-module-audit-and-claude-implementation-plan-2026-07-16.md`) opisał 18 ustaleń M1-* i 7-PR-owy plan naprawczy. PR 1/7 (containment RBAC, [#770](https://github.com/artur-t-96/Nexus/pull/770)) jest scalony. Ten audyt szukał **rzeczy, których na liście M1-* NIE ma** — i znalazł **19 nowych, potwierdzonych ustaleń** (1×H, 10×M, 8×L) oraz **2 fałszywe tropy** (świadomie odrzucone i udokumentowane, żeby nikt ich nie zgłosił ponownie).

Kluczowy wzorzec przewijający się przez najgroźniejsze findingi: **PR #770 utwardził tylko router `client-demand` (contacts/knowledge/materials/framework/projekcje klienta), ale te same wrażliwe dane są czytane przez INNE routery, które `ClientAccess` całkowicie omijają.** To residualne obejścia containmentu, nie regresje.

---

## 2. Rejestr ustaleń (posortowany wg skorygowanej wagi)

| ID | Waga | Status | Ustalenie | Plik |
|---|---|---|---|---|
| M1B-SEC-01 | **H** | CONFIRMED | `POST /api/prep-kit/generate` zwraca `ClientKnowledge` dowolnego klienta z pominięciem `ClientAccess` (cross-team BOLA) | `app/api/prep_kit.py:60,94` |
| M1B-SEC-02 | M | CONFIRMED | `GET /api/clients/{id}/team` ujawnia imię+email+rolę całego zespołu (TAC/DL) każdemu zalogowanemu, w tym `viewer`, cross-client | `app/api/clients_team.py:91` |
| M1B-SEC-03 | M | CONFIRMED | Odczyty `client_orders` (`TacPlus`) zwracają `rate_candidate`/`monthly_margin`/`rate_client` roli `tac`, której polityka `VIEW_FINANCE` (admin+DL) jawnie odmawia | `app/api/client_orders.py:161` |
| M1B-SEC-04 | M | CONFIRMED | `GET /candidates/{id}/rate-history` (bare `CurrentUser`) zwraca historyczne stawki kandydata każdemu zalogowanemu; zapis wymaga admin/DL (asymetria read/write) | `app/api/phase5.py:169` |
| M1B-SEC-05 | M | CONFIRMED | `POST /api/ai/generate-job-description` ujawnia `selling_points` klienta po fuzzy `ilike` na nazwie, bez `ClientAccess` (leak + enumeracja klientów) | `app/api/ai_writer.py:79,95` |
| M1B-DATA-01 | M | CONFIRMED | `delete_client` bez guardu: mieszane polityki `ON DELETE` → dla klienta z Job/Contract **500 IntegrityError**, dla prospekta z samą MSA/orderami **cichy hard-cascade** (utrata danych finansowo-prawnych) | `app/api/clients.py:450` |
| M1B-FIN-01 | M | CONFIRMED | `monthly_margin_pct` dzieli marżę **miesięczną** przez `total_value` **lifetime** → % marży zaniżony ~N-krotnie (N = miesiące zamówienia) | `app/api/my_clients.py:283` |
| M1B-FIN-02 | M | CONFIRMED | `MrrSummary.total_mrr` = `SUM` miesięcznych snapshotów MRR w oknie → ~N-krotne zawyżenie (skaluje się z parametrem `months`) | `app/api/dynareporter_clients_mrr.py:149` |
| M1B-LIFE-01 | M | CONFIRMED | `create_contract_with_order` bez idempotencji → podwójny submit/retry tworzy DWA aktywne Contract+Order → podwójne liczenie marży/MRR/LTV | `app/api/client_orders.py:555` |
| M1B-UX-01 | M | CONFIRMED | Zmiana klienta w formularzu oferty nie czyści `hiring_manager_contact_id`; select renderuje „— brak —”, a submit wysyła **stary** kontakt innego klienta (cicha korupcja cross-client) | `frontend/.../AppShell.tsx:1181` |
| M1B-UX-02 | M | CONFIRMED | Błąd (403 z `ClientAccess` / 500) na `GET` klienta renderuje się jako „Nie znaleziono klienta” (brak obsługi `isError`) | `frontend/src/app/clients/[id]/page.tsx:779` |
| M1B-FIN-03 | L | PLAUSIBLE | `active_mrr` w profilu klienta to suma **marży**, nie przychodu — niespójność etykiety MRR z resztą modułu | `app/api/clients.py:340` |
| M1B-FIN-04 | L | PLAUSIBLE | `avg_days_to_fill` = `start_date − created_at` z cichym odrzuceniem ujemnych → survivorship bias na backfillu historii | `app/api/my_clients.py:311` |
| M1B-LIFE-02 | L | CONFIRMED | Wybór „latest order” bez deterministycznego tie-breaka po `id` → przy równych `start_date` pokazuje starą stawkę/marżę | `app/api/client_orders.py:190` |
| M1B-FILE-01 | L | CONFIRMED | Create orderu/MSA/aneksu: plik zapisany do storage **przed** `db.flush`; błąd FK (np. niewalidowany `job_id`) porzuca osierocony blob (wyciek dysku) | `app/api/client_orders.py:344` |
| M1B-FILE-02 | L | CONFIRMED | Download orderu/aneksu/MSA rzuca niezłapany `FileNotFoundError` → **HTTP 500** zamiast 404 gdy plik zniknął (sibling one-pager to łapie — niespójność 3-z-4) | `app/api/client_orders.py:496` |
| M1B-PERF-01 | L | CONFIRMED | `list_one_pagers`: `SELECT User.email` per one-pager (N+1 na liście materiałów) | `app/api/client_materials.py:149` |
| M1B-PERF-02 | L | CONFIRMED | `contracts-with-orders` (autocomplete przedłużeń) materializuje CAŁĄ historię klienta bez filtra statusu w SQL, odrzuca większość w Pythonie + re-fetch `Candidate`/`Job` mimo eager-load | `app/api/client_orders.py:248` |
| M1B-PERF-03 | L | CONFIRMED | `kpi_by_dl`: 2 zapytania per Delivery Lead w pętli (N+1 po DL) | `app/api/admin_clients_overview.py:236` |

### Świadomie odrzucone (żeby nie zgłaszać ponownie)

| Kandydat | Dlaczego NIE jest luką |
|---|---|
| Brak `X-Content-Type-Options: nosniff` na downloadach | **FAŁSZ** — `SecurityHeadersMiddleware` (`app/main.py:280`, zarejestrowane :561) robi `setdefault('X-Content-Type-Options','nosniff')` na KAŻDEJ odpowiedzi, w tym na `FileResponse`. Plus `Content-Disposition: attachment` (Starlette przy podanym `filename=`). Wektor inline-XSS nie istnieje. |
| `formatPLN(maximumFractionDigits:3)` → grosze z 3 cyframi | **NIEWYKONALNE** — wszystkie pola zasilające formatter (`active_mrr`/`ltv`/`monthly_rate_client`/`monthly_margin`/`total_revenue`) są w schemacie `Optional[int]`; Pydantic wymusza `int` na granicy API, więc część ułamkowa nigdy nie dociera do frontendu. Config jest niechlujny, ale bug prezentacyjny się nie manifestuje. |

---

## 3. Szczegóły — najważniejsze ustalenia

### M1B-SEC-01 (H) — prep-kit omija `ClientAccess`, wyciek `ClientKnowledge` między zespołami

**Dowód (`app/api/prep_kit.py`):** endpoint `POST /api/prep-kit/generate` bramkowany wyłącznie `Depends(get_current_user)` (L60). Dla przekazanego `job_id` ładuje **wszystkie** wpisy wiedzy klienta: `select(ClientKnowledge).where(ClientKnowledge.client_id == job.client_id)` (L94–97) i renderuje je do odpowiedzi — `tech_stack`/`culture`/`general` → `client_overview`, `selling_points` → `selling_points`, `interview_questions` → `likely_questions` (przez `question_suggestions.suggest_questions_for_prep`, tier_3). Kanoniczny router `client_knowledge.py` bramkuje **te same wiersze** przez `resolve_client_access(...).can_view_knowledge` (= `is_admin_like OR is_client_team OR is_job_assigned`). `prep_kit` całkowicie omija tę bramę i nie robi żadnego per-klient checku na Job/Candidate.

**Scenariusz:** rekruter przypisany tylko do klienta A (lub `viewer`) woła `POST /api/prep-kit/generate` z `job_id` klienta B i dowolnym istniejącym `candidate_id` → dostaje prywatną wiedzę klienta B. To **BOLA cross-team**, nie tylko luka roli `viewer` — dodanie blokady viewera JEJ NIE ZAMYKA; trzeba bramy per-klient.

**Nowość vs Codex:** M1-SEC-01/02 dotyczą routera `client-demand` (zapis + projekcje), naprawione #770 w samym resolverze. To inny router, którego #770 nie tknął.

**Rekomendacja:** po załadowaniu Job wywołać `resolve_client_access(db, current_user, job.client_id)` i pominąć/odrzucić sekcje wiedzy gdy `not can_view_knowledge` (albo 403).

### M1B-SEC-05 (M) — `ai_writer` czyta `selling_points` po fuzzy-match nazwy, bez `ClientAccess`

**Dowód (`app/api/ai_writer.py`):** `POST /api/ai/generate-job-description`, gate `get_current_user` (L79). Wyszukuje klienta `select(Client).where(Client.name.ilike(f"%{request.client_name}%"))` (L95) i ładuje `ClientKnowledge` kategorii `selling_points` (L99–107), wstrzykując treść do sekcji „Co oferujemy?”. Brak `ClientAccess`. Fuzzy `ilike` na nazwie dodatkowo pozwala **enumerować klientów** i podbierać ich selling points po zgadywanych fragmentach nazwy.

**Rekomendacja:** pobierać wiedzę dopiero po `resolve_client_access(...).can_view_knowledge` dla dopasowanego `client.id`; rozważyć exact-match zamiast `ilike` substring.

### M1B-SEC-02 (M) — `GET /clients/{id}/team` wycieka służbowe emaile zespołu

**Dowód (`app/api/clients_team.py:91`):** `get_client_team` na bare `CurrentUser`, po samym `_ensure_client_exists` zwraca `name`/`email`/`role` wszystkich TAC i DL klienta. Zapisy (`POST/DELETE/PUT`) poprawnie mają `HeadOfRecruitmentPlus` — dziura jest tylko na **odczycie**. Router nie był objęty #770. `viewer` (rola `user`, wg doc „QC/klient” — potencjalnie zewnętrzny) może iterować `client_id` i enumerować pełną strukturę delivery + emaile pracowników cross-client.

**Rekomendacja:** gate `OperationalUser`/`RecruiterPlus` (wyłączyć viewera), a docelowo `resolve_client_access(...).can_view_contacts` per klient.

### M1B-SEC-03 (M) — odczyty `client_orders` dają marżę/koszt roli `tac`

**Dowód:** `client_orders.py` **nie importuje** `financial_access` ani `client_access`. Odczyty (`GET /{id}/orders`, `/contracts-with-orders`, `/orders/{id}`, `/orders/{id}/file`) na `TacPlus` (= admin/DL/**tac**) i serializują `rate_client`/`rate_candidate`/`monthly_margin`/`total_value` bez redakcji. Siostrzane routery redagują dla nie-`VIEW_FINANCE`: `contracts.py` (`_redact_contract_finance`), `contractors.py` (P0.12 — bliźniacza powierzchnia). `tac` nie ma `VIEW_FINANCE` (`app/analytics/capabilities.py`) → tu dostaje **koszt kandydata** i marżę dla dowolnego klienta.

**Rekomendacja:** dołożyć redakcję pól kwotowych dla ról bez `VIEW_FINANCE` (spójnie z `contracts.py`/`contractors.py`).

### M1B-SEC-04 (M) — `rate-history` kandydata na bare `CurrentUser`

**Dowód (`app/api/phase5.py`):** `list_rate_history` (L169) = `CurrentUser`; `create/update/delete` = `ManagerOrAdmin`. Odczyt zwraca `rate`/`currency`/`contract_type`/`client_id` — finansowo-konkurencyjnie wrażliwe stawki historyczne kandydata każdemu zalogowanemu (viewer/sourcer/recruiter/tac), mimo że nie mają prawa ich zapisać.

**Rekomendacja:** bramka co najmniej `RecruiterPlus` + `require_financial_access` (dane są finansowe).

### M1B-DATA-01 (M) — `delete_client` bez guardu, mieszane `ON DELETE`

**Dowód:** `delete_client` (`clients.py:450`) robi bezwarunkowe `db.delete(client)` (po dodaniu `Activity('deleted')` do sesji). FK na `clients.id` mają **niespójne** polityki: `contact`/`contract`/`job`/`client_knowledge` = `nullable=False` BEZ `ondelete`; `client_framework_contract`/`client_order` = `ondelete=CASCADE`. Relacje `Client.jobs`/`contracts` bez `cascade`/`passive_deletes`.
- **Ścieżka B (częsta):** klient z jakimkolwiek Job/Contract → SQLAlchemy próbuje `UPDATE ... SET client_id=NULL` na kolumnie `NOT NULL` → **IntegrityError 500**.
- **Ścieżka A (rzadsza, nieodwracalna):** prospekt mający tylko CASCADE-dzieci (MSA/ordery/rate_cards) i zero RESTRICT-dzieci → DELETE się udaje, DB **po cichu kaskadowo kasuje dane finansowo-prawne**.

**Rekomendacja:** przed `db.delete` policzyć twarde zależności → 409 gdy istnieją (jak `delete_order` robi soft-cancel), albo przejść na archiwizację (spójne z M1-ID-02). Docelowo ujednolicić polityki FK.

### M1B-FIN-01 (M) — `margin_pct`: mianownik lifetime, licznik miesięczny

**Dowód (`my_clients.py:283`):** `margin_pct = monthly_margin_total / active_rev * 100`, gdzie `monthly_margin_total = Σ Contract.monthly_margin` (marża/**miesiąc**), a `active_rev = Σ ClientOrder.total_value` (jawnie „całkowita wartość okresu” = **lifetime**). Dla zamówienia 24-mies. margin_pct zaniżony ~24×.

**Scenariusz liczbowy:** `rate_client=200`, `rate_candidate=140`, `billing=160h`, 24 mies. → `monthly_margin=9600`; `total_value≈768000`; `margin_pct=1.25%` zamiast ~30%.

**Rekomendacja:** dzielić przez **miesięczny** przychód (`Σ monthly_rate_client` aktywnych) albo pomnożyć marżę × liczbę miesięcy. Ujednolicić bazę Contract vs ClientOrder.

### M1B-FIN-02 (M) — `total_mrr` sumuje snapshoty miesięczne

**Dowód (`dynareporter_clients_mrr.py:149`):** `total_mrr = func.sum(DrClientMrr.mrr)` po wszystkich wierszach z okna `[today-months*30, today]`, bez `GROUP BY`/latest-per-client. MRR to snapshot miesięczny → suma N miesięcy ≈ N× MRR punktowego; skaluje się liniowo z parametrem `months` (dowód że to nie jest MRR). W tym samym zapytaniu `avg_consultants` liczy się przez `AVG`, a `total_mrr` przez `SUM` — jawna niespójność.

**Rekomendacja:** wziąć MRR z ostatniego miesiąca (lub `AVG`/miesiąc), nie `SUM`; jeśli intencją jest kumulacja przychodu — przemianować pole.

### M1B-LIFE-01 (M) — brak idempotencji w `create_contract_with_order`

**Dowód (`client_orders.py:555`):** Flow B tworzy atomowo `Contract(status=active)` + `ClientOrder(status=active, filled_at=now)` bez klucza idempotencji ani guardu duplikatu (walidacje sprawdzają tylko istnienie candidate/job/framework). Podwójny klik / retry proxy → dwa kompletne aktywne kontrakty na tego samego kandydata → analytics podwaja marżę/MRR/LTV.

**Nowość vs Codex:** M1-LIFE-02 wylicza 5 innych wyścigów; double-submit atomowego create Contract+Order (Flow B) nie jest wśród nich.

**Rekomendacja:** guard idempotencji (brak istniejącego aktywnego Contract dla `candidate_id+client_id+job_id`) lub klient-generowany idempotency-key.

### M1B-UX-01 (M) — stale hiring manager cross-client w formularzu oferty

**Dowód (`AppShell.tsx`):** lista HM keyowana po kliencie; `onChange('client_id')` ustawia tylko `client_id`; `useEffect` auto-fill obsługuje tylko `tac_id`/`delivery_lead_id`. Nic nie zeruje `hiring_manager_contact_id`. Po zmianie klienta stary `id` nie pasuje do żadnego `<option>` → select pokazuje „— brak —”, a stan trzyma stary id, który submit wysyła. Backend (brak same-client FK — M1-DATA-01) zapisuje cicho → oferta klienta B z kontaktem klienta A.

**Rekomendacja:** w handlerze zmiany `client_id` czyścić `hiring_manager_contact_id`.

### M1B-UX-02 (M) — 403/500 na kliencie renderuje się jako „Nie znaleziono”

**Dowód (`clients/[id]/page.tsx:779`):** główne `useQuery(['client', id])` destrukturyzuje tylko `data, isLoading` — brak `isError`. Po błędzie `client=undefined` → twardy „Nie znaleziono klienta”. Skleja 403 (odmowa `ClientAccess` z #770), 500 i realne 404 w jeden mylący stan („klient zniknął”). To ta sama klasa co znane [[rbac-containment-403-reads-as-data-loss]], w nowym miejscu (top-level query całej strony).

**Rekomendacja:** rozróżnić `isError` + status: 403 → „Brak dostępu”, 404 → „Nie znaleziono”, inne → generyczny błąd z retry.

*(Szczegóły ustaleń L — patrz rejestr w §2; wszystkie z dokładnym plikiem/linią i scenariuszem w journalu audytu.)*

---

## 4. Krytyk kompletności — hipotezy do następnej rundy (NIEZWERYFIKOWANE)

Te obszary nie zostały pokryte ani przez plan Codexa, ani przez powyższe findingi. Wymagają osobnej weryfikacji (podano jak):

1. **Traffit-sync tworzy klientów-sieroty (M?)** — `_UPSERT_CLIENT` (keyed `(external_source, external_id)`) prawdopodobnie tworzy klientów **bez przypisania zespołu** (→ w modelu `ClientAccess` widoczni tylko dla admina) i **bez dedup/normalizacji** względem ręcznie utworzonych (trwały duplikat po NIP/nazwie, którego sync nigdy nie rekonciliuje). Inna POWIERZCHNIA niż M1-ID-01/02 (tam tylko interaktywny CRUD). *Weryfikacja: przeczytać `app/services/traffit/importer.py` `_UPSERT_CLIENT`/`import_clients`; prześledzić `resolve_client_access` dla klienta z zerowym zespołem.*
2. **Brak audit-trail dla części akcji klienta (M?)** — po #770 kontakty/wiedza mają audit event, ale `client_orders`, `clients_team` (reassign), `phase5` (rate-history) i sam `delete_client` — najbardziej wrażliwe operacje uprzywilejowane — piszą mało lub nic trwałego (brak odpowiednika `candidate_audit.py`). *Weryfikacja: `grep -n 'Activity\|audit' app/api/client_orders.py app/api/clients_team.py app/api/phase5.py`.*
3. **entrypoint.sh safety-net drift dla tabel klienta (M?)** — prod alembic ORPHANED (~0170); jeśli `entrypoint.sh` nie mirroruje `client_knowledge`/`clients.display_name`/`hidden`/`is_system` (migr 0127), każdy `ADD COLUMN` powyżej punktu sieroctwa **cicho no-opuje** na prod, a projekcja legal/display potem 500-uje na brakującej kolumnie. *Weryfikacja: `grep -n 'client_knowledge\|display_name\|is_system' entrypoint.sh`.*
4. **Brak ścieżki RODO/erasure dla PII kontaktów klienta (M?)** — `contacts` trzyma `name`/`email`/`phone`/`last_personal_touchpoint_at`, ale — w odróżnieniu od kandydatów (anonymize + hard-delete + retencja z M2) — brak right-to-be-forgotten dla hiring managera. *Weryfikacja: `grep -n 'anonymize\|retention\|erase\|rodo' app/api/clients*.py`.*
5. **Notification egress bez per-client scope (L?)** — `contract_alerts` prawdopodobnie postuje jeden zbiorczy summary Slack (wszyscy klienci) na współdzielony webhook, bez filtra `ClientAccess`; każdy w kanale widzi id kontraktów i daty końca klientów, do których nie ma prawa wg #770. *Weryfikacja: `app/tasks/contract_alerts.py` `_post_slack_summary`.*

---

## 5. Rekomendowana kolejność naprawy

Ustalenia bezpieczeństwa (M1B-SEC-*) i utrata danych (M1B-DATA-01) to naturalny **PR 1.5 / containment-domykający** — spójny z duchem PR #770, przed PR 2/7 (kanoniczny klient):

1. **Fala bezpieczeństwa (H+M):** M1B-SEC-01..05 — podpiąć `resolve_client_access`/redakcję finansów do prep_kit, ai_writer, clients_team GET, client_orders reads, phase5 rate-history. Wszystkie to podpięcie istniejącego resolvera z #770 do routerów, które go omijają — mały, spójny diff + macierz testów (analogicznie do `test_client_access_matrix.py`).
2. **Utrata danych (M):** M1B-DATA-01 — guard `delete_client` (409 przy zależnościach / archiwizacja). Zbiega się z M1-ID-02 z planu Codexa (PR 2/7).
3. **Poprawność finansowa (M):** M1B-FIN-01/02, M1B-LIFE-01 — wpisują się w M1-FIN-01 / lifecycle z planu (PR 4/7, PR 7/7).
4. **Frontend (M):** M1B-UX-01/02 — wpisują się w PR 6/7.
5. **L-ki** — oportunistycznie przy dotykaniu odpowiednich plików.

---

## 6. Ograniczenia audytu

- Analiza statyczna kodu na `origin/main` bdf5a75; brak dostępu do prod-DB (patrz [[nexus-prod-db-access-dead-ssh]]) → scenariusze zależne od danych (M1B-FIN-04 survivorship bias, ścieżka A M1B-DATA-01) są potwierdzone w kodzie, ale ich **częstotliwość** na prod niezmierzona.
- 2 findingi odrzucone przez warstwę adwersaryjną i re-weryfikację (§2) — udokumentowane, by nie wracały.
- Hipotezy §4 są celowo NIEZWERYFIKOWANE (następna runda / preflight).
