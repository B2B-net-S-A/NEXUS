# Skrócenie ścieżki merge → produkcja

Data: 2026-08-07. Zakres: `.github/workflows/{ci,ci-gate,deploy}.yml` + jeden kontrakt testowy.

## Problem

Nawet zmiana jednej stałej jechała na produkcję ~52 min od otwarcia PR-a, a przy
kolizji z innym merge'em — godzinami.

### Pomiar wyjściowy (PR #1059, commit `b4af6c58`, zmiana jednej liczby)

| Etap | Czas |
|---|---|
| PR otwarty → merge (CI na PR) | 24 min |
| CI na `main` — **te same testy drugi raz** | 24 min 24 s |
| Deploy (Coolify build + smoke + deep health) | 3 min 58 s |
| **Razem** | **~52 min** |

### Rozbicie CI (24 min) — trzy przebiegi na `main`, 2026-08-06

| Job | 31103760726 | 31100489776 | 31096666193 |
|---|---|---|---|
| Gitleaks secret scan | 17 s | 20 s | 14 s |
| Trivy + hadolint | 31 s | 27 s | 27 s |
| Frontend (typecheck + build) | 5 min 11 s | 5 min 36 s | 5 min 01 s |
| **Backend (ruff + pytest)** | **24 min 20 s** | **24 min 00 s** | **23 min 47 s** |

Wewnątrz backendu (run 31103760726): setup + pip + alembic + import smoke
1 min 38 s, codecov 12 s, **pytest 22 min 20 s** (4792 testy, jeden proces).

Czyli 92% czasu joba backendowego to jeden krok, i on sam wyznaczał długość
całego CI — reszta jobów kończyła się w 5 min i czekała.

### Trzy przyczyny, nie jedna

1. **Pytest bez zrównoleglenia.** 4792 testy w jednym procesie, brak
   `pytest-xdist` w zależnościach.
2. **Te same testy dwa razy na każdą zmianę.** Raz na PR, raz po merge'u na
   `main`. Deploy wisiał na `workflow_run: ["CI"]`, więc te drugie 24 minuty
   siedziały w ścieżce krytycznej. Ponieważ `strict: true` gwarantuje aktualność
   gałęzi, drugi przebieg testował praktycznie ten sam kod.
3. **`strict: true` + 24-minutowe CI.** Przy pracy seriami PR robił się `BEHIND`
   zanim zdążył się zmergować → aktualizacja → CI od zera. Ogony w czasach
   merge'u: #1055 = 105 min, #1052 = 98 min, #1054 = 77 min, #1050 = 536 min.

**Coolify nie był winny** — cały Deploy stabilnie ~4 min.

## Zmiany

### 1. Zrównoleglenie pytest (`ci.yml`)

`pytest-xdist` + `-n 4 --dist loadfile`. `loadfile`, nie `load`: cały plik trafia
do jednego workera, więc kolejność wewnątrz pliku jest zachowana i zrównoleglenie
może zepsuć wyłącznie zależności *między* plikami.

`-n 4` jawnie, nie `auto` — ubuntu-latest ma dziś 4 vCPU (ta sama liczba), ale
jawna wartość nie zmieni cicho współbieżności i obciążenia współdzielonego
postgresa, gdyby GitHub zmienił rozmiar runnera.

### 2. Podział na dwa workflow (`ci-gate.yml` + `ci.yml`)

`workflow_run` reaguje na ukończenie **całego** workflow, nie pojedynczego joba —
dlatego samo rozbicie na joby w jednym pliku nic by nie dało. Stąd osobny plik:

| Workflow | Joby | Czas |
|---|---|---|
| **CI Gate** | Gitleaks secret scan · Backend (lint + migrations) | ~2 min |
| **CI** | Backend (pytest) · Frontend (typecheck + build) · Trivy + hadolint | ~8 min |

W bramce jest to, co tanio i realnie chroni produkcję: sekrety (nieodwracalne),
ruff (1 s), pełna choreografia alembica (migracja, która nie wchodzi, to
najczęstszy tryb awarii tego repo) i import smoke.

### 3. Deploy bramkowany na `CI Gate`, nie na `CI` (`deploy.yml`)

`workflows: ["CI"]` → `workflows: ["CI Gate"]`.

Czego świadomie **nie ma** w bramce:

- **Build frontendu** — Coolify i tak buduje oba obrazy ze źródeł, więc zepsuty
  build = nieudany deployment = czerwony job Deploy = brak wdrożenia. Bramkowanie
  na nim było duplikatem tej samej weryfikacji.
