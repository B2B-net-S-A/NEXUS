# Audyt NEXUS 25.09.2026 — runda 1

> **Baza:** `eed680914` · **Status:** naprawione w PR #1833 (merge 8d9755da2, na produkcji 25.09.2026 16:17 UTC). Martwy kod świadomie zostawiony (decyzja Artura).
> Oryginalny raport (prywatny artefakt): https://claude.ai/artifact/BtnT7zb5kwPk5gNLvg56x6
> Reguły wynikające z naprawy: `CLAUDE.md`, sekcja „Audyt 25.09.2026 — reguły po naprawie”.

NEXUS · commit eed680914 · 25.09.2026

# Pełny audyt aplikacji: błędy i martwy kod

8 agentów głównych i 9 pod-agentów czytało backend (422 tys. linii Pythona) i frontend (435 tys. linii TS). Tylko odczyt: nic nie zmieniono, nic nie wysłano na produkcję. Pozycje oznaczone „potwierdzone” sprawdziłem sam w kodzie po raporcie agenta, a jedną odtworzyłem skryptem. Pozostałe to twierdzenia agentów, z przeczytanym kodem, ale bez mojej weryfikacji.   **4** krytyczne: pieniądze, utrata danych, bezpieczeństwo **12** wysokie: blokują pracę albo kłamią na ekranie **~25** średnie i niskie, do naprawy przy okazji **~9 tys.** linii martwego kodu (BE ~5k, FE ~4k)

## Czeka na decyzję (stan w chwili raportu)

- **Czy naprawiam?** Proponuję jeden PR z 16 pozycjami krytycznymi i wysokimi (15 potwierdziłem w kodzie), każda z testem, który najpierw pada. Martwy kod osobnym PR-em, bo dotyka kilkudziesięciu testów.
- **SECRET_KEY z historii gita.** Repo jest publiczne, a kod przy starcie tylko loguje ostrzeżenie (`config.py:2051`). Sprawdź w Sentry/logach, czy `log_if_secret_key_leaked` się odzywa. Jeśli tak, klucz trzeba zrotować (ja tego nie zrobię, to sekret produkcyjny).
- **Decyzje o martwym kodzie:** całe `/api/analytics/v1` (802 linie + 216 we froncie), stary `/api/dashboard`, modele `dr_*` i dwukierunkowego Traffita (tabele są w bazie). Usunięcie tras jest proste, DROP tabel to osobna decyzja.
- **Konta serwisowe nie mają ekranu.** CLAUDE.md mówi „Ustawienia → Konta serwisowe”, a frontend nie ma żadnego odwołania do `/api/settings/service-accounts`. Albo dopisać ekran, albo poprawić opis.

## Krytyczne

### Zamiana kontraktora przy zaplanowanym zastępstwie rozdaje tę samą pulę MD dwa razy `[Zamówienia MD]` `[potwierdzone]`

`client_order_groups.py:6131` `swap_consultant` · `order_line_takeover.py:733-780`

**Scenariusz:** osoba X ma wypowiedzenie z przyszłą datą, DL planuje „Wejdź za konsultanta” (linia draft). Ktoś robi „Zamianę kontraktora” na X. Następca dostaje pozostałe MD, a nocne `activate_due_takeovers` przenosi `X.md_remaining` jeszcze raz na zastępcę. `swap_consultant` nie woła `scheduled_successor_of`. Jedyne wywołanie jest w decyzji o offboardingu (`:5491`).

### Poczta zamówień myli różne numery zamówień i nadpisuje szkic `[Poczta zamówień]` `[odtworzone skryptem]`

`order_mail_planner.py:211` `titles_collide`

**Scenariusz:** reguła „cyfry jednego kończą cyfry drugiego” miała łączyć BIK `4500030751` z `30751`. Łączy też `830/2026` z `1830/2026`, `4/2026` z `34/2026` i `3/07/2026/BL` z `13/07/2026/BL` (odtworzone). Skutek: szkic z maila „830/2026” dostaje `FILL_DRAFT` i jego numer oraz okres są nadpisywane przez „1830/2026”, czyli ta sama klasa błędu co naprawiony Alior. Inny wariant: `ACTION_REVISION`, którego nikt nie zapisze, ani automat, ani „Zastosuj”.

### Zamówienie z maila może przepaść po cichu `[Poczta zamówień]` `[2 agenci niezależnie]`

