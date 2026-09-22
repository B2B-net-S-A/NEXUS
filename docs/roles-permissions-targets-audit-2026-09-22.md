# Audyt ról, uprawnień i targetów — 22.09.2026

Zakres: kod (`main` @ e87c15f8e) + stan produkcji (SQL tylko do odczytu, 22.09).
Nic nie zostało zmienione ani w kodzie, ani na produkcji.

## 1. Kto jest w organizacji (produkcja)

44 aktywne konta z 251.

| Rola główna | Aktywni | Uwagi |
|---|---|---|
| admin | 6 | 4 z nich mają `can_delete_clients` |
| recruiter | 16 | 7 kont z importu Traffita ma pustą tablicę `roles`, 5 nigdy się nie zalogowało |
| delivery_lead | 8 | 3 to hybrydy DL + TAC (90, 91, 101) |
| talent_community_manager | 5 | 1 hybryda TCM + sourcer |
| sourcer | 4 | |
| tac | 2 | TAC łącznie ma 6 osób (z hybrydami); nr 88 nieaktywny od 02.07 |
| head_of_recruitment | 2 | 1 hybryda HoR + TAC (11) |
| finance | 1 | |
| user (legacy) | 0 | migracja 0210 zakończona |

- Delivery Leadzi 90, 91 i 145 nie mają żadnego klienta.
- Dwa przypisania DL ↔ klient wskazują na nieaktywne konta (użytkownicy 5 i 197).
- DynaReporter (`allowed_sections`) jest pusty u wszystkich poza jednym DL, czyli zgodnie z wygaszeniem.

## 2. Model uprawnień: cztery warstwy

1. **Sekcja** (`rbac_role_section_permissions` + nadpisania per osoba): Sourcing · Pipeline · Delivery · Insights · Finance · System. Jest sufitem, a nie przyznaniem.
2. **Akcja** (`rbac_role_action_permissions`): generator B2B i potwierdzenie podpisu.
3. **Guard roli na trasie** (aliasy z `deps.py`, `candidate_access.py`, `recruitment_access.py`, `contract_access.py`): około 40 aliasów i około 30 zbiorów ról wpisanych na sztywno.
4. **Capability analityczne** (`analytics/capabilities.py`), przycinane sekcjami Insights i Finance.

Do tego zakres danych (`resolve_dashboard_scope`), członkostwo w rekrutacji, portfel DL i flagi imienne (`can_delete_clients`).

### Macierz sekcji: kod vs produkcja

| Rola | Sourcing | Pipeline | Delivery | Insights | Finance |
|---|---|---|---|---|---|
| admin | W | W | W | W | W (+System) |
| finance | W | W | W | R | W |
| head_of_recruitment | W | W | – | W | – |
| delivery_lead | W | W | W | R | – |
| talent_community_manager | W | W | **R w kodzie / W na produkcji** | R | – |
| tac, recruiter, sourcer | W | W | – | R | – |

Na produkcji są **dwie różnice względem kodu**, obie wprowadził admin 82 między 03 a 04.09: TCM ma `delivery = write` i `b2b_contract_generator = manage` (w kodzie odpowiednio `read` i `view`). Nadpisań per osoba: 0.

### Co każda rola realnie może (skrót)

| | admin | HoR | DL | TCM | finance | TAC | recruiter | sourcer |
|---|---|---|---|---|---|---|---|---|
| Kandydaci: odczyt / zapis | ✓/✓ | ✓/✓ | ✓/✓ | ✓/✓ | ✓/✓ | ✓/✓ | ✓/✓ | ✓/✓ |
| Tworzenie / edycja rekrutacji (`TacPlus`) | ✓ | – | ✓ | – | – | ✓ | – | – |
| Strona `/jobs/new` (intake z maila) | ✓ | – | ✓ | – | – | – | – | – |
| Ruchy w pipeline, zatrudnij / odrzuć | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | tylko bez etapów końcowych |
| Klienci, kontrakty, zamówienia | ✓ | – | ✓ | odczyt (prod: zapis) | ✓ | – | – | – |
| Cykl życia zamówień | ✓ | – | ✓ | – | ✓ (+MANAGE_FINANCE) | – | – | – |
| Kwoty klienta | ✓ | – | własny portfel | – | ✓ | – | – | – |
| Finanse (moduł) | ✓ | – | – | – | ✓ | – | – | – |
| Insights → Rada | ✓ | ✓ | – | – | ✓ | – | – | – |
| Generator B2B, stawki w dokumencie | ✓ | ✓ | własny portfel | ✓ | ✓ | ✓ | ✓ | ✓ |
| Potwierdzenie podpisu B2B | ✓ | – | ✓ | ✓ | – | ✓ | – | – |
| Reguły CV, karta klienta | ✓ | – | ✓ | – | – | – | – | – |
| Ranking rekruterów (analityka) | ✓ | ✓ | **–** | ✓ | ✓ | ✓ | ✓ | ✓ |

