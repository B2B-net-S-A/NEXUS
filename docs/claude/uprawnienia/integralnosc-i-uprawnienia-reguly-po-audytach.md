# Integralność i uprawnienia — reguły po audytach Codexa 13–14.09.2026 (PR 1 i PR 2)

<!-- indeks: feedback z rozmowy, blokady wiersza kontraktu, bramka sekcji tras, CV nie są kasowane, kursor M365, statystyki liczą osoby, „obecny” kontrakt, wersja procesu przy ruchu -->

Plan i status: `docs/uat/08-audyty-codex-2026-09-14.md`. Reguły, które łatwo
cofnąć „przy okazji”:

- **Feedback z rozmowy jest przypięty do wydarzenia, na które autor ma wgląd.**
  `interview_feedback.py`: router za `PIPELINE_SECTION_DEPENDENCIES`;
  `_bind_feedback_to_event` sprawdza `user_can_view_event` (właściciel, uczestnik,
  role z odczytem kalendarza), potem spójność `event.candidate_id`/`job_id`
  z payloadem (422), a rekrutację dziedziczy z wydarzenia i przepuszcza przez
  `ensure_job_membership`. `needs_attention` zdejmuje autor feedbacku albo ktoś,
  kto może edytować wydarzenie. Do 14.09 dowolny `event_id` z cudzym kandydatem
  przechodził bez sprawdzenia. Uczestnik cudzego spotkania MUSI móc zapisać
  feedback — dlatego bramka to odczyt, nie mutacja (`test_interview_feedback_access.py`).
- **Zmiana statusu kontraktu blokuje wiersz** (`with_for_update()` w
  `update_contract`, `update_contract_status`, `void_contract_endpoint`,
  `activate_contract`, `reopen_contract_endpoint`, `terminate_contract`,
  `create_contract_amendment`, `bulk_mark_ended`, `bulk_extend_contracts`;
  `finalize_contract_draft` przez `_load_contract_with_relations(for_update=True)`;
  pilnuje test AST w `test_contract_status_concurrency.py`). Bez tego `void`
  i równoległy `revert` na przeterminowanym obiekcie oba przechodziły, a ostatni
  zapis wygrywał. `resync_contract` odświeża pola cyklu życia po blokadzie —
  obiekt bywa załadowany przed nią. **Kolejność blokad jest jedna: kontrakty →
  zamówienia** (PR2, 23.09.2026 — do tego dnia writery zamówień blokowały
  `client_orders` przed `contracts`, a `commit_order_write` → `resync_contract`
  brał kontrakt dopiero przy commicie: ABBA z handlerami kontraktu). Każdy
  writer zamówień woła `contract_lifecycle.lock_contract_then_orders`
  (kontrakty rosnąco, potem zamówienia rosnąco; kontrakty zamówień doczytuje
  sam) albo `lock_order_group_lines` PRZED pierwszą blokadą i zapisem
  zamówienia; tworzenie zamówienia blokuje kontrakt przed INSERT-em. Pilnuje
  tego test AST `test_order_writer_lock_order.py` — nowa funkcja z `FOR UPDATE`
  na `ClientOrder` bez helpera = czerwone CI (wyjątki z powodem w `EXEMPT`).
- **Zakończenie współpracy przechodzi przez maszynę stanów**
  (`_status_after_termination`, `/terminate` i aneks `early_termination`, od
  15.09.2026). Do tego dnia obie ścieżki liczyły status z samej daty końca:
  jedno „Zakończ współpracę” wskrzeszało unieważnioną umowę (`void → ended`,
  przy przyszłej dacie `active`), a szkic z przyszłą datą dostawał `active`
  z pominięciem bramki aktywacji. Teraz `void` = 409 przed jakimkolwiek zapisem,
  a szkic/`ready_for_signature` z przyszłą datą zachowuje status.
- **Każda zalogowana trasa `/api/**` ma bramkę sekcji albo opisany wyjątek**
  (`test_section_ceiling_contract.py`, F02, 15.09.2026). Bramka roli
  (`require_roles`, `OperationalUser`, `RecruitmentReadAccess`…) NIE sprawdza
  sekcji — konto z odebraną sekcją dalej wołało ok. 20 routerów (pulpity, KPI,
  Cortex, priorytety, maile odmów, obecność, struktura zespołu, stary
  DynaReporter — oba usunięte 23.09.2026). Nowy router: `dependencies=` z `app.api.section_access`
  (`require_section_access`, `_any` gdy zapisujący siedzą w różnych sekcjach,
  `_any_read` dla wspólnych odczytów) albo wpis do `_SECTIONLESS_ALLOWLIST`
  z powodem. Front montuje widżety według `hasSectionAccess`, nie samych ról —
  inaczej odebrana sekcja daje serię kart błędu 403 (`RoleDashboard`,
  `useMyKpis`). `POST /api/fireflies/sync` (dawniej GET —
  zapisuje notatki, więc musi przejść bramkę zapisu).
