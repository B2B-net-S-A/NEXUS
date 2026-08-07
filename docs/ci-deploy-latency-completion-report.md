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

## Wynik

| | Przed | Po |
|---|---|---|
| pytest (backend) | 22 min 20 s | **5 min 35 s** |
| Bramka przed deployem | 24 min | ~2 min |
| **merge → produkcja** | **~28 min** | **~6 min** (bramka 2 min + deploy 4 min) |

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

**Zastrzeżenie co do liczb:** 5 min 35 s zmierzone lokalnie (Docker na macOS,
4 workery). Runner `ubuntu-latest` ma 4 vCPU, więc rząd wielkości powinien się
zgadzać, ale dokładną wartość poda pierwszy przebieg w CI.

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