## 3. Targety per rola

### Co dziś obowiązuje

| Cel | recruiter | sourcer | TAC | DL | HoR / TCM / fin | Źródło |
|---|---|---|---|---|---|---|
| **Widget KPI Coach** (topbar) | | | | | | `kpi_catalog.py` |
| Rozmowy / dzień | 15 | 15 | 15 | – | – | CloudTalk, **wyłączony** |
| Weryfikacje / dzień | 4 | 4 | 4 | – | – | |
| Nowi kandydaci / dzień | 3 | 5 | 2 | – | – | |
| Rekomendacje (CV) / tydzień | 15 | **brak** | 12 | – | – | |
| Placementy / miesiąc | 2 | 1 | 3 | – | – | |
| **Panel „Moje KPI”** (tabela w bazie) | | | | | | `kpi_role_defaults` |
| Weryfikacje / dzień | 4 | 4 | 4 | 0 | – | |
| Precyzja / miesiąc | 75% | 75% | 75% | 0 | – | |
| Placementy / miesiąc | **1** | **1** | **1** | 0 | – | |
| Nowe CV / dzień | **5** | **brak** | **5** | – | – | |
| **Nagrody i poziomy** | | | | | | |
| Wyścig miesięczny (1500 zł) | ≥4 weryf./dzień, ≥75%, ≥2 placementy | tak | tak | – | – | `competitions.py:71` |
| Liga kwartalna (5000/3000/2000 zł) | min. 1/2/3 placementy wg miesiąca | tak | tak | – | – | `insights_scoring_config` |
| Liga DL | – | – | – | hit ratio ≥30%, ≥3 placementy | – | |
| Ścieżka Senior / Expert | 6/6 lub 12/12 · 12/6 lub 24/12 | tak | tak | – | – | |
| Power Calling | 3 weryf./dzień (raport) **albo** 15 rozmów/dzień (alert 11:45) | | | | HoR dostaje tabelę | |

- Osobistych targetów (`user_kpi_targets`): 0.
- Kampanii rekrutacyjnych: 0.
- Progi ścieżki rozwoju nigdy nie były edytowane (wartości z seeda z 01.09).

## 4. Niespójności (zweryfikowane)

Priorytet: **P1** = daje złe liczby albo zły dostęp dziś, **P2** = przyciski lub trasy, które kończą się 403, albo martwe reguły, **P3** = porządki.

### Targety

**T1 · P1 · Dwa systemy KPI dają tej samej osobie różne cele.**
- Placementy na miesiąc: widget mówi recruiter 2 / TAC 3 / sourcer 1, panel mówi 1 / 1 / 1. Wyścig z nagrodą wymaga 2, a próg seniora to 1 na miesiąc.
- Nowe CV na dzień: widget mówi sourcer 5 / recruiter 3, panel recruiter 5 i nic dla sourcera. Kierunek jest odwrotny.
- **Jak poprawić:** jeden katalog KPI (`kpi_catalog` jako jedyne źródło) z identyfikatorami panelu jako aliasami, jeden zestaw liczb uzgodniony z Arturem i migracja danych `kpi_role_defaults` (usuwa stare `daily_activity_count` i `weekly_screenings` z 0034 i zasiewa nowe identyfikatory).

**T2 · P1 · Codzienny raport „PowerCalling 11:45” mierzy coś, czego nie ma.**
- CloudTalk wyłączony od 28.07, tabela `calls` ma 0 wierszy w 60 dni.
- Mimo to przez 30 dni poszły 44 tabele do HoR z „0/15 ❌” przy każdym rekruterze i 268 alertów indywidualnych (do 17.09). Wszystkie nieprzeczytane.
- Trigger nie sprawdza `CLOUDTALK_ENABLED` (`notification_triggers.py:441`).
- Target „Rozmowy dziś 15” w widgecie jest z tego samego powodu nieosiągalny.
- **Jak poprawić:** trigger i KPI `daily_completed_calls` wyłączone, gdy `CLOUDTALK_ENABLED=false`. Test: brak rozmów i wyłączona telefonia oznaczają zero powiadomień.