`order_mail_ingest.py:1547`, `:1561`, `:1632-1650`, `:1946`

**Dwie drogi:** (1) Znacznik ostatniego maila przesuwa się, zanim pobiorą się załączniki. Po przerwie mail z 09:00 z błędem 503 na `/attachments` i udany mail z 11:30 dają kolejny bieg od 09:30 (nakładka 2 h), więc mail z 09:00 nie wraca. (2) Każdy wyjątek w przetwarzaniu daje status `failed`, który jest końcowy: recheck go nie bierze, kolejka go nie pokazuje, a ponownie przysłany ten sam PDF jest oznaczany jako duplikat. Health w obu przypadkach jest zielony (`partial` nie degraduje).

### Formuły Excela w eksporcie kandydatów, wejście z anonimowego formularza kariery `[Bezpieczeństwo]` `[potwierdzone]`

`candidates.py:2719` `_row_for_export` · `import_export.py:390` · także `client_directory.py:585`, `dl_alerts.py:451`, `b2b_contract_generator.py:2220`

**Scenariusz:** ktoś bez logowania wysyła zgłoszenie z imieniem `=HYPERLINK("https://…?"&A1;"CV")`. Rekruter eksportuje listę do XLSX, a openpyxl zapisuje tekst zaczynający się od „=” jako formułę. Ochrona `_safe_text` już istnieje w `order_excel_export.py:227`, tylko nie jest użyta w tych eksportach.

## Wysokie

### „Cofnij zakończenie” zwraca 409 dla umów, które przed zakończeniem były „Kończące się” `[Kontrakty]` `[potwierdzone]`

`contract_termination_reversal.py:605, 642, 723` · `contract_lifecycle.py:183`

Migawka zapisuje stan „przed” = `ending`, bo nocny cron robi najpierw `active → ending`. Cel cofnięcia to `ending`, a maszyna stanów nie zna przejścia `ended → ending`. Podgląd pokazuje cel bez blokad, wykonanie daje 409. Dotyczy każdej umowy terminowej zakończonej przez cron.

### Kolejka Cpro stoi, gdy nie ma ustawionej osoby firmowej `[Rekrutacja / Nordea]` `[potwierdzone]`

`board_tasks.py:388, 574` · `cpro_sender.py:257`

Zadanie trafia do zapasowej osoby z `jobs.cpro_sender_id`, więc widzi je tylko ona (admin i HoR nie). Przy „✓ Wrzucone” serwer zna tylko osobę firmową i role admin/DL/HoR, więc rekruter dostaje 403. Według pamięci projektu osoba od Cpro (Sandra) nie jest ustawiona.

### Delivery Lead nie zapisze debriefu, więc karta nie przejdzie na „Umowę” `[Kalendarz / pipeline]` `[potwierdzone]`

`interview_cycle.py:681` · `calendar_access.py:115`

Właścicielem rozmowy jest rekruter z wniosku. `_load_interview_event` wpuszcza tylko właściciela, uczestnika albo admina, HoR lub Finanse. DL przeciąga kartę na „Umowa” i dostaje 409 `DEBRIEF_REQUIRED`, a otwarcie okna debriefu kończy się 404. Gałąź członkostwa w `save_debrief` nigdy się nie wykonuje.

### „Zakończ zamówienie” nie blokuje wiersza grupy: podwójny wpis i złe przywrócenie `[Zamówienia MD]` `[potwierdzone]`

`client_order_groups.py:~4181-4230`

Status jest sprawdzany przed `_lock_group_lines` i potem nie jest odświeżany. Dwa kliknięcia dają drugie zdarzenie „Zakończono zamówienie” z pustą listą linii, a „Przywróć” czyta to drugie i nie odtwarza obsady. Pasuje do objawu z ticketu 7 (dwukrotne „Zakończono”). W `cancel`/`restore` to samo już naprawiono (S3).

### Traffit: nieskończona pętla stronicowania przy trwałym 5xx `[Integracje]` `[potwierdzone]`

`traffit/client.py:317-372`

Z `skip_on_5xx`, gdy `total_count()` padnie, `total_pages_known=None`, a każda strona z 5xx robi `page += 1; continue` bez warunku stopu. Pętla trzyma `_sync_lock` do restartu kontenera, a heartbeat zgłosi to dopiero po ~24 h.

