# CI: auto-discovery zamiast ręcznej listy 285 plików testowych

> Kontynuacja PR #931. Zamyka KLASĘ błędu: „nowy test nie działa, bo nikt nie
> dopisał go do `ci.yml`".

## Problem

`.github/workflows/ci.yml` odpalał ręcznie wyliczoną listę ~285 plików
testowych. Kontrakt `backend/tests/test_ci_coverage_contract.py` pilnował, żeby
nowy plik nie wypadł z listy — ale sama lista pozostawała ręczną robotą, więc
pokrycie było **opt-in**: test chronił cokolwiek tylko wtedy, gdy autor pamiętał
o dopisaniu nazwy pliku.

Docelowo lista miała zniknąć na rzecz `pytest tests/ --ignore=<jawne wyjątki>`.
Pomiar z 2026-07-27 pokazał, że tak się NIE da: `pytest tests/` z 32 ignorami
zbiera dokładnie ten sam zestaw plików co lista z `ci.yml` — różni się
**wyłącznie kolejność** (alfabetyczna zamiast kolejności z `ci.yml`) — a mimo to
daje 6 awarii zamiast 0.

Kolejność z `ci.yml` była więc *load-bearing*: maskowała testy zależne od
kolejności.

## Co zostało zrobione

### 1. Naprawa sprzężenia (10 awarii, 8 plików)

Wszystkie zreprodukowane deterministycznie i zweryfikowane pojedynczo
w obrazie prod na świeżo zmigrowanej bazie.

| Plik | Awarie | Przyczyna | Naprawa |
|---|---|---|---|
| `test_scoring_service.py` | 3 | `test_cortex_api.py` woła endpoint kuracji → `refresh_alias_map()` → nadpisuje **globalny** `scoring_service.ALIAS_MAP` i taksonomię `skill_normalize` na resztę procesu | autouse fixture `_isolate_skill_taxonomy` w `tests/conftest.py` przywraca oba globale po każdym teście |
| `test_cv_generator_b2b_pipeline.py` | 1 | jw. (bolding czytał zahydratyzowaną taksonomię — „REST API" rozpadało się na „REST") | jw. |
| `test_cvsnapshot_txn_alerts_dedup.py` | 1 | **błąd w teście**: `cand_id, stage_id, job_id = cand.id, job.id, stage.id` — `stage_id` trzymał id JOBA. Działało tylko dopóki sekwencje `jobs` i `candidate_stages` szły w parze | poprawiona kolejność krotki |
| `test_teams_notifications.py` | 1 | `created_by_user_id=1` na sztywno; `users.id=1` istniał tylko dopóki jakiś wcześniejszy test go nie skasował → `ForeignKeyViolation` | fixture `channel_author_id` zakłada własnego użytkownika (Core SQL, żeby plik dało się odpalić solo — ORM `User` odpala `configure_mappers()`) |
| `test_contract_analytics.py` | 1 | **błąd produkcyjny**, nie testu — patrz niżej | guard na `start_date is None` |
| `test_contracts_expansion.py` | 1 | `_any_contract()` brał **dowolny** wiersz z globalnej listy i go MUTOWAŁ (terminate). Do tego `if not contract: return` — cichy no-op na pustej bazie | plik ma własny `owned_contract` fixture; asercje na własnych, znanych datach |
| `test_contracts_filters_multi.py` | 3 | asercja `id in <nieprzefiltrowany listing page_size=100>` — prawdziwa tylko póki tabela miała <100 wierszy | każdy request scope'owany `q=<marker>`; asercja na równości zbiorów |
| `test_contracts_search.py` | 1 | jw. (blank-`q` no-op sprawdzany przez obecność na stronie 1) | invariant wyrażony jako `total(blank q) == total(brak q)` |

**Błąd produkcyjny (`app/api/contract_analytics.py:390`)**: `/api/contract-analytics/revenue-forecast`
porównywał `c.start_date < next_month` w Pythonie, a `Contract.start_date` jest
`Optional[date]` (kolumna NULLABLE). Jeden aktywny kontrakt bez daty startu →
`TypeError` → **500 na całej prognozie**. Dodany guard `c.start_date is not None`,
zgodnie z konwencją `app/analytics/metrics.py:687`, która już tak robi. NULL
`end_date` nadal znaczy „czas nieokreślony" i wchodzi do prognozy.

### 2. `ci.yml` → auto-discovery

285 wyliczonych ścieżek → `pytest tests/` + 26 `--ignore=`. Netto **−284/+37 linii**.
Nowy plik testowy jest odtąd zbierany automatycznie; zapomnienie przestało być
możliwe, możliwe jest tylko **świadome** wykluczenie.

### 3. Odwrócony parser w kontrakcie

Stary `_ci_listed_files()` czytał `tests/…\.py` jako „plik pokryty przez CI".
Po zamianie potraktowałby `--ignore=tests/test_x.py` **dokładnie odwrotnie niż
trzeba** — listę wyjątków przeczytałby jako dowód pokrycia i przepuściłby build,
nie chroniąc niczego.