**T3 · P1 · Osoba z kilkoma rolami dostaje target 0.**
- `resolve_target` patrzy tylko na główną rolę (`kpi_engine.py:225`, `kpi_panel.py:378`).
- Przykład z produkcji: 145 to rekruter z rolą DL, 90, 91 i 101 to DL z rolą TAC. Widget ich wpuszcza (`kpis.py:79`), ale wszystkie targety wychodzą 0, więc nic nie pokazuje. Komentarz w kodzie wprost mówi, że taki ktoś „powinien widzieć swoje KPI”.
- Wyścigi i Hall of Fame liczą role dodatkowe, a ścieżka rozwoju i nudge KPI nie.
- **Jak poprawić:** jedna funkcja `target_for(user, kpi)` po `get_all_roles()` (maksimum z ról) i jedno miejsce opisujące tę regułę.

**T4 · P2 · „Weryfikacje na dzień” mają trzy progi:** 3 (raport Power Calling), 4 (KPI) i 4 (wyścig, na sztywno w `competitions.py:71`).
- Wyścig i panel zespołu (75% na sztywno w `kpi_team.py:40`) nie czytają bazy, więc zmiana targetu w bazie ich nie rusza.
- Ustawienie `power_calling_min_per_day` w adminie DynaReportera nie jest nigdzie czytane.
- **Jak poprawić:** wyścig i panel zespołu czytają te same wartości co KPI, a martwe ustawienie trzeba usunąć.

**T5 · P2 · Targetów nie da się zmienić w aplikacji.** Dokumentacja twierdzi, że można („bez deploya”), ale żadna trasa ani ekran nie zapisuje do `kpi_role_defaults` ani `user_kpi_targets`. **Jak poprawić:** prosty edytor w Ustawienia → Rekrutacja (admin i HoR), z historią zmian.

**T6 · P2 · Obietnice bez pokrycia.**
- TCM ma capability „własne KPI rekrutacyjne”, ale nie ma żadnego targetu.
- DL ma „własne KPI delivery”, ale nie istnieje żadne KPI delivery, a panel liczy DL jako operacyjnego z targetami 0.
- Sourcer nie ma targetu rekomendacji, choć startuje w wyścigu rekomendacji.
- **Do decyzji:** jakie cele mają TCM i DL (np. dla DL hit ratio 30% i czas do przedstawienia kandydata). Albo zdjąć capability.

**T7 · P3 · Hit ratio DL 30% jest wpisane w 6 plikach** (`competitions.py:51`, `reports.py:720`, `insights_dl_scope.py:29`, `insights_clients.py:96`, `dynareporter_delivery_lead_dashboard.py:36`, schema). Do jednej stałej.

### Uprawnienia

**U1 · P1 · Produkcja rozjechała się z kodem dla TCM.**
- W bazie TCM ma zapis w Delivery i pełny generator B2B, w kodzie i w teście (`test_section_access.py:131`) odczyt i podgląd.
- Świeże środowisko albo przywrócenie z seeda odbierze TCM te prawa bez ostrzeżenia.
- Zapis w Delivery otwiera TCM każdą trasę Delivery, której guard wpuszcza TCM (np. status kontraktu, skrzynka zamówień).
- **Do decyzji:** jeśli to świadome, przenieść do `DEFAULT_ROLE_SECTION_ACCESS` / `DEFAULT_ROLE_ACTION_ACCESS` i testów. Jeśli nie, cofnąć w panelu RBAC.

**U2 · P1 · TAC nadal jest „bramką” mimo decyzji z 22.09.**
- `TacPlus` (46 tras) w praktyce oznacza admin + DL + TAC, więc **rekruter nie założy ani nie edytuje rekrutacji**, nie zapisze ogłoszenia, nie zapisze szablonu maila i nie zatwierdzi podpowiedzi Championa.
- Pod tym samym guardem są potwierdzenie podpisu B2B i właściciel terminów rozmów (`interview_cycle.py:66`).
- Zakres zespołu DL w dashboardzie liczy się z `ClientTacAssignment` (`access_scope.py:133`). Bez przypisań TAC „zespół DL” jest pusty.
- **Do decyzji + zmiana:** zastąpić `TacPlus` jawnym `DeliveryLeadPlus` (tam, gdzie to praca DL) albo `RecruiterPlus` (tam, gdzie pracuje rekruter). Zakres DL budować z `jobs.delivery_lead_id` → rekruter i współpracownicy. Sześć osób z rolą TAC przepiąć na recruiter/DL.

