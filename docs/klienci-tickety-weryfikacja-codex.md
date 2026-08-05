# Weryfikacja analizy Codexa + nowe rekomendacje

> Fact-check audytu Codexa (`clients-orders-contracts-tickets-1-5-review-...-2026-08-05.md`)
> skonfrontowany z żywym kodem na tym samym commicie `e228b601`, przez 6 agentów
> **adwersaryjnych** (zadanie: obalić każde twierdzenie, nie potwierdzić). Każdy werdykt z `plik:linia`.
> Uzupełnia i miejscami **koryguje** moją wcześniejszą analizę [klienci-tickety-analiza.md](klienci-tickety-analiza.md).
> Data: 2026-08-05.

---

## 1. Werdykt o analizie Codexa — w skrócie

**Analiza Codexa jest solidna i w większości poprawna.** Powstała niezależnie ode mnie i **zbiega się z moją na wszystkich kluczowych wnioskach strategicznych** (sekcje sterowane `ClientPortfolioScope.category`, masowa naprawa statusów niebezpieczna, nazwa → `display_name`, #4 w większości już zrobiony, #2 = konsultant + filtr FE, #3 kolizja order/contract + nie bramkować po nazwie, #5 głównie istnieje + data przyszła nie może archiwizować od razu). Dwa niezależne audyty dochodzące do tych samych wniosków to mocny sygnał, że fundament jest trafny.

Weryfikacja adwersaryjna 25+ konkretnych twierdzeń Codexa dała:
- **~15 CONFIRMED** (Codex ma rację, często z dokładnym cytatem),
- **~7 PARTIAL** (rdzeń prawdziwy, ale Codex przeszacował zakres/severity),
- **1 REFUTED** (twierdzenie materialnie błędne — patrz niżej),
- kilka **overreach** (rekomendacje w skali enterprise, przesadzone dla wewnętrznego narzędzia na 12 DL + 12 rekruterów).

**Najważniejsze:** weryfikacja wykazała, że **Codex miał rację, a MOJA wcześniejsza analiza się myliła** w jednym punkcie (usunięcie „Otwartych rekrutacji"). Poniżej uczciwie oznaczam też korekty do mojej własnej analizy.

---

## 2. Gdzie Codex miał rację, a JA się myliłem (korekty mojej analizy)

| # | Moje wcześniejsze twierdzenie | Prawda (zweryfikowana) | Dowód |
|---|---|---|---|
| K1 | „Usunięcie listy Otwarte rekrutacje jest **bezpieczne/izolowane**" | **BŁĄD.** Sekcja hostuje jedyne w appce UI „zamknij rekrutację jako przegraną" (`CloseJobAsLostModal` = jedyny caller `POST /api/jobs/{id}/close`), akcję „Dodaj kandydata" i link. Usunięcie bez re-homingu = twarda strata funkcji. | `ProfileTab.tsx:107-159, 136, 144`; `JobRow.tsx:47-52,81`; `ProjectsTab.tsx:67-105` (read-only, brak akcji); grep: `CloseJobAsLostModal` renderowany tylko w `ProfileTab.tsx` |
| K2 | „**Formularz uzupełniania draftu nie istnieje** — drafty uzupełnia się inline" | **BŁĄD dla draftu Kontraktu.** Istnieje dedykowany `DraftCompletionModal.tsx` + jawny krok `draft→active` przez `POST /api/contracts/{id}/activate` z walidacją braków (409), w zakładce „Do uzupełnienia" `ContractorsListV2`. (Prawda tylko dla draftu ClientOrder w `OrdersAndContractsTab` — tam nie ma flipa statusu.) *Codex twierdził to samo co ja — oboje się myliliśmy.* | `DraftCompletionModal.tsx:71-116`; `contracts.py:1598-1645`; `ContractorsListV2.tsx:42,240,335,387-394` |
| K3 | „`entrypoint.sh` **nie ma żadnego DDL dla `client_orders`**" | **BŁĄD faktyczny.** `entrypoint.sh:2050` ma już `ALTER TABLE client_orders ADD COLUMN IF NOT EXISTS filled_at ...` (mirror migracji 0176). Wniosek (nowa kolumna `project_part` potrzebuje mirrora) **pozostaje słuszny** — właśnie dlatego, że ten wzorzec już istnieje. | `entrypoint.sh:2050` |

To ważne, bo K1 zmienia plan wykonania ticketa #3 (trzeba najpierw przenieść akcje), a K2 upraszcza #3 (formularz kompletacji częściowo istnieje).

---

## 3. Gdzie Codex przeszacował lub się pomylił (overreach / błędy)

| # | Twierdzenie Codexa | Werdykt | Prawda |
|---|---|---|---|
| E1 | „Traffit sync jest **obecnie WŁĄCZONY**" → nazwa/status cofa się w 24h | PARTIAL | Mechanizm nadpisania potwierdzony, ale: (a) dotyczy **tylko** klientów z Traffita (`external_source='traffit'`, `external_id NOT NULL`) — manualni/portfolio nietknięci; (b) `TRAFFIT_SYNC_ENABLED` **domyślnie False** (`config.py:761`), realny stan prod = env, **nie weryfikowalny z kodu**. Ryzyko realne, ale **warunkowe**. |
| E2 | Generyczny `PATCH /contracts/{id}` może ustawić **status** i metadane zakończenia | PARTIAL | `status` jest **celowo wykluczony** z `ContractUpdate` (`schemas/contract.py:156-159`) i guard koherencji jest downgrade-only → PATCH **nigdy** nie ustawi `ended`. Wyciekają tylko `terminated_at`/`reason`/`end_date` (realny obchód audytu). „status" = błąd. |
| E3 | „Retry terminacji **ponownie dodaje aneks** i aktywność" | PARTIAL | Sekwencyjny retry z tą samą datą **NIE** dubluje aneksu (pierwsze wywołanie obniża `end_date`, warunek `when < previous_end_date` staje się fałszem). Aneks dubluje się **tylko** przy współbieżności lub wcześniejszej dacie. Ale **duplikat `Activity('terminated')` jest realny** — dopisywany bezwarunkowo przy każdym wywołaniu (`contracts.py:2923-2935`). |
| E4 | „terminate wymaga `reason` **+ lessons**" | PARTIAL | `reason` wymagany na endpointcie POST. `lessons` **NIE** (`Optional[str]=None`). I ścieżka PATCH pozwala pisać pola zakończenia bez wymaganego powodu. |
| E5 | „`project_part` powinien być **dedykowaną tabelą słownikową** `client_order_parts` z FK" | OVERREACH | Precedens słownika w kodzie to JEDNA generyczna tabela (`models/dictionary.py`), **nie** per-taksonomia i **nie** client-scoped. Dedykowana tabela dla 5 stałych wartości jednego klienta to gold-plating **wbrew** wzorcowi repo. Właściwy wybór: **enum** (jak `ClientOrderStatus`) albo `VARCHAR + CHECK`. *(Zgodne z moją rekomendacją.)* |
| E6 | „2-3 rekordy klienta e-Zdrowie" | drobna nieścisłość | **2 realne** wiersze `clients` (115, 5257). „Wpis kanoniczny" to curowany `display_name`/needle, niekoniecznie 3. wiersz. |

**Nadmiar ciężaru (kalibracja skali).** Codex proponuje aparat enterprise: osobny ADR, tryb shadow-read, dedykowaną capability `END_ENGAGEMENT`, optymistyczną współbieżność (`expected_version`/`If-Match`), klucze idempotencji, 8 osobnych PR-ów. To poprawne inżyniersko, ale dla wewnętrznego narzędzia (12 DL + 12 rekruterów, ~56k kandydatów, **solo dev**, tempo ludzkie a nie wysokie QPS) część z tego jest przesadą. Realne, tanie odpowiedniki podaję w sekcji 6.

---

## 4. Uzgodniona prawda per ticket (po dwóch audytach + weryfikacji)

- **#1 (statusy + nazwa):** Oba audyty zgodne. Sekcje = `ClientPortfolioScope.category` (potwierdzone testami: `test_client_directory.py:247`). „Aktywny w Nieaktywnych" powstaje mechanicznie: klient z Traffita **nieobecny w workbooku** dostaje scope `inactive`, status zostaje `active` (`client_portfolio_import.py:2209-2270`). **Masowa naprawa statusów = NO-GO** (nie ruszy sekcji, mislabeluje, cofa się na Traffit gdy włączony). Edycja nazwy = realny bug → `display_name`. Kontrolka statusu **działa**; przycisk „Edytuj" nie jest capability-gated (kosmetyka, backend broni `TacPlus` → 403).
- **#2 (wyszukiwarka):** Oba zgodne. Filtr FE, endpoint bez paginacji → bezpieczny. Konsultant, nie firma. **GO**, mały.
- **#3 (project_part e-Zdrowie):** Oba zgodne co do kierunku. **Enum/VARCHAR+CHECK, nie tabela słownikowa** (E5). Bramka po `client_id` (oba wiersze 115/5257), **nie po nazwie** — needle `e-zdrowia` **już dziś nie łapie** realnych nazw `E-Zdrowie`/`eZdrowie` (kończą się na -ie), więc §10 PFRON odpala się tylko dla curowanego `Centrum e-Zdrowia` (latentny bug). Reguła „reprezentatywnego zamówienia" (aktywne w dacie). **Korekta K1:** usunięcie „Otwartych rekrutacji" najpierw wymaga przeniesienia akcji. **Korekta K2:** formularz kompletacji draftu **istnieje** dla Kontraktu (`DraftCompletionModal`).
- **#4 (stawka przychodowa + sprzątanie):** Oba zgodne — pkt 1 **w większości zrobiony** (inline `rate_client` z „ustaw stawkę", admin+manage_finance). Pkt 2/3 czyste. **Codex dołożył 2 realne drobne bugi** (patrz sekcja 5): `/mc` hardcode i `0`-jako-brak.
- **#5 (zakończenie + sync):** Oba zgodne — większość istnieje, rdzeń to **jeden dwukierunkowy serwis** Contract↔Order, data przyszła nie archiwizuje od razu, B2B bez zmian. **Codex dołożył realne higieniczne bugi** (sekcja 5): duplikat Activity, brak `required` na dacie, limit 100 w archiwum, historia liczona z żywej stawki, TAC nieograniczony na terminacji.

---

## 5. Realne drobne bugi, które Codex słusznie wykrył (a ja pominąłem/niedoważyłem)

Warte naprawy **przy okazji** implementacji odpowiednich ticketów. Severity skalibrowane do skali.

| Bug | Gdzie | Severity | Fix |
|-----|-------|----------|-----|
| **`0` traktowane jak brak** — `order.rate_client **or** contract.rate_client` gubi legalną stawkę = 0 | `client_orders.py:121, 359-361` | niska (rzadkie) | zmień `or` → `is not None` (wiersz historii już to robi dobrze, `OrdersAndContractsTab.tsx:924`) |
| **Etykieta `/mc` zahardkodowana** — surowa stawka w jednostce kontraktu (h/dzień/mc) zawsze „/mc"; Alior ma stawki godzinowe | `OrdersAndContractsTab.tsx:644,673,925` | niska (kilku klientów) | najpierw wystaw `rate_unit` w `ClientOrderRead`/`ContractWithOrdersRead`, potem etykietuj z niego |
| **Duplikat `Activity('terminated')`** przy każdym retry/replay terminacji | `contracts.py:2923-2935` | średnia (łatwo wywołać) | guard `if contract.terminated_at is not None → 409/no-op` (tani, zamiast pełnej idempotencji) |
| **Modal terminacji pozwala wysłać bez daty** (brak `required`, puste→null→`today()`) | `TerminateContractModal.tsx`, `ContractTerminationDialog.tsx` | średnia (jakość danych) | `required` na inpucie + walidacja w schemacie |
| **Archiwum ucięte do 100** (i `total_placements` liczy uciętą listę) | `clients.py:399, 486` (i `436` lost_jobs) | niska (>100 zakończeń/klient) | paginacja lub jawny „pokaż więcej" gdy budujesz zakładkę Archiwum (#5 krok 2) |
| **Historia liczona z żywej, edytowalnej stawki** — edycja `rate_client` przepisuje przeszłość; ignoruje `client_rate_schedule` | `clients.py:70-85, 419` | średnia (raportowanie) | snapshot stawki przy zakończeniu, gdy budujesz Archiwum |
| **Obchód audytu przez PATCH** — `terminated_at`/`reason`/`end_date` da się ustawić `PATCH /contracts/{id}` z pominięciem Amendment+Activity | `contracts.py:1499-1500`; `schemas/contract.py:169-171` | niska | usuń pola zakończenia z `ContractUpdate` (kierować przez `/terminate`) |
| **Granica dnia UTC, nie Europe/Warsaw** — lifecycle używa naiwnego `date.today()` mimo istniejącego `BUSINESS_TZ` + `app/core/scheduling.py` | `contracts.py`, `contract_alerts.py`, `dl_portal_expiry_scanner.py` | niska (okno ~1-2h/dobę) | użyj istniejącego helpera Warsaw (near-zero koszt) przy pracy nad #5 |
| **Off-by-one: terminate vs scheduler** — terminate: `end_date==today` = ended; oba demony: `< today` (ostatni dzień włącznie) | `contracts.py:224` vs `contract_alerts.py:71`, `dl_portal_expiry_scanner.py:114` | niska (dryf badge o 1 dzień) | ujednolić regułę (włącznie) przy #5 |
| **TAC nieograniczony na terminacji** — zwykły TAC może zakończyć **dowolny** kontrakt dowolnego klienta (bez scope), a nie może tknąć `ClientOrder` | `contracts.py:2857,2880` vs `client_orders.py:433...` (`DlAssignedOrAdmin`) | do decyzji | świadoma decyzja: czy zawęzić terminate do przypisanych DL/admin |

Żaden z tych bugów nie psuje pieniędzy ani nie jest eksploatowalny przez zaufany zespół wewnętrzny — to higiena poprawnościowa. Ale są tanie i realne; naprawiaj je **w ramach** odpowiedniego ticketa, nie jako osobne P0.

---

## 6. Nowe rekomendacje — co powinniśmy zrobić (skalibrowane do skali)

Zgadzam się z Codexem, że **nie robimy jednego wielkiego PR-a** i że #1 (masowa naprawa) oraz #5 (jako monolit) idą do przeróbki. Ale odchudzam proces do realiów solo-deva.

### Faza A — szybkie wygrane (rób teraz, niskie ryzyko)
1. **#2 wyszukiwarka** — filtr FE w `OrdersAndContractsTab` (reuse `useDebouncedValue` z `ProjectsTab`), match `candidate_name` ∨ `order.title` ∨ `contract_id`; wymuś rozwinięcie historii; diacritic-insensitive. **S.**
2. **#4 pkt 2+3** — usuń span „Contract {id}" i blok „z rekrutacji" (`OrdersAndContractsTab.tsx:597-599, 716-721`). Czyste, zero utraty danych. **S.**
3. **#4 bugi przy okazji** — `or`→`is not None` (0-jako-brak) i wystaw `rate_unit` + popraw etykietę „/mc". **S.**
4. **#1 bug 4 (nazwa)** — edycja kieruje na `display_name` (dodaj do `ClientUpdate`, formularz wysyła `display_name`); wszyscy konsumenci już czytają `coalesce(display_name, name)`. **Bez migracji. S/M.**
5. **#1 kosmetyka** — capability-gate przycisku „Edytuj" (usuwa mylące 403 dla nie-TAC). **S.**

### Faza B — decyzje przed budową (tanie, ale konieczne)
6. **#1 sekcje vs status** — decyzja produktowa: (a) UI do zmiany `scope.category` (endpoint `client_directory.py:547` istnieje, tylko poluzować RBAC + podpiąć FE) — **lekka, rekomendowana**; albo (b) przebudowa „status steruje sekcją" — ciężka, rozbija multi-scope. **Odrzuć masowy backfill statusów.** Jeśli chcesz data-fix przynależności — celuj w `scope.category`, nie `status`.
7. **#1 status a Traffit** — potwierdź, czy `TRAFFIT_SYNC_ENABLED` jest ON na prod (jeśli tak, ręczna edycja statusu klientów z Traffita cofa się; wtedy trzeba usunąć `status` z `DO UPDATE SET` importera albo osobna kolumna). Jeśli OFF — problem znika.
8. **#3 bramka e-Zdrowie** — najpierw **scal duplikaty 115/5257** (`merged_into_client_id` istnieje), potem bramkuj po `client_id`, nie po nazwie. Przy okazji napraw latentny bug needle `e-zdrowia` (nie łapie realnych nazw).

### Faza C — większe buildy (po decyzjach)
9. **#3 project_part** — kolumna **enum/VARCHAR+CHECK** nullable na `client_orders` + migracja + **mirror w `entrypoint.sh`** (wzorzec `filled_at` już tam jest); wpięcie w `NewContractorOrderDialog` (+ `DraftCompletionModal` — istnieje!); reguła „aktywne zamówienie w dacie" wystawiona na `ActiveConsultantItem`; filtr w Profilu tylko dla e-Zdrowie. **Przed usunięciem „Otwartych rekrutacji" przenieś `CloseJobAsLostModal` (twarda strata) i add-candidate do Projektów.** **L.**
10. **#5 zakończenie** — jeden serwis `terminate_engagement(contract_id, end_date, reason, actor)` w transakcji: kontrakt + pasujące zamówienia, **idempotentny** (guard `terminated_at is not None`), data przyszła nie archiwizuje od razu, B2B nietknięty. Potem 3 powierzchnie UI (przycisk „Zakończ" w Zamówieniach, „Zakończ projekt" w Kontraktach z pickerem przy 2+ projektach, zakładka „Archiwum konsultantów" z `historical.placements` + kolumna kosztu z `rate_candidate`). Przy okazji: `required` na dacie, snapshot stawki, paginacja archiwum, granica Warsaw. **Bez migracji. L.**

### Czego świadomie NIE robimy (odchudzenie względem Codexa)
- ❌ Pełna optymistyczna współbieżność (`expected_version`/`If-Match`) na terminacji — dla tempa ludzkiego wystarczy tani guard idempotencji + `required` data. (Jeśli kiedyś pojawi się realny double-submit, dołóż `SELECT FOR UPDATE` — jedna linia.)
- ❌ Dedykowana tabela słownikowa `client_order_parts` — enum wystarczy (E5).
- ❌ Osobna capability `END_ENGAGEMENT` + formalny ADR + shadow-read jako obowiązkowy proces — dla solo-deva wystarczy decyzja w tym dokumencie + zwykły PR. (TAC-scope terminacji: świadoma decyzja tak/nie, ale bez budowania nowej maszynerii capability, jeśli obecny `TacPlus` jest akceptowalny.)
- ⚠️ 8 osobnych PR-ów Codexa → realnie **~5-6 PR-ów** (Faza A można zbić w 2-3 PR-y; #3 i #5 po jednym większym każdy). Batchuj config/migracje, bo każdy push = pełny rebuild Coolify.

---

## 7. Bottom line

- **Analiza Codexa jest wiarygodna** — niezależnie potwierdza mój fundament i **dokłada realną wartość**: ~10 drobnych, prawdziwych bugów higienicznych, które przeoczyłem lub niedoważyłem, oraz **jedną korektę mojego błędu** (usunięcie „Otwartych rekrutacji" nie jest bezpieczne).
- **Ma kilka nieścisłości** (Traffit „włączony" bezwarunkowo, PATCH ustawia status, retry dubluje aneks, wymaga „lessons", tabela słownikowa, 2-3 wiersze) — żadna nie zmienia strategicznych wniosków, ale warto je znać, żeby nie ścigać nieistniejących problemów.
- **Jest lekko przeważona ciężarem** dla skali tego narzędzia — moja Faza A–C powyżej to lżejsza, wykonalna solo wersja tego samego planu.
- **Zgoda co do meritum obu audytów:** zaakceptuj cele biznesowe #1–#5, odrzuć dosłowną implementację #1 (masowa naprawa) i #5 (monolit), zacznij od Fazy A, rozstrzygnij decyzje z Fazy B, potem #3 i #5.

*Weryfikacja: 6 agentów adwersaryjnych, 146 wywołań narzędzi, commit `e228b601` (ten sam co audyt Codexa). Każdy werdykt z cytatem `plik:linia`. Korekty do mojej wcześniejszej analizy naniesione w [klienci-tickety-analiza.md](klienci-tickety-analiza.md).*