Nowy `_ci_ignored_files()` parsuje `--ignore=`, a lista ignorów jest **jedynym
baseline'em**. Trzy asercje:

1. `test_ci_collects_the_whole_tests_directory` — CI musi wołać `pytest tests/`
   i nie wolno mu wyliczać plików jako celów (guard przed regresją do starego modelu).
2. `test_every_ci_ignore_is_a_declared_exception` — każdy `--ignore=` ma
   uzasadnienie i kategorię w tym pliku.
3. `test_baseline_matches_ci_and_has_no_stale_entries` — wpis baseline'u musi
   istnieć na dysku i faktycznie być ignorowany.

Komentarze w `ci.yml` są odfiltrowane przed parsowaniem — nazwa pliku w prozie
nie jest konfiguracją (złapane w praktyce: własny komentarz odpalił guard #1).

Kategoria `_SUITE_INTERFERENCE` **zlikwidowana** (4 pliki naprawione).

Baseline: 32 → **26**, dwoma niezależnymi ścieżkami:
* −2 na `main` — #941 naprawił `test_candidate_stage_cv_branded` i
  `test_engagement_magic_link` („wygasły link daje 200" było no-opem w setupie
  testu: `UPDATE … WHERE token == <surowy sekret>` trafiał w 0 wierszy po
  migracjach hash-at-rest, nie dziurą w produkcie);
* −4 tutaj — `_SUITE_INTERFERENCE`.

Gałąź została **przerebase'owana na `main`** po tym, jak doszło tam 10 commitów,
z czego 5 dotykało `ci.yml` (piny akcji: checkout v6.0.2, setup-node 6.4.0,
cache 5.0.5). Transformacja została **odtworzona na świeżej wersji `ci.yml`
z `main`**, a nie wymuszona ze starej — inaczej cofnęłaby zarówno piny, jak i
podpięcie dwóch plików z #941.

## Weryfikacja

Środowisko identyczne z CI: obraz `nexus-ai-program-backend:latest`, świeżo
zmigrowana baza (`alembic upgrade heads`, head `0198`), `DATABASE_URL` +
`SECRET_KEY` + `RUN_LIVE_TESTS=0` i **nic więcej** (ustawienie
`M365_TOKEN_ENCRYPTION_KEY` fałszowałoby wynik — CI go nie ustawia).

- **Reprodukcja przed naprawą** — deterministyczna, nie „z kolejności":
  200 dodatkowych kontraktów w bazie odtworzyło 5 awarii listingowych, jeden
  kontrakt z `start_date IS NULL` odtworzył 500 w prognozie, baza bez `users.id=1`
  odtworzyła `ForeignKeyViolation`, a `test_cortex_api.py` przed
  `test_scoring_service.py` odtworzył 4 awarie taksonomii w 30 s.
- **Po naprawie** — te same warunki, komplet zielony.
- **Kontrakt** — sprawdzony mutacyjnie: trzy mutacje `ci.yml` (nieuzasadniony
  `--ignore`, usunięty `--ignore` wciąż-czerwonego pliku, powrót do wyliczania
  celów) łapane przez dokładnie tę asercję, która ma je łapać.
- **Pełny przebieg** — komenda parsowana wprost z `ci.yml`, żeby weryfikacja
  odpalała to, co odpali CI. Wynik: **3504 passed, 14 skipped, 0 failed**
  (21 min) — zero z 10 wyjściowych awarii, zero nowych regresji.
- `ruff check app/` + `ruff format --check app/` — czyste.
- Narzut `_isolate_skill_taxonomy` — **niemierzalny** (`test_scoring_service.py`:
  66 testów w 1,15 s). Kontenery są puste w ~każdym teście, więc snapshot to
  kopia pustych struktur; płacą tylko testy, które faktycznie hydratyzują
  taksonomię.

### Artefakt pomiarowy, NIE awaria kodu

`test_backup_service_contract.py` (20 testów) czyta pliki z **roota repo**
(`parents[2]`: `docker-compose.yml`, `backup/*.sh`). Harness montował tylko
`backend/`, więc `parents[2]` rozwiązywało się do `/` i pliki „znikały" —
`FileNotFoundError` wyglądający jak prawdziwa regresja. Po domontowaniu roota:
**20/20 zielone**. W CI problem nie występuje (checkout ma całe repo).
Harness poprawiony.

## Uwaga operacyjna

W trakcie prac `docker kill` filtrowany po obrazie ubił 3 kontenery
`nexus-ai-program-backend:latest`, z czego **2 nie należały do tej sesji**
(`ecstatic_wescoff` działał już na starcie). Nic produkcyjnego — to obraz
lokalny/dev — ale jeśli w innej sesji przerwał się przebieg testów, to stąd.
Dalej używane były wyłącznie nazwane kontenery.