- **Usunięcie kandydata NIE kasuje żadnych CV** (decyzja Artura 26.09.2026:
  „nie usuwać nigdy żadnych CV”, RODO pomijamy). Pliki w magazynie (CV, dokumenty,
  snapshoty etapów, wejścia generatora), wygenerowane CV i zgłoszenia z formularza
  z CV zostają; do rejestru `cv_source_cleanup` nic z usunięcia nie trafia (do
  26.09 szły tam wszystkie klucze osoby). Nie dokładaj kasowania CV do usuwania
  kandydata ani do żadnego automatu bez wyraźnego polecenia Artura.
- **M365: kursor folderu przesuwa się tylko po czystym biegu folderu.** Graph
  daje `deltaLink` dopiero na ostatniej stronie, więc „ostatnia czysta strona”
  nie istnieje — przy jakimkolwiek błędzie importu folder zostaje na starym
  kursorze (upserty są idempotentne), a `last_sync_status = error` z liczbą
  błędów. Trwale zepsuta wiadomość = folder w pętli co 30 min — to sygnał
  w sondzie, nie stan do wyciszenia.
- **Statystyki liczą osoby, nie wiersze etapów.** Uzgodnienie placementów
  deduplikuje próby (`DISTINCT ON (candidate_id, job_id)`, liczba prób
  w `verifier_anchored.attempts`, totale osobnym zapytaniem; klucz złączenia
  `COALESCE(job_id, 0)`, bo PG16 odrzuca `IS NOT DISTINCT FROM` w FULL JOIN).
  Raport DL czyta `analytics_first_milestones.first_reached_at`; wakaty i fill
  rate `count(DISTINCT candidate_id)`. `_sum_finance` oznacza sumę jako
  `partial` z licznikami `contracts_without_cost_leg`/`…revenue_leg`, a ranking
  klientów (`margin_lookup_pln`/`revenue_lookup_pln` → `(sumy, incomplete,
  unpriced)`) oznacza klienta z kontraktem bez jednej nogi jako niepełnego,
  ale zostawia SUMĘ CZĘŚCIOWĄ z wycenionych kontraktów — jak kafel na profilu
  (`active_mrr_unpriced_contracts`); `None` daje wyłącznie brak kursu NBP.
  Podpisana umowa B2B jest aktywna z samą stawką kosztową do czasu zamówienia,
  więc `None` dla całego klienta zdejmowałoby kwoty z większości rankingu
  i z całego wiersza DL w przeglądzie admina. Źródła
  z Traffita idą jako `candidate_source_events` (`note` = `traffit:source:<id>`,
  idempotentnie), więc raport źródeł je widzi. Źródło bez daty ma
  `captured_at` = data importu i dopisek `UNDATED_IMPORT_NOTE_MARK` na końcu
  `note` (przeżywa przycięcie do 500 znaków) — raport źródeł i metryka v1
  pomijają je w oknie (`undated_import_event`), inaczej pełny sync wrzucałby
  historię w „ostatnie 30 dni". Raport niesie model atrybucji (`multi_touch`,
  wiersze się nie sumują), `unique_candidates` i pokrycie nowych kandydatów
  bez źródła. Stary `GET /api/reports/board` usunięty (15.09) — liczył
  powtórne zatrudnienia i nie miał konsumenta; kokpit Rady to `/api/insights/board`.
- **Monitoring nie może być zielony bez odczytu:** `sentry-daily-monitor` bez
  tokenu = `::error::` + `exit 1`, częściowy digest wysyła i kończy `exit 1`;
  deploy ma krok `/api/health/alembic` (bookmark bazy == heads kodu,
  `orphaned == []`) — czerwony deploy przy dryfie jest zamierzony.
