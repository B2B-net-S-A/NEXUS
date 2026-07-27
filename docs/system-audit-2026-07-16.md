# NEXUS (ATS) — Pełny audyt systemu

**Data:** 2026-07-16
**Zakres:** cały monorepo (`backend/` FastAPI + SQLAlchemy async, `frontend/` Next.js 15) — bezpieczeństwo, poprawność, dane finansowe, migracje, zadania w tle, prywatność (RODO).
**Metoda:** statyczny audyt wieloagentowy — 12 wymiarów × finder, każde znalezisko przeszło adwersaryjną weryfikację (osobny agent czytający realny kod, z domyślnym werdyktem „REFUTED, chyba że defekt jest realny i osiągalny"). Łącznie 43 agenty, 31 surowych znalezisk → **29 potwierdzonych, 2 odrzucone**.

> **Ograniczenia audytu (uczciwie):** to analiza statyczna kodu w worktree. **Nie** uruchomiłem: backendowego `ruff`/`pytest` (brak lokalnego venv — `python3 3.9`, brak `ruff`/`uvx`), ani zapytań do prod-DB (SSH martwe — patrz memory). Frontend `tsc --noEmit` + `next lint` **przeszły** (ostrzeżenia w limicie 300; jedyny błąd type-check to nieszkodliwy artefakt stale `.next` dla usuniętej strony `preview/candidates-split`). Nie potwierdzałem eksploitów na żywym systemie — każde znalezisko ma jednak zweryfikowany cytat z kodu (plik:linia).

---

## Podsumowanie wykonawcze

| Severity | Liczba | Najważniejsze |
|---|---|---|
| 🔴 **High** | 6 | Systemowa luka RBAC: rola „viewer" czyta PII kandydatów w wielu routerach; tabela bez mirrora w entrypoint → 500 na prodzie; niedoszacowanie przychodu przez `int()` |
| 🟠 **Medium** | 13 | Mieszanie walut bez FX w KPI, brak Secure na cookie JWT, dedupe pętli w pamięci → duplikaty po redeployu, brak limitu/quota na płatnych LLM |
| 🟡 **Low** | 10 | Nieograniczone `limit` w kilku endpointach, PII w logach, 2 rozjechane głowy migracji, rozdrobnione braki walidacji |

### Motyw przewodni (najważniejszy wniosek)

**Kontenment M2 (gate PII kandydatów) objął `candidates.py`, ale nie „siostrzane" routery.** Rola `UserRole.user` = read-only viewer (persona QC/klient, tworzona m.in. przez self-registration) przechodzi przez `Depends(get_current_user)` bez filtra roli w co najmniej **5 miejscach**, które i tak dosięgają danych kandydatów: `candidate_pins`, `cv_generator_b2b`, `prep_kit`, `emails/preview`, `import_export`. To nie pięć osobnych bugów — to **jedna dziura w projekcie**: nowe routery dodawane po M2 nie były podpinane pod kanoniczne gate'y (`candidate_access.py` / `require_roles`). Rekomendacja #1 poniżej adresuje to systemowo.

---

## 🔴 High

### H1 — Tabela `job_shortlist_entries` (migracja 0172) nie ma mirrora w `entrypoint.sh` → 500 na prodzie
- **Plik:** `backend/entrypoint.sh` (brak bloku CREATE TABLE), migracja `backend/alembic/versions/0172_job_shortlist_entries.py`, endpointy `backend/app/api/job_shortlist.py:54,121,142,182,201`
- **Kategoria:** schema-drift · **Werdykt:** CONFIRMED
- **Problem:** Na prodzie `DEBUG=false`, więc `Base.metadata.create_all` **nie** leci (`main.py:408-410`), a alembic jest chronicznie „osierocony" (~0170) — `alembic upgrade heads` nie dokłada 0172. Safety-net w `entrypoint.sh` mirroruje ~40 innych nowych tabel (`match_impressions`, `match_outcomes`, `match_index_outbox`, wszystkie `traffit_*`, `analytics_metric_snapshots`, `workflow_revisions`, …) **z wyjątkiem `job_shortlist_entries`** (`grep -c shortlist entrypoint.sh` = 0).
- **Scenariusz awarii:** dowolne wywołanie endpointów shortlisty → `UndefinedTable` → HTTP 500 (crash na prodzie, którego nie widać lokalnie, bo w devie `create_all` maskuje brak).
- **Fix:** dodać idempotentny `CREATE TABLE IF NOT EXISTS job_shortlist_entries (...)` obok pozostałych bloków nowych tabel w `entrypoint.sh` (okolice linii 435–527). Zgodnie z memory `entrypoint-safetynet-new-columns`.

### H2 — Rola viewer czyta email/imię dowolnego kandydata przez toggle „pinów"
- **Plik:** `backend/app/api/candidate_pins.py:98` (`toggle_pin`); router w `main.py:587-589`
- **Kategoria:** rbac / pii · **Werdykt:** CONFIRMED
- **Problem:** `POST /api/candidates/{id}/pin` gate'owany tylko przez `current_user: CurrentUser` (`deps.py:152` = dowolny zalogowany, bez filtra roli). Sprawdza jedynie, że kandydat istnieje, a w gałęzi „create" zwraca `pin.candidate` z `email/name/lastname`.
- **Scenariusz:** konto `UserRole.user` woła `POST /api/candidates/1/pin`, `/2/pin`, … — każda odpowiedź ujawnia email i pełne imię kandydata (enumeracja PII zakazana przez macierz M2). Cap `MAX_PINS_PER_USER` obchodzi się przez toggle-off.
- **Fix:** podpiąć `RecruitmentReadAccess`/`require_roles` lub `candidate_access` na routerze `candidate_pins`; nie zwracać PII kandydata w odpowiedzi pinu dla roli viewer. *(Uwaga weryfikatora: `list_my_pins`/`get_pin_state` NIE wyciekają dowolnych kandydatów — tylko własne piny; naprawa dotyczy głównie `toggle_pin`.)*

### H3 — Cały moduł CV-generator omija gate'y RBAC kandydatów (+ IDOR na wygenerowanych CV)
- **Plik:** `backend/app/api/cv_generator_b2b.py:408` (`search_candidates`), `:409` (`del current_user # auth only`); router w `main.py:842`
- **Kategoria:** rbac · **Werdykt:** CONFIRMED
- **Problem (a):** każdy route `/api/cv-generator/*` gate'owany bare `CurrentUser`. `GET /candidates?q=` zwraca `name/lastname/email` kandydatów (enumeracja PII), a `POST /generate` pozwala viewerowi wygenerować pełne brandowane CV dowolnego kandydata.
- **Problem (b) — IDOR:** `GET /generated` i `GET /generated/{id}/docx` nie są scope'owane do właściciela → dowolny użytkownik operacyjny czyta cudze wygenerowane CV.
- **Fix:** router-level `dependencies=[Depends(require_roles(...))]` + scoping `generated` po `user_id` (owner check).

### H4 — `GET /api/export/candidates` ładuje całą tabelę (~49k) do pamięci, bez limitu i bez gate roli
- **Plik:** `backend/app/api/import_export.py:271-285`
- **Kategoria:** resource-exhaustion (+ PII export) · **Werdykt:** CONFIRMED
- **Problem:** `select(Candidate).order_by(created_at.desc())` → `.scalars().all()` bez `.limit()`, potem budowa całego CSV w pamięci (`_build_candidates_csv`) i `StreamingResponse(BytesIO(csv_bytes))` z `Content-Length`. Brak paginacji **i** brak gate roli.
- **Scenariusz:** dowolny zalogowany (w tym viewer) woła endpoint kilka razy równolegle → materializacja ~49k obiektów ORM + pełny CSV naraz → OOM na single-worker kontenerze i zablokowanie event-loopu. Dodatkowo: **eksport całego PII kandydatów przez rolę, która nie ma do niego prawa.**
- **Fix:** streaming z paginacją/`yield_per`, twardy cap, gate `require_roles`/`CandidateExportAccess`.

### H5 — `prep_kit/generate` chroniony tylko uwierzytelnieniem → viewer czyta PII, notatki screeningowe i wiedzę o kliencie
- **Plik:** `backend/app/api/prep_kit.py:60`; router w `main.py:835`
- **Kategoria:** rbac / pii · **Werdykt:** CONFIRMED
- **Problem:** `POST /api/prep-kit/generate` = `Depends(get_current_user)` (tylko auth). Handler ładuje `Candidate` (L69), `ScreeningNote` (L102) i `ClientKnowledge` klienta (L96) i zwraca prep-kit z red-flagami, weryfikowanymi umiejętnościami, motywacjami, ryzykiem kontroferty i danymi wynagrodzenia.
- **Fix:** dodać `require_roles`/`RecruitmentReadAccess` + `candidate_access`.

### H6 — `reports._monthly` obcina ułamek stawki przez `int(value)` → zaniżanie przychodu i marży
- **Plik:** `backend/app/api/reports.py:41-57` (helper), wpływ na `:345-346, 411-412, 1415-1416, 1509`
- **Kategoria:** money · **Werdykt:** CONFIRMED
- **Problem:** `Contract.rate_client`/`margin` to `Numeric(12,3)` (`models/contract.py:128,149`), więc realne wartości jak `164.375`. `_monthly` robi `int(value) * mnożnik` — obcina ułamek **per jednostkę** przed pomnożeniem: `int(164.375)*160 = 26240` zamiast `26300` (−60 PLN/mc, zawsze w dół). Ścieżka SQL (`_sql_monthly`, `col*22`, Numeric-precise) i model liczą inaczej → **rozjazd między raportem Python a SQL**.
- **Fix:** liczyć na `Decimal` (bez `int()`), zaokrąglać dopiero na końcu (`ROUND_HALF_UP`). Reporting-only (nie fakturowanie), ale wewnętrznie niespójne.

---

## 🟠 Medium

### M1 — `calendar_reminder_loop`: dedupe przypomnień w pamięci → ponowne wysyłki po każdym redeployu
- **Plik:** `backend/app/api/calendar.py:775` (`reminded_ids: set = set()` lokalne), gate na `:792`
- **Kategoria:** idempotency · **Werdykt:** CONFIRMED (weryfikator obniżył high→medium: to duplikat in-app Notification + WS toast, nie email)
- **Problem:** brak trwałej flagi na `CalendarEvent` (kontrast: `chat_email_fallback` stempluje wiersz). Redeploy w oknie 14–16 min przed eventem → re-wysyłka przypomnienia.
- **Fix:** trwała kolumna `reminder_sent_at` na evencie zamiast setu w pamięci.

### M2 — `fx_service.convert_to_pln` cicho zwraca kwotę 1:1 gdy brak kursu
- **Plik:** `backend/app/services/fx_service.py:105-107`
- **Kategoria:** money · **Werdykt:** CONFIRMED
- **Problem:** `if row is None: return Decimal(amount)` — brak kursu (NBP nie pobrany / waluta spoza tabeli A) daje przelicznik 1:1 bez sygnału. `revenue_forecast?convert_currency=true` traktuje 100 EUR/h jak 100 PLN/h (~4.3× zaniżenie).
- **Fix:** przy braku kursu zwracać błąd/`None` + flagę „nieprzeliczono", nie ciche 1:1.

### M3 — `revenue_forecast` rzuca 500 (TypeError) gdy aktywny kontrakt ma `start_date = NULL`
- **Plik:** `backend/app/api/contract_analytics.py:264-269`
- **Kategoria:** money · **Werdykt:** CONFIRMED
- **Problem:** `c.start_date < next_month` bez guardu NULL; zapytanie filtruje tylko `status in [active, ending]`, a `start_date` jest `nullable=True`. Repro: `POST /api/clients/{id}/contract-with-order` z pominiętym `contract_start_date` → aktywny kontrakt z NULL → `None < date` → 500 dla całego endpointu.
- **Fix:** guard `c.start_date is not None` lub `COALESCE`/filtr w zapytaniu.

### M4 — Podgląd szablonu emaila ujawnia pełne imię kandydata roli viewer
- **Plik:** `backend/app/api/emails.py:424` (`preview_template_by_id`), `:545` (`preview_email`); router `main.py:708`
- **Kategoria:** pii · **Werdykt:** CONFIRMED
- **Problem:** oba endpointy bare `CurrentUser`, przyjmują `candidate_id`, renderują `{{candidate_name}}` = `name + lastname`. Viewer enumeruje pełne imiona przez `?candidate_id=1..N`.
- **Fix:** gate roli + ewentualnie zakaz podstawiania PII w podglądzie dla viewerów.

### M5 — Przejściowy błąd Proxycurl (429/500) bumpuje `linkedin_synced_at` → kandydat wypada z auto-resync na 60 dni
- **Plik:** `backend/app/services/proxycurl/sync.py:119-138`; scheduler `app/tasks/linkedin_sync.py:63-75`
- **Kategoria:** fake-progress · **Werdykt:** CONFIRMED (high→medium: status/error są stemplowane, więc wykrywalne)
- **Problem:** gałąź `except ProxycurlError` ustawia status/`linkedin_sync_error`, ale **bezwarunkowo** `linkedin_synced_at = now()` + commit. Pętla dobiera tylko `synced_at < now-60d` → nieudany fetch „liczy się jako sync".
- **Fix:** nie ruszać `linkedin_synced_at` na błędach retryowalnych (429/503/5xx); resync po krótszym backoffie.

### M6 — Cookie JWT `nexus_access` bez atrybutu `Secure`
- **Plik:** `frontend/src/store/auth.ts:217-219`; clear-path `frontend/src/lib/api.ts:142`
- **Kategoria:** cookie-security · **Werdykt:** CONFIRMED
- **Problem:** `document.cookie = "nexus_access=...; path=/; max-age=...; samesite=lax"` — brak `Secure`. Żądanie http (przed edge-301) lub MITM w LAN dołączy JWT po plaintext. (Token jest też w `localStorage`, więc już XSS-exposed — `Secure` adresuje osobny wektor: cleartext na drucie.)
- **Fix:** dodać `Secure` (i rozważyć `httpOnly` cookie ustawiane przez backend zamiast JS).

### M7 — `admin_engagement_inventory`: `asyncio.wait_for(db.execute)` zatruwa współdzieloną sesję na timeout
- **Plik:** `backend/app/api/admin_engagement_inventory.py:367-370`, `:408-410`, pętla `:419-422`
- **Kategoria:** async-db · **Werdykt:** CONFIRMED
- **Problem:** anulowanie asyncpg przez `wait_for` zostawia połączenie w złym stanie; kolejne checki na **tej samej** sesji rzucają, są łykane przez `except Exception` i raportowane jako `error` bez rollbacku. (Bliźniak L6.)
- **Fix:** timeout po stronie DB (`statement_timeout`) lub osobna sesja per-check + rollback/reconnect na wyjątku.

### M8 — MINDY `/chat` i `/commentary`: płatne wywołania Claude bez quota i bez rate-limitu, nieograniczony content
- **Plik:** `backend/app/api/dynareporter_mindy.py:153` (`commentary`), `:204` (`chat`)
- **Kategoria:** external-api-cost · **Werdykt:** CONFIRMED (high→medium: wymaga capability sekcji „mindy")
- **Problem:** oba wołają `call_claude` przez `run_in_threadpool` bez `@limiter.limit` i bez `ai_quota.check_and_increment` (jako jedyne płatne LLM endpointy). `MindyChatMessage.content` bez `max_length` (lista wiadomości capped 20, ale treść nie).
- **Fix:** dodać `ai_quota` + `@limiter.limit` + `max_length` na `content`, spójnie z resztą LLM-endpointów.

### M9 — `slack_sla_alerts_loop`: dedupe breachy w pamięci → re-spam Slacka po restarcie
- **Plik:** `backend/app/tasks/slack_sla_alerts.py:108`; rejestracja `main.py:508`
- **Kategoria:** idempotency · **Werdykt:** CONFIRMED
- **Problem:** `alerted: set[int] = set()` lokalne; po redeployu każdy wciąż-przekroczony SLA traktowany jako nowy → N duplikatów na `SLACK_WEBHOOK_URL`. Docstring wprost to przyznaje jako „acceptable noise" — ale przy kilku deployach dziennie to realny szum.
- **Fix:** trwały store wysłanych alertów (kolumna/tabela) zamiast setu.

### M10 — `ai_writer._generate_with_claude`: `anthropic.Anthropic()` bez timeoutu → wyczerpanie threadpoola
- **Plik:** `backend/app/api/ai_writer.py:228,254`
- **Kategoria:** external-api-timeout · **Werdykt:** CONFIRMED
- **Problem:** klient bez `timeout=`/`max_retries=` → domyślne 600s SDK. Zawieszony upstream trzyma wątek threadpoola do 10 min; na single-worker kilka wolnych wywołań blokuje inne `run_in_threadpool` (parsing CV, inne LLM). To dokładnie wzorzec, który `claude_client.call_claude` miał eliminować.
- **Fix:** użyć `claude_client.call_claude` (albo jawnie ustawić `timeout`/`max_retries`).

### M11 — Publiczny `/apply`: zapis CV z surową nazwą pliku klienta (bez strip separatorów)
- **Plik:** `backend/app/api/public_share.py:293-306`
- **Kategoria:** path / input-validation · **Werdykt:** CONFIRMED (angle „traversal poza UPLOAD_DIR" — patrz odrzucone R1; realny impact: 500 + niespójność)
- **Problem:** `filename = upload.filename or "cv.pdf"` → `os.path.join(UPLOAD_DIR, f"candidate_{id}_{filename}")` bez sanitacji. Siostry sanitują (`candidates.py:3708` `.replace("/", "_")`, `:3910` `Path(...).name`). Endpoint jest **nieuwierzytelniony** (token-gated).
- **Scenariusz:** `filename="a/b"` → nieobsłużony `OSError` → 500 (a przynajmniej zatruta ścieżka/niespójność). Prefiks `candidate_{id}_` blokuje czysty escape `..`, ale separator `/` psuje zapis.
- **Fix:** `safe = Path(filename).name.replace("/", "_")` jak w ścieżkach uwierzytelnionych.

### M12 — KPI przychodu/marży sumują kwoty w mieszanych walutach bez FX
- **Plik:** `backend/app/api/reports.py:345-346`; `contract_analytics.py:105-106` (`margin_by_contractor`), `:144-145` (`margin_by_client`)
- **Kategoria:** money · **Werdykt:** CONFIRMED
- **Problem:** `sum(_monthly_rate_client(c) ...)` i `func.sum(_sql_monthly(...))` bez grupowania/konwersji po `Contract.currency`. Kontrakt 100 EUR/h wchodzi jako 16000 „PLN" (prawdziwie ~68800). `fx_service` istnieje właśnie dlatego, że wspieramy nie-PLN — MRR, top-klienci i tabele marży cicho mieszają waluty.
- **Fix:** `convert_to_pln` przed agregacją (opcja jak w `revenue_forecast`), lub grupowanie per waluta.

### M13 — `cloudtalk_sync._upsert_call`: SELECT-then-INSERT bez `ON CONFLICT` → abort commitu całej strony przy współbieżnym webhooku
- **Plik:** `backend/app/tasks/cloudtalk_sync.py:150-153`; `calls.cloudtalk_call_id` = `VARCHAR(255) UNIQUE`
- **Kategoria:** race · **Werdykt:** CONFIRMED
- **Problem:** backfill i live-webhook (`calls.py::_process_cloudtalk...`) oba upsertują po `cloudtalk_call_id`. Insert webhooka między SELECT (None) a batchowym `commit()` (do 100 calls/sesję) → `IntegrityError` na UNIQUE → wysadza commit całej strony.
- **Fix:** `insert(...).on_conflict_do_update/nothing` (Postgres upsert) zamiast SELECT-then-INSERT.

---

## 🟡 Low

### L1 — Mapa RBAC w middleware pomija część drzew tras (defense-in-depth)
- **Plik:** `frontend/src/middleware.ts:89-97` (`resolveAllowedRoles`), `:140-145`
- **Werdykt:** CONFIRMED — trasy spoza `PROTECTED_ROUTES` (np. `/pending-verifications`) dostają `NextResponse.next()` bez sprawdzenia tokenu/wygaśnięcia. To tylko warstwa DiD (dane zależą od backendu), ale sprzeczne z udokumentowanym gate `/preview`. **Fix:** default-deny w middleware.

### L2 — Log SMTP zapisuje adres odbiorcy i temat do stdout (→ Loki)
- **Plik:** `backend/app/services/email.py:83` (+ `:55,60,71,89`)
- **Werdykt:** CONFIRMED (weryfikator: odbiorcy to userzy wewnętrzni, nie kandydaci → PII = email wewn. + temat, nie dane kandydata). **Fix:** logować bez adresu/tematu (albo tylko id/hash).

### L3 — `_grosze_part` może zwrócić 100 groszy zamiast rolować do złotego (kwota słownie w umowach B2B)
- **Plik:** `backend/app/services/b2b_contract_generator/number_words.py:186-189,204`
- **Werdykt:** CONFIRMED — `amount=1.999` → „jeden złoty sto groszy" zamiast „dwa złote"; liczba złotych nie inkrementuje się gdy grosze zaokrąglą do 100. Float od Decimal-stawek grozi off-by-one grosz. Legalnie wiążące „kwota słownie". **Fix:** liczyć na `Decimal`, przenieść 100 gr do złotych.

### L4 — Traffit daily sync przesuwa watermark na `run_start` mimo błędów faz (tylko 48h lookback)
- **Plik:** `backend/app/tasks/traffit_sync.py:311-315, 347-379`
- **Werdykt:** CONFIRMED — faza rzucająca >48h (outage/mapping bug) traci rekordy starsze niż lookback (delta skanuje tylko 48h wstecz). **Fix:** nie przesuwać `last_synced_at` gdy `any_error`, albo trzymać per-fazę watermark. *(Full-reconcile tygodniowy łagodzi, ale okno pozostaje.)*

### L5 — `dashboard/recent-activity`: nieograniczony `limit`
- **Plik:** `backend/app/api/dashboard.py:131,140`
- **Werdykt:** CONFIRMED — `limit: int = 20` bez `Query(ge=1, le=...)` (siostra `recent_hires:181` ma `Query(8, ge=1, le=50)`). `?limit=1e8` → skan+serializacja PII; `?limit=-1` → 500. **Fix:** `Query(20, ge=1, le=100)`.

### L6 — `admin_pipeline_inventory`: `wait_for(db.execute)` zatruwa współdzieloną sesję (bliźniak M7)
- **Plik:** `backend/app/api/admin_pipeline_inventory.py:418-421,459-460,470-473`
- **Werdykt:** PLAUSIBLE — warunkowe na przekroczeniu 20s; impact = błędny raport + zatrucie sesji requestu. **Fix:** jak M7.

### L7 — `fx/list_rates`: nieograniczony `limit`
- **Plik:** `backend/app/api/fx.py:32,37`
- **Werdykt:** CONFIRMED — `limit: int = 50` bez clampu; `?limit=-1` → „LIMIT must not be negative" 500. Tabela FxRate mała, więc realnie chodzi o negatywny-limit 500. **Fix:** `Query(50, ge=1, le=500)`.

### L8 — Dwie trwale rozjechane głowy migracji `0177` (nigdy nie scalone)
- **Plik:** `0177_analytics_snapshots_cutovers` vs `0177_workflow_revisions` (obie schodzą z `0174` dwoma rozłącznymi łańcuchami 0175/0176); `.github/workflows/backup-drill.yml:78`
- **Werdykt:** CONFIRMED — `alembic upgrade head` (**l.poj.**) rzuca „Multiple head revisions"; backup-drill (DR restore) używa `head` l.poj. → fail gdy `BACKUP_DRILL_SSH_KEY` ustawiony. Prod i CI używają `heads` (l.mn.) → **niezagrożone**. Tabele obu głów są rozłączne, więc `heads` aplikuje obie bez kolizji. **Fix:** dodać migrację `merge` scalającą oba 0177. *(204 migracje → realnie 2 głowy; wcześniejsze „26 głów" to artefakt naiwnego parsera na wielolinijkowych krotkach `down_revision`.)*

### L9 — `calendar_reminder_loop`: `asyncio.create_task` bez referencji → task może zostać GC-owany przed końcem
- **Plik:** `backend/app/api/calendar.py:791-794`
- **Werdykt:** CONFIRMED — `event.id` dodawany do `reminded_ids` **przed** `create_task`; zgubiona referencja (RUF006) → task może zniknąć mid-`await` (przed `db.commit`), przypomnienie nigdy nie powstaje i nie jest retryowane. **Fix:** trzymać referencje w secie + `try/except` w `_send_reminder`.

### L10 — Bulk-kontrakty: nieograniczona lista `ids` + wiersz audytu per nieistniejący id
- **Plik:** `backend/app/api/contracts.py:775,779,814-822`
- **Werdykt:** CONFIRMED — `contract_ids = Query(..., alias="ids")` bez capa; pętla audytu iteruje po **żądanych** id (nie znalezionych), wstawiając `Activity` nawet dla nieistniejących → zaśmiecanie logu audytu + amplifikacja zapisu. *(Uwaga: `bulk_mark_ended:835` NIE jest identyczny — jego insert jest w pętli po znalezionych.)* **Fix:** cap długości `ids` + audyt tylko dla realnie zmienionych.

---

## Odrzucone (sprawdzone, nie-defekty)

| # | Znalezisko | Dlaczego odrzucone |
|---|---|---|
| R1 | „Path traversal poza UPLOAD_DIR w publicznym `/apply`" (`public_share.py:302`) | Empirycznie: prefiks `candidate_{id}_` sklejony bez separatora → pierwszy komponent to zawsze `candidate_5_<...>`, nigdy istniejący katalog; kernel nie przetworzy `..`. **Traversal poza katalog nie zachodzi.** (Realny, węższy problem — 500 na separatorze — ujęty jako **M11**.) |
| R2 | „Webhook CloudTalk gubi call dla niedopasowanego numeru, zwraca 200" (`calls.py:457`) | Zamierzone: `Call.candidate_id` jest `NOT NULL` FK — tabela `calls` to z definicji „rozmowy z kandydatami". Brak dopasowania = brak wiersza to projekt, nie bug. |

---

## Obserwacje środowiskowe / higiena

- **Frontend:** `tsc --noEmit` + `next lint` czyste (ostrzeżenia w limicie 300). Jedyny błąd type-check = stale artefakt `.next/types` dla usuniętej strony `preview/candidates-split` — nie kod źródłowy.
- **Backend lint/testy lokalnie nie uruchomione** (brak `ruff`/venv; `python3` 3.9). Rekomendacja: polegać na CI (`ruff` + `pytest`) — nie ma tu regresu wykrywalnego bez uruchomienia.
- **Migracje:** 204 pliki, **2 głowy** (L8). Chroniczny „osierocony alembic" na prodzie oznacza, że **każda** nowa tabela/kolumna/enum/DATA musi być zmirrorowana idempotentnie w `entrypoint.sh` — H1 to świeży przykład przeoczenia tej reguły (memory `entrypoint-safetynet-new-columns`).
- **Hardening, który działa (potwierdzone):** `SECRET_KEY` twardo failuje start na prodzie przy defaulcie (`config.py:779-812`); brak bare `except:` w backendzie; brak `hashlib.md5/sha1`; entrypoint drop-privileges root→appuser; Sentry replay masked (per observability.md).

---

## Rekomendacje (priorytetowo)

1. **Systemowo domknąć RBAC „viewer" na routerach dosięgających kandydatów** (H2, H3, H4, H5, M4 + L1). Jeden wspólny mechanizm: router-level `dependencies=[Depends(require_roles(...))]` + użycie `candidate_access.py` na każdym endpoincie zwracającym PII kandydata. Dodać test kontraktowy „viewer → 403" dla całej rodziny tras (jak w M2 dla `candidates.py`).
2. **H1 — dodać mirror `job_shortlist_entries` w `entrypoint.sh`** (bezpośredni 500 na prodzie) i dorobić do checklisty PR-a „każda nowa tabela → mirror w safety-net".
3. **Uspójnić matematykę pieniędzy** (H6, M2, M3, M12, L3): jedna ścieżka `Decimal`, konwersja FX przed każdą agregacją wielowalutową, guardy NULL/zero, brak `int()`/float na stawkach.
4. **Trwały dedupe zamiast setów w pamięci** dla pętli tła (M1, M9, L4, L9) — Coolify redeployuje wielokrotnie dziennie, więc każdy in-memory watermark to źródło duplikatów/utraty.
5. **Ujednolicić klienty zewnętrzne:** wszystkie LLM przez `claude_client.call_claude` (timeout+quota+limiter) — M8, M10; wszystkie upserty webhooków przez `ON CONFLICT` — M13; wszystkie `limit` query-param z `Query(ge, le)` — L5, L7, L10.
6. **Drobne bezpieczeństwo:** `Secure` (i najlepiej `httpOnly`) na cookie JWT (M6); sanitacja nazwy pliku w publicznym `/apply` (M11); nie logować adresu/tematu emaila (L2); migracja `merge` dla dwóch głów 0177 (L8).

---

*Audyt wygenerowany metodą wieloagentową (12 wymiarów × finder + adwersaryjny weryfikator na każde znalezisko). Wszystkie 29 potwierdzonych znalezisk mają zweryfikowany cytat z kodu (plik:linia). Nie potwierdzano eksploitów na żywym systemie — przed „fix" warto odtworzyć każdy scenariusz lokalnie/w CI.*