- **Pytest** — przeszedł już na PR na tym samym kodzie i nadal leci na `main`
  równolegle.

### 4. Kontrakt migracji (`test_client_directory_migration_contract.py`)

`test_hosted_ci_runs_fresh_retry_downgrade_and_reupgrade_cycle` czytał `ci.yml`
i sprawdzał choreografię alembica, którą przeniesiono do bramki. Kontrakt
przepisany tak, by sprawdzał **zachowanie** („hostowane CI przechodzi cykl"),
a nie który plik je zawiera: przegląda oba workflow i wymaga, by *któryś*
spełniał komplet warunków. Każdy plik osobno, nie na sklejce — `_normalise_sql`
zwija także znaki nowej linii, więc konkatenacja mogłaby skleić ostatnią komendę
jednego pliku z pierwszą komendą drugiego i sfabrykować dopasowanie.

## Wynik (liczby z PRAWDZIWEGO CI, nie lokalne)

| | Przed | Po |
|---|---|---|
| Gitleaks | 17 s | 21 s |
| Backend — lint + migracje (bramka) | *(w jobie 24 min)* | **1 min 28 s** |
| Backend — pytest | 22 min 20 s | **15 min 12 s** |
| Frontend | 5 min 11 s | 5 min 24 s |
| **Bramka przed deployem** | **24 min** | **1 min 28 s** |
| **merge → produkcja** | **~28 min** | **~5,5 min** |

Główny cel osiągnięty: **czas wdrożenia przestał zależeć od pytestu**. Bramka to
1,5 min, deploy ~4 min.

Przyspieszenie samego pytestu jest natomiast **skromniejsze, niż zapowiadał
pomiar lokalny**: 1,47× w CI wobec ~3× u mnie. Powód nie leży w nierównym
podziale plików — największy plik ma 126 z 4792 testów (2,6%), więc
`--dist loadfile` nie jest tu wąskim gardłem. Bardziej prawdopodobna jest
przesubskrypcja: runner `ubuntu-latest` ma 4 vCPU dzielone między 4 workery
**i** kontener postgresa, podczas gdy lokalnie były 3 rdzenie zapasu.
Do sprawdzenia w przyszłości: `-n 3` (rdzeń zostaje bazie) — każdy taki
eksperyment kosztuje jeden cykl CI, więc nie zgadywany tutaj.

## Weryfikacja

Środowisko odtwarzające CI: `python:3.12-slim` + `postgres:16-alpine`, ten sam
zestaw zmiennych, ta sama lista `--ignore`.

| Przebieg | Warunki | Wynik |
|---|---|---|
| 1 | mount tylko `backend/`, brak libów systemowych | 35 failed, 4 errors — **artefakt środowiska** |
| 2 | mount całego repo + libsy, baza brudna po przebiegu 1 | 5 failed, 4787 passed |
| A/B | czysta baza, pliki podejrzane, serialnie **vs** `-n 4` | 21 passed w OBU — xdist nie jest przyczyną |
| 3 | **czysta baza, pełny suite, `-n 4 --dist loadfile`** | **4792 passed, 14 skipped, 0 failed, 5 min 35 s** |

Przebieg 3 zgadza się z baselinem CI co do liczby testów i pominięć
(4792 passed / 14 skipped), więc zrównoleglenie nie zmieniło zakresu — tylko czas.

Diagnoza 5 porażek z przebiegu 2, rozłożona eksperymentem A/B:

- **4 × brudna baza.** Część testów wstawia rekordy o stałych kluczach
  (np. `b2b_generated_contracts` z `year=9999, seq=1`) i ich nie sprząta, więc
  suite jest jednorazowy na danej bazie. W CI maskuje to świeży kontener
  postgresa per job, więc **nie ma wpływu na CI**. Osobny dług, zgłoszony do
  odrębnego zadania — nie mieszany do tego PR-a.
- **1 × kontrakt migracji.** Przebieg wystartował zanim naniosłem poprawkę
  opisaną w §4; po niej test przechodzi.

Osobno potwierdzone na świeżym postgresie: pełna choreografia alembica z bramki
przechodzi, a `from app.main import app` się importuje.

### Czego pomiar lokalny NIE złapał

Pierwszy przebieg w prawdziwym CI wywrócił się na jednym teście —
`test_inventory_detects_anomalies_and_does_not_mutate`, z komunikatem
„endpoint zmutował dane!". To była **realna niezgodność z xdistem**, nie flake:

Test mierzył `COUNT(*)` z całej tabeli `contracts` przed i po wywołaniu GET-a,
żeby udowodnić, że endpoint jest read-only. Pod zrównolegleniem równoległy
worker wstawiający własny kontrakt między dwoma pomiarami wygląda dokładnie
tak samo jak endpoint mutujący dane — więc test oskarżał endpoint o cudzy zapis.

Lokalnie przechodził, bo mam 8 rdzeni i przeplecenie wypadało inaczej; runner
ma 4 vCPU. **Wniosek na przyszłość: zielony przebieg lokalny nie jest dowodem
zgodności z xdistem dla testów mierzących stan globalny.**

Naprawione znacznikiem wodnym: `MAX(id)` przed wywołaniem, potem liczenie tylko
`id <= znacznik`. Wiersze cudzych workerów dostają wyższe id z sekwencji i
wypadają z pomiaru, a wykrywanie zniknięcia wiersza sprzed wywołania zostaje.
Świadomie tracimy wykrywanie INSERT-u przez endpoint — nowy wiersz też ma id
powyżej znacznika, więc jest nieodróżnialny od wstawki cudzego workera, a
przypisania INSERT-u do konkretnego zapisującego nie da się zrobić samym
liczeniem przy równoległym wykonaniu.

Zweryfikowane odtworzeniem wyścigu: `test_engagement_inventory` puszczony
`-n 4` równolegle z trzema plikami masowo tworzącymi kontrakty, 3 próby —
23 passed za każdym razem.

## Odtwarzalność suite'u na trwałej bazie

Osobna klasa problemu, wyszła przy okazji. Suite dawał się uruchomić dokładnie
raz na danej bazie; drugi przebieg padał. W CI maskował to świeży kontener
postgresa per job, więc bolało tylko lokalnie.

Dwie różne przyczyny, mimo że objawiały się razem:

1. **`test_engagement_inventory.py`** — seedował wiersz o stałej parze
   `(year=9999, seq=1/2)` przy UNIQUE na tej parze i nie sprzątał.
   Naprawa: seed jest teraz **idempotentny** — kasuje dokładnie tę jedną parę
   przed wstawieniem (nigdy zakres). `contract_number` celowo nie jest kluczem:
   nie ma na nim UNIQUE, a duplikat numeru jest właśnie tym, co ten test bada.

2. **`test_contract_finance_redaction.py`** — pobierał jedną stronę
   `?page_size=100` i wymagał swojego wiersza na niej, czyli zakładał prawie
   pustą tabelę. Przy nagromadzonych kontraktach wiersz wypadał poza stronę i
   test czerwieniał z powodu niezwiązanego z redakcją danych finansowych, czyli
   z tym, co bada. Podbicie `page_size` tylko przesunęłoby próg (endpoint tnie
   na 200), więc naprawa przechodzi po **wszystkich** stronach — to zdejmuje
   założenie o rozmiarze bazy całkowicie.

**Dowód:** dwa pełne przebiegi pod rząd na tej samej bazie, bez resetu między
nimi — 4792 passed / 0 failed w obu (7 min 44 s i 10 min 14 s; drugi wolniejszy,
bo baza urosła).

## Świadomy kompromis

Produkcja może żyć kilka minut zanim pytest na `main` się skończy. Okno kryje
przypadek dwóch PR-ów zmergowanych blisko siebie, które osobno są zielone,
a razem nie. Sygnałem jest wtedy czerwone „CI" na `main` → rollback
(`deployment-runbook` §2). Deep healthcheck w `deploy.yml` łapie osobną,
częstszą klasę: migrację, która nie weszła na prod.

Rollback samej zmiany: w `deploy.yml` zmień `workflows: ["CI Gate"]` z powrotem
na `workflows: ["CI"]` — deploy znowu poczeka na pytest.

## Branch protection

Nazwy jobów się zmieniły, więc wymagane checki też. Nowa lista:

```
Gitleaks secret scan
Backend (lint + migrations)
Backend (pytest)
Frontend (typecheck + build)
```

Reszta ustawień bez zmian (`strict: true`, `enforce_admins: true`, linear
history, 0 wymaganych approvali).

**Wpływ na otwarte PR-y:** w chwili zmiany otwartych było 16 (głównie
dependabot). Każdy musi raz przebiec, żeby wyprodukować kontekst
`Backend (lint + migrations)`. Nie dokłada to pracy ponad to, czego i tak
wymagał `strict: true` — te PR-y i tak wymagały aktualizacji przed merge'em.
