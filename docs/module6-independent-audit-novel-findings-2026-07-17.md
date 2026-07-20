# Moduł 6 — niezależny audyt uzupełniający (findings, których NIE ma u Codexa)

- Data: 2026-07-17
- Anchor kodu: `origin/main` @ `2cad312` (po zmergowaniu całej Fali A containment)
- Metoda: workflow wieloagentowy — 8 niezależnych finderów per subsystem (każdy dostał pełny katalog ~30 findingów Codexa jako „known — nie raportuj"), następnie adwersarialna weryfikacja każdego kandydata przeciw realnemu kodowi, dedup i synteza
- Charakter: read-only audyt kodu; zero zmian danych produkcyjnych

> **Uwaga o kompletności:** przebieg został ucięty przez limit sesji. Z 32 agentów ukończyło 17. Dwa całe obszary (**frontend**, **data-model/migracje**) nie zostały zaudytowane wcale, a 13 kandydatów nie przeszło weryfikacji. Raport jawnie to rozdziela — nie udaję, że pokrycie jest pełne.

---

## 0. Streszczenie

24 kandydatów w 6 obszarach. **Żaden nie jest powtórzeniem findingu Codexa** — finder dostawał katalog Codexa i miał obowiązek uzasadnić nowość.

| Status | Liczba |
|---|---|
| Zweryfikowane CONFIRMED | 6 |
| Zweryfikowane PARTIAL (realny mechanizm, zawyżona severity) | 5 |
| Niezweryfikowane (weryfikator ubity limitem) | 12 |
| Zweryfikowane przeze mnie ręcznie + **naprawione** | 1 |
| Obszary bez audytu | 2 (frontend, data-model) |

**Najważniejszy wynik: audyt złapał regresję, którą sam wprowadziłem w Fali A** (iCal, sekcja 1). To najmocniejszy argument, że ten przebieg był wart zachodu.

Dwa motywy przewijają się przez niezależne obszary i to jest realna wartość poza pojedynczymi bugami:

1. **`user.role` (primary) zamiast `has_any_role` (union)** — 4 niezależne wystąpienia w 4 różnych plikach. Ludzie z rolą kwalifikującą jako **drugorzędną** po cichu nie dostają powiadomień / tracą dostęp. Codex dotknął tego tylko raz, przy członkostwie w czacie kandydata (P1.8), i nie rozpoznał jako wzorca systemowego.
2. **Nieograniczone `SELECT` po tabelach append-only** w pętlach tła — 3 niezależne wystąpienia. `candidate_stages` i `candidates` ładowane w całości do pamięci Pythona, cyklicznie.

---

## 1. NAPRAWIONE — regresja z Fali A (iCal UID collision)

**To był mój błąd, wprowadzony w PR-07 (#805).** Naprawiony w **#816**.

- Plik: `backend/app/services/ical_import.py` (upsert), indeks: `backend/alembic/versions/0010_calendar_external_source.py:39`
- Severity: **P1**

PR-07 zawęził lookup upserta o `created_by`, żeby zamknąć cross-user overwrite (P0.8 Codexa). Ale w bazie jest partial unique index **bez** `created_by`:

```sql
CREATE UNIQUE INDEX ux_calendar_events_external
  ON calendar_events (external_source, external_id)
  WHERE external_id IS NOT NULL
```

Skutek: gdy drugi użytkownik importuje feed ze współdzielonym (standardowym) UID-em — lookup scoped po `created_by` **nie trafia** → `INSERT` → `IntegrityError` **na commicie** → rollback **całej** transakcji → znikają **wszystkie** wydarzenia z tego importu, a błąd jest połykany do `result.errors`.

Czyli PR-07 zamienił *cichy overwrite cudzego eventu* na *twardą, całkowitą utratę importu*. Obie rzeczy są nie do przyjęcia.

**Fix (#816):** przed `INSERT` sprawdzamy, czy `(external_source, external_id)` jest już zajęte przez kogokolwiek — jeśli tak, liczymy w `skipped_conflict` i `continue`, więc reszta batcha commituje się normalnie. Dodatkowo `seen_uids` na powtórzony UID w obrębie jednego feedu (wiersze pending są niewidoczne dla `SELECT`, więc inaczej i tak wywaliłyby indeks na commicie). Cudzy event nadal nigdy nie jest nadpisywany — P0.8 zostaje zamknięty.

**Follow-up (świadomie nie teraz):** docelowo unikalność powinna być per-owner — `(external_source, external_id, created_by)`. To wymaga migracji + mirrora w `entrypoint.sh` (prod alembic jest orphaned), więc czeka aż wróci pipeline deployu.

---

## 2. Zweryfikowane CONFIRMED

### 2.1. Odbiorcy alertów tła wybierani po roli PRIMARY — P2
`backend/app/tasks/contract_alerts.py:77`

Zapytania o odbiorców filtrują `User.role == / .in_(...)` (rola główna). Osoby, które kwalifikującą rolę mają jako **drugorzędną** (`User.roles`), **nigdy** nie dostają powiadomień kontraktowych / compliance / sprzętowych / SLA / KPI. Cisza jest nieodróżnialna od „brak alertów".

### 2.2. `_latest_stage_per_pair` ładuje całą tabelę `candidate_stages` do Pythona — P2
`backend/app/services/notification_triggers.py:129`

Brak `WHERE`/`LIMIT` na tabeli append-only, wykonywane **2–6× co 5 minut**. Rośnie liniowo z historią pipeline'u — klasyczny cichy zabójca pamięci/CPU repliki.

### 2.3. Webhook transkryptu CloudTalk robi synchroniczny LLM enrichment w requeście — P2
`backend/app/api/calls.py:432` (potwierdzone przy `:445`)

Wywołanie modelu w ścieżce webhooka → timeouty po stronie dostawcy → retry → kolejne wywołania LLM. Burza retry + kosztów, dokładnie wtedy, gdy system jest już obciążony.

### 2.4. Trigger PowerCalling KPI wyklucza użytkowników hybrydowych — P3
`backend/app/services/notification_triggers.py:330`

Rekruterzy/HR wybierani przez `User.role ==`, podczas gdy eskalacja DL w tym samym pliku używa `User.roles.contains`. Niespójność w jednym module: hybryda ról znika z KPI, ale jest w eskalacji.

### 2.5. Proxycurl ignoruje `Retry-After` w formacie HTTP-date — P3
`backend/app/services/proxycurl/client.py:256`

Odejmowanie naive/aware `datetime` rzuca wyjątek, kod wpada w fallback 2 s. Przy 429 od płatnego API oznacza to dobijanie się zamiast respektowania backoffu → koszt i ryzyko bana.

### 2.6. Brak limitu subskrypcji presence na połączenie/użytkownika — P3
`backend/app/api/ws.py:136` (potwierdzone przy `:356-366`)

Uwierzytelniony użytkownik może subskrybować nieograniczoną liczbę zasobów; stan trzymany w procesie → rośnie pamięć backendu. (Uzupełnia P1.3/P1.4 Codexa, ale to inny wektor: wyczerpanie zasobu, nie IDOR.)

---

## 3. Zweryfikowane PARTIAL — mechanizm realny, severity zawyżona

Weryfikator potwierdził kod, ale obniżył wagę. Zostawiam je jako dług, nie jako pilne.

| Finding | Plik | Ocena |
|---|---|---|
| Lookup kandydata po telefonie = nieindeksowalny `right(regexp_replace(...))` → seq scan ~49k wierszy na każde zdarzenie | `api/calls.py:359`, `tasks/cloudtalk_sync.py:89` | **P2** — realnie nieindeksowalne (kolumna `phone` bez indeksu, predykat non-sargable), ale regex po 49k krótkich stringach to praca sub-sekundowa; realny koszt to backfill robiący ~5000 skanów na run, nie DoS. Feature śpi za `CLOUDTALK_ENABLED=false`. Codex widział tylko `.limit(1)`/złe dopasowanie — wymiar wydajnościowy jest nowy. |
| `initiate-call` bez scope'u kandydata i **bez rate-limitu** | `api/cloudtalk.py:291` | **P2** — brak limitera potwierdzony (globalny `default_limits=[]`, peer-routery mają `@limiter.limit`), gate to bare `CurrentUser` zamiast `CandidatePIIAccess`. Realny wektor toll-fraud/oracle, ale dziś dormant (flaga off + wymagany agent mapping). |
| `slack_sla_alerts` wciąga całą `candidate_stages` do pamięci co 30 min | `tasks/slack_sla_alerts.py:37` | **P2** — ten sam wzorzec co 2.2 |
| Dedup `contract_alerts` jest trwały i globalny (title-LIKE, bez okna czasu) | `tasks/contract_alerts.py:82` | **P3** — przedłużony kontrakt ponownie wchodzący w próg nigdy nie zaalertuje; zapytanie dedup rośnie bez ograniczeń |
| `GET /api/fireflies/sync` — mutujący GET, bez rate-limitu | `api/fireflies.py:22` | **P3** — Codex flagował brak owner-scope; brak limitera i koszt LLM per wywołanie to nowy wymiar |

---

## 4. Niezweryfikowane kandydaci (weryfikator ubity limitem)

**Nie traktować jako potwierdzone.** Każdy ma konkretny plik i linię — do domknięcia w następnym przebiegu.

**M365 / poczta**
- `services/m365/matcher.py:185` — matcher `smart_name` ładuje **całą** tabelę kandydatów przy każdym niedopasowanym mailu przychodzącym *(zgłoszone jako P1 — priorytet weryfikacji)*
- `api/microsoft365.py:229` — reconnect zeruje przestarzałą kolumnę `delta_token_messages` zamiast `delta_token_inbox/sent` → `backfill_in_progress` zawieszony na zawsze
- `api/microsoft365.py:514` — webhook Graph robi jedno zapytanie DB na wpis tablicy kontrolowanej przez nadawcę, bez limitu długości i bez rate-limitu
- `api/email_threads.py:208` — cross-mailbox privilege check po `role.value` zamiast `has_any_role` *(wzorzec §0.1)*

**Kalendarz**
- `api/calendar.py:111` — `GET /calendar/events` bez paginacji i z 3 zapytaniami per event (3N+1)
- `services/m365/calendar.py:95` — payload zaproszenia etykietuje `timeZone=Europe/Warsaw`, ale wysyła `isoformat()` z offsetem UTC → zaproszenie w Outlooku ląduje o złej godzinie i rozjeżdża się z lokalnym wierszem
- `api/calendar.py:440` — scope konfliktów kalendarza po roli primary *(wzorzec §0.1)*

**Czat**
- `services/job_membership.py:25` — członkostwo czatu po `user.role == UserRole.admin` zamiast `has_any_role` (drift od migracji 0110) *(wzorzec §0.1)*
- `api/job_chat.py:627` — nieograniczone reakcje emoji na wiadomość: brak limitu, dowolne 16-znakowe stringi, amplifikacja przez WS + re-agregację
- `api/admin_chats.py:149` — paginacja nieosiągalna: `has_more` liczone, ale nie ma parametru kursora/offsetu
- `api/candidate_chat.py:266` — `create_message` rozwiązuje pełny zbiór członkostwa **trzykrotnie** na każdą wiadomość

**Powiadomienia**
- `api/notifications.py:215` — zapytanie dedup obcina dzień w UTC, a unique index obcina w `Europe/Warsaw` → `IntegrityError`/500 i zgubiona edycja Champion Profile

---

## 5. Czego ten audyt NIE pokrył

Uczciwie, żeby nie tworzyć fałszywego poczucia pokrycia:

- **Frontend** — finder nie wystartował. Zero nowych findingów UI/kontraktowych.
- **Data-model / migracje / integralność schematu** — finder nie wystartował. To akurat obszar, w którym znaleziona regresja iCal (§1) żyła, więc **prawdopodobieństwo kolejnych rozjazdów kod↔constraint jest niezerowe** — to najbardziej wartościowy kierunek kolejnego przebiegu.
- Weryfikacja 12 kandydatów z §4.

---

## 6. Rekomendacja

1. **Zmergować #816** (regresja iCal) — to jedyna rzecz, która realnie psuje dane użytkownika *teraz*.
2. Jednym PR-em domknąć wzorzec `has_any_role` (4 miejsca: `contract_alerts`, `notification_triggers`, `job_membership`, `email_threads`, `calendar`) — mechanicznie proste, jednoznacznie poprawne, likwiduje całą klasę „cichej ciszy" w powiadomieniach.
3. Jednym PR-em ograniczyć trzy nieograniczone skany tabel append-only (`notification_triggers`, `slack_sla_alerts`) — dodać okno czasowe/`LIMIT`.
4. Dokończyć weryfikację §4 i **przepuścić brakujące dwa obszary (frontend, data-model)**, gdy limit sesji się zresetuje.

Reszta to dług do kolejki, nie pilne — zwłaszcza że część dotyczy integracji śpiących za flagami (`CLOUDTALK_ENABLED=false`).