### Traffit: jeden zły wiersz cofa paczkę i zamraża `__daily__` `[Integracje]` `[od agenta]`

`traffit/importer.py:4489-4558` (aktywności), `:3784` i `:3203` (pliki/CV)

Wiersze nie mają savepointu, więc `rollback()` cofa do 499 aktywności (i notatki z nich) z tej paczki. Błąd plików `emp {id}: …` nie pasuje do `_ERROR_REF_RE`, jest „nieprzypisany”, więc kwarantanna go nie odkłada, a watermark stoi na stałe. Po wznowieniu z kursora błędy sprzed kursora są zapominane.

### Finanse → Zmiany: zmiana waluty stawki jest niewidoczna `[Finanse]` `[potwierdzone]`

`finance_order_changes.py:692` · `finance-order-changes.ts:252` · `order_change_checks.py:473`

Dziennik zapisuje `old_currency`, ale `OrderChangeItem` go nie niesie, a front formatuje obie strony bieżącą walutą. PLN→EUR przy tej samej kwocie wygląda jak „1 000,00 EUR/h → 1 000,00 EUR/h”, na ekranie, w Excelu i w historii.

### „Dodaj przedłużenie” nie sprawdza rekrutacji: 500 albo cudza rekrutacja `[Zamówienia]` `[potwierdzone]`

`client_orders.py:1914, 2077`

PATCH i Flow B walidują `job_id`, POST nie. Nieistniejąca rekrutacja daje FK i gołe 500 („Network Error”). Rekrutacja innego klienta przechodzi, a lista zamówień pokazuje cudzy tytuł.

### „Porządek w requestach”: klik przy zamkniętej rekrutacji znika z ekranu i nic nie robi `[Przydział]` `[potwierdzone]`

`request_work_states.py:81, 190-220`

Zakładka „Zakończone” pokazuje ~4 tys. zamkniętych rekrutacji z przyciskami stanu. PATCH nie sprawdza `Job.status`, więc powstaje `searching` przy `closed`. Wiersz znika ze wszystkich zakładek, nie trafia do puli przydziału, a do tego idzie zdarzenie auto-matcha dla zamkniętej rekrutacji.

### Analityka kontraktów liczy inne MRR niż profil klienta `[Finanse]` `[potwierdzone]`

`contract_analytics.py:108, 132` · `consultant_population.py:131`

Kontrakt bez daty startu, którego zamówienia zaczynają się w przyszłości, to według reguły S5 kontrakt „planowany”. Analityka woła `current_contracts` bez `fallback_start_by_contract`, więc dokłada jego marżę do sum firmy, utylizacji i rozkładu lokalizacji.

### Maile przy rejestracji i resecie hasła blokują cały backend `[Integracje]` `[potwierdzone]`

`auth.py:338, 377, 462, 617, 668, 760` · `admin.py:643, 678` → `app_mail.py:241, 348`

Synchroniczne MSAL i `httpx.post` (15 s, powtórzone raz po 401) w handlerze `async`. Wolny Graph albo Entra zatrzymuje pętlę zdarzeń, więc stoi też `/api/health/live`. W `admin.py` przez cały ten czas trzymana jest blokada wiersza użytkownika.

### URL webhooka Slacka (sekret) ląduje w logach Loki `[Bezpieczeństwo]` `[potwierdzone]`

`tasks/contract_alerts.py:341-344`

`raise_for_status()` rzuca `HTTPStatusError`, którego tekst zawiera pełny adres `hooks.slack.com/services/…`, a ten trafia do `logger.warning`. Te same logi mają też dane osobowe: `importer.py:2303` (e-mail z `IntegrityError`), `database.py:42` (brak `hide_parameters`), `compass_lifecycle.py:506`.

## Średnie i niskie

Z raportów agentów, z przeczytanym kodem, ale nie sprawdzone przeze mnie. Do naprawy przy okazji albo w drugim kroku.

**Pieniądze i zamówienia (9)**