**U3 · P1 (do decyzji) · Stawki wszystkich umów B2B widzi każda rola poza DL.**
- `_generator_rate_content_visible` wpuszcza bez zawężenia rekrutera, sourcera, TCM i nawet legacy `user` (`b2b_contract_generator.py:443`, `contract_access.py:199`).
- DL jako jedyny widzi stawki tylko we własnym portfelu, czyli najwięcej wie ten, kto najmniej odpowiada.
- To efekt otwarcia generatora 20.08, ale kłóci się z zasadą „TCM bez finansów”.
- **Jak poprawić:** stawki cudzych umów tylko przy `VIEW_FINANCE`, DL we własnym portfelu, autor — swoje dokumenty. `user` usunąć z krotki.

**U4 · P2 · Przycisk „Nowa rekrutacja” widzi TAC, a strona go odsyła.**
- `job.create` = `TacPlus` (przycisk, skróty `j` i ⌘⇧J), `/jobs/new` = admin + DL (`app/jobs/new/page.tsx:22`, `job_request_intake.py:80`).
- Test capability sprawdza zły endpoint.
- **Jak poprawić:** jedna capability `job.create` = `DeliveryLeadPlus`, spójna z intake.

**U5 · P2 · HoR ma „parytet z rekruterem” (17.09), ale nie wszędzie.**
- Nie może przejąć rekrutacji ani być jej właścicielem (`jobs.py:430`), choć handoff już go przyjmuje (`jobs.py:2500`, `as_owner=True`).
- Nie ma „Mojej pracy” (`dashboard_v2.py:77`), nie jest „dzwoniącym” (`candidate_contact.py:62`), nie widzi historii rekrutacji ani podpowiedzi Championa (`jobs.py:132`, `champion_suggestions.py:49`).
- We froncie `/applications` blokuje HoR (`middleware.ts:304`, `nav-registry.ts:361`).
- **Jak poprawić:** jeden zbiór „operator rekrutacji” w jednym module, używany przez wszystkie te miejsca. HoR dołączyć, jeśli decyzja z 17.09 obejmuje własność.

**U6 · P2 · Finanse: pełny zapis operacyjny w sekcjach, ale kwot zmienić nie mogą.**
- Domyślnie Finance ma zapis w Sourcing, Pipeline i Delivery, może zatrudniać, odrzucać i ruszać cykl zamówień.
- Jednocześnie zmiana kwot kontraktu i zamówienia to tylko admin (`contracts.py:1468`, `client_orders.py:912`), mimo capability `MANAGE_FINANCE`.
- CLAUDE.md mówi co innego („zapisy finansowe wymagają `manage_finance`” i „odczyt nie nadaje zapisu”).
- Nie ma też Outlooka w Ustawieniach (`settings-registry.ts:226`), choć ma tworzenie wydarzeń.
- **Do decyzji:** albo Finance = zapis kwot przez `MANAGE_FINANCE` i minimalny zapis operacyjny, albo zostaje tak jak jest, ale z poprawionymi testami (`test_finance_role_endpoint_guards.py:247,283`) i dokumentacją.

**U7 · P2 · Martwe przyznania: rola wpuszczona przez guard, ale sekcja jej to odbiera.**
- HoR na trasach Delivery: zamówienia, alerty DL, klienci.
- TAC na 31 trasach kontraktów, klientów i podpisów.
- Nie szkodzą, ale mylą każdego, kto czyta guard. Do usunięcia z aliasów (albo dać HoR odczyt Delivery, jeśli ma go mieć).

**U8 · P2 · Front sprawdza role zamiast sekcji** w ośmiu miejscach: profil klienta (`clients/[id]/page.tsx:767`), akcje zamówień (`store/auth.ts:374`), tryb operacyjny Kontraktów (`contracts/page.tsx:46`) i inne. DL z obniżoną sekcją widzi przyciski, które kończą się 403. **Jak poprawić:** do każdego warunku dodać `hasSectionAccess(user, "delivery", "write")`.

**U9 · P2 · Analityka.**
- DL nie ma capability „ranking rekruterów”, więc raport rekrutacji zwraca mu 403, choć DL jest w Hall of Fame.
- HoR nie widzi przetargów, choć TAC widzi.
- TCM ma „własne KPI”, a endpoint zwraca mu pustą listę.
- **Jak poprawić:** ujednolicić `ROLE_CAPABILITIES` z decyzjami (DL: dodać `VIEW_RECRUITMENT_RANKING`).