- **„Obecny" kontrakt = start nie później niż dziś ALBO brak daty startu —
  JEDNA reguła na każdej powierzchni**
  (`contractor_identity.is_current_contract`/`current_contracts`, UAT B46, PR 2;
  pusta data od 18.09.2026): profil klienta (kafel „Aktywne MRR", liczniki),
  zakładka Analityka (`/my-clients/{id}/dashboard`), ranking Rady
  (`insights_clients`), przegląd admina, licznik katalogu klientów
  (`client_directory.py` — to on jest lustrem tej reguły w SQL i jedynym
  miejscem, w którym może się rozjechać). **„Planowany" to twierdzenie
  o PRZYSZŁOŚCI i wymaga daty, która jeszcze nie nadeszła**; pusta data jest
  brakiem WIEDZY, a konsultant nie przestaje pracować dlatego, że nikt nie
  wpisał dnia rozpoczęcia. Audyt 18.09.2026 zmierzył cenę pierwszej wersji:
  u klienta 15 trzy AKTYWNE kontrakty z żywymi liniami zamówień siedziały
  w „Planowanych", czyli 13 920 PLN/mc (54% marży klienta) poza „Aktywnym MRR"
  przy kaflu deklarującym komplet (`unpriced = 0`). Profil podstawia datę
  reprezentatywnego zamówienia (`fallback_start`), więc umowa bez własnej daty,
  ale z zamówieniem startującym za tydzień, zostaje planowana NAPRAWDĘ.
  Kontrakt z przyszłym startem jedzie na profilu OSOBNO jako „Planowani" —
  z tą samą redakcją kwot co „Obecni". Pierwsza wersja poprawki zmieniła tylko
  profil i ten sam klient pokazywał inną marżę w sąsiedniej zakładce; pilnuje
  tego `test_margin_rounding_parity.py` (kontrakt o przyszłym starcie
  w fixture) i `test_contract_current_without_start_date.py`.
  **Szeregi czasowe (`insights_board`, `insights_board_yoy`) świadomie wymagają
  daty startu** — bez niej nie da się umieścić kontraktu na osi miesięcy.
- **Stan ekranu w adresie:** `/candidates/search` trzyma request w `?s=`
  (`lib/candidate-search-request.ts` — tylko pola o kształcie zgodnym z bazą,
  bo adres pisze użytkownik), porównanie kandydatów wraca z `?sel=`,
  Administracja w Ustawieniach ma `?sub=`, kalendarz otwiera `?event=`
  (+`&action=feedback`) i zdejmuje parametr po zamknięciu albo nieudanym
  odczycie — efekty na WARTOŚCI parametru (miękka nawigacja).
- **Ruch w pipeline ma opcjonalne `expected_state_version`** (`StageMove`,
  F05): rozjazd z `RecruitmentProcess.state_version` pod blokadą = 409
  `PIPELINE_VERSION_CONFLICT` bez zapisu; `None` = bez sprawdzenia (importy,
  ruchy zbiorcze). Karta kanbanu i odpowiedź ruchu niosą
  `process_state_version` (0 = brak procesu; jedno zapytanie hurtowe
  `_process_state_versions`); POJEDYNCZE ruchy z tablicy, doków i warsztatów
  (screening, CV, rozmowy) ją odsyłają, zbiorcze (`checkVersion: false`) nie.
  409 = toast „przesunięty przez kogoś innego”, odświeżenie tablicy (oba
  klucze) i historii doku, BEZ ponowienia (`lib/pipeline-version-conflict.ts`).
  Karta bez liczby NIE wysyła wersji (zgadnięte 0 = fałszywy konflikt).
  `POST /api/auth/refresh` przyjmuje token WYŁĄCZNIE w ciele (F06).
- **`finance_trend` nie miesza źródeł:** każdy punkt niesie `basis`
  (`legacy_monthly_report` | `contracts`) i osobne pola (`mrr` tylko live,
  `monthly_revenue`/`result_after_other_costs` tylko legacy); trend kotwiczony
  na końcu okresu (`end=`), a `source_watermarks`/`quality` czytają świeżość
  syncu Traffita (36 h jak `checks.traffit`).
- **Uczestnik wydarzenia kalendarza ma DWA kształty:** tekst (wydarzenia z NEXUS)
  albo `{address, name}` (synchronizacja M365). Renderuj wyłącznie przez
  `lib/calendar-attendees.ts` (`attendeeLabel`) — obiekt wstawiony wprost wywracał
  cały kalendarz (React #31) dla każdego wydarzenia z Outlooka (retest 15.09.2026).
- **Listy z „Pokaż więcej" idą po `offset` w API** (dzwonek, Targ, pule
  talentów): dzwonek podnosi `limit` zamiast doklejać strony — „nieprzeczytane
  najpierw" przetasowuje kolejność po kliknięciu, więc doklejanie dawało
  duplikaty.