- Edycja daty końca wskrzesza zakończoną umowę z pominięciem `reopen_contract`, a Generator zostaje „Zakończony” (`contracts.py:3957`).
- Przepięcie kontraktu na innego klienta nie sprawdza duplikatu osoby u klienta docelowego, co daje podwójne MRR (`contract_client_reassign.py`).
- „Cofnij zakończenie” bez migawki zeruje datę końca umowy zlecenie/UoP (`contract_termination_reversal.py:480`).
- „Marża %” Rady dzieli przez przychód z kontraktami bez nogi kosztowej (`insights_board.py:414`), a Finanse przez `margin_revenue`.
- `works_until_md_exhausted` bez warunku M10: rozjazd „Kończących się” Finansów z pigułką DL (`order_facts.py:96`).
- PATCH zamówienia omija bramki statusu szkicu (aktywny szkic bez startu, „zakończony szkic”).
- FIN-MD-02 po przejęciu z zakresem opcjonalnym daje ujemne `md_total` (CeZ).
- `activate_due_takeovers` i nocny sync kosztu pracują na obiektach wczytanych przed blokadą.
- `FILL_DRAFT` wypełnia szkic linii MD jak zamówienie okresowe (`rate_client` zamiast `md_rate_*`).

**Rekrutacja, wyszukiwanie, kalendarz (9)**

- `/move` zwraca 500 po awarii efektu ubocznego, choć ruch jest zapisany: rollback wygasza `current_user` (`pipeline.py:1451-1620`).
- Obejście bramki QC, bramki Cpro i debriefu przez „Zamknięci” (`cv_qc.py:1364`, `pipeline_move_rules.py:51`).
- Okno „Przesuń dalej” blokuje „✓ Wrzucone”, które serwer by przyjął (`move_requirements.py:386`).
- `recruiter_id` we wniosku o terminy nie jest sprawdzany: blokada w Outlooku dowolnej osoby, zły komunikat 409.
- Słowo kluczowe nie trafia w „Vue.js”/„Node.js” w samym CV: wariant z kropką nie istnieje (`keyword_terms.py:177`). Zachowanie parsera tsvector do potwierdzenia `ts_debug`.
- Weto HM zwalnia z bramki „tylko umowa o pracę” (`matching.py:355`).
- Granice doby w UTC w filtrach `stage_moved_*` / `sent_to_client_*` listy kandydatów.
- Data `9999-12-31` w filtrach daje 500 (`OverflowError`).
- Data przepięcia z `.date()` w UTC (`job_similarity.py:481, 651`).

**Integracje, Jarvis, portale (8)**

- Jarvis a RODO: `global_search` nie wiąże rozmowy z kandydatem, więc usunięcie kandydata zostawia rozmowę z nazwiskiem.
- Mail systemowy z `ReadTimeout` jest wysyłany ponownie (duplikaty do DL i rekruterów).
- Outbox indeksu: 5 prób w 2,5 min bez backoffu, więc nowi kandydaci zostają bez wektora na stałe (jeśli worker jest włączony).
- `import_jobs` trzyma jedną transakcję przez ~4,3 tys. zapytań HTTP (~15 min).
- „Zatrzymaj” przy bezczynnej rozmowie Jarvisa przerywa następną turę; blokada tury wygasa przed jej końcem.
- Portale (flagi OFF): stary wiersz `failed` z zamknięciem zamyka nowe ogłoszenie; wycofanie w trakcie POST zostawia ogłoszenie.
- `create_task` bez trzymanej referencji w 7 trasach admina.
- Limit 1500 tokenów na krok nie mieści pola `note` (8000 znaków) w narzędziach zapisu.

**Frontend, bezpieczeństwo, baza (7)**

- „Dodaj do puli”: błąd zapytania pokazuje „Brak pul” (`CandidatesListV2.tsx:2630`).
- `UserMultiSelect`, `ClientMultiSelect`, `CompetenceCategoryMultiSelect`: przy ładowaniu i błędzie „Brak użytkowników/klientów” (filtry `/jobs`).
- Egzekwowane CSP nie ma `script-src` (pełna polityka tylko Report-Only, świadomie przejściowo).
- Pobranie dokumentu z `disposition=inline` serwuje `Content-Type` podany przy uploadzie (HTML na domenie API).
- Brak indeksu `candidate_stages (stage, moved_at)` i `(candidate_id, job_id)` pod follow-upy, a okno od 24.09 rośnie bez końca.
- Retencja `jarvis_ui_events` kasuje po `created_at` bez indeksu na tej kolumnie.
- `trainee_call_*` bez retencji (wzrost samoograniczający).

## Martwy kod