**U10 · P3 · Porządki.**
- Nieużywane aliasy: `ApproverPlus`, `CandidateFinanceAccess`, `ExecutiveUser`, `ContractLegalAccess`, `OnboardedUser`.
- `OperationalUser` i `RecruiterPlus` to identyczne zbiory.
- „Panel managera” w ⌘K prowadzi na `/dashboard`.
- Lista ról w UI jest kopiowana w pięciu miejscach zamiast importowana.
- Szablony maili: admin-only w UI, a zapis w API ma każdy rekruter.
- Nieaktualny CLAUDE.md: HoR w `_ORDER_LIFECYCLE_ROLES` i w gałęzi organizacyjnej `/my-clients` (w kodzie go tam nie ma).
- Resztki UI TAC poza listą rekrutacji.

### Dane kont

**D1 · P3.**
- 7 rekruterów z Traffita ma pustą tablicę `roles`; 5 z nich nigdy się nie zalogowało, a konto 88 (TAC) jest nieaktywne od 02.07. Warto przejrzeć i dezaktywować.
- DL 90, 91 i 145 bez klientów: albo przypisać, albo zdjąć rolę DL.
- Dwa przypisania klientów na nieaktywnych DL (5, 197) trzeba przepiąć, inaczej klienci nie mają alertów.

## 5. Proponowana kolejność napraw

| Paczka | Co | Wymaga decyzji? |
|---|---|---|
| **A** (od ręki) | T2 PowerCalling i target rozmów przy wyłączonej telefonii · T3 targety po wszystkich rolach · U4 jedna capability `job.create` · U8 sekcje we froncie · U9 DL + ranking · U10 porządki | nie |
| **B** | T1 + T4 + T5: jeden katalog KPI, jedne liczby, edytor targetów | tak: które liczby obowiązują |
| **C** | U2: wygaszenie TAC jako bramki (`TacPlus` → DL/Recruiter), zakres DL bez `ClientTacAssignment`, przepięcie 6 kont TAC | tak: kto zakłada rekrutacje |
| **D** | U1 TCM · U3 stawki w generatorze · U6 Finanse | tak: polityka |
| **E** | D1 porządki kont (panel admina) | tak: które konta wyłączyć |

## Pytania do Artura

1. Czy TCM ma mieć zapis w Delivery i pełny generator B2B? Tak jest dziś na produkcji, inaczej niż w kodzie.
2. Czy rekruter ma sam zakładać i edytować rekrutacje? Dziś nie może, bo guard `TacPlus` wpuszcza tylko admina, DL i TAC.
3. Czy stawki wszystkich umów B2B mają być widoczne dla rekruterów, sourcerów i TCM?
4. Finanse: czy mają zmieniać kwoty kontraktów i zamówień i czy mają mieć zapis w rekrutacji?
5. Które liczby KPI obowiązują: placementy na miesiąc 1 czy 2, nowe CV sourcera 5 czy brak? Czy HoR, TCM i DL mają mieć własne targety?

## Decyzje Artura (22.09.2026)

| # | Temat | Decyzja |
|---|---|---|
| 1 | TCM | Delivery = **odczyt** (cofnąć zapis z produkcji), generator B2B = **pełny** (manage), zapisane w kodzie i testach |
| 2 | Rekrutacje | Zakłada **admin / DL** (`/jobs/new`). **Rekruter prowadzący i współpracownicy edytują swoją rekrutację** (opis, ogłoszenia, Champion). TAC przestaje być warunkiem |
| 3 | Stawki B2B | Rekruter, sourcer i TCM widzą stawki **tylko w umowach, które sami wygenerowali, albo z rekrutacji, które prowadzą**. Wszystkie stawki: admin i Finanse; DL: swój portfel. Legacy `user` usunięty z listy |
| 4 | Finanse | **Zmieniają kwoty** kontraktów i zamówień przez `MANAGE_FINANCE`; pełny dostęp operacyjny z 19.08 zostaje |
| 5 | Placementy / mc | **1 dla wszystkich** (rekruter, sourcer, TAC); wyścig z nagrodą **zostaje przy 2**, a próg przechodzi do konfiguracji |
| 6 | Nowi kandydaci / dzień | **5 dla wszystkich** (rekruter, sourcer, TAC) |
| 7 | Cele liderów | **DL**: hit ratio 30% i placementy w portfelu. **HoR i TCM**: cele zespołowe (suma celów ludzi), bez osobistych |
| 8 | Konta TAC | **Zostają bez zmian**; kod przestaje wymagać TAC do czegokolwiek |
| 9 | Nieużywane konta | **Wyłączyć** 236, 237, 238, 240, 243 (nigdy niezalogowani) i 88 (TAC, nieaktywny od 02.07) |
| 10 | Realizacja | **Jeden PR** ze wszystkimi decyzjami i poprawkami od ręki |