Frontend nie woła żadnego endpointu, którego nie ma w backendzie. Sprawdzono 628 wywołań `api.*` przeciw 1186 trasom, więc nie ma ukrytych 404. Martwy kod to głównie pozostałości po przebudowach z 09.2026.
| Co | Gdzie | Linie | Ryzyko usunięcia |
| Routery bez konsumenta: `/api/analytics/v1` (+ `stats-api.ts`), stary `/api/dashboard`, `financial-adjustments`, `identity-quarantine`, `admin/workflows`, TAC i sourcer-categories w `team_structure`, ~20 pojedynczych tras | backend/app/api | ~3 500 | średnie: 1–12 plików testów na router, kontrakt OpenAPI analytics |
| Gałęzie `except AIQuotaExceeded` (nic już nie rzuca: `raise` = 0) | 23 pliki | ~280 | niskie, klasa zostaje dla testów |
| Nieużywane schematy Pydantic (14 klas Priority Work, `UserCreate/Update/List`, `candidate_risk.py`, `candidate_search_v3.py`) i helpery bez wywołań | schemas, services | ~1 000 | niskie |
| Nieczytane ustawienia (21× `TRAFFIT_INTEGRATION_*`, Szafir, `APP_NAME`…); `TALENT_RADAR_STRUCTURED_SKILLS_ENABLED` przełączany w teście, który przez to nic nie testuje | core/config.py | ~60 | niskie |
| Stary pulpit DL (`app/dashboard/delivery-lead/_components`, strona robi redirect), stara gamifikacja, `NotificationsTab`, `dashboard-v2-api.ts` | frontend | ~2 700 | niskie, z wpisami BASELINE bramki CI |
| Resztki trybu „Tabela” w `person-rows.ts`, `TalentRadarResults`, `OrdersAndContractsTab` (tylko harness), martwe eksporty | frontend | ~1 300 | niskie, harnessy do poprawy |
| Stare skrypty i seedy (`seed_v4/v5`, `embed_all`, ETL DynaReportera) | backend/, scripts/ | ~1 300 | niskie |
| Modele `dr_*` i dwukierunkowego Traffita (8 klas) | models | ~1 100 | decyzja: tabele są w bazie |
| Świadomie za flagami `false`: linki CV do klienta, interaktywne CV, TAC, CloudTalk | frontend | ~640 | nie ruszać bez decyzji |

Poza tym bramka CI `check-unreachable-modules.mjs` ma 11 nieaktualnych wpisów po Cortexie i DynaReporterze, a `@types/dompurify` w package.json jest zbędny. Siedem pętli tła kończy pracę przy domyślnych flagach (Priority Work, coach nudger, contact queue, recording discovery, weekly eval, match digest). Ich stanu w Coolify nie sprawdzałem.

## Sprawdzone i czyste

- Jedna głowa Alembica (413 rewizji). Migracje 0340–0383 są zgodne z modelami i lustrem w `entrypoint.sh`.
- Kolejność blokad kontrakty → zamówienia jest zachowana na wszystkich ścieżkach zapisu. `business_today()` wszędzie w pieniądzach.
- Lustra front↔back (etapy Tablicy, następna akcja, stan requestu, wyrażenie umiejętności, zapisane wyszukiwania) są zgodne.
- Łańcuch auth (impersonacja, konta serwisowe, OAuth, praktykant) jest fail-closed. Webhooki mają HMAC ze stałoczasowym porównaniem. SSRF w iCal jest zabezpieczony.

- Jarvis nie wykonuje zapisu bez kliknięcia człowieka, a `args` są zamrożone.
- Każda pętla tła ma try/except wokół iteracji (sprawdzone skanem AST). `CancelledError` nie jest połykany.
- FK do kandydata mają CASCADE/SET NULL (migracja 0146 + nowe tabele). SQL tylko przez parametry.
- Frontend przestrzega reguł `isSuccess`, `apiErrorMessage` i obu kluczy kanbana, poza wymienionymi wyjątkami.

**Niepotwierdzone:** lokalnie nie da się uruchomić testów. Python w systemie to 3.9, a `config.py` wymaga 3.12. Worktree nie ma `node_modules`, więc type-check i vitest też nie ruszyły. Stanu flag w Coolify i produkcji nie sprawdzałem (tylko odczyt kodu).


---

## Notatki weryfikacyjne koordynatora

Surowe notatki z weryfikacji (plik:linia sprawdzone w kodzie). „POTWIERDZONE” = sprawdzone przez koordynatora, bez oznaczenia = zgłoszone przez agenta.

#### Kontrakty (pod-agent lifecycle)
- V1 POTWIERDZONE: contract_termination_reversal.py:605 status_target z migawki 'ending' -> :723 assert_transition(ended, ending) — brak krawędzi w ALLOWED_TRANSITIONS (contract_lifecycle.py:183). Guard :642 tylko dla ended. Cron contract_alerts.py:129 zapisuje stan po active->ending. 409 przy Cofnij zakończenie.
- #2 update_contract coerced_status (contracts.py:3957) — średnia, niezweryfikowane
- #3 reassign bez duplikatu osoby — średnia
- #4 historia bez migawki zeruje end_date UZ/UoP — średnia
- V2 POTWIERDZONE: contract_analytics.py:132 current_contracts(rows, today) bez fallback_start_by_contract; _started_by :108 SQL bez zamówień. Rozjazd MRR Finanse vs profil klienta (reguła S5 24.09).
- #3 średnia: insights_board.py:414 margin_pct = margin/revenue (revenue zawiera kontrakty bez nogi kosztowej) vs contract_analytics margin_revenue.
#### Pipeline
- V3 POTWIERDZONE: board_tasks.py:388 assignee_id = firm_sender or job.cpro_sender_id or task_assignee_id; _sees_cpro :574 -> tylko ta osoba (admin/HoR nie widzą); cpro_sender.can_send_to_cpro :257 zna tylko firmowego + role -> rekruter z zapasu dostaje 403. Kolejka stoi gdy firmowy nieustawiony (a Sandra nieustawiona wg pamięci).
- #2 /move 500 po rollback efektu ubocznego (pipeline.py:1451-1620) — średnia
- #3 obejście bramki QC/debriefu przez "Zamknięci" (cv_qc.py:1364, pipeline_move_rules PRE_CONTRACT_COLUMNS bez closed) — średnio-wysoka
- #4 MoveNextDialog blokuje ✓Wrzucone na QC (move_requirements.py:386) — średnia
#### Security
- V4 POTWIERDZONE: candidates.py:2719 _row_for_export bez _safe_text; openpyxl traktuje '=...' jako formułę; wejście z anonimowego formularza kariery. _safe_text istnieje w order_excel_export.py.
- SECRET_KEY z historii: tylko log, rotacja niepotwierdzona (znane w pamięci)
- CSP enforced bez script-src (świadome, przejściowe)
- inline Content-Type z uploadu (średnia)
#### Kalendarz
- V5 POTWIERDZONE: interview_cycle.py:681 _load_interview_event -> user_can_view_event (calendar_access.py:115) = override (admin/HoR/finance) | owner | attendee. DL spoza właściciela -> 404 na debrief; bramka debriefu /move (409 DEBRIEF_REQUIRED) blokuje DL-a na "Umowa".
- #2 recruiter_id w slot request nie walidowany (średnia)
#### Frontend
- CandidatesListV2.tsx:2630 BulkAddToPoolModal: błąd = "Brak pul" (średnio-wysoka)
- UserMultiSelect/ClientMultiSelect/CompetenceCategoryMultiSelect: CommandEmpty przy błędzie/ładowaniu
- node_modules brak w worktree — type-check nieuruchomiony
#### Zamówienia
- V6 POTWIERDZONE: finance_order_changes.py:692 OrderChangeItem bez old_currency (model ma old_currency, audit je zapisuje); front finance-order-changes.ts:252 formatuje obie strony item.currency -> "1000 EUR/h → 1000 EUR/h" przy PLN→EUR.
- V7 POTWIERDZONE: client_orders.py:1914/2077 POST orders job_id bez walidacji (brak Job w ciele 1918-2076) -> FK 500 / cudza rekrutacja.
- #2 order_facts.works_until_md_exhausted bez warunku order_group_id (M10) — średnio-wysoka
- #4 PATCH status omija bramki draft (średnia)
- #5 nocny sync kosztu czyta przed blokadą (niska)
#### Przydział
- V8 POTWIERDZONE: request_work_states.py:81 _listable = published OR finished; PATCH (190-222) bez sprawdzenia Job.status -> zamknięta rekrutacja z "Zakończone" po kliknięciu "Szukamy" znika z ekranu, work_state=searching przy status=closed.
- job_similarity.py:481,651 .date() na moved_at UTC (niska waga)
#### Wyszukiwanie
- keyword_terms.py:177 tsquery_path_variants tylko '/' i '-', brak '.'; "Vue.js"/"Node.js" = jeden token host w tsvector -> "vue" nie znajdzie w samym CV. Kod potwierdzony; zachowanie parsera do potwierdzenia ts_debug (brak lokalnego PG).
- matching.py:355 weto HM omija employment_only (niska)
- candidates.py:1172,1286 granice doby UTC w stage_moved_*/sent_to_client_* (niska)
- 9999-12-31 -> OverflowError 500 (niska)
#### MD
- V9 POTWIERDZONE: swap_consultant (client_order_groups.py:6131) nie woła scheduled_successor_of (jedyne użycie :5491 w resolve_md_offboarding_case) -> zaplanowane przejęcie + zamiana = podwójna pula MD przy activate_due_takeovers.
- V10 POTWIERDZONE: close_order_group (~4181) status sprawdzany przed _lock_group_lines, bez ponownego odczytu -> podwójne "Zakończono zamówienie", restore czyta złe zdarzenie (zgodne z objawem z ticketu 7).
- #3 FIN-MD-02 po przejęciu z opcją -> ujemne md_total (średnia, CeZ)
- #4 activate_due_takeovers stary obiekt target (średnia)
#### Poczta zamówień
- V11 POTWIERDZONE (skrypt): order_mail_planner.py:211 titles_collide endswith po cyfrach: 830/2026 == 1830/2026, 4/2026 == 34/2026 -> FILL_DRAFT nadpisuje szkic / REVISION blokuje zapis.
- #2 FILL_DRAFT na linii grupy MD (średnia)
- #3 watermark przesuwa się za maile bez pobranych załączników (order_mail_ingest.py:1547) — średnia
- #4 status failed ostateczny + blokuje duplikat SHA (średnia)
#### Integracje
- V12 POTWIERDZONE: traffit/client.py:317-372 skip_on_5xx + total_count padł -> total_pages_known=None -> nieskończone page+=1 przy trwałym 5xx; trzyma _sync_lock.
- V13 POTWIERDZONE: contract_alerts.py:341 raise_for_status -> HTTPStatusError z URL webhooka Slack -> logger.warning (sekret w Loki).
- V14 POTWIERDZONE: auth.py:338 (i inne) send_email_verification_email -> email.send_email -> sync httpx.post + MSAL w async handlerze (blokada pętli zdarzeń do 30 s).
- order mail watermark (#1) i failed (#2) potwierdzone też przez drugiego agenta
- Traffit aktywności rollback całej paczki (importer.py:4489) — wysoka wg agenta
- Traffit emp {id} bez ext= -> nieprzypisany błąd zamraża __daily__ (importer.py:3784) — wysoka wg agenta
- Jarvis RODO: global_search bez entity_type candidate -> rozmowy z nazwiskami nie kasowane (średnio-wysoka)
- system_mail ReadTimeout -> ponowna wysyłka (średnia)
- PII w logach: importer.py:2303, database.py:42 bez hide_parameters, compass_lifecycle.py:506
- Portale: stary failed z close zamyka nowe ogłoszenie (flagi OFF)
#### Martwy kod BE (sprawdzone grep)
- raise AIQuotaExceeded: 0; gałęzie except: 50 trafień
- schemas/candidate_risk.py 0 importów; statsApi 0 wywołań poza plikiem; /api/dashboard/{stats,kpis,recent,pipeline-funnel} 0 w FE; /api/settings/service-accounts 0 w FE (rozjazd z CLAUDE.md)
- analytics_v1.py 802 l, dashboard.py 266 l
#### Faza naprawy
- bc9cb1492 na fix/audit-2026-09-25: migracja 0384 (cv_sent partial, jarvis created_at) + CLAUDE.md konta serwisowe.
- Pominięte: retencja trainee_call_items — sprzeczna ze specyfikacją (pozycje to dziennik telefonów; "niezainteresowany = nigdy", "zły numer"). Indeks (candidate_id, job_id) pominięty: candidate_id index wystarcza dla podzapytań.
- Agenci: mail, orders, contracts, recruitment, security, integrations (worktree, gałęzie fix/audit-0925-<obszar>)
